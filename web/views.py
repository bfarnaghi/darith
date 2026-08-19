# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import json
import mimetypes
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.formats import date_format
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from webauthn.helpers.exceptions import WebAuthnException

from .forms import (
    AccountDeletionForm,
    BankAccountForm,
    BudgetPreferenceForm,
    CategoryForm,
    DashboardAnimationForm,
    ExpenseForm,
    FeedbackForm,
    IncomeForm,
    MonthlyExpenseForm,
    PlanningSettingsForm,
    RecurringIncomeForm,
    RegistrationForm,
    SavingsGoalForm,
    SecuritySettingsForm,
    TransferForm,
    UsernameChangeForm,
    UserPasswordChangeForm,
)
from .exports import build_user_csv_response
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
    Transfer,
)
from .notifications import (
    notify_feedback,
    notify_new_user,
    notify_subscription_payment,
)
from .security import (
    LOCKED_SESSION_KEY,
    PIN_ATTEMPTS_SESSION_KEY,
    PIN_BLOCKED_UNTIL_SESSION_KEY,
    mark_session_locked,
    mark_session_unlocked,
    touch_session,
)
from .services import (
    InsufficientFunds,
    build_daily_forecast,
    build_monthly_budget,
    build_next_month_forecast,
    delete_transaction,
    delete_transfer,
    fund_due_savings_goals,
    fund_goal_for_month,
    goal_funding_reminders,
    post_due_recurring,
    save_transaction,
    save_transfer,
)
from .subscriptions import (
    get_active_plan,
    get_user_subscription,
    report_manual_payment,
)
from .webauthn_service import (
    authentication_options,
    credential_from_response,
    registration_options,
    verify_authentication,
    verify_registration,
)


DEFAULT_EXPENSE_CATEGORIES = ["Bills", "Food", "Health", "Housing", "Leisure", "Transport"]
DEFAULT_INCOME_CATEGORIES = ["Freelance", "Other", "Salary"]


def _display_money(amount, preference, sign=""):
    if preference.hide_financial_values:
        return "******"
    prefix = sign
    if not sign and amount < 0:
        prefix = "−"
    return f"{prefix}{preference.currency_symbol}{abs(amount):,.2f}"


def _forecast_timeline_payload(daily_forecast, preference):
    status_labels = {
        "healthy": _("Good"),
        "warning": _("Tight"),
        "danger": _("Not enough"),
    }
    rows = []
    for row in daily_forecast["rows"]:
        events = []
        for event in row["events"]:
            sign = "+" if event["kind"] == "income" else "−"
            events.append(
                {
                    "kind": event["kind"],
                    "name": event["name"],
                    "amount": _display_money(event["amount"], preference, sign),
                }
            )

        rows.append(
            {
                "date": row["date"].isoformat(),
                "dateLabel": date_format(row["date"], "D, j M"),
                "dateLong": date_format(row["date"], "l, j/m/Y"),
                "safe": _display_money(row["safe_to_spend"], preference),
                "balance": _display_money(row["opening_balance"], preference),
                "incomeLeft": _display_money(
                    row["remaining_income"], preference, "+"
                ),
                "expensesLeft": _display_money(
                    row["remaining_expenses"], preference, "−"
                ),
                "savingsLeft": _display_money(
                    row["remaining_savings"], preference, "−"
                ),
                "dailyRemaining": _display_money(
                    row["remaining_daily_costs"], preference, "−"
                ),
                "buffer": _display_money(row["emergency_buffer"], preference),
                "hasBuffer": row["emergency_buffer"] > 0,
                "incomeToday": _display_money(row["income"], preference, "+"),
                "expensesToday": _display_money(row["expenses"], preference, "−"),
                "savingsToday": _display_money(row["savings"], preference, "−"),
                "dailyCost": _display_money(row["daily_cost"], preference, "−"),
                "status": row["status"],
                "statusLabel": status_labels[row["status"]],
                "events": events,
                "isToday": row["date"] == daily_forecast["start_date"],
                "isMonthStart": row["date"].day == 1,
            }
        )
    return rows


def home(request):
    return render(request, "landing.html")


def tutorial(request):
    return render(request, "tutorial.html")


def pricing(request):
    plan = get_active_plan()
    return render(
        request,
        "pricing.html",
        {
            "plan": plan,
            "trial_days": plan.trial_days if plan else 45,
            "subscriptions_enabled": settings.SUBSCRIPTIONS_ENABLED,
        },
    )


@require_POST
def set_language_preference(request):
    language = request.POST.get("language", "")
    supported_languages = {code for code, _name in settings.LANGUAGES}
    if language not in supported_languages:
        language = settings.LANGUAGE_CODE

    if request.user.is_authenticated:
        preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
        if preference.language != language:
            preference.language = language
            preference.save(update_fields=["language"])

    translation.activate(language)
    request.LANGUAGE_CODE = language
    redirect_to = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("home")
    if not url_has_allowed_host_and_scheme(
        redirect_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        redirect_to = reverse("home")
    response = redirect(redirect_to)
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )
    return response


@login_required
def account_settings(request):
    return render(
        request,
        "account.html",
        {
            "form": AccountDeletionForm(user=request.user),
            "subscriptions_enabled": settings.SUBSCRIPTIONS_ENABLED,
        },
    )


def _dashboard_redirect(tab="overview"):
    return redirect(f"{reverse('dashboard')}?tab={tab}")


def _show_form_errors(request, form):
    errors = [str(error) for field_errors in form.errors.values() for error in field_errors]
    messages.error(request, " ".join(errors) or _("Please check the form and try again."))


def _adjust_balances_when_deleting(user):
    preference, _created = BudgetPreference.objects.get_or_create(user=user)
    return (
        preference.transaction_deletion_mode
        == BudgetPreference.DELETE_BALANCE_AUTOMATIC
    )


@require_POST
@login_required
def toggle_financial_visibility(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    preference.hide_financial_values = not preference.hide_financial_values
    preference.save(update_fields=["hide_financial_values"])
    return _dashboard_redirect("overview")


def _request_json(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(_("The browser sent an invalid security response.")) from error


@require_POST
@login_required
def passkey_registration_options(request):
    return HttpResponse(registration_options(request), content_type="application/json")


@require_POST
@login_required
def passkey_registration_verify(request):
    try:
        payload = _request_json(request)
        verification = verify_registration(request, payload["credential"])
        name = str(payload.get("name") or _("My passkey")).strip()[:80]
        PasskeyCredential.objects.create(
            user=request.user,
            name=name or "My passkey",
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            transports=payload["credential"].get("response", {}).get("transports", []),
        )
    except (KeyError, ValueError, IntegrityError, WebAuthnException) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)
    return JsonResponse({"ok": True})


@require_POST
@login_required
def delete_passkey(request, item_id):
    credential = get_object_or_404(
        PasskeyCredential, pk=item_id, user=request.user
    )
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    is_last_passkey = not request.user.passkey_credentials.exclude(pk=item_id).exists()
    if preference.lock_timeout_minutes and is_last_passkey and not preference.darith_pin_hash:
        messages.error(
            request,
            _("Add a Darith PIN or turn off inactivity lock before removing your last passkey."),
        )
    else:
        credential.delete()
        messages.success(request, _("Passkey removed."))
    return _dashboard_redirect("overview")


@require_POST
def passkey_login_options(request):
    if request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": _("You are already signed in.")}, status=400)
    return HttpResponse(authentication_options(request), content_type="application/json")


@require_POST
def passkey_login_verify(request):
    if request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": _("You are already signed in.")}, status=400)
    try:
        payload = _request_json(request)
        with transaction.atomic():
            credential = credential_from_response(payload)
            verification = verify_authentication(request, payload, credential)
            credential.sign_count = verification.new_sign_count
            credential.last_used_at = timezone.now()
            credential.save(update_fields=["sign_count", "last_used_at"])
        login(
            request,
            credential.user,
            backend="django.contrib.auth.backends.ModelBackend",
        )
        mark_session_unlocked(request)
    except (ValueError, PasskeyCredential.DoesNotExist, WebAuthnException):
        return JsonResponse(
            {"ok": False, "error": "That passkey could not be verified."},
            status=400,
        )
    return JsonResponse({"ok": True, "redirect": reverse("dashboard")})


@login_required
def session_locked(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    if not preference.lock_timeout_minutes:
        mark_session_unlocked(request)
        return redirect("dashboard")
    if not request.session.get(LOCKED_SESSION_KEY):
        return redirect("dashboard")
    return render(
        request,
        "locked.html",
        {
            "has_pin": preference.has_darith_pin,
            "has_passkey": request.user.passkey_credentials.exists(),
        },
    )


@require_POST
@login_required
def security_unlock(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    now = time.time()
    blocked_until = float(request.session.get(PIN_BLOCKED_UNTIL_SESSION_KEY, 0))
    if blocked_until > now:
        messages.error(request, _("Too many attempts. Try again in a few minutes."))
        return redirect("session_locked")
    if not preference.darith_pin_hash:
        messages.error(request, _("A Darith PIN has not been configured."))
        return redirect("session_locked")
    if check_password(request.POST.get("pin", ""), preference.darith_pin_hash):
        mark_session_unlocked(request)
        return redirect("dashboard")

    attempts = int(request.session.get(PIN_ATTEMPTS_SESSION_KEY, 0)) + 1
    if attempts >= 5:
        request.session[PIN_ATTEMPTS_SESSION_KEY] = 0
        request.session[PIN_BLOCKED_UNTIL_SESSION_KEY] = now + 300
        messages.error(request, _("Too many attempts. PIN unlock is paused for 5 minutes."))
    else:
        request.session[PIN_ATTEMPTS_SESSION_KEY] = attempts
        messages.error(request, _("Incorrect Darith PIN."))
    return redirect("session_locked")


@require_POST
@login_required
def passkey_unlock_options(request):
    if not request.user.passkey_credentials.exists():
        return JsonResponse({"ok": False, "error": "No passkey is configured."}, status=400)
    return HttpResponse(
        authentication_options(request, request.user),
        content_type="application/json",
    )


@require_POST
@login_required
def passkey_unlock_verify(request):
    try:
        payload = _request_json(request)
        with transaction.atomic():
            credential = credential_from_response(payload, request.user)
            verification = verify_authentication(request, payload, credential)
            credential.sign_count = verification.new_sign_count
            credential.last_used_at = timezone.now()
            credential.save(update_fields=["sign_count", "last_used_at"])
        mark_session_unlocked(request)
    except (ValueError, PasskeyCredential.DoesNotExist, WebAuthnException):
        return JsonResponse(
            {"ok": False, "error": "That passkey could not be verified."},
            status=400,
        )
    return JsonResponse({"ok": True, "redirect": reverse("dashboard")})


@require_POST
@login_required
def security_lock(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    if preference.lock_timeout_minutes:
        mark_session_locked(request)
    return JsonResponse({"ok": True, "redirect": reverse("session_locked")})


@require_POST
@login_required
def security_activity(request):
    if request.session.get(LOCKED_SESSION_KEY):
        return JsonResponse({"ok": False}, status=423)
    touch_session(request)
    return HttpResponse(status=204)


def _seed_categories(user):
    if not ExpenseCategory.objects.filter(user=user).exists():
        for name in DEFAULT_EXPENSE_CATEGORIES:
            ExpenseCategory.objects.get_or_create(user=user, name=name)
    if not IncomeCategory.objects.filter(user=user).exists():
        for name in DEFAULT_INCOME_CATEGORIES:
            IncomeCategory.objects.get_or_create(user=user, name=name)


@login_required
def dashboard(request):
    today = timezone.localdate()
    _seed_categories(request.user)
    posted_count = post_due_recurring(request.user, today)
    if posted_count:
        messages.info(
            request,
            ngettext(
                "Posted %(count)d scheduled transaction.",
                "Posted %(count)d scheduled transactions.",
                posted_count,
            ) % {"count": posted_count},
        )
    funded_goal_count = fund_due_savings_goals(request.user, today)
    if funded_goal_count:
        messages.info(
            request,
            ngettext(
                "Funded %(count)d saving goal.",
                "Funded %(count)d saving goals.",
                funded_goal_count,
            ) % {"count": funded_goal_count},
        )

    accounts = list(BankAccount.objects.filter(user=request.user))
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    transfers = list(
        Transfer.objects.filter(user=request.user).select_related(
            "source_bank", "source_goal", "destination_bank", "destination_goal"
        )
    )
    expenses = list(
        Expense.objects.filter(user=request.user, is_skipped=False).select_related(
            "category", "bank_account"
        )
    )
    incomes = list(
        Income.objects.filter(user=request.user, is_skipped=False).select_related(
            "category", "bank_account"
        )
    )
    transactions = [
        {
            "id": item.id,
            "kind": "expense",
            "text": item.text,
            "amount": item.amount,
            "date": item.date,
            "category": item.category,
            "bank_account": item.bank_account,
            "object": item,
        }
        for item in expenses
    ] + [
        {
            "id": item.id,
            "kind": "income",
            "text": item.text,
            "amount": item.amount,
            "date": item.date,
            "category": item.category,
            "bank_account": item.bank_account,
            "object": item,
        }
        for item in incomes
    ] + [
        {
            "id": item.id,
            "kind": "transfer",
            "text": item.name,
            "amount": item.amount,
            "date": item.date,
            "source": item.source,
            "destination": item.destination,
            "object": item,
        }
        for item in transfers
    ]
    transactions.sort(key=lambda item: (item["date"], item["id"]), reverse=True)

    recurring_incomes = list(
        RecurringIncome.objects.filter(user=request.user).select_related("category", "bank_account")
    )
    recurring_expenses = list(
        MonthlyExpense.objects.filter(user=request.user).select_related("category", "bank_account")
    )
    savings_goals = list(
        SavingsGoal.objects.filter(
            user=request.user, is_archived=False
        ).select_related("bank_account")
    )
    goal_reminders = goal_funding_reminders(request.user, today)
    daily_forecast = build_daily_forecast(request.user, today)
    budget = build_monthly_budget(
        request.user, today, daily_forecast=daily_forecast
    )
    next_budget = build_next_month_forecast(
        request.user,
        today,
        budget,
        daily_forecast=daily_forecast,
    )
    active_animation = getattr(preference, f"{budget['status']}_gif")

    context = {
        "active_tab": request.GET.get("tab", "overview"),
        "today": today,
        "accounts": accounts,
        "transactions": transactions,
        "recent_transactions": transactions[:6],
        "recurring_incomes": recurring_incomes,
        "recurring_expenses": recurring_expenses,
        "savings_goals": savings_goals,
        "goal_reminders": goal_reminders,
        "subscriptions_enabled": settings.SUBSCRIPTIONS_ENABLED,
        "user_subscription": (
            get_user_subscription(request.user)
            if settings.SUBSCRIPTIONS_ENABLED
            else None
        ),
        "expense_categories": ExpenseCategory.objects.filter(user=request.user),
        "income_categories": IncomeCategory.objects.filter(user=request.user),
        "budget": budget,
        "next_budget": next_budget,
        "forecast_timeline": _forecast_timeline_payload(
            daily_forecast, preference
        ),
        "forecast_start": daily_forecast["start_date"],
        "forecast_end": daily_forecast["end_date"],
        "budget_preference": preference,
        "passkeys": request.user.passkey_credentials.all(),
        "currency_symbol": preference.currency_symbol,
        "currency_code": preference.currency,
        "active_budget_animation": bool(active_animation),
        "account_form": BankAccountForm(),
        "budget_preference_form": BudgetPreferenceForm(instance=preference),
        "dashboard_animation_form": DashboardAnimationForm(instance=preference),
        "planning_settings_form": PlanningSettingsForm(instance=preference),
        "security_settings_form": SecuritySettingsForm(instance=preference),
        "username_change_form": UsernameChangeForm(instance=request.user),
        "password_change_form": UserPasswordChangeForm(request.user),
        "account_deletion_form": AccountDeletionForm(user=request.user),
        "feedback_form": FeedbackForm(),
        "transfer_form": TransferForm(user=request.user, initial={"date": today}),
        "expense_form": ExpenseForm(user=request.user, initial={"date": today}),
        "income_form": IncomeForm(user=request.user, initial={"date": today}),
        "recurring_income_form": RecurringIncomeForm(
            user=request.user, initial={"start_date": today}
        ),
        "monthly_expense_form": MonthlyExpenseForm(
            user=request.user, initial={"start_date": today}
        ),
        "savings_goal_form": SavingsGoalForm(
            user=request.user, initial={"start_date": today, "current_balance": 0}
        ),
        "category_form": CategoryForm(),
        "account_edit_forms": [
            (item, BankAccountForm(instance=item, auto_id=f"account_{item.id}_%s"))
            for item in accounts
        ],
        "expense_edit_forms": [
            (item, ExpenseForm(instance=item, user=request.user, auto_id=f"expense_{item.id}_%s"))
            for item in expenses
        ],
        "income_edit_forms": [
            (item, IncomeForm(instance=item, user=request.user, auto_id=f"income_{item.id}_%s"))
            for item in incomes
        ],
        "recurring_income_edit_forms": [
            (
                item,
                RecurringIncomeForm(
                    instance=item, user=request.user, auto_id=f"recurring_income_{item.id}_%s"
                ),
            )
            for item in recurring_incomes
        ],
        "monthly_expense_edit_forms": [
            (
                item,
                MonthlyExpenseForm(
                    instance=item, user=request.user, auto_id=f"monthly_expense_{item.id}_%s"
                ),
            )
            for item in recurring_expenses
        ],
        "savings_goal_edit_forms": [
            (
                item,
                SavingsGoalForm(
                    instance=item, user=request.user, auto_id=f"saving_{item.id}_%s"
                ),
            )
            for item in savings_goals
        ],
        "transfer_edit_forms": [
            (
                item,
                TransferForm(
                    instance=item, user=request.user, auto_id=f"transfer_{item.id}_%s"
                ),
            )
            for item in transfers
        ],
    }
    return render(request, "dashboard.html", context)


@login_required
def export_data_csv(request):
    return build_user_csv_response(request.user)


def _require_subscriptions_enabled():
    if not settings.SUBSCRIPTIONS_ENABLED:
        raise Http404("Subscriptions are not enabled.")


@login_required
def subscription_overview(request):
    _require_subscriptions_enabled()
    return render(
        request,
        "subscription.html",
        {
            "plan": get_active_plan(),
            "subscription": get_user_subscription(request.user, create=True),
        },
    )


@require_POST
@login_required
def report_subscription_payment(request):
    _require_subscriptions_enabled()
    plan = get_active_plan()
    if plan is None:
        messages.error(request, _("A subscription plan is not available yet."))
        return redirect("subscription_overview")

    subscription = get_user_subscription(request.user, create=True)
    if (
        subscription.status == subscription.STATUS_PENDING
        and subscription.payment_reported_at
    ):
        messages.info(request, _("Your payment is already waiting for verification."))
    else:
        subscription = report_manual_payment(request.user)
        notify_subscription_payment(subscription)
        messages.success(
            request,
            _("Payment reported. An administrator will verify it and update your access."),
        )
    return redirect("subscription_overview")


@require_POST
@login_required
def create_bank_account(request):
    form = BankAccountForm(request.POST)
    if form.is_valid():
        account = form.save(commit=False)
        account.user = request.user
        try:
            account.save()
            messages.success(request, _("Bank account added."))
        except IntegrityError:
            messages.error(request, _("You already have an account with that name."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("accounts")


@require_POST
@login_required
def update_bank_account(request, account_id):
    account = get_object_or_404(BankAccount, pk=account_id, user=request.user)
    form = BankAccountForm(request.POST, instance=account)
    if form.is_valid():
        try:
            form.save()
            messages.success(request, _("Bank account updated."))
        except IntegrityError:
            messages.error(request, _("You already have an account with that name."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("accounts")


@require_POST
@login_required
def delete_bank_account(request, account_id):
    account = get_object_or_404(BankAccount, pk=account_id, user=request.user)
    try:
        account.delete()
        messages.success(request, _("Bank account removed. Its transaction history was kept."))
    except ProtectedError:
        messages.error(
            request,
            _("This account is used by a transfer. Delete that transfer or change the goal account first."),
        )
    return _dashboard_redirect("accounts")


def _create_transaction(request, form_class, tab):
    form = form_class(request.POST, user=request.user)
    if form.is_valid():
        save_transaction(form, request.user)
        kind = _("Expense") if form._meta.model is Expense else _("Income")
        messages.success(
            request,
            _("%(kind)s added and balance updated.") % {"kind": kind},
        )
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect(tab)


def _update_transaction(request, form_class, model, item_id):
    item = get_object_or_404(model, pk=item_id, user=request.user)
    form = form_class(request.POST, instance=item, user=request.user)
    if form.is_valid():
        save_transaction(form, request.user, item)
        kind = _("Expense") if model is Expense else _("Income")
        messages.success(request, _("%(kind)s updated.") % {"kind": kind})
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("transactions")


@require_POST
@login_required
def create_expense(request):
    return _create_transaction(request, ExpenseForm, "transactions")


@require_POST
@login_required
def update_expense(request, expense_id):
    return _update_transaction(request, ExpenseForm, Expense, expense_id)


@require_POST
@login_required
def delete_expense(request, expense_id):
    item = get_object_or_404(Expense, pk=expense_id, user=request.user)
    is_recurring_occurrence = bool(item.monthly_expense_id)
    adjust_balance = _adjust_balances_when_deleting(request.user)
    delete_transaction(item, adjust_balance=adjust_balance)
    if not adjust_balance:
        messages.success(
            request,
            _("Expense removed. The bank balance was left unchanged by your setting."),
        )
    elif is_recurring_occurrence:
        messages.success(
            request,
            _(
                "This monthly expense was removed and its balance restored. "
                "Future months remain scheduled."
            ),
        )
    else:
        messages.success(request, _("Expense removed and balance restored."))
    return _dashboard_redirect("transactions")


@require_POST
@login_required
def create_income(request):
    return _create_transaction(request, IncomeForm, "transactions")


@require_POST
@login_required
def update_income(request, income_id):
    return _update_transaction(request, IncomeForm, Income, income_id)


@require_POST
@login_required
def delete_income(request, income_id):
    item = get_object_or_404(Income, pk=income_id, user=request.user)
    is_recurring_occurrence = bool(item.recurring_income_id)
    adjust_balance = _adjust_balances_when_deleting(request.user)
    delete_transaction(item, adjust_balance=adjust_balance)
    if not adjust_balance:
        messages.success(
            request,
            _("Income removed. The bank balance was left unchanged by your setting."),
        )
    elif is_recurring_occurrence:
        messages.success(
            request,
            _(
                "This monthly income was removed and its balance updated. "
                "Future months remain scheduled."
            ),
        )
    else:
        messages.success(request, _("Income removed and balance updated."))
    return _dashboard_redirect("transactions")


@require_POST
@login_required
def create_transfer(request):
    form = TransferForm(request.POST, user=request.user)
    if form.is_valid():
        try:
            save_transfer(form, request.user)
            messages.success(request, _("Transfer completed."))
        except (InsufficientFunds, ValidationError) as error:
            messages.error(request, " ".join(error.messages))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("transactions")


@require_POST
@login_required
def update_transfer(request, item_id):
    item = get_object_or_404(Transfer, pk=item_id, user=request.user)
    form = TransferForm(request.POST, instance=item, user=request.user)
    if form.is_valid():
        try:
            save_transfer(form, request.user, item)
            messages.success(request, _("Transfer updated."))
        except (InsufficientFunds, ValidationError) as error:
            messages.error(request, " ".join(error.messages))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("transactions")


@require_POST
@login_required
def remove_transfer(request, item_id):
    item = get_object_or_404(Transfer, pk=item_id, user=request.user)
    adjust_balance = _adjust_balances_when_deleting(request.user)
    delete_transfer(item, adjust_balance=adjust_balance)
    if adjust_balance:
        messages.success(request, _("Transfer removed and balances restored."))
    else:
        messages.success(
            request,
            _("Transfer removed. Account balances were left unchanged by your setting."),
        )
    return _dashboard_redirect("transactions")


def _create_plan(request, form_class, tab="plans"):
    kwargs = {"user": request.user} if form_class in (
        RecurringIncomeForm,
        MonthlyExpenseForm,
        SavingsGoalForm,
    ) else {}
    form = form_class(request.POST, **kwargs)
    if form.is_valid():
        item = form.save(commit=False)
        item.user = request.user
        item.save()
        messages.success(request, _("Monthly plan added."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect(tab)


def _update_plan(request, form_class, model, item_id):
    item = get_object_or_404(model, pk=item_id, user=request.user)
    kwargs = {"instance": item}
    if form_class in (RecurringIncomeForm, MonthlyExpenseForm, SavingsGoalForm):
        kwargs["user"] = request.user
    form = form_class(request.POST, **kwargs)
    if form.is_valid():
        form.save()
        messages.success(request, _("Monthly plan updated. Future postings use the new values."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("plans")


@require_POST
@login_required
def create_recurring_income(request):
    return _create_plan(request, RecurringIncomeForm)


@require_POST
@login_required
def update_recurring_income(request, item_id):
    return _update_plan(request, RecurringIncomeForm, RecurringIncome, item_id)


@require_POST
@login_required
def delete_recurring_income(request, item_id):
    item = get_object_or_404(RecurringIncome, pk=item_id, user=request.user)
    item.posted_incomes.filter(is_skipped=True).delete()
    item.delete()
    messages.success(
        request,
        _("Recurring income plan removed. Existing posted income remains in Activity."),
    )
    return _dashboard_redirect("plans")


@require_POST
@login_required
def create_monthly_expense(request):
    return _create_plan(request, MonthlyExpenseForm)


@require_POST
@login_required
def update_monthly_expense(request, item_id):
    return _update_plan(request, MonthlyExpenseForm, MonthlyExpense, item_id)


@require_POST
@login_required
def delete_monthly_expense(request, item_id):
    item = get_object_or_404(MonthlyExpense, pk=item_id, user=request.user)
    item.posted_expenses.filter(is_skipped=True).delete()
    item.delete()
    messages.success(
        request,
        _("Monthly expense plan removed. Existing posted expenses remain in Activity."),
    )
    return _dashboard_redirect("plans")


@require_POST
@login_required
def create_savings_goal(request):
    return _create_plan(request, SavingsGoalForm)


@require_POST
@login_required
def update_savings_goal(request, item_id):
    item = get_object_or_404(
        SavingsGoal, pk=item_id, user=request.user, is_archived=False
    )
    form = SavingsGoalForm(request.POST, instance=item, user=request.user)
    if form.is_valid():
        form.save()
        messages.success(
            request, _("Saving goal updated. Future funding uses the new values.")
        )
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("plans")


@require_POST
@login_required
def delete_savings_goal(request, item_id):
    goal = get_object_or_404(
        SavingsGoal, pk=item_id, user=request.user, is_archived=False
    )
    if goal.current_balance != 0:
        messages.error(
            request,
            _("Move the remaining balance to a bank account before deleting this goal account."),
        )
    else:
        goal.is_archived = True
        goal.save(update_fields=["is_archived"])
        messages.success(request, _("Saving goal account removed. Its transfer history was kept."))
    return _dashboard_redirect("plans")


@require_POST
@login_required
def fund_savings_goal(request, item_id):
    goal = get_object_or_404(
        SavingsGoal, pk=item_id, user=request.user, is_archived=False
    )
    try:
        item = fund_goal_for_month(goal, request.user, timezone.localdate())
        if item:
            preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
            messages.success(
                request,
                _("%(amount)s moved to %(goal)s.")
                % {
                    "amount": f"{preference.currency_symbol}{item.amount:,.2f}",
                    "goal": goal.name,
                },
            )
        else:
            messages.info(request, _("This goal is already funded for the month."))
    except (InsufficientFunds, ValidationError) as error:
        messages.error(request, " ".join(error.messages))
    except IntegrityError:
        messages.info(request, _("This goal is already funded for the month."))
    return _dashboard_redirect("overview")


@require_POST
@login_required
def update_budget_preference(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    form = BudgetPreferenceForm(request.POST, instance=preference)
    if form.is_valid():
        form.save()
        messages.success(request, _("Daily spending expectation updated."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("overview")


@require_POST
@login_required
def update_planning_settings(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    form = PlanningSettingsForm(request.POST, instance=preference)
    if form.is_valid():
        form.save()
        messages.success(request, _("Planning settings saved."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("overview")


@require_POST
@login_required
def update_username(request):
    form = UsernameChangeForm(request.POST, instance=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, _("Username updated."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("overview")


@require_POST
@login_required
def update_account_password(request):
    form = UserPasswordChangeForm(request.user, request.POST)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, _("Password updated."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("overview")


@require_POST
@login_required
def update_dashboard_animations(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    form = DashboardAnimationForm(
        request.POST, request.FILES, instance=preference
    )
    if form.is_valid():
        form.save()
        messages.success(request, _("Settings updated."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("overview")


@require_POST
@login_required
def update_security_settings(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    form = SecuritySettingsForm(request.POST, instance=preference)
    if form.is_valid():
        form.save()
        mark_session_unlocked(request)
        messages.success(request, _("Security settings updated."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("overview")


@require_POST
@login_required
def remove_darith_pin(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    if preference.lock_timeout_minutes and not request.user.passkey_credentials.exists():
        messages.error(
            request,
            _("Add a passkey or turn off inactivity lock before removing your PIN."),
        )
    elif preference.darith_pin_hash:
        preference.darith_pin_hash = ""
        preference.save(update_fields=["darith_pin_hash"])
        messages.success(request, _("Darith PIN removed."))
    else:
        messages.info(request, _("There is no Darith PIN to remove."))
    return _dashboard_redirect("overview")


@require_POST
@login_required
def delete_user_account(request):
    form = AccountDeletionForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, _("Account not deleted. Check every confirmation field."))
        return render(
            request,
            "account.html",
            {
                "form": form,
                "subscriptions_enabled": settings.SUBSCRIPTIONS_ENABLED,
            },
            status=400,
        )

    user = request.user
    user.delete()
    logout(request)
    messages.success(
        request,
        _("Your Darith account and live data were permanently deleted."),
    )
    return redirect("login")


@require_POST
@login_required
def submit_feedback(request):
    form = FeedbackForm(request.POST)
    if form.is_valid():
        feedback = form.save(commit=False)
        feedback.user = request.user
        feedback.page = request.POST.get("page", "dashboard")[:80]
        feedback.save()
        notify_feedback(feedback)
        messages.success(request, _("Thank you. Your feedback was sent."))
    else:
        _show_form_errors(request, form)
    tab = request.POST.get("tab", "overview")
    if tab not in {"overview", "accounts", "transactions", "plans", "categories"}:
        tab = "overview"
    return _dashboard_redirect(tab)


@require_POST
@login_required
def remove_dashboard_gif(request, status):
    status_labels = {
        "healthy": _("on-track"),
        "warning": _("warning"),
        "danger": _("out-of-budget"),
    }
    if status not in status_labels:
        raise Http404("Unknown budget status.")

    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    field_name = f"{status}_gif"
    current_gif = getattr(preference, field_name)
    if current_gif.name:
        setattr(preference, field_name, None)
        preference.save(update_fields=[field_name])
        messages.success(
            request,
            _("The %(status)s GIF was removed.") % {"status": status_labels[status]},
        )
    else:
        messages.info(request, _("There is no GIF to remove for this budget state."))
    return _dashboard_redirect("overview")


@require_POST
@login_required
def remove_profile_picture(request):
    preference, _created = BudgetPreference.objects.get_or_create(user=request.user)
    if preference.profile_picture.name:
        preference.profile_picture = None
        preference.save(update_fields=["profile_picture"])
        messages.success(request, _("Your profile picture was removed."))
    else:
        messages.info(request, _("There is no profile picture to remove."))
    return _dashboard_redirect("overview")


@login_required
def dashboard_animation(request, status):
    if status not in {"healthy", "warning", "danger"}:
        raise Http404("Unknown budget status.")
    preference = get_object_or_404(BudgetPreference, user=request.user)
    animation = getattr(preference, f"{status}_gif")
    if not animation.name:
        raise Http404("No animation is configured for this status.")
    try:
        animation.open("rb")
    except (FileNotFoundError, OSError) as error:
        raise Http404("The animation file is unavailable.") from error

    response = FileResponse(animation, content_type="image/gif")
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = f'inline; filename="darith-{status}.gif"'
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


@login_required
def profile_picture(request):
    preference = get_object_or_404(BudgetPreference, user=request.user)
    picture = preference.profile_picture
    if not picture.name:
        raise Http404("No profile picture is configured.")
    try:
        picture.open("rb")
    except (FileNotFoundError, OSError) as error:
        raise Http404("The profile picture is unavailable.") from error

    content_type = mimetypes.guess_type(picture.name)[0] or "application/octet-stream"
    response = FileResponse(picture, content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = 'inline; filename="darith-profile-picture"'
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


def _category_model(kind):
    if kind == "income":
        return IncomeCategory
    if kind == "expense":
        return ExpenseCategory
    raise Http404("Unknown category type")


@require_POST
@login_required
def create_category(request, kind):
    model = _category_model(kind)
    form = CategoryForm(request.POST)
    if form.is_valid():
        category, created = model.objects.get_or_create(
            user=request.user, name=form.cleaned_data["name"]
        )
        messages.success(
            request,
            _("Category added.") if created else _("That category already exists."),
        )
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("categories")


@require_POST
@login_required
def update_category(request, kind, item_id):
    model = _category_model(kind)
    category = get_object_or_404(model, pk=item_id, user=request.user)
    form = CategoryForm(request.POST)
    if form.is_valid():
        category.name = form.cleaned_data["name"]
        try:
            category.save()
            messages.success(request, _("Category updated."))
        except IntegrityError:
            messages.error(request, _("That category already exists."))
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("categories")


@require_POST
@login_required
def delete_category(request, kind, item_id):
    model = _category_model(kind)
    get_object_or_404(model, pk=item_id, user=request.user).delete()
    messages.success(request, _("Category removed. Existing transactions were kept."))
    return _dashboard_redirect("categories")


def user_login(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        user = authenticate(
            request, username=request.POST.get("username"), password=request.POST.get("password")
        )
        if user is not None:
            login(request, user)
            mark_session_unlocked(request)
            return redirect("dashboard")
        messages.error(request, _("Invalid username or password."))
    return render(request, "login.html")


def create_account(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        language = getattr(request, "LANGUAGE_CODE", settings.LANGUAGE_CODE)
        BudgetPreference.objects.create(user=user, language=language)
        notify_new_user(user)
        login(request, user)
        mark_session_unlocked(request)
        messages.success(request, _("Your account is ready."))
        return redirect("dashboard")
    return render(request, "create_account.html", {"form": form})


@require_POST
def user_logout(request):
    logout(request)
    return redirect("login")


def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email", "")
        user = User.objects.filter(email__iexact=email).first()
        if user:
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            reset_link = request.build_absolute_uri(reverse("reset_password", args=[uid, token]))
            message = render_to_string("reset_password_email.html", {"reset_link": reset_link})
            send_mail(
                _("Password reset request"),
                _("Open this link to reset your password: %(link)s") % {"link": reset_link},
                None,
                [user.email],
                html_message=message,
            )
        messages.success(request, _("If that email exists, a password reset link has been sent."))
        return redirect("login")
    return render(request, "forgot_password.html")


def reset_password(request, uidb64, token):
    try:
        user = User.objects.get(pk=urlsafe_base64_decode(uidb64).decode())
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    if user is None or not default_token_generator.check_token(user, token):
        return render(request, "password_reset_failed.html")
    form = SetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        login(request, user)
        mark_session_unlocked(request)
        return render(request, "password_reset_done.html")
    return render(request, "reset_password.html", {"form": form})
