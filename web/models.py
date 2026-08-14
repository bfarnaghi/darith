# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models


MONEY_VALIDATORS = [MinValueValidator(Decimal("0.01"))]


class OwnedCategory(models.Model):
    name = models.CharField(max_length=50)
    # Nullable only for categories left by pre-1.0 installations.
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name


class IncomeCategory(OwnedCategory):
    class Meta(OwnedCategory.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_income_category_per_user"
            )
        ]


class ExpenseCategory(OwnedCategory):
    class Meta(OwnedCategory.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_expense_category_per_user"
            )
        ]


class Token(models.Model):
    """Legacy API token retained for compatibility with existing installations."""

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=48)

    def __str__(self):
        return f"{self.user}-token"


class BankAccount(models.Model):
    name = models.CharField(max_length=100)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bank_accounts")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_bank_account_per_user"
            )
        ]

    def __str__(self):
        return f"{self.name} - {self.balance}"


class RecurringItem(models.Model):
    name = models.CharField(max_length=100)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=MONEY_VALIDATORS
    )
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE)

    class Meta:
        abstract = True
        ordering = ["start_date", "name"]

    @property
    def day_of_month(self):
        return self.start_date.day

    def __str__(self):
        return f"{self.name} - {self.amount}"


class RecurringIncome(RecurringItem):
    category = models.ForeignKey(
        IncomeCategory, on_delete=models.SET_NULL, blank=True, null=True
    )


class MonthlyExpense(RecurringItem):
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.SET_NULL, blank=True, null=True
    )


class Income(models.Model):
    text = models.CharField(max_length=255)
    date = models.DateField()
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=MONEY_VALIDATORS
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="incomes")
    category = models.ForeignKey(
        IncomeCategory, on_delete=models.SET_NULL, blank=True, null=True
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="incomes",
    )
    recurring_income = models.ForeignKey(
        RecurringIncome,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="posted_incomes",
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recurring_income", "date"],
                name="unique_recurring_income_occurrence",
            )
        ]

    def __str__(self):
        return f"{self.amount} - {self.date}"


class Expense(models.Model):
    text = models.CharField(max_length=255)
    date = models.DateField()
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=MONEY_VALIDATORS
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="expenses")
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.SET_NULL, blank=True, null=True
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="expenses",
    )
    monthly_expense = models.ForeignKey(
        MonthlyExpense,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="posted_expenses",
    )

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["monthly_expense", "date"],
                name="unique_monthly_expense_occurrence",
            )
        ]

    def __str__(self):
        return f"{self.amount} - {self.bank_account} - {self.date}"


class SavingsGoal(models.Model):
    name = models.CharField(max_length=100)
    monthly_amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=MONEY_VALIDATORS
    )
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="savings_goals")

    class Meta:
        ordering = ["start_date", "name"]

    def __str__(self):
        return f"{self.name} - {self.monthly_amount}"
