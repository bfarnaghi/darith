# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils.translation import gettext as _

from .models import (
    BankAccount,
    BudgetPreference,
    DailySpendingAdjustment,
    Expense,
    Income,
    MonthlyExpense,
    PlanOccurrence,
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
    """Return planned dates for once, daily, weekly, or monthly plans."""
    lower = max(item.start_date, range_start)
    upper = min(item.end_date or range_end, range_end)
    if lower > upper:
        return []

    frequency = getattr(item, "frequency", "monthly") or "monthly"
    if frequency == "once":
        return [item.start_date] if lower <= item.start_date <= upper else []

    if frequency == "daily":
        count = (upper - lower).days + 1
        return [lower + timedelta(days=offset) for offset in range(count)]

    if frequency == "weekly":
        days_from_start = (lower - item.start_date).days
        offset = (-days_from_start) % 7
        first = lower + timedelta(days=offset)
        dates = []
        occurrence = first
        while occurrence <= upper:
            dates.append(occurrence)
            occurrence += timedelta(days=7)
        return dates

    # Monthly plans keep the original day-of-month behavior and clamp dates
    # such as the 31st to the end of shorter months.
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


def _occurrence_override_map(user):
    overrides = {}
    for item in PlanOccurrence.objects.filter(user=user).select_related(
        "recurring_income", "monthly_expense", "savings_goal"
    ):
        plan_id = (
            item.recurring_income_id
            or item.monthly_expense_id
            or item.savings_goal_id
        )
        overrides[(item.kind, plan_id, item.scheduled_date)] = item
    return overrides


def _actual_occurrence_sets(user):
    return {
        "income": set(
            Income.objects.filter(user=user, recurring_income__isnull=False)
            .values_list("recurring_income_id", "date")
        ),
        "expense": set(
            Expense.objects.filter(user=user, monthly_expense__isnull=False)
            .values_list("monthly_expense_id", "date")
        ),
        "saving": set(
            Transfer.objects.filter(user=user, destination_goal__isnull=False, goal_period__isnull=False)
            .values_list("destination_goal_id", "goal_period")
        ),
    }


def _occurrence_is_already_done(kind, plan_id, scheduled_date, override, actual_sets):
    if override and override.status in {
        PlanOccurrence.STATUS_CONFIRMED,
        PlanOccurrence.STATUS_SKIPPED,
    }:
        return True
    if kind == PlanOccurrence.KIND_SAVING:
        return (plan_id, scheduled_date.replace(day=1)) in actual_sets["saving"]
    # Before occurrence overrides existed, recurring transactions were posted on
    # their planned date. Keep treating those historical rows as completed.
    return (plan_id, scheduled_date) in actual_sets[kind]


def _default_occurrence_amount(kind, plan, scheduled_date):
    if kind == PlanOccurrence.KIND_SAVING:
        return goal_monthly_contribution(plan, scheduled_date)
    return plan.amount


def pending_plan_occurrences(user, today):
    """Return planned items due by today that still need a user decision."""
    overrides = _occurrence_override_map(user)
    actual_sets = _actual_occurrence_sets(user)
    items = []

    plan_groups = [
        (PlanOccurrence.KIND_INCOME, RecurringIncome.objects.filter(user=user)),
        (PlanOccurrence.KIND_EXPENSE, MonthlyExpense.objects.filter(user=user)),
        (
            PlanOccurrence.KIND_SAVING,
            SavingsGoal.objects.filter(user=user, is_archived=False),
        ),
    ]
    for kind, queryset in plan_groups:
        for plan in queryset.select_related("bank_account"):
            occurrence_start = (
                max(plan.start_date, today.replace(day=1))
                if kind == PlanOccurrence.KIND_SAVING
                else plan.start_date
            )
            for scheduled_date in occurrence_dates(plan, occurrence_start, today):
                override = overrides.get((kind, plan.pk, scheduled_date))
                if _occurrence_is_already_done(
                    kind, plan.pk, scheduled_date, override, actual_sets
                ):
                    continue
                effective_date = override.effective_date if override else scheduled_date
                if effective_date > today:
                    continue
                amount = (
                    override.amount
                    if override
                    else _default_occurrence_amount(kind, plan, scheduled_date)
                )
                if amount <= ZERO:
                    continue
                items.append(
                    {
                        "kind": kind,
                        "plan": plan,
                        "scheduled_date": scheduled_date,
                        "date": effective_date,
                        "amount": amount,
                        "override": override,
                        "is_overdue": effective_date < today,
                    }
                )

    items.sort(key=lambda item: (item["date"], item["kind"], item["plan"].name))
    return items


def next_plan_occurrence(user, kind, plan, today, search_days=400):
    """Return the next unresolved occurrence for one plan."""
    overrides = _occurrence_override_map(user)
    actual_sets = _actual_occurrence_sets(user)
    end = today + timedelta(days=search_days)
    for scheduled_date in occurrence_dates(plan, today, end):
        override = overrides.get((kind, plan.pk, scheduled_date))
        if _occurrence_is_already_done(
            kind, plan.pk, scheduled_date, override, actual_sets
        ):
            continue
        effective_date = override.effective_date if override else scheduled_date
        amount = (
            override.amount
            if override
            else _default_occurrence_amount(kind, plan, scheduled_date)
        )
        if amount > ZERO:
            return {
                "kind": kind,
                "plan": plan,
                "scheduled_date": scheduled_date,
                "date": effective_date,
                "amount": amount,
                "override": override,
            }
    return None


def plan_for_occurrence(user, kind, plan_id):
    if kind == PlanOccurrence.KIND_INCOME:
        return RecurringIncome.objects.select_related("bank_account", "category").get(
            pk=plan_id, user=user
        )
    if kind == PlanOccurrence.KIND_EXPENSE:
        return MonthlyExpense.objects.select_related("bank_account", "category").get(
            pk=plan_id, user=user
        )
    if kind == PlanOccurrence.KIND_SAVING:
        return SavingsGoal.objects.select_related("bank_account").get(
            pk=plan_id, user=user, is_archived=False
        )
    raise ValidationError(_("Unknown plan type."))


def occurrence_initial(user, kind, plan, scheduled_date):
    override = PlanOccurrence.objects.filter(
        user=user,
        kind=kind,
        scheduled_date=scheduled_date,
        **{
            "recurring_income": plan if kind == PlanOccurrence.KIND_INCOME else None,
            "monthly_expense": plan if kind == PlanOccurrence.KIND_EXPENSE else None,
            "savings_goal": plan if kind == PlanOccurrence.KIND_SAVING else None,
        },
    ).first()
    return {
        "amount": override.amount if override else _default_occurrence_amount(kind, plan, scheduled_date),
        "date": override.effective_date if override else scheduled_date,
    }


@transaction.atomic
def apply_plan_occurrence_action(
    user, kind, plan, scheduled_date, action, effective_date, amount, today
):
    """Confirm, move, or skip one occurrence without changing the whole plan."""
    filters = {
        "user": user,
        "kind": kind,
        "scheduled_date": scheduled_date,
        "recurring_income": plan if kind == PlanOccurrence.KIND_INCOME else None,
        "monthly_expense": plan if kind == PlanOccurrence.KIND_EXPENSE else None,
        "savings_goal": plan if kind == PlanOccurrence.KIND_SAVING else None,
    }
    occurrence, _created = PlanOccurrence.objects.select_for_update().get_or_create(
        defaults={"effective_date": effective_date, "amount": amount}, **filters
    )
    occurrence.effective_date = effective_date
    occurrence.amount = amount

    if action == "move":
        if effective_date < today:
            raise ValidationError(_("Move it to today or a future date."))
        occurrence.status = PlanOccurrence.STATUS_PENDING
        occurrence.full_clean()
        occurrence.save()
        return occurrence

    if action == "skip":
        occurrence.status = PlanOccurrence.STATUS_SKIPPED
        occurrence.full_clean()
        occurrence.save()
        return occurrence

    if action != "confirm":
        raise ValidationError(_("Unknown action."))
    if effective_date > today:
        raise ValidationError(_("You can only mark an item done on today or an earlier date."))

    if kind == PlanOccurrence.KIND_INCOME:
        if Income.objects.filter(recurring_income=plan, date=effective_date).exists():
            raise ValidationError(_("This income is already recorded on that date."))
        item = Income.objects.create(
            user=user,
            text=plan.name,
            amount=amount,
            date=effective_date,
            category=plan.category,
            bank_account=plan.bank_account,
            recurring_income=plan,
        )
        adjust_account_balance(plan.bank_account_id, amount)
    elif kind == PlanOccurrence.KIND_EXPENSE:
        if Expense.objects.filter(monthly_expense=plan, date=effective_date).exists():
            raise ValidationError(_("This expense is already recorded on that date."))
        item = Expense.objects.create(
            user=user,
            text=plan.name,
            amount=amount,
            date=effective_date,
            category=plan.category,
            bank_account=plan.bank_account,
            monthly_expense=plan,
        )
        adjust_account_balance(plan.bank_account_id, -amount)
    else:
        if not plan.bank_account_id:
            raise ValidationError(_("Choose a bank account for this saving goal first."))
        remaining = (
            max(plan.target_amount - plan.current_balance, ZERO)
            if plan.target_amount is not None
            else None
        )
        if remaining is not None:
            amount = min(amount, remaining)
            occurrence.amount = amount
        if amount <= ZERO:
            raise ValidationError(_("This saving goal is already complete."))
        if plan.bank_account.balance < amount:
            raise InsufficientFunds(_("The bank account does not have enough money."))
        period = scheduled_date.replace(day=1)
        if Transfer.objects.filter(destination_goal=plan, goal_period=period).exists():
            raise ValidationError(_("This saving is already recorded for that month."))
        item = Transfer(
            user=user,
            name=_("Save for %(goal)s") % {"goal": plan.name},
            amount=amount,
            date=effective_date,
            source_bank=plan.bank_account,
            destination_goal=plan,
            goal_period=period,
        )
        item.full_clean()
        item.save()
        _apply_transfer(item)

    occurrence.status = PlanOccurrence.STATUS_CONFIRMED
    occurrence.full_clean()
    occurrence.save()
    return occurrence


def daily_spending_amount(user, preference, day, adjustments=None):
    """Return the expected daily spending for one date, including temporary cuts."""
    base = preference.expected_daily_expense if preference else ZERO
    if adjustments is None:
        adjustments = DailySpendingAdjustment.objects.filter(
            user=user, start_date__lte=day, end_date__gte=day
        )
    amounts = [
        adjustment.daily_amount
        for adjustment in adjustments
        if adjustment.start_date <= day <= adjustment.end_date
    ]
    return min([base, *amounts]) if amounts else base


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


def _default_forecast_horizon(today, months_ahead=0):
    """Return the end date for the current month or up to 3 months ahead."""
    try:
        months_ahead = int(months_ahead)
    except (TypeError, ValueError):
        months_ahead = 0
    months_ahead = max(0, min(months_ahead, 3))
    target_month = today.replace(day=1)
    for _ in range(months_ahead):
        target_month = add_month(target_month)
    return month_bounds(target_month)[1]


def _goal_saving_events(user, range_start, range_end, overrides=None, actual_sets=None):
    """Return unresolved saving contributions by date for a future range."""
    overrides = overrides or _occurrence_override_map(user)
    actual_sets = actual_sets or _actual_occurrence_sets(user)
    goals = SavingsGoal.objects.filter(
        user=user,
        start_date__lte=range_end,
        is_archived=False,
    ).select_related("bank_account")

    events = []
    for goal in goals:
        if goal.bank_account and not goal.bank_account.include_in_budget:
            continue

        remaining = None
        if goal.target_amount is not None:
            remaining = max(goal.target_amount - goal.current_balance, ZERO)

        # Include a saving from an older month when the user moved only that
        # occurrence into this forecast range.
        first_month = range_start.replace(day=1)
        older_moved = [
            item
            for (kind, plan_id, scheduled), item in overrides.items()
            if kind == PlanOccurrence.KIND_SAVING
            and plan_id == goal.pk
            and scheduled < first_month
            and item.status == PlanOccurrence.STATUS_PENDING
            and range_start <= item.effective_date <= range_end
        ]
        for item in sorted(older_moved, key=lambda value: value.effective_date):
            amount = item.amount
            if remaining is not None:
                amount = min(amount, remaining)
            if amount > ZERO:
                events.append(
                    {
                        "scheduled_date": item.scheduled_date,
                        "date": item.effective_date,
                        "kind": "saving",
                        "name": goal.name,
                        "amount": amount,
                        "goal": goal,
                    }
                )
                if remaining is not None:
                    remaining = max(remaining - amount, ZERO)

        # Include the current month even when its normal saving day has already
        # passed. If it is still unresolved, the dashboard keeps it due today.
        for scheduled_date in occurrence_dates(goal, first_month, range_end):
            override = overrides.get(
                (PlanOccurrence.KIND_SAVING, goal.pk, scheduled_date)
            )
            if _occurrence_is_already_done(
                PlanOccurrence.KIND_SAVING,
                goal.pk,
                scheduled_date,
                override,
                actual_sets,
            ):
                continue

            amount = (
                override.amount
                if override
                else (
                    remaining
                    if remaining is not None
                    and goal.target_date
                    and scheduled_date >= goal.target_date
                    else min(goal.monthly_amount, remaining)
                    if remaining is not None
                    else goal.monthly_amount
                )
            )
            if amount <= ZERO:
                continue

            effective_date = override.effective_date if override else scheduled_date
            if effective_date < range_start:
                effective_date = range_start
            if effective_date > range_end:
                continue

            events.append(
                {
                    "scheduled_date": scheduled_date,
                    "date": effective_date,
                    "kind": "saving",
                    "name": goal.name,
                    "amount": amount,
                    "goal": goal,
                }
            )
            if remaining is not None:
                remaining = max(remaining - amount, ZERO)
                if remaining <= ZERO:
                    break
    return events


def _timeline_status(safe_to_spend, daily_expense, currency_symbol):
    """Classify a day using the safe-to-spend amount for its calendar month."""
    if safe_to_spend < ZERO:
        shortfall = abs(safe_to_spend)
        return (
            "danger",
            _("You may be %(amount)s short this month. Check your plans.")
            % {"amount": f"{currency_symbol}{shortfall:,.2f}"},
        )

    tight_threshold = daily_expense * Decimal("3")
    if daily_expense > ZERO and safe_to_spend < tight_threshold:
        return (
            "warning",
            _("Your plan is okay. You have %(amount)s extra to spend this month.")
            % {"amount": f"{currency_symbol}{safe_to_spend:,.2f}"},
        )

    return ("healthy", _("Your plan looks good this month."))


def _annotate_forecast_rows(rows, emergency_buffer, currency_symbol):
    """Add remaining-plan totals, safe-to-spend, and status to forecast rows."""
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
        protected_amount = (
            remaining_daily_costs + uncovered_commitments + emergency_buffer
        )
        row.update(
            {
                "remaining_income": remaining_income,
                "remaining_expenses": remaining_expenses,
                "remaining_savings": remaining_savings,
                "remaining_daily_costs": remaining_daily_costs,
                "uncovered_commitments": uncovered_commitments,
                "emergency_buffer": emergency_buffer,
                "protected_amount": protected_amount,
                "day_headroom": row["opening_balance"] - protected_amount,
            }
        )

    safe_month_key = None
    minimum_future_headroom = None
    for row in reversed(rows):
        key = (row["date"].year, row["date"].month)
        if key != safe_month_key:
            safe_month_key = key
            minimum_future_headroom = row["day_headroom"]
        else:
            minimum_future_headroom = min(
                minimum_future_headroom, row["day_headroom"]
            )
        row["safe_to_spend"] = minimum_future_headroom
        row["status"], row["warning"] = _timeline_status(
            minimum_future_headroom,
            row["daily_cost"],
            currency_symbol,
        )
    return rows


def build_daily_forecast(user, today, horizon_end=None):
    """Build Darith's end-of-day plan without pretending planned items happened."""
    preference = BudgetPreference.objects.filter(user=user).first()
    months_ahead = preference.forecast_months if preference else 0
    horizon_end = horizon_end or _default_forecast_horizon(today, months_ahead)
    if horizon_end < today:
        horizon_end = today

    accounts = BankAccount.objects.filter(user=user, include_in_budget=True)
    current_balance = _sum(accounts, "balance")
    emergency_buffer = preference.emergency_buffer if preference else ZERO
    currency_symbol = (
        preference.currency_symbol
        if preference
        else BudgetPreference.CURRENCY_SYMBOLS[BudgetPreference.CURRENCY_EUR]
    )
    adjustments = list(
        DailySpendingAdjustment.objects.filter(
            user=user, start_date__lte=horizon_end, end_date__gte=today
        )
    )
    overrides = _occurrence_override_map(user)
    actual_sets = _actual_occurrence_sets(user)

    event_map = {}

    def add_event(event_date, kind, name, amount, scheduled_date=None, plan=None):
        if not (today <= event_date <= horizon_end) or amount <= ZERO:
            return
        bucket = event_map.setdefault(
            event_date,
            {"income": ZERO, "expense": ZERO, "saving": ZERO, "events": []},
        )
        bucket[kind] += amount
        bucket["events"].append(
            {
                "kind": kind,
                "name": name,
                "amount": amount,
                "scheduled_date": scheduled_date,
                "plan_id": getattr(plan, "pk", None),
            }
        )

    plan_groups = [
        (
            PlanOccurrence.KIND_INCOME,
            RecurringIncome.objects.filter(
                user=user,
                bank_account__include_in_budget=True,
                start_date__lte=horizon_end,
            ),
        ),
        (
            PlanOccurrence.KIND_EXPENSE,
            MonthlyExpense.objects.filter(
                user=user,
                bank_account__include_in_budget=True,
                start_date__lte=horizon_end,
            ),
        ),
    ]
    for kind, queryset in plan_groups:
        for plan in queryset:
            for scheduled_date in occurrence_dates(plan, today, horizon_end):
                override = overrides.get((kind, plan.pk, scheduled_date))
                if _occurrence_is_already_done(
                    kind, plan.pk, scheduled_date, override, actual_sets
                ):
                    continue
                effective_date = override.effective_date if override else scheduled_date
                amount = override.amount if override else plan.amount
                if effective_date < today:
                    if kind == PlanOccurrence.KIND_INCOME:
                        continue
                    effective_date = today
                add_event(
                    effective_date,
                    kind,
                    plan.name,
                    amount,
                    scheduled_date=scheduled_date,
                    plan=plan,
                )

    # A past occurrence can be moved to a future date. Its scheduled date is no
    # longer inside the normal forecast range, so add that override explicitly.
    moved_overrides = PlanOccurrence.objects.filter(
        user=user,
        status=PlanOccurrence.STATUS_PENDING,
        scheduled_date__lt=today,
        effective_date__gte=today,
        effective_date__lte=horizon_end,
    ).select_related("recurring_income", "monthly_expense")
    for override in moved_overrides:
        if override.kind == PlanOccurrence.KIND_INCOME and override.recurring_income:
            plan = override.recurring_income
        elif override.kind == PlanOccurrence.KIND_EXPENSE and override.monthly_expense:
            plan = override.monthly_expense
        else:
            continue
        if plan.bank_account.include_in_budget:
            add_event(
                override.effective_date,
                override.kind,
                plan.name,
                override.amount,
                scheduled_date=override.scheduled_date,
                plan=plan,
            )

    # Keep unresolved past expenses due today until the user confirms, moves,
    # or skips them. Past income is not assumed to have arrived.
    for pending in pending_plan_occurrences(user, today):
        if pending["scheduled_date"] >= today:
            continue
        if pending["kind"] != PlanOccurrence.KIND_EXPENSE:
            continue
        plan = pending["plan"]
        if plan.bank_account.include_in_budget:
            add_event(
                today,
                "expense",
                plan.name,
                pending["amount"],
                scheduled_date=pending["scheduled_date"],
                plan=plan,
            )

    for event in _goal_saving_events(
        user, today, horizon_end, overrides=overrides, actual_sets=actual_sets
    ):
        add_event(
            event["date"],
            "saving",
            event["name"],
            event["amount"],
            scheduled_date=event["scheduled_date"],
            plan=event["goal"],
        )

    rows = []
    day = today
    opening_balance = current_balance
    while day <= horizon_end:
        bucket = event_map.get(
            day,
            {"income": ZERO, "expense": ZERO, "saving": ZERO, "events": []},
        )
        daily_cost = daily_spending_amount(
            user, preference, day, adjustments=adjustments
        )
        closing_balance = (
            opening_balance
            + bucket["income"]
            - bucket["expense"]
            - bucket["saving"]
            - daily_cost
        )
        rows.append(
            {
                "date": day,
                "opening_balance": opening_balance,
                "closing_balance": closing_balance,
                "income": bucket["income"],
                "expenses": bucket["expense"],
                "savings": bucket["saving"],
                "daily_cost": daily_cost,
                "events": list(bucket["events"]),
            }
        )
        opening_balance = closing_balance
        day += timedelta(days=1)

    _annotate_forecast_rows(rows, emergency_buffer, currency_symbol)
    return {
        "start_date": today,
        "end_date": horizon_end,
        "daily_expense": preference.expected_daily_expense if preference else ZERO,
        "emergency_buffer": emergency_buffer,
        "current_balance": current_balance,
        "rows": rows,
    }


def _simulate_spending_change(
    base_rows,
    extra_amount,
    adjustment_start,
    adjustment_end,
    daily_amount,
    emergency_buffer,
    currency_symbol,
):
    rows = []
    opening_balance = base_rows[0]["opening_balance"] if base_rows else ZERO
    first_date = base_rows[0]["date"] if base_rows else None
    for source in base_rows:
        day = source["date"]
        expenses = source["expenses"] + (extra_amount if day == first_date else ZERO)
        daily_cost = source["daily_cost"]
        if adjustment_start <= day <= adjustment_end:
            daily_cost = min(daily_cost, daily_amount)
        closing_balance = (
            opening_balance
            + source["income"]
            - expenses
            - source["savings"]
            - daily_cost
        )
        rows.append(
            {
                "date": day,
                "opening_balance": opening_balance,
                "closing_balance": closing_balance,
                "income": source["income"],
                "expenses": expenses,
                "savings": source["savings"],
                "daily_cost": daily_cost,
                "events": source["events"],
            }
        )
        opening_balance = closing_balance
    _annotate_forecast_rows(rows, emergency_buffer, currency_symbol)
    return rows


def _spending_simulation_has_cash(rows, emergency_buffer):
    return bool(rows) and min(row["closing_balance"] for row in rows) >= emergency_buffer


def calculate_spending_tradeoff(user, today, amount, days):
    """Suggest a temporary daily-spending level for one extra planned expense."""
    days = max(1, min(int(days), 365))
    adjustment_start = today + timedelta(days=1)
    adjustment_end = today + timedelta(days=days)
    horizon_end = month_bounds(adjustment_end)[1]
    base = build_daily_forecast(user, today, horizon_end=horizon_end)
    preference = BudgetPreference.objects.filter(user=user).first()
    currency_symbol = (
        preference.currency_symbol
        if preference
        else BudgetPreference.CURRENCY_SYMBOLS[BudgetPreference.CURRENCY_EUR]
    )
    current_daily = daily_spending_amount(
        user, preference, adjustment_start
    )
    safe_before = base["rows"][0]["safe_to_spend"] if base["rows"] else ZERO

    unchanged = _simulate_spending_change(
        base["rows"],
        amount,
        adjustment_start,
        adjustment_end,
        current_daily,
        base["emergency_buffer"],
        currency_symbol,
    )
    if _spending_simulation_has_cash(unchanged, base["emergency_buffer"]):
        return {
            "possible": True,
            "needs_change": False,
            "amount": amount,
            "days": days,
            "current_daily": current_daily,
            "suggested_daily": current_daily,
            "daily_reduction": ZERO,
            "start_date": adjustment_start,
            "end_date": adjustment_end,
            "safe_before": safe_before,
            "safe_after": min(row["closing_balance"] for row in unchanged) - base["emergency_buffer"],
        }

    zero_daily = _simulate_spending_change(
        base["rows"],
        amount,
        adjustment_start,
        adjustment_end,
        ZERO,
        base["emergency_buffer"],
        currency_symbol,
    )
    if not _spending_simulation_has_cash(zero_daily, base["emergency_buffer"]):
        return {
            "possible": False,
            "needs_change": True,
            "amount": amount,
            "days": days,
            "current_daily": current_daily,
            "suggested_daily": ZERO,
            "daily_reduction": current_daily,
            "start_date": adjustment_start,
            "end_date": adjustment_end,
            "safe_before": safe_before,
            "safe_after": (
                min(row["closing_balance"] for row in zero_daily) - base["emergency_buffer"]
                if zero_daily
                else -amount
            ),
        }

    # Find the highest cent value that still keeps the plan safe.
    low = 0
    high = int((current_daily * 100).to_integral_value())
    best = 0
    best_rows = zero_daily
    while low <= high:
        mid = (low + high) // 2
        candidate = Decimal(mid) / Decimal("100")
        simulated = _simulate_spending_change(
            base["rows"],
            amount,
            adjustment_start,
            adjustment_end,
            candidate,
            base["emergency_buffer"],
            currency_symbol,
        )
        if _spending_simulation_has_cash(simulated, base["emergency_buffer"]):
            best = mid
            best_rows = simulated
            low = mid + 1
        else:
            high = mid - 1

    suggested = Decimal(best) / Decimal("100")
    return {
        "possible": True,
        "needs_change": suggested < current_daily,
        "amount": amount,
        "days": days,
        "current_daily": current_daily,
        "suggested_daily": suggested,
        "daily_reduction": current_daily - suggested,
        "start_date": adjustment_start,
        "end_date": adjustment_end,
        "safe_before": safe_before,
        "safe_after": min(row["closing_balance"] for row in best_rows) - base["emergency_buffer"],
    }


@transaction.atomic
def apply_spending_tradeoff(user, today, name, amount, days, bank_account, suggested_daily):
    """Add the one-time expense plan and its temporary daily-spending change."""
    if bank_account.user_id != user.id:
        raise ValidationError(_("Choose one of your own bank accounts."))
    expense_plan = MonthlyExpense.objects.create(
        user=user,
        name=name or _("Extra spending"),
        amount=amount,
        frequency="once",
        start_date=today,
        end_date=None,
        bank_account=bank_account,
    )
    preference, _created = BudgetPreference.objects.get_or_create(user=user)
    current_daily = daily_spending_amount(user, preference, today + timedelta(days=1))
    if suggested_daily < current_daily:
        DailySpendingAdjustment.objects.create(
            user=user,
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=max(1, min(int(days), 365))),
            daily_amount=suggested_daily,
            reason=expense_plan.name,
        )
    return expense_plan


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
    if not rows and daily_forecast is not None:
        # The visible Money by day range may stop at the current month.
        # Next-month calculations still need their own full month of rows.
        daily_forecast = build_daily_forecast(user, today, horizon_end=period_end)
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
    daily_forecast = daily_forecast or build_daily_forecast(user, today)
    month_rows = [
        row for row in daily_forecast["rows"] if today <= row["date"] <= month_end
    ]
    current_row = month_rows[0]
    month_end_row = month_rows[-1]

    expected_income = sum((row["income"] for row in month_rows), ZERO)
    expected_expenses = sum((row["expenses"] for row in month_rows), ZERO)
    remaining_daily_expenses = sum((row["daily_cost"] for row in month_rows), ZERO)
    month_end_savings_target = sum((row["savings"] for row in month_rows), ZERO)
    upcoming = []
    for row in month_rows:
        for event in row["events"]:
            upcoming.append(
                {
                    "kind": event["kind"],
                    "name": event["name"],
                    "date": row["date"],
                    "amount": event["amount"],
                }
            )

    pending = pending_plan_occurrences(user, today)
    savings_target = sum(
        (
            item["amount"]
            for item in pending
            if item["kind"] == PlanOccurrence.KIND_SAVING
            and (
                not item["plan"].bank_account
                or item["plan"].bank_account.include_in_budget
            )
        ),
        ZERO,
    )
    later_savings_target = max(month_end_savings_target - savings_target, ZERO)
    current_balance = _sum(accounts, "balance")
    included_account_count = accounts.count()
    savings_balance = _sum(
        SavingsGoal.objects.filter(user=user, is_archived=False), "current_balance"
    )
    days_remaining = (month_end - today).days + 1
    preference = BudgetPreference.objects.filter(user=user).first()
    base_daily_expense = preference.expected_daily_expense if preference else ZERO
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
        "expected_daily_expense": base_daily_expense,
        "today_daily_expense": current_row["daily_cost"],
        "remaining_daily_expenses": remaining_daily_expenses,
        "uncovered_future_expenses": uncovered_future_expenses,
        "savings_target": savings_target,
        "month_end_savings_target": month_end_savings_target,
        "later_savings_target": later_savings_target,
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
        "forecast_horizon_end": month_end,
    }
