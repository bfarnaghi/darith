# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import base64
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import (
    BankAccount,
    BudgetPreference,
    Expense,
    ExpenseCategory,
    Income,
    IncomeCategory,
    MonthlyExpense,
    PasskeyCredential,
    RecurringIncome,
    SavingsGoal,
    SubscriptionPlan,
    Transfer,
    Token,
    UserSubscription,
    UserFeedback,
)
from .notifications import send_telegram_admin_notification
from .services import (
    build_daily_forecast,
    build_monthly_budget,
    build_next_month_forecast,
    fund_due_savings_goals,
    goal_funding_reminders,
    goal_monthly_contribution,
    post_due_recurring,
)
from .subscriptions import initialize_user_subscription, report_manual_payment


BASE_DIR = Path(__file__).resolve().parent.parent
VALID_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
)


def valid_profile_png():
    output = io.BytesIO()
    Image.new("RGB", (24, 24), "#1456d9").save(output, format="PNG")
    return output.getvalue()


class SeoFileTests(SimpleTestCase):
    def test_robots_txt_allows_public_home_and_blocks_private_pages(self):
        response = self.client.get("/robots.txt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        body = response.content.decode()
        self.assertIn("User-agent: *", body)
        self.assertIn("Allow: /", body)
        self.assertIn("Disallow: /admin/", body)
        self.assertIn("Disallow: /dashboard/", body)
        self.assertIn("Disallow: /subscription/", body)
        self.assertIn("Sitemap: https://darith.app/sitemap.xml", body)

    def test_sitemap_xml_lists_only_public_homepage(self):
        response = self.client.get("/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        body = response.content.decode()
        self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', body)
        self.assertIn("<loc>https://darith.app/</loc>", body)
        self.assertNotIn("/dashboard/", body)
        self.assertNotIn("/admin/", body)
        self.assertNotIn("/subscription/", body)


class TutorialPageTests(SimpleTestCase):
    def test_tutorial_is_public_and_explains_the_complete_workflow(self):
        response = self.client.get(reverse("tutorial"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Understand your money, one section at a time.")
        self.assertContains(response, "Safe to spend today")
        self.assertContains(response, "Why Darith checks every future day")
        self.assertContains(response, "Money timeline")
        self.assertContains(response, "Tracking-only accounts")
        self.assertContains(response, "Automatic posting")
        self.assertContains(response, "Saving goals")
        self.assertContains(response, "Passkey")
        self.assertContains(response, "No bank credentials")
        self.assertContains(response, "images/dashboard-preview.png")


class TelegramNotificationTests(SimpleTestCase):
    @override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    @patch("web.notifications.urlopen")
    def test_notification_is_disabled_without_credentials(self, urlopen_mock):
        sent = send_telegram_admin_notification(
            "New user created",
            (("Username", "ben"),),
        )

        self.assertFalse(sent)
        urlopen_mock.assert_not_called()

    @override_settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_CHAT_ID="-1001234567890",
        TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS=3,
    )
    @patch("web.notifications.urlopen")
    def test_notification_posts_json_to_the_configured_chat(self, urlopen_mock):
        urlopen_mock.return_value.__enter__.return_value.read.return_value = b'{"ok": true}'

        sent = send_telegram_admin_notification(
            "New feedback received",
            (("Username", "ben"), ("Page", "dashboard")),
        )

        self.assertTrue(sent)
        request = urlopen_mock.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            request.full_url,
            "https://api.telegram.org/bot123456:test-token/sendMessage",
        )
        self.assertEqual(payload["chat_id"], "-1001234567890")
        self.assertIn("New feedback received", payload["text"])
        self.assertIn("Username: ben", payload["text"])
        self.assertNotIn("feedback message", payload["text"])
        urlopen_mock.assert_called_once_with(request, timeout=3)

    @override_settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_CHAT_ID="-1001234567890",
        TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS=1,
    )
    @patch("web.notifications.urlopen", side_effect=OSError("network unavailable"))
    def test_notification_failure_does_not_escape(self, urlopen_mock):
        sent = send_telegram_admin_notification(
            "Subscription payment reported",
            (("Reference", "DARITH-000001"),),
        )

        self.assertFalse(sent)
        urlopen_mock.assert_called_once()


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "delete-me",
            "delete-me@example.com",
            "good-password-123",
        )
        self.other_user = User.objects.create_user(
            "keep-me",
            "keep-me@example.com",
            "good-password-123",
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name="Main",
            balance=Decimal("125.00"),
        )
        UserFeedback.objects.create(
            user=self.user,
            message="Please remove this with my account.",
            page="dashboard",
        )
        self.client.force_login(self.user)

    def deletion_payload(self, **overrides):
        payload = {
            "confirm_deletion": "on",
            "signature": "DELETE delete-me",
            "current_password": "good-password-123",
        }
        payload.update(overrides)
        return payload

    @override_settings(SUBSCRIPTIONS_ENABLED=True)
    def test_account_page_is_available_without_subscription_access(self):
        response = self.client.get(reverse("account_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DELETE delete-me")
        self.assertContains(response, "Permanently delete account")

    def test_dashboard_settings_include_the_account_tab(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'data-settings-tab="account"')
        self.assertContains(response, "DELETE delete-me")

    def test_every_server_side_confirmation_is_required(self):
        invalid_payloads = (
            self.deletion_payload(confirm_deletion=""),
            self.deletion_payload(signature="DELETE someone-else"),
            self.deletion_payload(current_password="wrong-password"),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(reverse("delete_user_account"), payload)

                self.assertEqual(response.status_code, 400)
                self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
                self.assertContains(
                    response,
                    "Account not deleted",
                    status_code=400,
                )

    def test_confirmed_deletion_removes_user_data_and_logs_out(self):
        response = self.client.post(
            reverse("delete_user_account"),
            self.deletion_payload(),
        )

        self.assertRedirects(response, reverse("login"))
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(BankAccount.objects.filter(pk=self.account.pk).exists())
        self.assertFalse(UserFeedback.objects.filter(user_id=self.user.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.other_user.pk).exists())
        self.assertNotIn("_auth_user_id", self.client.session)


class PricingPageTests(TestCase):
    def setUp(self):
        self.plan = SubscriptionPlan.objects.create(
            name="Darith Monthly",
            monthly_price=Decimal("8.00"),
            currency="eur",
            trial_days=45,
            is_active=True,
        )

    @override_settings(SUBSCRIPTIONS_ENABLED=True)
    def test_pricing_is_public_and_uses_the_active_admin_plan(self):
        response = self.client.get(reverse("pricing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Use Darith locally for free")
        self.assertContains(response, "Free for individuals")
        self.assertContains(response, "8.00")
        self.assertContains(response, "45-day hosted trial")
        self.assertContains(response, "A simple manual process.")
        self.assertContains(response, "No automatic card charge")
        self.assertContains(response, "https://buymeacoffee.com/darith")
        self.assertContains(response, "https://github.com/bfarnaghi/darith")

    @override_settings(SUBSCRIPTIONS_ENABLED=True)
    def test_signed_in_user_can_open_pricing_without_active_access(self):
        user = User.objects.create_user("pricing-user", password="good-password-123")
        self.client.force_login(user)

        response = self.client.get(reverse("pricing"))

        self.assertEqual(response.status_code, 200)


class ProductionSettingsTests(SimpleTestCase):
    production_environment = {
        "DJANGO_DEBUG": "false",
        "DJANGO_SECRET_KEY": (
            "production-check-only-0123456789abcdefghijklmnopqrstuvwxyz-ABCDEFG"
        ),
        "DJANGO_ALLOWED_HOSTS": "darith.app,www.darith.app",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://darith.app,https://www.darith.app",
        "DJANGO_DB_ENGINE": "postgresql",
        "DJANGO_DB_NAME": "darith",
        "DJANGO_DB_USER": "darith",
        "DJANGO_DB_PASSWORD": "production-check-password",
        "DJANGO_DB_HOST": "db.example.com",
        "DJANGO_DB_SSLMODE": "require",
    }

    def run_deployment_check(self, **overrides):
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("DJANGO_")
        }
        environment.update(self.production_environment)
        environment.update(overrides)
        return subprocess.run(
            [sys.executable, "-B", "manage.py", "check", "--deploy"],
            cwd=BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_secure_production_settings_pass_deployment_check(self):
        result = self.run_deployment_check()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("System check identified no issues", result.stdout)

    def test_production_uses_fingerprinted_static_files(self):
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("DJANGO_")
        }
        environment.update(self.production_environment)
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                (
                    "from darith.settings import STORAGES; "
                    "print(STORAGES['staticfiles']['BACKEND'])"
                ),
            ],
            cwd=BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ManifestStaticFilesStorage", result.stdout)

    def test_production_rejects_development_secret(self):
        result = self.run_deployment_check(DJANGO_SECRET_KEY="development-only-change-me")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set DJANGO_SECRET_KEY", result.stderr)

    def test_production_rejects_sqlite(self):
        result = self.run_deployment_check(DJANGO_DB_ENGINE="sqlite")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SQLite is only allowed", result.stderr)

    def test_production_rejects_unencrypted_postgres(self):
        result = self.run_deployment_check(DJANGO_DB_SSLMODE="disable")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_DB_SSLMODE must be", result.stderr)


class AdminPrivacyTests(TestCase):
    private_finance_models = (
        BankAccount,
        BudgetPreference,
        Expense,
        ExpenseCategory,
        Income,
        IncomeCategory,
        MonthlyExpense,
        RecurringIncome,
        SavingsGoal,
        Transfer,
        Token,
        PasskeyCredential,
    )

    def test_private_finance_models_are_not_registered_in_admin(self):
        for model in self.private_finance_models:
            self.assertNotIn(model, admin.site._registry)

        self.assertIn(User, admin.site._registry)
        self.assertIn(SubscriptionPlan, admin.site._registry)
        self.assertIn(UserSubscription, admin.site._registry)
        self.assertIn(UserFeedback, admin.site._registry)

    def test_admin_index_only_shows_identity_and_subscription_management(self):
        administrator = User.objects.create_superuser(
            "administrator", "admin@example.com", "good-password-123"
        )
        self.client.force_login(administrator)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Users")
        self.assertContains(response, "Subscription plans")
        self.assertContains(response, "User subscriptions")
        self.assertNotContains(response, "Bank accounts")
        self.assertNotContains(response, "Expenses")
        self.assertNotContains(response, "Income categories")


class DocumentationTests(SimpleTestCase):
    def test_deployment_guide_is_local_and_minimal(self):
        guide = (BASE_DIR / "DEPLOYMENT.md").read_text()

        self.assertIn("# Local Setup", guide)
        self.assertIn("python manage.py runserver", guide)
        self.assertIn("db.sqlite3", guide)
        self.assertNotIn("Nginx", guide)
        self.assertNotIn("systemd", guide)


class FinanceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ben", "ben@example.com", "good-password-123")
        self.other_user = User.objects.create_user(
            "other", "other@example.com", "good-password-123"
        )
        self.account = BankAccount.objects.create(
            user=self.user, name="Main", balance=Decimal("1000.00")
        )
        self.expense_category = ExpenseCategory.objects.create(
            user=self.user, name="Food"
        )
        self.income_category = IncomeCategory.objects.create(
            user=self.user, name="Salary"
        )
        self.client.force_login(self.user)

    def test_new_passwords_use_argon2(self):
        self.assertTrue(self.user.password.startswith("argon2$"))

    def test_home_is_a_public_product_page(self):
        self.client.logout()
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Personal money, made clear")
        self.assertContains(response, "No bank credentials")
        self.assertContains(response, "Private by account")
        self.assertContains(response, "Protected data storage")
        self.assertContains(response, "Limited admin view")
        self.assertContains(response, "Know what's safe to spend today.")
        self.assertContains(response, "See your safe-to-spend amount instantly.")
        self.assertContains(response, "Free for your own local setup.")
        self.assertContains(response, "45-day hosted trial")
        self.assertContains(response, "No card required")
        self.assertContains(response, "Daric")
        self.assertContains(response, "images/daric-coin.jpg")
        self.assertNotContains(response, 'class="hero-product"')
        self.assertNotContains(response, "animations")
        self.assertContains(response, reverse("create_account"))
        self.assertContains(response, "Try Darith free")
        self.assertContains(response, "Try Darith free for 45 days")
        self.assertContains(response, "Free self-hosted version")
        self.assertContains(response, "https://github.com/bfarnaghi/darith")
        self.assertContains(response, "images/darith-demo.gif")
        self.assertContains(response, "images/dashboard-mobile.png")
        self.assertContains(response, reverse("tutorial"))
        self.assertContains(response, reverse("pricing"))

        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open dashboard")

    def test_next_month_forecast_uses_estimated_closing_balance(self):
        self.account.balance = Decimal("200.00")
        self.account.save(update_fields=["balance"])
        BudgetPreference.objects.create(
            user=self.user,
            expected_daily_expense=Decimal("10.00"),
        )
        RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("1300.00"),
            start_date=date(2026, 8, 28),
            category=self.income_category,
            bank_account=self.account,
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="Rent",
            amount=Decimal("550.00"),
            start_date=date(2026, 8, 28),
            category=self.expense_category,
            bank_account=self.account,
        )

        current = build_monthly_budget(self.user, date(2026, 8, 14))
        forecast = build_next_month_forecast(
            self.user, date(2026, 8, 14), current
        )

        self.assertEqual(forecast["month_start"], date(2026, 9, 1))
        self.assertEqual(forecast["opening_balance"], Decimal("770.00"))
        self.assertEqual(forecast["expected_income"], Decimal("1300.00"))
        self.assertEqual(forecast["expected_expenses"], Decimal("550.00"))
        self.assertEqual(forecast["daily_expenses"], Decimal("300.00"))
        self.assertEqual(forecast["free_to_spend"], Decimal("470.00"))
        self.assertEqual(forecast["projected_balance"], Decimal("1220.00"))
        self.assertEqual(forecast["status"], "healthy")

    def test_next_month_forecast_includes_income_surplus_and_respects_income_end_date(self):
        BudgetPreference.objects.create(
            user=self.user,
            expected_daily_expense=Decimal("10.00"),
        )
        RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("1387.00"),
            start_date=date(2026, 8, 28),
            category=self.income_category,
            bank_account=self.account,
        )
        RecurringIncome.objects.create(
            user=self.user,
            name="August only income",
            amount=Decimal("257.04"),
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 30),
            category=self.income_category,
            bank_account=self.account,
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="September rent",
            amount=Decimal("330.00"),
            start_date=date(2026, 9, 1),
            category=self.expense_category,
            bank_account=self.account,
        )

        forecast = build_next_month_forecast(self.user, date(2026, 8, 18))

        self.assertEqual(forecast["expected_income"], Decimal("1387.00"))
        self.assertEqual(forecast["expected_expenses"], Decimal("330.00"))
        self.assertEqual(forecast["daily_expenses"], Decimal("300.00"))
        self.assertEqual(forecast["free_to_spend"], Decimal("1874.04"))
        self.assertEqual(forecast["projected_balance"], Decimal("3261.04"))
        self.assertEqual(forecast["status"], "healthy")

    def test_next_month_forecast_excludes_expense_after_its_end_date(self):
        MonthlyExpense.objects.create(
            user=self.user,
            name="Old rent",
            amount=Decimal("550.00"),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 30),
            category=self.expense_category,
            bank_account=self.account,
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="New rent",
            amount=Decimal("330.00"),
            start_date=date(2026, 9, 1),
            category=self.expense_category,
            bank_account=self.account,
        )

        forecast = build_next_month_forecast(self.user, date(2026, 8, 18))

        self.assertEqual(forecast["expected_expenses"], Decimal("330.00"))

    def test_daily_forecast_separates_next_month_opening_cash_from_safe_spending(self):
        self.account.balance = Decimal("527.14")
        self.account.save(update_fields=["balance"])
        BudgetPreference.objects.create(
            user=self.user,
            expected_daily_expense=Decimal("10.00"),
        )
        RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("1387.00"),
            start_date=date(2026, 9, 2),
            category=self.income_category,
            bank_account=self.account,
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="September commitments",
            amount=Decimal("597.95"),
            start_date=date(2026, 9, 10),
            category=self.expense_category,
            bank_account=self.account,
        )
        SavingsGoal.objects.create(
            user=self.user,
            name="September savings",
            monthly_amount=Decimal("503.85"),
            start_date=date(2026, 9, 30),
            current_balance=Decimal("0.00"),
            bank_account=self.account,
        )

        forecast = build_daily_forecast(self.user, date(2026, 8, 18))
        september_first = next(
            row for row in forecast["rows"] if row["date"] == date(2026, 9, 1)
        )
        september_end = next(
            row for row in forecast["rows"] if row["date"] == date(2026, 9, 30)
        )

        self.assertEqual(september_first["opening_balance"], Decimal("387.14"))
        self.assertEqual(september_first["remaining_daily_costs"], Decimal("300.00"))
        self.assertEqual(september_first["safe_to_spend"], Decimal("87.14"))
        self.assertEqual(september_end["closing_balance"], Decimal("372.34"))

    def test_daily_forecast_detects_liquidity_gap_when_bill_arrives_before_salary(self):
        self.account.balance = Decimal("397.14")
        self.account.save(update_fields=["balance"])
        BudgetPreference.objects.create(
            user=self.user,
            expected_daily_expense=Decimal("10.00"),
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="Rent",
            amount=Decimal("330.00"),
            start_date=date(2026, 9, 1),
            category=self.expense_category,
            bank_account=self.account,
        )
        RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("1387.00"),
            start_date=date(2026, 9, 28),
            category=self.income_category,
            bank_account=self.account,
        )

        forecast = build_daily_forecast(self.user, date(2026, 8, 31))
        september_first = next(
            row for row in forecast["rows"] if row["date"] == date(2026, 9, 1)
        )

        self.assertEqual(september_first["opening_balance"], Decimal("387.14"))
        self.assertEqual(september_first["day_headroom"], Decimal("87.14"))
        self.assertEqual(september_first["safe_to_spend"], Decimal("-242.86"))
        self.assertEqual(september_first["status"], "danger")

    def test_security_settings_hash_pin_and_require_unlock_method(self):
        response = self.client.post(
            reverse("update_security_settings"),
            {"lock_timeout_minutes": "5", "new_pin": "4286", "confirm_pin": "4286"},
        )
        self.assertRedirects(response, f"{reverse('dashboard')}?tab=overview")
        preference = BudgetPreference.objects.get(user=self.user)
        self.assertEqual(preference.lock_timeout_minutes, 5)
        self.assertNotEqual(preference.darith_pin_hash, "4286")
        self.assertTrue(check_password("4286", preference.darith_pin_hash))

        preference.darith_pin_hash = ""
        preference.lock_timeout_minutes = 0
        preference.save(update_fields=["darith_pin_hash", "lock_timeout_minutes"])
        self.client.post(
            reverse("update_security_settings"),
            {"lock_timeout_minutes": "1", "new_pin": "", "confirm_pin": ""},
        )
        preference.refresh_from_db()
        self.assertEqual(preference.lock_timeout_minutes, 0)

    def test_inactivity_lock_redirects_and_pin_unlocks(self):
        preference = BudgetPreference.objects.create(
            user=self.user,
            lock_timeout_minutes=1,
            darith_pin_hash=make_password("4286"),
        )
        self.client.get(reverse("dashboard"))
        session = self.client.session
        session["darith_last_activity"] = time.time() - 61
        session.save()

        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("session_locked"), fetch_redirect_response=False)
        self.assertTrue(self.client.session["darith_locked"])
        self.assertEqual(self.client.get(reverse("session_locked")).status_code, 200)

        response = self.client.post(reverse("security_unlock"), {"pin": "4286"})
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFalse(self.client.session["darith_locked"])
        preference.refresh_from_db()
        self.assertEqual(preference.lock_timeout_minutes, 1)

    def test_passkey_options_are_scoped_to_current_user(self):
        credential = PasskeyCredential.objects.create(
            user=self.user,
            name="Laptop",
            credential_id=b"credential-one",
            public_key=b"public-key",
            transports=["internal"],
        )
        PasskeyCredential.objects.create(
            user=self.other_user,
            name="Other device",
            credential_id=b"credential-two",
            public_key=b"other-public-key",
        )

        response = self.client.post(reverse("passkey_unlock_options"))
        self.assertEqual(response.status_code, 200)
        options = response.json()
        self.assertEqual(len(options["allowCredentials"]), 1)
        self.assertEqual(options["allowCredentials"][0]["transports"], ["internal"])
        self.assertIsNotNone(options["challenge"])
        self.assertEqual(credential.user, self.user)

        registration_response = self.client.post(
            reverse("passkey_registration_options")
        )
        self.assertEqual(registration_response.status_code, 200)
        registration_options = registration_response.json()
        self.assertEqual(registration_options["rp"]["id"], "testserver")
        self.assertEqual(registration_options["user"]["name"], self.user.username)
        self.assertEqual(
            registration_options["authenticatorSelection"]["userVerification"],
            "required",
        )

    @patch("web.views.notify_feedback")
    def test_feedback_is_saved_for_signed_in_user(self, notify_feedback_mock):
        response = self.client.post(
            reverse("submit_feedback"),
            {"message": "The monthly view is useful.", "page": "dashboard", "tab": "overview"},
        )
        self.assertRedirects(response, f"{reverse('dashboard')}?tab=overview")
        feedback = UserFeedback.objects.get()
        self.assertEqual(feedback.user, self.user)
        self.assertEqual(feedback.message, "The monthly view is useful.")
        notify_feedback_mock.assert_called_once_with(feedback)

    def test_dashboard_gif_is_validated_and_private_to_its_owner(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root
        ):
            response = self.client.post(
                reverse("update_dashboard_animations"),
                {
                    "healthy_gif": SimpleUploadedFile(
                        "normal.gif", VALID_GIF, content_type="image/gif"
                    )
                },
            )

            self.assertRedirects(response, f"{reverse('dashboard')}?tab=overview")
            preference = BudgetPreference.objects.get(user=self.user)
            self.assertTrue(preference.healthy_gif.name.endswith(".gif"))
            self.assertNotIn("normal.gif", preference.healthy_gif.name)

            response = self.client.get(
                reverse("dashboard_animation", args=["healthy"])
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/gif")
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(b"".join(response.streaming_content), VALID_GIF)

            self.client.force_login(self.other_user)
            response = self.client.get(
                reverse("dashboard_animation", args=["healthy"])
            )
            self.assertEqual(response.status_code, 404)

    def test_profile_picture_is_validated_private_and_removable(self):
        profile_bytes = valid_profile_png()
        with tempfile.TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root
        ):
            response = self.client.post(
                reverse("update_dashboard_animations"),
                {
                    "profile_picture": SimpleUploadedFile(
                        "portrait.png", profile_bytes, content_type="image/png"
                    )
                },
            )

            self.assertRedirects(response, f"{reverse('dashboard')}?tab=overview")
            preference = BudgetPreference.objects.get(user=self.user)
            self.assertIn(f"profile-pictures/{self.user.id}/", preference.profile_picture.name)
            self.assertNotIn("portrait.png", preference.profile_picture.name)
            profile_path = preference.profile_picture.path

            response = self.client.get(reverse("profile_picture"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(b"".join(response.streaming_content), profile_bytes)
            self.assertContains(self.client.get(reverse("dashboard")), reverse("profile_picture"))

            self.client.force_login(self.other_user)
            self.assertEqual(self.client.get(reverse("profile_picture")).status_code, 404)
            self.client.force_login(self.user)

            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("remove_profile_picture"))

            self.assertRedirects(response, f"{reverse('dashboard')}?tab=overview")
            preference.refresh_from_db()
            self.assertFalse(preference.profile_picture)
            self.assertFalse(os.path.exists(profile_path))

    def test_profile_picture_rejects_files_larger_than_two_megabytes(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root
        ):
            self.client.post(
                reverse("update_dashboard_animations"),
                {
                    "profile_picture": SimpleUploadedFile(
                        "oversized.png",
                        b"0" * ((2 * 1024 * 1024) + 1),
                        content_type="image/png",
                    )
                },
            )

            preference = BudgetPreference.objects.get(user=self.user)
            self.assertFalse(preference.profile_picture)

    def test_dashboard_gif_can_be_replaced_and_removed_with_a_button(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root
        ):
            self.client.post(
                reverse("update_dashboard_animations"),
                {
                    "healthy_gif": SimpleUploadedFile(
                        "first.gif", VALID_GIF, content_type="image/gif"
                    )
                },
            )
            preference = BudgetPreference.objects.get(user=self.user)
            first_path = preference.healthy_gif.path
            self.assertTrue(os.path.exists(first_path))

            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(
                    reverse("update_dashboard_animations"),
                    {
                        "healthy_gif": SimpleUploadedFile(
                            "replacement.gif", VALID_GIF, content_type="image/gif"
                        )
                    },
                )

            preference.refresh_from_db()
            replacement_path = preference.healthy_gif.path
            self.assertNotEqual(first_path, replacement_path)
            self.assertFalse(os.path.exists(first_path))
            self.assertTrue(os.path.exists(replacement_path))
            self.assertContains(self.client.get(reverse("dashboard")), "Remove GIF")

            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse("remove_dashboard_gif", args=["healthy"])
                )

            self.assertRedirects(response, f"{reverse('dashboard')}?tab=overview")
            preference.refresh_from_db()
            self.assertFalse(preference.healthy_gif)
            self.assertFalse(os.path.exists(replacement_path))
            self.assertEqual(
                self.client.get(
                    reverse("dashboard_animation", args=["healthy"])
                ).status_code,
                404,
            )

    def test_dashboard_gif_rejects_invalid_content_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root
        ):
            self.client.post(
                reverse("update_dashboard_animations"),
                {
                    "warning_gif": SimpleUploadedFile(
                        "warning.gif", b"not really a gif", content_type="image/gif"
                    )
                },
            )
            preference = BudgetPreference.objects.get(user=self.user)
            self.assertFalse(preference.warning_gif)

            self.client.post(
                reverse("update_dashboard_animations"),
                {
                    "danger_gif": SimpleUploadedFile(
                        "danger.gif",
                        b"GIF89a" + (b"0" * (2 * 1024 * 1024)),
                        content_type="image/gif",
                    )
                },
            )
            preference.refresh_from_db()
            self.assertFalse(preference.danger_gif)

    def test_dashboard_uses_the_gif_for_the_current_budget_state(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root
        ):
            preference = BudgetPreference.objects.create(
                user=self.user,
                expected_daily_expense=Decimal("9999.00"),
                danger_gif=SimpleUploadedFile(
                    "danger.gif", VALID_GIF, content_type="image/gif"
                ),
            )

            response = self.client.get(reverse("dashboard"))

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["budget"]["status"], "danger")
            self.assertTrue(response.context["active_budget_animation"])
            self.assertContains(
                response, reverse("dashboard_animation", args=["danger"])
            )
            self.assertTrue(preference.danger_gif)

    def test_dashboard_theme_and_currency_are_saved_for_only_the_signed_in_user(self):
        response = self.client.post(
            reverse("update_dashboard_animations"),
            {"theme": "purple", "currency": "USD"},
        )

        self.assertRedirects(response, f"{reverse('dashboard')}?tab=overview")
        preference = BudgetPreference.objects.get(user=self.user)
        self.assertEqual(preference.theme, BudgetPreference.THEME_PURPLE)
        self.assertEqual(preference.currency, BudgetPreference.CURRENCY_USD)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'data-theme="purple"')
        self.assertContains(response, "$1,000.00")

        self.client.force_login(self.other_user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'data-theme="ocean"')
        self.assertContains(response, "€0.00")

    def test_iranian_toman_can_be_selected_as_the_display_currency(self):
        response = self.client.post(
            reverse("update_dashboard_animations"),
            {"currency": "IRT"},
        )

        self.assertRedirects(response, f"{reverse('dashboard')}?tab=overview")
        preference = BudgetPreference.objects.get(user=self.user)
        self.assertEqual(preference.currency, BudgetPreference.CURRENCY_IRT)
        self.assertContains(self.client.get(reverse("dashboard")), "IRT 1,000.00")

    def test_financial_visibility_is_saved_per_user_and_masks_dashboard_amounts(self):
        response = self.client.post(reverse("toggle_financial_visibility"))

        self.assertRedirects(response, f"{reverse('dashboard')}?tab=overview")
        preference = BudgetPreference.objects.get(user=self.user)
        self.assertTrue(preference.hide_financial_values)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'data-values-hidden="true"')
        self.assertContains(response, "******")
        self.assertGreaterEqual(response.content.count(b"******"), 10)
        self.assertContains(response, 'aria-label="Show amounts"')

        self.client.force_login(self.other_user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'data-values-hidden="false"')
        self.assertContains(response, 'aria-label="Hide amounts"')

    def test_csv_export_contains_only_the_signed_in_users_data(self):
        Expense.objects.create(
            user=self.user,
            text="Coffee",
            amount=Decimal("12.50"),
            date=date(2026, 8, 14),
            category=self.expense_category,
            bank_account=self.account,
        )
        BankAccount.objects.create(
            user=self.other_user,
            name="Other user secret account",
            balance=Decimal("9999.00"),
        )
        BankAccount.objects.create(
            user=self.user,
            name="=SUM(1,1)",
            balance=Decimal("20.00"),
        )

        response = self.client.get(reverse("export_data_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("attachment;", response["Content-Disposition"])
        content = response.content.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(content)))
        self.assertNotIn("Other user secret account", content)
        self.assertTrue(
            any(
                row["record_type"] == "bank_account"
                and row["name"] == "Main"
                and row["currency"] == "EUR"
                and row["included_in_budget"] == "yes"
                for row in rows
            )
        )
        self.assertTrue(
            any(
                row["record_type"] == "expense"
                and row["name"] == "Coffee"
                and row["amount"] == "-12.50"
                for row in rows
            )
        )
        self.assertTrue(
            any(
                row["record_type"] == "bank_account"
                and row["name"] == "'=SUM(1,1)"
                for row in rows
            )
        )

    def test_csv_export_uses_the_users_display_currency(self):
        BudgetPreference.objects.create(
            user=self.user, currency=BudgetPreference.CURRENCY_GBP
        )

        response = self.client.get(reverse("export_data_csv"))
        rows = list(
            csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
        )

        self.assertTrue(rows)
        self.assertTrue(all(row["currency"] == "GBP" for row in rows))

    def test_dashboard_requires_login_and_renders_budget(self):
        self.client.logout()
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Safe to spend today")
        self.assertContains(response, "Your money timeline")
        self.assertContains(response, "1,000.00")

    def test_create_update_and_delete_expense_adjusts_balance(self):
        response = self.client.post(
            reverse("create_expense"),
            {
                "text": "Groceries",
                "amount": "75.50",
                "date": "2026-08-10",
                "category": self.expense_category.id,
                "bank_account": self.account.id,
            },
        )
        self.assertEqual(response.status_code, 302)
        expense = Expense.objects.get(text="Groceries")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("924.50"))

        self.client.post(
            reverse("update_expense", args=[expense.id]),
            {
                "text": "Groceries and lunch",
                "amount": "100.00",
                "date": "2026-08-10",
                "category": self.expense_category.id,
                "bank_account": self.account.id,
            },
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("900.00"))

        self.client.post(reverse("delete_expense", args=[expense.id]))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertFalse(Expense.objects.filter(pk=expense.id).exists())

    def test_manual_deletion_mode_leaves_expense_balance_unchanged(self):
        BudgetPreference.objects.create(
            user=self.user,
            transaction_deletion_mode=BudgetPreference.DELETE_BALANCE_MANUAL,
        )
        self.client.post(
            reverse("create_expense"),
            {
                "text": "Manual correction",
                "amount": "100.00",
                "date": "2026-08-14",
                "category": self.expense_category.id,
                "bank_account": self.account.id,
            },
        )
        expense = Expense.objects.get(text="Manual correction")

        response = self.client.post(reverse("delete_expense", args=[expense.id]), follow=True)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("900.00"))
        self.assertFalse(Expense.objects.filter(pk=expense.id).exists())
        self.assertContains(response, "bank balance was left unchanged")

    def test_manual_deletion_mode_leaves_income_balance_unchanged(self):
        BudgetPreference.objects.create(
            user=self.user,
            transaction_deletion_mode=BudgetPreference.DELETE_BALANCE_MANUAL,
        )
        self.client.post(
            reverse("create_income"),
            {
                "text": "Manual income",
                "amount": "100.00",
                "date": "2026-08-14",
                "category": self.income_category.id,
                "bank_account": self.account.id,
            },
        )
        income = Income.objects.get(text="Manual income")

        self.client.post(reverse("delete_income", args=[income.id]))

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1100.00"))
        self.assertFalse(Income.objects.filter(pk=income.id).exists())

    def test_income_can_move_between_accounts_when_edited(self):
        savings = BankAccount.objects.create(
            user=self.user, name="Savings", balance=Decimal("250.00")
        )
        self.client.post(
            reverse("create_income"),
            {
                "text": "Bonus",
                "amount": "200.00",
                "date": "2026-08-10",
                "category": self.income_category.id,
                "bank_account": self.account.id,
            },
        )
        income = Income.objects.get(text="Bonus")
        self.client.post(
            reverse("update_income", args=[income.id]),
            {
                "text": "Bonus",
                "amount": "300.00",
                "date": "2026-08-10",
                "category": self.income_category.id,
                "bank_account": savings.id,
            },
        )
        self.account.refresh_from_db()
        savings.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertEqual(savings.balance, Decimal("550.00"))

    def test_future_manual_transaction_is_rejected(self):
        response = self.client.post(
            reverse("create_expense"),
            {
                "text": "Future",
                "amount": "10.00",
                "date": "2099-01-01",
                "category": self.expense_category.id,
                "bank_account": self.account.id,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Expense.objects.filter(text="Future").exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))

    def test_recurring_income_posts_month_end_once(self):
        plan = RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("100.00"),
            start_date=date(2026, 1, 31),
            end_date=date(2026, 2, 28),
            category=self.income_category,
            bank_account=self.account,
        )
        self.assertEqual(post_due_recurring(self.user, date(2026, 2, 28)), 2)
        self.assertEqual(post_due_recurring(self.user, date(2026, 2, 28)), 0)
        self.assertEqual(
            list(plan.posted_incomes.order_by("date").values_list("date", flat=True)),
            [date(2026, 1, 31), date(2026, 2, 28)],
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1200.00"))

    def test_deleting_posted_recurring_income_suppresses_that_month(self):
        plan = RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("100.00"),
            start_date=date(2026, 8, 10),
            category=self.income_category,
            bank_account=self.account,
        )
        post_due_recurring(self.user, date(2026, 8, 14))
        income = plan.posted_incomes.get()

        self.client.post(reverse("delete_income", args=[income.pk]))

        income.refresh_from_db()
        self.assertTrue(income.is_skipped)
        self.assertEqual(post_due_recurring(self.user, date(2026, 8, 14)), 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))

    def test_recurring_expense_posts_and_updates_balance(self):
        plan = MonthlyExpense.objects.create(
            user=self.user,
            name="Rent",
            amount=Decimal("450.00"),
            start_date=date(2026, 8, 5),
            end_date=None,
            category=self.expense_category,
            bank_account=self.account,
        )
        self.assertEqual(post_due_recurring(self.user, date(2026, 8, 14)), 1)
        expense = plan.posted_expenses.get()
        self.assertEqual(expense.date, date(2026, 8, 5))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("550.00"))

    def test_deleting_a_posted_monthly_expense_does_not_recreate_it(self):
        plan = MonthlyExpense.objects.create(
            user=self.user,
            name="Rent",
            amount=Decimal("450.00"),
            start_date=date(2026, 8, 5),
            category=self.expense_category,
            bank_account=self.account,
        )
        post_due_recurring(self.user, date(2026, 8, 14))
        expense = plan.posted_expenses.get()

        response = self.client.post(reverse("delete_expense", args=[expense.pk]))

        self.assertRedirects(response, f"{reverse('dashboard')}?tab=transactions")
        expense.refresh_from_db()
        self.assertTrue(expense.is_skipped)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertEqual(post_due_recurring(self.user, date(2026, 8, 14)), 0)
        self.assertEqual(
            build_monthly_budget(self.user, date(2026, 8, 14))["actual_expenses"],
            Decimal("0.00"),
        )

        dashboard_response = self.client.get(reverse("dashboard"))
        transaction_ids = {
            (item["kind"], item["id"])
            for item in dashboard_response.context["transactions"]
        }
        self.assertNotIn(("expense", expense.pk), transaction_ids)

        self.assertEqual(post_due_recurring(self.user, date(2026, 9, 5)), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("550.00"))

    def test_deleting_monthly_expense_plan_stops_future_postings(self):
        plan = MonthlyExpense.objects.create(
            user=self.user,
            name="Membership",
            amount=Decimal("20.00"),
            start_date=date(2026, 9, 1),
            category=self.expense_category,
            bank_account=self.account,
        )

        response = self.client.post(
            reverse("delete_monthly_expense", args=[plan.pk])
        )

        self.assertRedirects(response, f"{reverse('dashboard')}?tab=plans")
        self.assertFalse(MonthlyExpense.objects.filter(pk=plan.pk).exists())
        self.assertEqual(post_due_recurring(self.user, date(2026, 10, 1)), 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))

    def test_future_monthly_expense_is_reserved_before_it_is_charged(self):
        MonthlyExpense.objects.create(
            user=self.user,
            name="Insurance",
            amount=Decimal("120.00"),
            start_date=date(2026, 8, 20),
            category=self.expense_category,
            bank_account=self.account,
        )

        budget = build_monthly_budget(self.user, date(2026, 8, 14))

        self.assertEqual(budget["expected_expenses"], Decimal("120.00"))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertEqual(post_due_recurring(self.user, date(2026, 8, 19)), 0)
        self.assertEqual(post_due_recurring(self.user, date(2026, 8, 20)), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("880.00"))

    def test_monthly_budget_projects_plans_and_savings(self):
        RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("2000.00"),
            start_date=date(2026, 8, 25),
            category=self.income_category,
            bank_account=self.account,
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="Rent",
            amount=Decimal("500.00"),
            start_date=date(2026, 8, 20),
            category=self.expense_category,
            bank_account=self.account,
        )
        SavingsGoal.objects.create(
            user=self.user,
            name="Emergency fund",
            monthly_amount=Decimal("400.00"),
            start_date=date(2026, 1, 1),
        )

        budget = build_monthly_budget(self.user, date(2026, 8, 14))
        self.assertEqual(budget["expected_income"], Decimal("2000.00"))
        self.assertEqual(budget["expected_expenses"], Decimal("500.00"))
        self.assertEqual(budget["savings_target"], Decimal("400.00"))
        self.assertEqual(budget["projected_balance"], Decimal("2100.00"))
        self.assertEqual(budget["free_to_spend"], Decimal("100.00"))
        self.assertEqual(budget["status"], "healthy")

    def test_tracking_only_account_is_excluded_from_monthly_budget(self):
        tracking_account = BankAccount.objects.create(
            user=self.user,
            name="Cash reserve",
            balance=Decimal("500.00"),
            include_in_budget=False,
        )
        Income.objects.create(
            user=self.user,
            text="Tracked income",
            amount=Decimal("200.00"),
            date=date(2026, 8, 10),
            category=self.income_category,
            bank_account=tracking_account,
        )
        Expense.objects.create(
            user=self.user,
            text="Tracked expense",
            amount=Decimal("50.00"),
            date=date(2026, 8, 11),
            category=self.expense_category,
            bank_account=tracking_account,
        )
        RecurringIncome.objects.create(
            user=self.user,
            name="Tracked future income",
            amount=Decimal("300.00"),
            start_date=date(2026, 8, 20),
            category=self.income_category,
            bank_account=tracking_account,
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="Tracked future expense",
            amount=Decimal("75.00"),
            start_date=date(2026, 8, 22),
            category=self.expense_category,
            bank_account=tracking_account,
        )
        SavingsGoal.objects.create(
            user=self.user,
            name="Tracked saving",
            monthly_amount=Decimal("100.00"),
            start_date=date(2026, 1, 1),
            bank_account=tracking_account,
        )

        budget = build_monthly_budget(self.user, date(2026, 8, 14))

        self.assertEqual(budget["current_balance"], Decimal("1000.00"))
        self.assertEqual(budget["included_account_count"], 1)
        self.assertEqual(budget["actual_income"], Decimal("0.00"))
        self.assertEqual(budget["actual_expenses"], Decimal("0.00"))
        self.assertEqual(budget["expected_income"], Decimal("0.00"))
        self.assertEqual(budget["expected_expenses"], Decimal("0.00"))
        self.assertEqual(budget["savings_target"], Decimal("0.00"))
        self.assertEqual(budget["upcoming"], [])

    def test_future_surplus_changes_outlook_without_becoming_spendable_early(self):
        self.account.balance = Decimal("200.00")
        self.account.save()
        BudgetPreference.objects.create(
            user=self.user,
            expected_daily_expense=Decimal("10.00"),
        )
        RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("1300.00"),
            start_date=date(2026, 8, 28),
            end_date=date(2026, 8, 28),
            category=self.income_category,
            bank_account=self.account,
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="Rent",
            amount=Decimal("550.00"),
            start_date=date(2026, 8, 28),
            end_date=date(2026, 8, 28),
            category=self.expense_category,
            bank_account=self.account,
        )

        budget = build_monthly_budget(self.user, date(2026, 8, 14))

        self.assertEqual(budget["current_balance"], Decimal("200.00"))
        self.assertEqual(budget["expected_income"], Decimal("1300.00"))
        self.assertEqual(budget["expected_expenses"], Decimal("550.00"))
        self.assertEqual(budget["actual_income"], Decimal("0.00"))
        self.assertEqual(budget["actual_expenses"], Decimal("0.00"))
        self.assertEqual(budget["remaining_daily_expenses"], Decimal("180.00"))
        self.assertEqual(budget["uncovered_future_expenses"], Decimal("0.00"))
        self.assertEqual(budget["free_to_spend"], Decimal("20.00"))
        self.assertEqual(budget["projected_balance"], Decimal("770.00"))

        with patch("web.views.timezone.localdate", return_value=date(2026, 8, 14)):
            response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "€0.00 received so far")
        self.assertContains(response, "€1,300.00 still due")
        self.assertContains(response, "First payment date")
        self.assertContains(response, "First charge date")

    def test_budget_warns_when_commitments_are_not_covered(self):
        self.account.balance = Decimal("100.00")
        self.account.save()
        SavingsGoal.objects.create(
            user=self.user,
            name="Emergency fund",
            monthly_amount=Decimal("400.00"),
            start_date=date(2026, 1, 1),
        )
        budget = build_monthly_budget(self.user, date(2026, 8, 14))
        self.assertEqual(budget["free_to_spend"], Decimal("-700.00"))
        self.assertEqual(budget["status"], "danger")
        self.assertIn("projected", budget["warning"])

    def test_user_cannot_edit_another_users_account(self):
        private_account = BankAccount.objects.create(
            user=self.other_user, name="Private", balance=Decimal("900.00")
        )
        response = self.client.post(
            reverse("update_bank_account", args=[private_account.id]),
            {"name": "Stolen", "balance": "0.00"},
        )
        self.assertEqual(response.status_code, 404)
        private_account.refresh_from_db()
        self.assertEqual(private_account.name, "Private")
        self.assertEqual(private_account.balance, Decimal("900.00"))

    def test_bank_account_crud(self):
        self.client.post(
            reverse("create_bank_account"),
            {
                "name": "Travel",
                "balance": "300.00",
                "include_in_budget": "on",
            },
        )
        account = BankAccount.objects.get(user=self.user, name="Travel")
        self.assertTrue(account.include_in_budget)
        self.client.post(
            reverse("update_bank_account", args=[account.id]),
            {"name": "Holiday", "balance": "450.00"},
        )
        account.refresh_from_db()
        self.assertEqual(account.name, "Holiday")
        self.assertEqual(account.balance, Decimal("450.00"))
        self.assertFalse(account.include_in_budget)
        self.assertContains(self.client.get(reverse("dashboard")), "Tracking only")
        self.client.post(reverse("delete_bank_account", args=[account.id]))
        self.assertFalse(BankAccount.objects.filter(pk=account.id).exists())

    def test_recurring_plan_and_savings_goal_crud(self):
        self.client.post(
            reverse("create_recurring_income"),
            {
                "name": "Contract",
                "amount": "800.00",
                "start_date": "2027-01-15",
                "end_date": "2027-12-15",
                "category": self.income_category.id,
                "bank_account": self.account.id,
            },
        )
        plan = RecurringIncome.objects.get(user=self.user, name="Contract")
        self.client.post(
            reverse("update_recurring_income", args=[plan.id]),
            {
                "name": "Client contract",
                "amount": "900.00",
                "start_date": "2027-01-15",
                "end_date": "2027-12-15",
                "category": self.income_category.id,
                "bank_account": self.account.id,
            },
        )
        plan.refresh_from_db()
        self.assertEqual(plan.amount, Decimal("900.00"))
        self.client.post(reverse("delete_recurring_income", args=[plan.id]))
        self.assertFalse(RecurringIncome.objects.filter(pk=plan.id).exists())

        self.client.post(
            reverse("create_savings_goal"),
            {
                "name": "Holiday",
                "monthly_amount": "150.00",
                "start_date": "2027-01-01",
                "current_balance": "0.00",
                "target_amount": "",
                "target_date": "",
                "bank_account": self.account.id,
            },
        )
        goal = SavingsGoal.objects.get(user=self.user, name="Holiday")
        self.client.post(reverse("delete_savings_goal", args=[goal.id]))
        goal.refresh_from_db()
        self.assertTrue(goal.is_archived)

    def test_category_crud(self):
        self.client.post(reverse("create_category", args=["expense"]), {"name": "Travel"})
        category = ExpenseCategory.objects.get(user=self.user, name="Travel")
        self.client.post(
            reverse("update_category", args=["expense", category.id]),
            {"name": "Trips"},
        )
        category.refresh_from_db()
        self.assertEqual(category.name, "Trips")
        self.client.post(reverse("delete_category", args=["expense", category.id]))
        self.assertFalse(ExpenseCategory.objects.filter(pk=category.id).exists())

    def test_deleting_account_keeps_transaction_history(self):
        expense = Expense.objects.create(
            user=self.user,
            text="Coffee",
            amount=Decimal("3.00"),
            date=date(2026, 8, 1),
            category=self.expense_category,
            bank_account=self.account,
        )
        self.client.post(reverse("delete_bank_account", args=[self.account.id]))
        expense.refresh_from_db()
        self.assertIsNone(expense.bank_account)


    def test_daily_expense_shortfall_warns_that_savings_may_be_needed(self):
        self.account.balance = Decimal("50.00")
        self.account.save()
        BudgetPreference.objects.create(
            user=self.user, expected_daily_expense=Decimal("5.00")
        )
        SavingsGoal.objects.create(
            user=self.user,
            name="Emergency",
            monthly_amount=Decimal("10.00"),
            start_date=date(2026, 1, 1),
            target_amount=Decimal("100.00"),
            target_date=date(2026, 7, 31),
            current_balance=Decimal("100.00"),
            bank_account=self.account,
        )

        budget = build_monthly_budget(self.user, date(2026, 8, 14))

        self.assertEqual(budget["days_remaining"], 18)
        self.assertEqual(budget["remaining_daily_expenses"], Decimal("90.00"))
        self.assertEqual(budget["free_to_spend"], Decimal("-190.00"))
        self.assertEqual(budget["status"], "danger")
        self.assertIn("projected", budget["warning"])

    def test_bank_transfer_create_update_and_delete_reverses_balances(self):
        second = BankAccount.objects.create(
            user=self.user, name="Second", balance=Decimal("100.00")
        )
        self.client.post(
            reverse("create_transfer"),
            {
                "name": "Move cash",
                "amount": "250.00",
                "date": "2026-08-14",
                "source": f"bank:{self.account.id}",
                "destination": f"bank:{second.id}",
            },
        )
        transfer = Transfer.objects.get(name="Move cash")
        self.account.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("750.00"))
        self.assertEqual(second.balance, Decimal("350.00"))

        self.client.post(
            reverse("update_transfer", args=[transfer.id]),
            {
                "name": "Smaller move",
                "amount": "150.00",
                "date": "2026-08-14",
                "source": f"bank:{self.account.id}",
                "destination": f"bank:{second.id}",
            },
        )
        self.account.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("850.00"))
        self.assertEqual(second.balance, Decimal("250.00"))

        self.client.post(reverse("delete_transfer", args=[transfer.id]))
        self.account.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertEqual(second.balance, Decimal("100.00"))

    def test_manual_deletion_mode_leaves_transfer_balances_unchanged(self):
        BudgetPreference.objects.create(
            user=self.user,
            transaction_deletion_mode=BudgetPreference.DELETE_BALANCE_MANUAL,
        )
        second = BankAccount.objects.create(
            user=self.user, name="Manual destination", balance=Decimal("100.00")
        )
        self.client.post(
            reverse("create_transfer"),
            {
                "name": "Manual transfer",
                "amount": "250.00",
                "date": "2026-08-14",
                "source": f"bank:{self.account.id}",
                "destination": f"bank:{second.id}",
            },
        )
        transfer = Transfer.objects.get(name="Manual transfer")

        self.client.post(reverse("delete_transfer", args=[transfer.id]))

        self.account.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("750.00"))
        self.assertEqual(second.balance, Decimal("350.00"))
        self.assertFalse(Transfer.objects.filter(pk=transfer.id).exists())

    def test_dated_goal_calculates_and_funds_monthly_amount_once(self):
        response = self.client.post(
            reverse("create_savings_goal"),
            {
                "name": "Bicycle",
                "monthly_amount": "",
                "target_amount": "600.00",
                "target_date": "2026-09-30",
                "current_balance": "0.00",
                "start_date": "2026-08-01",
                "bank_account": self.account.id,
            },
        )
        self.assertEqual(response.status_code, 302)
        goal = SavingsGoal.objects.get(name="Bicycle")
        self.assertEqual(goal.monthly_amount, Decimal("300.00"))

        with patch("web.views.timezone.localdate", return_value=date(2026, 8, 14)):
            self.client.post(reverse("fund_savings_goal", args=[goal.id]))
            self.client.post(reverse("fund_savings_goal", args=[goal.id]))

        goal.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(goal.current_balance, Decimal("300.00"))
        self.assertEqual(self.account.balance, Decimal("700.00"))
        self.assertEqual(
            Transfer.objects.filter(destination_goal=goal).count(),
            1,
        )
        self.assertEqual(goal_funding_reminders(self.user, date(2026, 8, 14)), [])

    def test_month_end_outlook_reserves_saving_scheduled_later_this_month(self):
        BudgetPreference.objects.create(
            user=self.user,
            expected_daily_expense=Decimal("10.00"),
        )
        SavingsGoal.objects.create(
            user=self.user,
            name="DL",
            monthly_amount=Decimal("50.00"),
            start_date=date(2026, 8, 30),
            target_amount=Decimal("150.00"),
            target_date=date(2026, 10, 30),
            current_balance=Decimal("0.00"),
            bank_account=self.account,
        )

        budget = build_monthly_budget(self.user, date(2026, 8, 18))

        # It is not actionable before 30 August, so the immediate saving-due
        # figure stays zero. The month-end outlook must still reserve it.
        self.assertEqual(budget["savings_target"], Decimal("0.00"))
        self.assertEqual(budget["month_end_savings_target"], Decimal("50.00"))
        self.assertEqual(budget["remaining_daily_expenses"], Decimal("140.00"))
        self.assertEqual(budget["projected_balance"], Decimal("810.00"))
        self.assertEqual(budget["free_to_spend"], Decimal("460.00"))

    def test_dated_goal_keeps_fixed_monthly_amount_in_later_months(self):
        response = self.client.post(
            reverse("create_savings_goal"),
            {
                "name": "DL",
                "monthly_amount": "",
                "target_amount": "150.00",
                "target_date": "2026-10-30",
                "current_balance": "0.00",
                "start_date": "2026-08-30",
                "bank_account": self.account.id,
            },
        )
        self.assertEqual(response.status_code, 302)
        goal = SavingsGoal.objects.get(name="DL")
        self.assertEqual(goal.monthly_amount, Decimal("50.00"))
        self.assertEqual(
            goal_monthly_contribution(goal, date(2026, 9, 1)),
            Decimal("50.00"),
        )

        goal.current_balance = Decimal("140.00")
        goal.save(update_fields=["current_balance"])
        self.assertEqual(
            goal_monthly_contribution(goal, date(2026, 10, 1)),
            Decimal("10.00"),
        )

    def test_mark_saved_handles_nearly_complete_goal_without_server_error(self):
        self.account.balance = Decimal("770.00")
        self.account.save()
        goal = SavingsGoal.objects.create(
            user=self.user,
            name="Bicycle",
            monthly_amount=Decimal("100.00"),
            start_date=date(2026, 8, 1),
            target_amount=Decimal("1000.00"),
            target_date=date(2026, 8, 19),
            current_balance=Decimal("900.00"),
            bank_account=self.account,
        )

        with patch("web.views.timezone.localdate", return_value=date(2026, 8, 14)):
            response = self.client.post(reverse("fund_savings_goal", args=[goal.id]))

        self.assertEqual(response.status_code, 302)
        goal.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(goal.current_balance, Decimal("1000.00"))
        self.assertEqual(self.account.balance, Decimal("670.00"))
        self.assertEqual(Transfer.objects.filter(destination_goal=goal).count(), 1)

    def test_goal_is_funded_automatically_on_its_monthly_effective_day(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            name="Travel",
            monthly_amount=Decimal("100.00"),
            start_date=date(2026, 8, 19),
            current_balance=Decimal("0.00"),
            bank_account=self.account,
        )

        self.assertEqual(fund_due_savings_goals(self.user, date(2026, 8, 18)), 0)
        self.assertEqual(fund_due_savings_goals(self.user, date(2026, 8, 19)), 1)
        self.assertEqual(fund_due_savings_goals(self.user, date(2026, 8, 20)), 0)
        goal.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(goal.current_balance, Decimal("100.00"))
        self.assertEqual(self.account.balance, Decimal("900.00"))

    def test_goal_account_is_listed_and_archived_only_after_it_is_empty(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            name="Reserve",
            monthly_amount=Decimal("100.00"),
            start_date=date(2027, 1, 1),
            current_balance=Decimal("100.00"),
            bank_account=self.account,
        )

        response = self.client.get(f"{reverse('dashboard')}?tab=accounts")
        self.assertContains(response, "Savings goal account")
        self.client.post(reverse("delete_savings_goal", args=[goal.id]))
        goal.refresh_from_db()
        self.assertFalse(goal.is_archived)

        goal.current_balance = Decimal("0.00")
        goal.save(update_fields=["current_balance"])
        self.client.post(reverse("delete_savings_goal", args=[goal.id]))
        goal.refresh_from_db()
        self.assertTrue(goal.is_archived)
        response = self.client.get(f"{reverse('dashboard')}?tab=accounts")
        self.assertNotContains(response, "Reserve")

    def test_monthly_totals_include_received_and_paid_activity(self):
        self.account.balance = Decimal("20.00")
        self.account.save()
        RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("1300.00"),
            start_date=date(2026, 8, 14),
            end_date=date(2026, 8, 28),
            category=self.income_category,
            bank_account=self.account,
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="Rent",
            amount=Decimal("550.00"),
            start_date=date(2026, 8, 14),
            category=self.expense_category,
            bank_account=self.account,
        )
        post_due_recurring(self.user, date(2026, 8, 14))

        budget = build_monthly_budget(self.user, date(2026, 8, 14))

        self.assertEqual(budget["current_balance"], Decimal("770.00"))
        self.assertEqual(budget["actual_income"], Decimal("1300.00"))
        self.assertEqual(budget["expected_income"], Decimal("0.00"))
        self.assertEqual(budget["income_month_total"], Decimal("1300.00"))
        self.assertEqual(budget["actual_expenses"], Decimal("550.00"))
        self.assertEqual(budget["expected_expenses"], Decimal("0.00"))
        self.assertEqual(budget["expense_month_total"], Decimal("550.00"))

    def test_goal_funding_does_not_post_without_enough_bank_balance(self):
        self.account.balance = Decimal("50.00")
        self.account.save()
        goal = SavingsGoal.objects.create(
            user=self.user,
            name="Laptop",
            monthly_amount=Decimal("200.00"),
            start_date=date(2026, 8, 1),
            bank_account=self.account,
        )

        with patch("web.views.timezone.localdate", return_value=date(2026, 8, 14)):
            self.client.post(reverse("fund_savings_goal", args=[goal.id]))

        goal.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(goal.current_balance, Decimal("0.00"))
        self.assertEqual(self.account.balance, Decimal("50.00"))
        self.assertFalse(Transfer.objects.filter(destination_goal=goal).exists())

    def test_goal_money_can_be_transferred_back_to_a_bank(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            name="Reserve",
            monthly_amount=Decimal("100.00"),
            start_date=date(2026, 1, 1),
            current_balance=Decimal("300.00"),
            bank_account=self.account,
        )
        self.client.post(
            reverse("create_transfer"),
            {
                "name": "Use reserve",
                "amount": "80.00",
                "date": "2026-08-14",
                "source": f"goal:{goal.id}",
                "destination": f"bank:{self.account.id}",
            },
        )
        goal.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(goal.current_balance, Decimal("220.00"))
        self.assertEqual(self.account.balance, Decimal("1080.00"))


class RegistrationTests(TestCase):
    @patch("web.views.notify_new_user")
    def test_registration_saves_email_and_logs_user_in(self, notify_new_user_mock):
        response = self.client.post(
            reverse("create_account"),
            {
                "username": "new-user",
                "email": "new@example.com",
                "password1": "a-strong-password-123",
                "password2": "a-strong-password-123",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="new-user")
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)
        notify_new_user_mock.assert_called_once_with(user)

    @patch("web.views.notify_new_user")
    def test_registration_keeps_the_visitors_selected_language(self, _notify):
        self.client.post(
            reverse("set_language_preference"),
            {"language": "it", "next": reverse("create_account")},
        )

        self.client.post(
            reverse("create_account"),
            {
                "username": "italian-user",
                "email": "italian@example.com",
                "password1": "a-strong-password-123",
                "password2": "a-strong-password-123",
            },
        )

        preference = BudgetPreference.objects.get(user__username="italian-user")
        self.assertEqual(preference.language, "it")


class LanguagePreferenceTests(TestCase):
    def test_visitor_language_is_stored_in_a_cookie_and_translates_public_pages(self):
        response = self.client.post(
            reverse("set_language_preference"),
            {"language": "fa", "next": reverse("home")},
        )

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(response.cookies["django_language"].value, "fa")
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'lang="fa"')
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, "پول شخصی، روشن و ساده")

    def test_signed_in_language_is_saved_and_overrides_the_old_cookie(self):
        user = User.objects.create_user("polyglot", password="good-password-123")
        self.client.force_login(user)

        response = self.client.post(
            reverse("set_language_preference"),
            {"language": "fr", "next": reverse("dashboard")},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(user.budget_preference.language, "fr")
        self.client.cookies["django_language"] = "es"
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'lang="fr"')
        self.assertContains(response, "Vue d’ensemble")

    def test_invalid_language_falls_back_to_english(self):
        response = self.client.post(
            reverse("set_language_preference"),
            {"language": "invalid", "next": reverse("home")},
        )

        self.assertEqual(response.cookies["django_language"].value, "en")


class ManualSubscriptionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "subscriber", "subscriber@example.com", "good-password-123"
        )
        self.plan = SubscriptionPlan.objects.create(
            name="Darith Monthly",
            monthly_price=Decimal("8.00"),
            currency="eur",
            payment_instructions="Send a bank transfer to the Darith account.",
            trial_days=14,
            is_active=True,
        )

    @override_settings(SUBSCRIPTIONS_ENABLED=True)
    def test_new_user_receives_the_configured_trial(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        subscription = UserSubscription.objects.get(user=self.user)
        self.assertEqual(subscription.status, UserSubscription.STATUS_TRIALING)
        self.assertEqual(
            subscription.access_until,
            timezone.localdate(self.user.date_joined) + timedelta(days=14),
        )
        self.assertTrue(subscription.has_access)

    @override_settings(SUBSCRIPTIONS_ENABLED=True)
    def test_middleware_requires_manual_access_when_trial_is_disabled(self):
        self.plan.trial_days = 0
        self.plan.save()
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('subscription_overview')}?next=%2Fdashboard%2F",
        )

        subscription = UserSubscription.objects.get(user=self.user)
        subscription.status = UserSubscription.STATUS_ACTIVE
        subscription.access_until = timezone.localdate() + timedelta(days=30)
        subscription.save()
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    @override_settings(SUBSCRIPTIONS_ENABLED=True)
    @patch("web.views.notify_subscription_payment")
    def test_user_reports_payment_and_admin_activation_grants_access(
        self, notify_subscription_payment_mock
    ):
        self.plan.trial_days = 0
        self.plan.save()
        self.client.force_login(self.user)

        response = self.client.post(reverse("report_subscription_payment"))

        self.assertRedirects(response, reverse("subscription_overview"))
        subscription = UserSubscription.objects.get(user=self.user)
        self.assertEqual(subscription.status, UserSubscription.STATUS_PENDING)
        self.assertIsNotNone(subscription.payment_reported_at)
        self.assertEqual(subscription.payment_reference, f"DARITH-{self.user.pk:06d}")
        self.assertFalse(subscription.has_access)
        notify_subscription_payment_mock.assert_called_once_with(subscription)

        response = self.client.get(reverse("subscription_overview"))
        self.assertContains(response, self.plan.payment_instructions)
        self.assertContains(response, subscription.payment_reference)
        self.assertContains(response, "Payment awaiting verification")
        self.assertContains(response, "free for individuals")
        self.assertContains(response, "https://github.com/bfarnaghi/darith")
        self.assertContains(response, "https://buymeacoffee.com/darith")
        self.assertContains(response, "automatically recurring monthly contributions")

        subscription.status = UserSubscription.STATUS_ACTIVE
        subscription.access_until = timezone.localdate() + timedelta(days=30)
        subscription.save()
        subscription.refresh_from_db()
        self.assertIsNone(subscription.payment_reported_at)
        self.assertIsNotNone(subscription.last_payment_verified_at)
        self.assertTrue(subscription.has_access)

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_verify_payment_and_set_access_date(self):
        self.plan.trial_days = 0
        self.plan.save()
        subscription = report_manual_payment(self.user)
        administrator = User.objects.create_superuser(
            "administrator",
            "admin@example.com",
            "admin-password-123",
        )
        self.client.force_login(administrator)
        paid_through = timezone.localdate() + timedelta(days=30)

        response = self.client.post(
            reverse("admin:web_usersubscription_change", args=[subscription.pk]),
            {
                "user": self.user.pk,
                "plan": self.plan.pk,
                "status": UserSubscription.STATUS_ACTIVE,
                "access_until": paid_through.isoformat(),
                "payment_note": "Wise payment verified.",
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, UserSubscription.STATUS_ACTIVE)
        self.assertEqual(subscription.access_until, paid_through)
        self.assertIsNone(subscription.payment_reported_at)
        self.assertIsNotNone(subscription.last_payment_verified_at)
        self.assertEqual(subscription.payment_note, "Wise payment verified.")

    def test_reporting_a_renewal_keeps_existing_access_until_expiry(self):
        subscription = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status=UserSubscription.STATUS_ACTIVE,
            access_until=timezone.localdate() + timedelta(days=5),
        )

        report_manual_payment(self.user)

        subscription.refresh_from_db()
        self.assertEqual(subscription.status, UserSubscription.STATUS_PENDING)
        self.assertTrue(subscription.has_access)
        self.assertIsNotNone(subscription.payment_reported_at)

    @override_settings(SUBSCRIPTIONS_ENABLED=True)
    def test_expired_access_is_revoked_and_home_stays_public(self):
        subscription = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status=UserSubscription.STATUS_ACTIVE,
            access_until=timezone.localdate() - timedelta(days=1),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, UserSubscription.STATUS_EXPIRED)
        self.assertFalse(subscription.has_access)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_initialization_is_idempotent(self):
        first = initialize_user_subscription(self.user)
        second = initialize_user_subscription(self.user)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(UserSubscription.objects.filter(user=self.user).count(), 1)
