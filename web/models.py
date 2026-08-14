# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from .validators import validate_dashboard_gif


MONEY_VALIDATORS = [MinValueValidator(Decimal("0.01"))]
DASHBOARD_ANIMATION_FIELDS = ("healthy_gif", "warning_gif", "danger_gif")


def dashboard_animation_upload_to(instance, filename):
    return f"dashboard-animations/{instance.user_id}/{uuid4().hex}.gif"


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


class BudgetPreference(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="budget_preference"
    )
    expected_daily_expense = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    healthy_gif = models.FileField(
        upload_to=dashboard_animation_upload_to,
        validators=[FileExtensionValidator(["gif"]), validate_dashboard_gif],
        blank=True,
    )
    warning_gif = models.FileField(
        upload_to=dashboard_animation_upload_to,
        validators=[FileExtensionValidator(["gif"]), validate_dashboard_gif],
        blank=True,
    )
    danger_gif = models.FileField(
        upload_to=dashboard_animation_upload_to,
        validators=[FileExtensionValidator(["gif"]), validate_dashboard_gif],
        blank=True,
    )

    def save(self, *args, **kwargs):
        replaced_files = []
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous:
                for field_name in DASHBOARD_ANIMATION_FIELDS:
                    old_file = getattr(previous, field_name)
                    new_file = getattr(self, field_name)
                    if old_file.name and old_file.name != new_file.name:
                        replaced_files.append((old_file.storage, old_file.name))

        super().save(*args, **kwargs)
        for storage, name in replaced_files:
            transaction.on_commit(lambda storage=storage, name=name: storage.delete(name))

    def __str__(self):
        return f"{self.user} - {self.expected_daily_expense} per day"


@receiver(post_delete, sender=BudgetPreference)
def delete_budget_animation_files(sender, instance, **kwargs):
    for field_name in DASHBOARD_ANIMATION_FIELDS:
        animation = getattr(instance, field_name)
        if animation.name:
            transaction.on_commit(
                lambda storage=animation.storage, name=animation.name: storage.delete(name)
            )


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
    is_skipped = models.BooleanField(default=False, editable=False)

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
    is_skipped = models.BooleanField(default=False, editable=False)

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
    # Retained for compatibility and refreshed when a target is edited.
    monthly_amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=MONEY_VALIDATORS
    )
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    target_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=MONEY_VALIDATORS,
        blank=True,
        null=True,
    )
    target_date = models.DateField(blank=True, null=True)
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="funded_goals",
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="savings_goals")

    class Meta:
        ordering = ["start_date", "name"]

    @property
    def progress_percent(self):
        if not self.target_amount or self.target_amount <= 0:
            return 0
        return min(int((self.current_balance / self.target_amount) * 100), 100)

    def __str__(self):
        return f"{self.name} - {self.monthly_amount}"


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=80, default="Darith Monthly")
    monthly_price = models.DecimalField(
        max_digits=8, decimal_places=2, validators=MONEY_VALIDATORS
    )
    currency = models.CharField(
        max_length=3,
        choices=[("eur", "EUR")],
        default="eur",
    )
    payment_instructions = models.TextField(
        blank=True,
        help_text=(
            "Explain how to pay manually, for example by bank transfer, PayPal, "
            "Revolut, or Wise. These instructions are shown to users."
        ),
    )
    trial_days = models.PositiveSmallIntegerField(
        default=14,
        validators=[MaxValueValidator(730)],
    )
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=Q(is_active=True),
                name="only_one_active_subscription_plan",
            )
        ]

    def save(self, *args, **kwargs):
        self.currency = self.currency.lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - {self.monthly_price} {self.currency.upper()}"


class UserSubscription(models.Model):
    STATUS_NOT_STARTED = "not_started"
    STATUS_PENDING = "pending"
    STATUS_TRIALING = "trialing"
    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = [
        (STATUS_NOT_STARTED, "Not started"),
        (STATUS_PENDING, "Payment reported"),
        (STATUS_TRIALING, "Free trial"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELED, "Canceled"),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="darith_subscription"
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="subscribers",
    )
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=STATUS_NOT_STARTED
    )
    access_until = models.DateField(
        blank=True,
        null=True,
        help_text="The last calendar date on which this user can access Darith.",
    )
    payment_reported_at = models.DateTimeField(blank=True, null=True)
    last_payment_verified_at = models.DateTimeField(blank=True, null=True)
    payment_note = models.CharField(
        max_length=255,
        blank=True,
        help_text="Private note for payment reference, method, or complimentary access.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.pk and self.status == self.STATUS_ACTIVE and self.payment_reported_at:
            previous_status = (
                type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if previous_status == self.STATUS_PENDING:
                self.last_payment_verified_at = timezone.now()
                self.payment_reported_at = None
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                        "last_payment_verified_at",
                        "payment_reported_at",
                    }
        super().save(*args, **kwargs)

    @property
    def payment_reference(self):
        return f"DARITH-{self.user_id:06d}"

    @property
    def has_access(self):
        return (
            self.status
            in {self.STATUS_PENDING, self.STATUS_TRIALING, self.STATUS_ACTIVE}
            and self.access_until is not None
            and self.access_until >= timezone.localdate()
        )

    @property
    def is_expired(self):
        return self.access_until is not None and self.access_until < timezone.localdate()

    def clean(self):
        super().clean()
        if self.status in {self.STATUS_TRIALING, self.STATUS_ACTIVE} and not self.access_until:
            raise ValidationError("Trial and active subscriptions need an access expiry date.")

    def __str__(self):
        return f"{self.user.username} - {self.get_status_display()}"


class Transfer(models.Model):
    name = models.CharField(max_length=100, default="Transfer")
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=MONEY_VALIDATORS
    )
    date = models.DateField()
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transfers")
    source_bank = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="outgoing_transfers",
    )
    source_goal = models.ForeignKey(
        SavingsGoal,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="outgoing_transfers",
    )
    destination_bank = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="incoming_transfers",
    )
    destination_goal = models.ForeignKey(
        SavingsGoal,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="incoming_transfers",
    )
    goal_period = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(source_bank__isnull=False, source_goal__isnull=True)
                    | Q(source_bank__isnull=True, source_goal__isnull=False)
                ),
                name="transfer_has_one_source",
            ),
            models.CheckConstraint(
                check=(
                    Q(destination_bank__isnull=False, destination_goal__isnull=True)
                    | Q(destination_bank__isnull=True, destination_goal__isnull=False)
                ),
                name="transfer_has_one_destination",
            ),
            models.UniqueConstraint(
                fields=["destination_goal", "goal_period"],
                condition=Q(destination_goal__isnull=False, goal_period__isnull=False),
                name="unique_goal_funding_period",
            ),
        ]

    @property
    def source(self):
        return self.source_bank or self.source_goal

    @property
    def destination(self):
        return self.destination_bank or self.destination_goal

    def clean(self):
        super().clean()
        sources = [self.source_bank, self.source_goal]
        destinations = [self.destination_bank, self.destination_goal]
        if sum(item is not None for item in sources) != 1:
            raise ValidationError("Choose exactly one source account.")
        if sum(item is not None for item in destinations) != 1:
            raise ValidationError("Choose exactly one destination account.")
        if self.source_bank_id and self.source_bank_id == self.destination_bank_id:
            raise ValidationError("Source and destination must be different.")
        if self.source_goal_id and self.source_goal_id == self.destination_goal_id:
            raise ValidationError("Source and destination must be different.")
        for item in [*sources, *destinations]:
            if item is not None and item.user_id != self.user_id:
                raise ValidationError("All transfer accounts must belong to the same user.")

    def __str__(self):
        return f"{self.name}: {self.source} to {self.destination}"
