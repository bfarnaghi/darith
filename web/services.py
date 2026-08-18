# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import calendar
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils.translation import gettext as _

from .models import (
    BankAccount,
    BudgetPreference,
    Expense,
    Income,
    MonthlyExpense,
    RecurringIncome,
    SavingsGoal,
    Transfer,
)


ZERO = Decimal("0.00")


class InsufficientFunds(ValidationError):
    pass


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


def adjust_goal_balance(goal_id, delta):
    goal = SavingsGoal.objects.select_for_update().get(pk=goal_id)
    goal.current_balance += delta
    goal.save(update_fields=["current_balance"])


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
def delete_transaction(item, adjust_balance=True):
    item = type(item).objects.select_for_update().get(pk=item.pk)
    if adjust_balance and item.bank_account_id:
        reverse_delta = item.amount if isinstance(item, Expense) else -item.amount
        adjust_account_balance(item.bank_account_id, reverse_delta)

    recurring_plan_id = (
        item.monthly_expense_id
        if isinstance(item, Expense)
        else item.recurring_income_id
    )
    if recurring_plan_id:
        item.is_skipped = True
        item.save(update_fields=["is_skipped"])
    else:
        item.delete()


def _source_balance(item):
    if item.source_bank_id:
        return BankAccount.objects.select_for_update().get(pk=item.source_bank_id).balance
    return SavingsGoal.objects.select_for_update().get(pk=item.source_goal_id).current_balance


def _apply_transfer(item, reverse=False, check_funds=True):
    source_delta = item.amount if reverse else -item.amount
    if not reverse and check_funds and _source_balance(item) < item.amount:
        raise InsufficientFunds(_("The source account does not have enough money."))

    if item.source_bank_id:
        adjust_account_balance(item.source_bank_id, source_delta)
    else:
        adjust_goal_balance(item.source_goal_id, source_delta)

    if item.destination_bank_id:
        adjust_account_balance(item.destination_bank_id, -source_delta)
    else:
        adjust_goal_balance(item.destination_goal_id, -source_delta)


@transaction.atomic
def save_transfer(form, user, instance=None):
    previous = None
    if instance and instance.pk:
        previous = Transfer.objects.select_for_update().get(pk=instance.pk)
        _apply_transfer(previous, reverse=True, check_funds=False)

    item = form.save(commit=False)
    item.user = user
    item.full_clean()
    item.save()
    _apply_transfer(item)
    return item


@transaction.atomic
def delete_transfer(item, adjust_balance=True):
    locked = Transfer.objects.select_for_update().get(pk=item.pk)
    if adjust_balance:
        _apply_transfer(locked, reverse=True, check_funds=False)
    locked.delete()


def goal_monthly_contribution(goal, as_of):
    remaining = max((goal.target_amount or ZERO) - goal.current_balance, ZERO)
    if goal.target_amount is None:
        return goal.monthly_amount
    if remaining == ZERO:
        return ZERO
    if not goal.target_date or as_of >= goal.target_date:
        return remaining

    # Dated goals get a fixed monthly amount when the form is saved.
    # Keep using that planned amount in later months instead of
    # recalculating it from the remaining months each time.
    return min(goal.monthly_amount, remaining)


def goal_funding_reminders(user, today):
    period = today.replace(day=1)
    goals = SavingsGoal.objects.filter(
        user=user, start_date__lte=today, is_archived=False
    ).select_related("bank_account")
    funded_goal_ids = set(
        Transfer.objects.filter(
            user=user, destination_goal__isnull=False, goal_period=period
        ).values_list("destination_goal_id", flat=True)
    )
    reminders = []
    for goal in goals:
        if goal.pk in funded_goal_ids:
            continue
        due = goal_monthly_contribution(goal, today)
        if due <= ZERO:
            continue
        reminders.append(
            {
                "goal": goal,
                "amount": due,
                "source_account": goal.bank_account,
                "can_fund": bool(goal.bank_account and goal.bank_account.balance >= due),
            }
        )
    return reminders


@transaction.atomic
def fund_goal_for_month(goal, user, today):
    goal = (
        SavingsGoal.objects.select_for_update()
        .get(pk=goal.pk, user=user, is_archived=False)
    )
    period = today.replace(day=1)
    if Transfer.objects.filter(destination_goal=goal, goal_period=period).exists():
        return None
    if not goal.bank_account_id:
        raise ValidationError(_("Choose a funding bank account for this goal first."))

    amount = goal_monthly_contribution(goal, today)
    if amount <= ZERO:
        return None
    item = Transfer(
        user=user,
        name=_("Save for %(goal)s") % {"goal": goal.name},
        amount=amount,
        date=today,
        source_bank=goal.bank_account,
        destination_goal=goal,
        goal_period=period,
    )
    item.full_clean()
    item.save()
    _apply_transfer(item)
    return item


def fund_due_savings_goals(user, through_date):
    """Fund this month's active goals once their monthly saving date is due."""
    month_start = through_date.replace(day=1)
    goals = SavingsGoal.objects.filter(
        user=user,
        start_date__lte=through_date,
        is_archived=False,
    ).select_related("bank_account")
    funded = 0

    for goal in goals:
        if not occurrence_dates(goal, month_start, through_date):
            continue
        try:
            item = fund_goal_for_month(goal, user, through_date)
        except (InsufficientFunds, ValidationError, IntegrityError):
            continue
        if item:
            funded += 1
    return funded


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


def _status_for_commitments(
    available_before_daily_costs,
    daily_expenses,
    savings_target,
    savings_balance,
    currency_symbol,
    period_label=None,
):
    period_label = period_label or _("this month")
    free_to_spend = available_before_daily_costs - daily_expenses - savings_target
    if available_before_daily_costs < daily_expenses:
        status = "danger"
        shortfall = daily_expenses - available_before_daily_costs
        if savings_balance >= shortfall:
            warning = _(
                "Your spendable accounts are %(amount)s short of expected daily costs. "
                "You may need to move money from savings."
            ) % {"amount": f"{currency_symbol}{shortfall:,.2f}"}
        else:
            warning = _(
                "Your spendable accounts are %(amount)s short of expected daily costs, "
                "even before the saving goals for %(period)s."
            ) % {
                "amount": f"{currency_symbol}{shortfall:,.2f}",
                "period": period_label,
            }
    elif free_to_spend < ZERO:
        status = "warning"
        shortfall = abs(free_to_spend)
        warning = _(
            "Daily costs are covered, but %(amount)s is still needed for the "
            "saving goals for %(period)s."
        ) % {
            "amount": f"{currency_symbol}{shortfall:,.2f}",
            "period": period_label,
        }
    else:
        status = "healthy"
        warning = _(
            "Expected bills, daily costs, and saving goals are covered %(period)s."
        ) % {"period": period_label}
    return status, warning, free_to_spend


def _goal_target_for_period(user, period_start, period_end):
    goals = SavingsGoal.objects.filter(
        user=user,
        start_date__lte=period_end,
        is_archived=False,
    ).select_related("bank_account")
    funded_goal_ids = set(
        Transfer.objects.filter(
            user=user,
            destination_goal__isnull=False,
            goal_period=period_start,
        ).values_list("destination_goal_id", flat=True)
    )
    target = ZERO
    for goal in goals:
        if goal.pk in funded_goal_ids:
            continue
        if not occurrence_dates(goal, period_start, period_end):
            continue
        if goal.bank_account and not goal.bank_account.include_in_budget:
            continue
        target += goal_monthly_contribution(goal, period_start)
    return target


def build_next_month_forecast(user, today, current_budget=None):
    current_budget = current_budget or build_monthly_budget(user, today)
    period_start = add_month(today.replace(day=1))
    _period_start, period_end = month_bounds(period_start)
    accounts = BankAccount.objects.filter(user=user, include_in_budget=True)
    incomes = RecurringIncome.objects.filter(
        user=user,
        bank_account__include_in_budget=True,
        start_date__lte=period_end,
    )
    expenses = MonthlyExpense.objects.filter(
        user=user,
        bank_account__include_in_budget=True,
        start_date__lte=period_end,
    )
    expected_income = sum(
        (
            plan.amount * len(occurrence_dates(plan, period_start, period_end))
            for plan in incomes
        ),
        ZERO,
    )
    expected_expenses = sum(
        (
            plan.amount * len(occurrence_dates(plan, period_start, period_end))
            for plan in expenses
        ),
        ZERO,
    )
    preference = BudgetPreference.objects.filter(user=user).first()
    daily_expense = preference.expected_daily_expense if preference else ZERO
    currency_symbol = (
        preference.currency_symbol
        if preference
        else BudgetPreference.CURRENCY_SYMBOLS[BudgetPreference.CURRENCY_EUR]
    )
    days_in_month = period_end.day
    daily_expenses = daily_expense * days_in_month
    savings_target = _goal_target_for_period(user, period_start, period_end)
    opening_balance = current_budget["projected_balance"]
    uncovered_expenses = max(expected_expenses - expected_income, ZERO)
    available_before_daily_costs = opening_balance - uncovered_expenses
    savings_balance = _sum(
        SavingsGoal.objects.filter(user=user, is_archived=False), "current_balance"
    )
    status, warning, free_to_spend = _status_for_commitments(
        available_before_daily_costs,
        daily_expenses,
        savings_target,
        savings_balance,
        currency_symbol,
        period_label=_("next month"),
    )
    return {
        "month_start": period_start,
        "month_end": period_end,
        "opening_balance": opening_balance,
        "expected_income": expected_income,
        "expected_expenses": expected_expenses,
        "daily_expenses": daily_expenses,
        "savings_target": savings_target,
        "projected_balance": (
            opening_balance
            + expected_income
            - expected_expenses
            - daily_expenses
            - savings_target
        ),
        "free_to_spend": free_to_spend,
        "status": status,
        "warning": warning,
        "included_account_count": accounts.count(),
    }


def build_monthly_budget(user, today):
    month_start, month_end = month_bounds(today)
    accounts = BankAccount.objects.filter(user=user, include_in_budget=True)
    recurring_incomes = RecurringIncome.objects.filter(
        user=user,
        bank_account__include_in_budget=True,
        start_date__lte=month_end,
    ).select_related("bank_account", "category")
    recurring_expenses = MonthlyExpense.objects.filter(
        user=user,
        bank_account__include_in_budget=True,
        start_date__lte=month_end,
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

    reminders = goal_funding_reminders(user, today)
    budget_reminders = [
        item
        for item in reminders
        if not item["source_account"] or item["source_account"].include_in_budget
    ]
    savings_target = sum((item["amount"] for item in budget_reminders), ZERO)
    current_balance = _sum(accounts, "balance")
    included_account_count = accounts.count()
    savings_balance = _sum(
        SavingsGoal.objects.filter(user=user, is_archived=False), "current_balance"
    )
    days_remaining = (month_end - today).days + 1
    preference = BudgetPreference.objects.filter(user=user).first()
    daily_expense = preference.expected_daily_expense if preference else ZERO
    currency_symbol = (
        preference.currency_symbol
        if preference
        else BudgetPreference.CURRENCY_SYMBOLS[BudgetPreference.CURRENCY_EUR]
    )
    remaining_daily_expenses = daily_expense * days_remaining
    projected_balance = (
        current_balance
        + expected_income
        - expected_expenses
        - remaining_daily_expenses
        - savings_target
    )
    uncovered_future_expenses = max(expected_expenses - expected_income, ZERO)
    available_before_daily_costs = current_balance - uncovered_future_expenses
    status, warning, free_to_spend = _status_for_commitments(
        available_before_daily_costs,
        remaining_daily_expenses,
        savings_target,
        savings_balance,
        currency_symbol,
    )
    daily_allowance = free_to_spend / days_remaining

    actual_income = _sum(
        Income.objects.filter(
            Q(bank_account__include_in_budget=True) | Q(bank_account__isnull=True),
            user=user,
            date__range=(month_start, today),
            is_skipped=False,
        ),
        "amount",
    )
    actual_expenses = _sum(
        Expense.objects.filter(
            Q(bank_account__include_in_budget=True) | Q(bank_account__isnull=True),
            user=user,
            date__range=(month_start, today),
            is_skipped=False,
        ),
        "amount",
    )
    income_month_total = actual_income + expected_income
    expense_month_total = actual_expenses + expected_expenses

    return {
        "month_start": month_start,
        "month_end": month_end,
        "current_balance": current_balance,
        "included_account_count": included_account_count,
        "savings_balance": savings_balance,
        "expected_income": expected_income,
        "expected_expenses": expected_expenses,
        "expected_daily_expense": daily_expense,
        "remaining_daily_expenses": remaining_daily_expenses,
        "uncovered_future_expenses": uncovered_future_expenses,
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
        "income_month_total": income_month_total,
        "expense_month_total": expense_month_total,
        "upcoming": sorted(upcoming, key=lambda item: item["date"]),
    }
