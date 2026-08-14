# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import calendar
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import BankAccount, Expense, Income, MonthlyExpense, RecurringIncome, SavingsGoal


ZERO = Decimal("0.00")


def month_bounds(day):
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return first, last


def add_month(day):
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def occurrence_dates(item, range_start, range_end):
    """Return monthly dates, clamping dates such as the 31st to month end."""
    lower = max(item.start_date, range_start)
    upper = min(item.end_date or range_end, range_end)
    if lower > upper:
        return []

    cursor = lower.replace(day=1)
    dates = []
    while cursor <= upper:
        day = min(item.day_of_month, calendar.monthrange(cursor.year, cursor.month)[1])
        occurrence = cursor.replace(day=day)
        if item.start_date <= occurrence <= upper and occurrence >= lower:
            dates.append(occurrence)
        cursor = add_month(cursor)
    return dates


def adjust_account_balance(account_id, delta):
    account = BankAccount.objects.select_for_update().get(pk=account_id)
    account.balance += delta
    account.save(update_fields=["balance"])


@transaction.atomic
def save_transaction(form, user, instance=None):
    previous = None
    if instance and instance.pk:
        previous = form._meta.model.objects.select_for_update().get(pk=instance.pk)
    previous_account_id = previous.bank_account_id if previous else None
    previous_amount = previous.amount if previous else ZERO
    is_expense = form._meta.model is Expense

    if previous_account_id:
        reverse_delta = previous_amount if is_expense else -previous_amount
        adjust_account_balance(previous_account_id, reverse_delta)

    item = form.save(commit=False)
    item.user = user
    item.save()

    apply_delta = -item.amount if is_expense else item.amount
    adjust_account_balance(item.bank_account_id, apply_delta)
    return item


@transaction.atomic
def delete_transaction(item):
    if item.bank_account_id:
        reverse_delta = item.amount if isinstance(item, Expense) else -item.amount
        adjust_account_balance(item.bank_account_id, reverse_delta)
    item.delete()


def post_due_recurring(user, through_date):
    """Post each due occurrence once and apply it to its account balance."""
    posted = 0
    with transaction.atomic():
        incomes = RecurringIncome.objects.filter(
            user=user, start_date__lte=through_date
        ).select_related("bank_account")
        expenses = MonthlyExpense.objects.filter(
            user=user, start_date__lte=through_date
        ).select_related("bank_account")

        for plan in incomes:
            for occurrence in occurrence_dates(plan, plan.start_date, through_date):
                _, created = Income.objects.get_or_create(
                    recurring_income=plan,
                    date=occurrence,
                    defaults={
                        "user": user,
                        "text": plan.name,
                        "amount": plan.amount,
                        "category": plan.category,
                        "bank_account": plan.bank_account,
                    },
                )
                if created:
                    adjust_account_balance(plan.bank_account_id, plan.amount)
                    posted += 1

        for plan in expenses:
            for occurrence in occurrence_dates(plan, plan.start_date, through_date):
                _, created = Expense.objects.get_or_create(
                    monthly_expense=plan,
                    date=occurrence,
                    defaults={
                        "user": user,
                        "text": plan.name,
                        "amount": plan.amount,
                        "category": plan.category,
                        "bank_account": plan.bank_account,
                    },
                )
                if created:
                    adjust_account_balance(plan.bank_account_id, -plan.amount)
                    posted += 1
    return posted


def _sum(queryset, field):
    return queryset.aggregate(total=Sum(field))["total"] or ZERO


def build_monthly_budget(user, today):
    month_start, month_end = month_bounds(today)
    accounts = BankAccount.objects.filter(user=user)
    recurring_incomes = RecurringIncome.objects.filter(
        user=user, start_date__lte=month_end
    ).select_related("bank_account", "category")
    recurring_expenses = MonthlyExpense.objects.filter(
        user=user, start_date__lte=month_end
    ).select_related("bank_account", "category")

    expected_income = ZERO
    expected_expenses = ZERO
    upcoming = []

    for plan in recurring_incomes:
        for occurrence in occurrence_dates(plan, today, month_end):
            if occurrence > today:
                expected_income += plan.amount
                upcoming.append(
                    {"kind": "income", "name": plan.name, "date": occurrence, "amount": plan.amount}
                )

    for plan in recurring_expenses:
        for occurrence in occurrence_dates(plan, today, month_end):
            if occurrence > today:
                expected_expenses += plan.amount
                upcoming.append(
                    {"kind": "expense", "name": plan.name, "date": occurrence, "amount": plan.amount}
                )

    goals = SavingsGoal.objects.filter(
        user=user, start_date__lte=month_end
    ).filter(end_date__isnull=True) | SavingsGoal.objects.filter(
        user=user, start_date__lte=month_end, end_date__gte=month_start
    )
    savings_target = _sum(goals.distinct(), "monthly_amount")
    current_balance = _sum(accounts, "balance")
    projected_balance = current_balance + expected_income - expected_expenses
    free_to_spend = projected_balance - savings_target
    days_remaining = (month_end - today).days + 1
    daily_allowance = free_to_spend / days_remaining

    if free_to_spend < 0:
        status = "danger"
        shortfall = abs(free_to_spend)
        warning = f"Your plan is short by EUR {shortfall:,.2f} for this month's commitments."
    elif projected_balance < savings_target:
        status = "warning"
        shortfall = savings_target - projected_balance
        warning = f"Your projected balance is EUR {shortfall:,.2f} below your savings target."
    else:
        status = "healthy"
        warning = "Your planned expenses and savings are covered this month."

    actual_income = _sum(
        Income.objects.filter(user=user, date__range=(month_start, today)), "amount"
    )
    actual_expenses = _sum(
        Expense.objects.filter(user=user, date__range=(month_start, today)), "amount"
    )

    return {
        "month_start": month_start,
        "month_end": month_end,
        "current_balance": current_balance,
        "expected_income": expected_income,
        "expected_expenses": expected_expenses,
        "savings_target": savings_target,
        "projected_balance": projected_balance,
        "free_to_spend": free_to_spend,
        "free_to_spend_abs": abs(free_to_spend),
        "days_remaining": days_remaining,
        "daily_allowance": daily_allowance,
        "daily_allowance_abs": abs(daily_allowance),
        "status": status,
        "warning": warning,
        "actual_income": actual_income,
        "actual_expenses": actual_expenses,
        "upcoming": sorted(upcoming, key=lambda item: item["date"]),
    }
