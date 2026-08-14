# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import base64
import csv
import io
import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    BankAccount,
    BudgetPreference,
    Expense,
    ExpenseCategory,
    Income,
    IncomeCategory,
    MonthlyExpense,
    RecurringIncome,
    SavingsGoal,
    SubscriptionPlan,
    Transfer,
    UserSubscription,
)
from .services import build_monthly_budget, goal_funding_reminders, post_due_recurring
from .subscriptions import initialize_user_subscription, report_manual_payment


BASE_DIR = Path(__file__).resolve().parent.parent
VALID_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
)


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
        self.assertContains(response, "Your information stays private")
        self.assertNotContains(response, "animations")
        self.assertContains(response, reverse("create_account"))

        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open dashboard")

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

    def test_dashboard_requires_login_and_renders_budget(self):
        self.client.logout()
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Free to spend this month")
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
        self.assertEqual(budget["free_to_spend"], Decimal("2100.00"))
        self.assertEqual(budget["status"], "healthy")

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
        self.assertEqual(budget["free_to_spend"], Decimal("-300.00"))
        self.assertEqual(budget["status"], "warning")
        self.assertIn("saving goals", budget["warning"])

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
            {"name": "Travel", "balance": "300.00"},
        )
        account = BankAccount.objects.get(user=self.user, name="Travel")
        self.client.post(
            reverse("update_bank_account", args=[account.id]),
            {"name": "Holiday", "balance": "450.00"},
        )
        account.refresh_from_db()
        self.assertEqual(account.name, "Holiday")
        self.assertEqual(account.balance, Decimal("450.00"))
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
        self.assertFalse(SavingsGoal.objects.filter(pk=goal.id).exists())

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
        self.assertEqual(budget["free_to_spend"], Decimal("-40.00"))
        self.assertEqual(budget["status"], "danger")
        self.assertIn("move money from savings", budget["warning"])

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
    def test_registration_saves_email_and_logs_user_in(self):
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
    def test_user_reports_payment_and_admin_activation_grants_access(self):
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

        response = self.client.get(reverse("subscription_overview"))
        self.assertContains(response, self.plan.payment_instructions)
        self.assertContains(response, subscription.payment_reference)
        self.assertContains(response, "Payment awaiting verification")

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
