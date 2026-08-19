from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0021_budgetpreference_planning_settings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="bankaccount",
            name="balance_updated_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="recurringincome",
            name="frequency",
            field=models.CharField(
                choices=[
                    ("once", "Once"),
                    ("daily", "Daily"),
                    ("weekly", "Weekly"),
                    ("monthly", "Monthly"),
                ],
                default="monthly",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="monthlyexpense",
            name="frequency",
            field=models.CharField(
                choices=[
                    ("once", "Once"),
                    ("daily", "Daily"),
                    ("weekly", "Weekly"),
                    ("monthly", "Monthly"),
                ],
                default="monthly",
                max_length=12,
            ),
        ),
        migrations.CreateModel(
            name="DailySpendingAdjustment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                (
                    "daily_amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="daily_spending_adjustments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-start_date", "-id"]},
        ),
        migrations.CreateModel(
            name="PlanOccurrence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[("income", "Income"), ("expense", "Expense"), ("saving", "Saving")],
                        max_length=12,
                    ),
                ),
                ("scheduled_date", models.DateField()),
                ("effective_date", models.DateField()),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Waiting"), ("confirmed", "Done"), ("skipped", "Skipped")],
                        default="pending",
                        max_length=12,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "monthly_expense",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="occurrence_changes",
                        to="web.monthlyexpense",
                    ),
                ),
                (
                    "recurring_income",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="occurrence_changes",
                        to="web.recurringincome",
                    ),
                ),
                (
                    "savings_goal",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="occurrence_changes",
                        to="web.savingsgoal",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plan_occurrences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["effective_date", "kind", "id"]},
        ),
        migrations.AddConstraint(
            model_name="planoccurrence",
            constraint=models.UniqueConstraint(
                condition=Q(recurring_income__isnull=False),
                fields=("recurring_income", "scheduled_date"),
                name="unique_income_plan_occurrence",
            ),
        ),
        migrations.AddConstraint(
            model_name="planoccurrence",
            constraint=models.UniqueConstraint(
                condition=Q(monthly_expense__isnull=False),
                fields=("monthly_expense", "scheduled_date"),
                name="unique_expense_plan_occurrence",
            ),
        ),
        migrations.AddConstraint(
            model_name="planoccurrence",
            constraint=models.UniqueConstraint(
                condition=Q(savings_goal__isnull=False),
                fields=("savings_goal", "scheduled_date"),
                name="unique_saving_plan_occurrence",
            ),
        ),
    ]
