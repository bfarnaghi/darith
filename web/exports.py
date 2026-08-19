# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import csv

from django.http import HttpResponse
from django.utils import timezone

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


CSV_COLUMNS = [
    "record_type",
    "record_id",
    "date",
    "end_date",
    "name",
    "amount",
    "balance",
    "included_in_budget",
    "currency",
    "category",
    "account",
    "source",
    "destination",
    "target_amount",
    "target_date",
    "recurring",
]


def _value(value):
    if value is None:
        return ""
    if isinstance(value, str):
        spreadsheet_value = value.lstrip(" \t\r\n")
        if spreadsheet_value.startswith(("=", "+", "-", "@")):
            return f"'{value}"
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _write_row(writer, **values):
    writer.writerow([_value(values.get(column)) for column in CSV_COLUMNS])


def build_user_csv_response(user):
    today = timezone.localdate()
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="darith-data-{today.isoformat()}.csv"'
    )
    response["Cache-Control"] = "no-store"
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(CSV_COLUMNS)

    preference = BudgetPreference.objects.filter(user=user).first()
    currency_code = (
        preference.currency if preference else BudgetPreference.CURRENCY_EUR
    )
    if preference:
        _write_row(
            writer,
            record_type="budget_preference",
            record_id=preference.pk,
            name="Expected daily expense",
            amount=preference.expected_daily_expense,
            currency=currency_code,
        )

    for account in BankAccount.objects.filter(user=user):
        _write_row(
            writer,
            record_type="bank_account",
            record_id=account.pk,
            name=account.name,
            balance=account.balance,
            included_in_budget="yes" if account.include_in_budget else "no",
            currency=currency_code,
        )

    for goal in SavingsGoal.objects.filter(user=user).select_related("bank_account"):
        _write_row(
            writer,
            record_type="savings_goal",
            record_id=goal.pk,
            date=goal.start_date,
            end_date=goal.end_date,
            name=goal.name,
            amount=goal.monthly_amount,
            balance=goal.current_balance,
            currency=currency_code,
            account=goal.bank_account.name if goal.bank_account else "",
            target_amount=goal.target_amount,
            target_date=goal.target_date,
        )

    for item in RecurringIncome.objects.filter(user=user).select_related(
        "category", "bank_account"
    ):
        _write_row(
            writer,
            record_type="recurring_income",
            record_id=item.pk,
            date=item.start_date,
            end_date=item.end_date,
            name=item.name,
            amount=item.amount,
            currency=currency_code,
            category=item.category.name if item.category else "",
            account=item.bank_account.name,
            recurring=item.frequency,
        )

    for item in MonthlyExpense.objects.filter(user=user).select_related(
        "category", "bank_account"
    ):
        _write_row(
            writer,
            record_type="recurring_expense",
            record_id=item.pk,
            date=item.start_date,
            end_date=item.end_date,
            name=item.name,
            amount=-item.amount,
            currency=currency_code,
            category=item.category.name if item.category else "",
            account=item.bank_account.name,
            recurring=item.frequency,
        )

    for item in Income.objects.filter(user=user, is_skipped=False).select_related(
        "category", "bank_account", "recurring_income"
    ):
        _write_row(
            writer,
            record_type="income",
            record_id=item.pk,
            date=item.date,
            name=item.text,
            amount=item.amount,
            currency=currency_code,
            category=item.category.name if item.category else "",
            account=item.bank_account.name if item.bank_account else "",
            recurring="yes" if item.recurring_income_id else "no",
        )

    for item in Expense.objects.filter(user=user, is_skipped=False).select_related(
        "category", "bank_account", "monthly_expense"
    ):
        _write_row(
            writer,
            record_type="expense",
            record_id=item.pk,
            date=item.date,
            name=item.text,
            amount=-item.amount,
            currency=currency_code,
            category=item.category.name if item.category else "",
            account=item.bank_account.name if item.bank_account else "",
            recurring="yes" if item.monthly_expense_id else "no",
        )

    for item in Transfer.objects.filter(user=user).select_related(
        "source_bank", "source_goal", "destination_bank", "destination_goal"
    ):
        _write_row(
            writer,
            record_type="transfer",
            record_id=item.pk,
            date=item.date,
            name=item.name,
            amount=item.amount,
            currency=currency_code,
            source=item.source.name,
            destination=item.destination.name,
            recurring="monthly_goal" if item.goal_period else "no",
        )

    return response
