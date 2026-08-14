# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_POST

from .forms import (
    BankAccountForm,
    CategoryForm,
    ExpenseForm,
    IncomeForm,
    MonthlyExpenseForm,
    RecurringIncomeForm,
    RegistrationForm,
    SavingsGoalForm,
)
from .models import (
    BankAccount,
    Expense,
    ExpenseCategory,
    Income,
    IncomeCategory,
    MonthlyExpense,
    RecurringIncome,
    SavingsGoal,
)
from .services import build_monthly_budget, delete_transaction, post_due_recurring, save_transaction


DEFAULT_EXPENSE_CATEGORIES = ["Bills", "Food", "Health", "Housing", "Leisure", "Transport"]
DEFAULT_INCOME_CATEGORIES = ["Freelance", "Other", "Salary"]


def home(request):
    return redirect("dashboard" if request.user.is_authenticated else "login")


def _dashboard_redirect(tab="overview"):
    return redirect(f"{reverse('dashboard')}?tab={tab}")


def _show_form_errors(request, form):
    errors = [str(error) for field_errors in form.errors.values() for error in field_errors]
    messages.error(request, " ".join(errors) or "Please check the form and try again.")


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
        messages.info(request, f"Posted {posted_count} scheduled transaction(s).")

    accounts = list(BankAccount.objects.filter(user=request.user))
    expenses = list(
        Expense.objects.filter(user=request.user).select_related("category", "bank_account")
    )
    incomes = list(
        Income.objects.filter(user=request.user).select_related("category", "bank_account")
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
    ]
    transactions.sort(key=lambda item: (item["date"], item["id"]), reverse=True)

    recurring_incomes = list(
        RecurringIncome.objects.filter(user=request.user).select_related("category", "bank_account")
    )
    recurring_expenses = list(
        MonthlyExpense.objects.filter(user=request.user).select_related("category", "bank_account")
    )
    savings_goals = list(SavingsGoal.objects.filter(user=request.user))

    context = {
        "active_tab": request.GET.get("tab", "overview"),
        "today": today,
        "accounts": accounts,
        "transactions": transactions,
        "recent_transactions": transactions[:6],
        "recurring_incomes": recurring_incomes,
        "recurring_expenses": recurring_expenses,
        "savings_goals": savings_goals,
        "expense_categories": ExpenseCategory.objects.filter(user=request.user),
        "income_categories": IncomeCategory.objects.filter(user=request.user),
        "budget": build_monthly_budget(request.user, today),
        "account_form": BankAccountForm(),
        "expense_form": ExpenseForm(user=request.user, initial={"date": today}),
        "income_form": IncomeForm(user=request.user, initial={"date": today}),
        "recurring_income_form": RecurringIncomeForm(
            user=request.user, initial={"start_date": today}
        ),
        "monthly_expense_form": MonthlyExpenseForm(
            user=request.user, initial={"start_date": today}
        ),
        "savings_goal_form": SavingsGoalForm(initial={"start_date": today}),
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
            (item, SavingsGoalForm(instance=item, auto_id=f"saving_{item.id}_%s"))
            for item in savings_goals
        ],
    }
    return render(request, "dashboard.html", context)


@require_POST
@login_required
def create_bank_account(request):
    form = BankAccountForm(request.POST)
    if form.is_valid():
        account = form.save(commit=False)
        account.user = request.user
        try:
            account.save()
            messages.success(request, "Bank account added.")
        except IntegrityError:
            messages.error(request, "You already have an account with that name.")
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
            messages.success(request, "Bank account updated.")
        except IntegrityError:
            messages.error(request, "You already have an account with that name.")
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("accounts")


@require_POST
@login_required
def delete_bank_account(request, account_id):
    account = get_object_or_404(BankAccount, pk=account_id, user=request.user)
    account.delete()
    messages.success(request, "Bank account removed. Its transaction history was kept.")
    return _dashboard_redirect("accounts")


def _create_transaction(request, form_class, tab):
    form = form_class(request.POST, user=request.user)
    if form.is_valid():
        save_transaction(form, request.user)
        messages.success(request, f"{form._meta.model.__name__} added and balance updated.")
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect(tab)


def _update_transaction(request, form_class, model, item_id):
    item = get_object_or_404(model, pk=item_id, user=request.user)
    form = form_class(request.POST, instance=item, user=request.user)
    if form.is_valid():
        save_transaction(form, request.user, item)
        messages.success(request, f"{model.__name__} updated.")
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
    delete_transaction(item)
    messages.success(request, "Expense removed and balance restored.")
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
    delete_transaction(item)
    messages.success(request, "Income removed and balance updated.")
    return _dashboard_redirect("transactions")


def _create_plan(request, form_class, tab="plans"):
    kwargs = {"user": request.user} if form_class in (
        RecurringIncomeForm,
        MonthlyExpenseForm,
    ) else {}
    form = form_class(request.POST, **kwargs)
    if form.is_valid():
        item = form.save(commit=False)
        item.user = request.user
        item.save()
        messages.success(request, "Monthly plan added.")
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect(tab)


def _update_plan(request, form_class, model, item_id):
    item = get_object_or_404(model, pk=item_id, user=request.user)
    kwargs = {"instance": item}
    if form_class in (RecurringIncomeForm, MonthlyExpenseForm):
        kwargs["user"] = request.user
    form = form_class(request.POST, **kwargs)
    if form.is_valid():
        form.save()
        messages.success(request, "Monthly plan updated. Future postings use the new values.")
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
    get_object_or_404(RecurringIncome, pk=item_id, user=request.user).delete()
    messages.success(request, "Recurring income removed.")
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
    get_object_or_404(MonthlyExpense, pk=item_id, user=request.user).delete()
    messages.success(request, "Monthly expense removed.")
    return _dashboard_redirect("plans")


@require_POST
@login_required
def create_savings_goal(request):
    return _create_plan(request, SavingsGoalForm)


@require_POST
@login_required
def update_savings_goal(request, item_id):
    return _update_plan(request, SavingsGoalForm, SavingsGoal, item_id)


@require_POST
@login_required
def delete_savings_goal(request, item_id):
    get_object_or_404(SavingsGoal, pk=item_id, user=request.user).delete()
    messages.success(request, "Savings goal removed.")
    return _dashboard_redirect("plans")


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
        _, created = model.objects.get_or_create(user=request.user, name=form.cleaned_data["name"])
        messages.success(request, "Category added." if created else "That category already exists.")
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
            messages.success(request, "Category updated.")
        except IntegrityError:
            messages.error(request, "That category already exists.")
    else:
        _show_form_errors(request, form)
    return _dashboard_redirect("categories")


@require_POST
@login_required
def delete_category(request, kind, item_id):
    model = _category_model(kind)
    get_object_or_404(model, pk=item_id, user=request.user).delete()
    messages.success(request, "Category removed. Existing transactions were kept.")
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
            return redirect("dashboard")
        messages.error(request, "Invalid username or password.")
    return render(request, "login.html")


def create_account(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Your account is ready.")
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
                "Password reset request",
                f"Open this link to reset your password: {reset_link}",
                None,
                [user.email],
                html_message=message,
            )
        messages.success(request, "If that email exists, a password reset link has been sent.")
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
        return render(request, "password_reset_done.html")
    return render(request, "reset_password.html", {"form": form})
