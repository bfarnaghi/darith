# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.formats import date_format
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


def _default_forecast_horizon(today):
    """Forecast through the end of next month by default."""
    next_month_start = add_month(today.replace(day=1))
    return month_bounds(next_month_start)[1]


def _goal_saving_events(user, range_start, range_end):
    """Return unfunded saving contributions by date for a future range.

    Goal amounts are simulated sequentially, so a dated goal that reaches its
    target in one forecast month is not charged again in later forecast months.
    """
    goals = SavingsGoal.objects.filter(
        user=user,
        start_date__lte=range_end,
        is_archived=False,
    ).select_related("bank_account")
    funded_periods = set(
        Transfer.objects.filter(
            user=user,
            destination_goal__isnull=False,
            goal_period__gte=range_start.replace(day=1),
            goal_period__lte=range_end.replace(day=1),
        ).values_list("destination_goal_id", "goal_period")
    )

    events = []
    for goal in goals:
        if goal.bank_account and not goal.bank_account.include_in_budget:
            continue

        remaining = None
        if goal.target_amount is not None:
            remaining = max(goal.target_amount - goal.current_balance, ZERO)

        # Start at the first day of the current month so an unfunded goal whose
        # normal saving day has already passed is treated as due today instead
        # of disappearing from the forecast.
        for occurrence in occurrence_dates(
            goal, range_start.replace(day=1), range_end
        ):
            period = occurrence.replace(day=1)
            if (goal.pk, period) in funded_periods:
                continue
            if remaining is not None:
                if remaining <= ZERO:
                    break
                amount = (
                    remaining
                    if goal.target_date and occurrence >= goal.target_date
                    else min(goal.monthly_amount, remaining)
                )
                remaining -= amount
            else:
                amount = goal.monthly_amount

            if amount > ZERO:
                effective_date = max(occurrence, range_start)
                events.append(
                    {
                        "date": effective_date,
                        "kind": "saving",
                        "name": goal.name,
                        "amount": amount,
                    }
                )
    return events


def _timeline_status(safe_to_spend, daily_expense, currency_symbol, horizon_end):
    """Classify a day as comfortable, tight, or projected shortfall."""
    if safe_to_spend < ZERO:
        shortfall = abs(safe_to_spend)
        return (
            "danger",
            _(
                "You are projected to be %(amount)s short before %(date)s if no plan changes."
            )
            % {
                "amount": f"{currency_symbol}{shortfall:,.2f}",
                "date": date_format(horizon_end, "j M"),
            },
        )

    tight_threshold = daily_expense * Decimal("3")
    if daily_expense > ZERO and safe_to_spend < tight_threshold:
        return (
            "warning",
            _(
                "Your plan is covered, but only %(amount)s is safe for optional spending through %(date)s."
            )
            % {
                "amount": f"{currency_symbol}{safe_to_spend:,.2f}",
                "date": date_format(horizon_end, "j M"),
            },
        )

    return (
        "healthy",
        _(
            "Planned bills, savings, and everyday costs stay protected through %(date)s."
        )
        % {
            "date": date_format(horizon_end, "j M"),
        },
    )


def build_daily_forecast(user, today, horizon_end=None):
    """Build the single source of truth for Darith's forward-looking budget.

    Each row represents the start of one day. ``opening_balance`` is the bank
    balance expected before that day's planned movements. ``safe_to_spend`` is
    the maximum optional amount that can be spent on that day without pushing
    any later day in the forecast horizon below its protected commitments.

    Protected commitments are:
    * expected daily costs for the rest of the selected calendar month; and
    * scheduled bills and saving contributions not covered by income that is
      still expected in that same month.

    This deliberately prevents future income from becoming spendable before it
    arrives while still allowing future income to cover future known bills.
    """
    horizon_end = horizon_end or _default_forecast_horizon(today)
    if horizon_end < today:
        horizon_end = today

    accounts = BankAccount.objects.filter(user=user, include_in_budget=True)
    current_balance = _sum(accounts, "balance")
    preference = BudgetPreference.objects.filter(user=user).first()
    daily_expense = preference.expected_daily_expense if preference else ZERO
    currency_symbol = (
        preference.currency_symbol
        if preference
        else BudgetPreference.CURRENCY_SYMBOLS[BudgetPreference.CURRENCY_EUR]
    )

    event_map = {}

    def add_event(event_date, kind, name, amount):
        bucket = event_map.setdefault(
            event_date,
            {"income": ZERO, "expense": ZERO, "saving": ZERO, "events": []},
        )
        bucket[kind] += amount
        bucket["events"].append(
            {"kind": kind, "name": name, "amount": amount}
        )

    recurring_incomes = RecurringIncome.objects.filter(
        user=user,
        bank_account__include_in_budget=True,
        start_date__lte=horizon_end,
    )
    recurring_expenses = MonthlyExpense.objects.filter(
        user=user,
        bank_account__include_in_budget=True,
        start_date__lte=horizon_end,
    )

    # Dashboard posting runs before forecasting, so recurring occurrences due
    # today are already reflected in the current account balance. Start those
    # planned events tomorrow to avoid counting them twice.
    for plan in recurring_incomes:
        for occurrence in occurrence_dates(plan, today, horizon_end):
            if occurrence > today:
                add_event(occurrence, "income", plan.name, plan.amount)

    for plan in recurring_expenses:
        for occurrence in occurrence_dates(plan, today, horizon_end):
            if occurrence > today:
                add_event(occurrence, "expense", plan.name, plan.amount)

    # A saving contribution due today may still be unfunded if its source bank
    # account did not have enough money, so today's saving event must remain in
    # the forecast unless a goal-period transfer already exists.
    for event in _goal_saving_events(user, today, horizon_end):
        add_event(event["date"], "saving", event["name"], event["amount"])

    rows = []
    day = today
    opening_balance = current_balance
    while day <= horizon_end:
        bucket = event_map.get(
            day,
            {"income": ZERO, "expense": ZERO, "saving": ZERO, "events": []},
        )
        closing_balance = (
            opening_balance
            + bucket["income"]
            - bucket["expense"]
            - bucket["saving"]
            - daily_expense
        )
        rows.append(
            {
                "date": day,
                "opening_balance": opening_balance,
                "closing_balance": closing_balance,
                "income": bucket["income"],
                "expenses": bucket["expense"],
                "savings": bucket["saving"],
                "daily_cost": daily_expense,
                "events": list(bucket["events"]),
            }
        )
        opening_balance = closing_balance
        day += timedelta(days=1)

    # First calculate the liquidity headroom for each date within its own
    # calendar month. Daily costs are deliberately reserved from bank cash even
    # when later income is expected; future income may cover future bills and
    # savings, but it is not treated as spendable cash before arrival.
    month_key = None
    remaining_income = ZERO
    remaining_expenses = ZERO
    remaining_savings = ZERO
    remaining_daily_costs = ZERO
    for row in reversed(rows):
        key = (row["date"].year, row["date"].month)
        if key != month_key:
            month_key = key
            remaining_income = ZERO
            remaining_expenses = ZERO
            remaining_savings = ZERO
            remaining_daily_costs = ZERO

        remaining_income += row["income"]
        remaining_expenses += row["expenses"]
        remaining_savings += row["savings"]
        remaining_daily_costs += row["daily_cost"]
        uncovered_commitments = max(
            remaining_expenses + remaining_savings - remaining_income,
            ZERO,
        )
        protected_amount = remaining_daily_costs + uncovered_commitments
        row.update(
            {
                "remaining_income": remaining_income,
                "remaining_expenses": remaining_expenses,
                "remaining_savings": remaining_savings,
                "remaining_daily_costs": remaining_daily_costs,
                "uncovered_commitments": uncovered_commitments,
                "protected_amount": protected_amount,
                "day_headroom": row["opening_balance"] - protected_amount,
            }
        )

    # Spending on a selected date affects every later balance. Therefore the
    # safe optional amount is the lowest future headroom, not merely the cash
    # visible on the selected day.
    minimum_future_headroom = None
    for row in reversed(rows):
        if minimum_future_headroom is None:
            minimum_future_headroom = row["day_headroom"]
        else:
            minimum_future_headroom = min(
                minimum_future_headroom, row["day_headroom"]
            )
        row["safe_to_spend"] = minimum_future_headroom
        row["status"], row["warning"] = _timeline_status(
            minimum_future_headroom,
            daily_expense,
            currency_symbol,
            horizon_end,
        )

    return {
        "start_date": today,
        "end_date": horizon_end,
        "daily_expense": daily_expense,
        "current_balance": current_balance,
        "rows": rows,
    }


def build_next_month_forecast(user, today, current_budget=None, daily_forecast=None):
    period_start = add_month(today.replace(day=1))
    _period_start, period_end = month_bounds(period_start)
    daily_forecast = daily_forecast or build_daily_forecast(
        user, today, horizon_end=period_end
    )
    rows = [
        row
        for row in daily_forecast["rows"]
        if period_start <= row["date"] <= period_end
    ]
    if not rows:
        return {
            "month_start": period_start,
            "month_end": period_end,
            "opening_balance": ZERO,
            "expected_income": ZERO,
            "expected_expenses": ZERO,
            "daily_expenses": ZERO,
            "savings_target": ZERO,
            "projected_balance": ZERO,
            "free_to_spend": ZERO,
            "status": "healthy",
            "warning": "",
            "included_account_count": 0,
        }

    first_row = rows[0]
    last_row = rows[-1]
    expected_income = sum((row["income"] for row in rows), ZERO)
    expected_expenses = sum((row["expenses"] for row in rows), ZERO)
    daily_expenses = sum((row["daily_cost"] for row in rows), ZERO)
    savings_target = sum((row["savings"] for row in rows), ZERO)
    return {
        "month_start": period_start,
        "month_end": period_end,
        "opening_balance": first_row["opening_balance"],
        "expected_income": expected_income,
        "expected_expenses": expected_expenses,
        "daily_expenses": daily_expenses,
        "savings_target": savings_target,
        "projected_balance": last_row["closing_balance"],
        "free_to_spend": first_row["safe_to_spend"],
        "status": first_row["status"],
        "warning": first_row["warning"],
        "included_account_count": BankAccount.objects.filter(
            user=user, include_in_budget=True
        ).count(),
    }


def build_monthly_budget(user, today, daily_forecast=None):
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
    # ``savings_target`` is the amount that is actionable/due as of today.
    # The month-end outlook must also reserve contributions scheduled later
    # in this month, even when their first saving date has not arrived yet.
    savings_target = sum((item["amount"] for item in budget_reminders), ZERO)
    month_end_savings_target = _goal_target_for_period(user, month_start, month_end)
    current_balance = _sum(accounts, "balance")
    included_account_count = accounts.count()
    savings_balance = _sum(
        SavingsGoal.objects.filter(user=user, is_archived=False), "current_balance"
    )
    days_remaining = (month_end - today).days + 1
    preference = BudgetPreference.objects.filter(user=user).first()
    daily_expense = preference.expected_daily_expense if preference else ZERO
    remaining_daily_expenses = daily_expense * days_remaining
    daily_forecast = daily_forecast or build_daily_forecast(user, today)
    current_row = daily_forecast["rows"][0]
    month_end_row = next(
        row for row in daily_forecast["rows"] if row["date"] == month_end
    )
    projected_balance = month_end_row["closing_balance"]
    uncovered_future_expenses = max(expected_expenses - expected_income, ZERO)
    status = current_row["status"]
    warning = current_row["warning"]
    free_to_spend = current_row["safe_to_spend"]
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
        "month_end_savings_target": month_end_savings_target,
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
        "forecast_horizon_end": daily_forecast["end_date"],
    }
