# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.contrib import admin

from .models import (
    BankAccount,
    BudgetPreference,
    Expense,
    ExpenseCategory,
    Income,
    IncomeCategory,
    MonthlyExpense,
    RecurringIncome,
    SavingsGoal,
    StripeWebhookEvent,
    SubscriptionPlan,
    Transfer,
    Token,
    UserSubscription,
)


admin.site.register(
    [
        BankAccount,
        BudgetPreference,
        Expense,
        ExpenseCategory,
        Income,
        IncomeCategory,
        MonthlyExpense,
        RecurringIncome,
        SavingsGoal,
        Transfer,
        Token,
    ]
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "monthly_price",
        "currency",
        "trial_days",
        "is_active",
        "stripe_price_id",
    )
    list_filter = ("is_active", "currency")
    search_fields = ("name", "stripe_price_id")


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "status",
        "plan",
        "admin_bypass",
        "admin_bypass_until",
        "current_period_end",
    )
    list_filter = ("status", "admin_bypass", "plan")
    search_fields = (
        "user__username",
        "user__email",
        "stripe_customer_id",
        "stripe_subscription_id",
    )
    readonly_fields = (
        "status",
        "stripe_customer_id",
        "stripe_subscription_id",
        "checkout_session_id",
        "checkout_session_expires_at",
        "trial_ends_at",
        "current_period_end",
        "cancel_at_period_end",
        "last_stripe_event_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Account", {"fields": ("user", "plan")}),
        (
            "Administrator access",
            {"fields": ("admin_bypass", "admin_bypass_until", "admin_note")},
        ),
        (
            "Stripe state",
            {
                "fields": (
                    "status",
                    "stripe_customer_id",
                    "stripe_subscription_id",
                    "trial_ends_at",
                    "current_period_end",
                    "cancel_at_period_end",
                    "checkout_session_id",
                    "checkout_session_expires_at",
                    "last_stripe_event_at",
                )
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(StripeWebhookEvent)
class StripeWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "event_id", "processed_at")
    search_fields = ("event_type", "event_id")
    readonly_fields = ("event_type", "event_id", "processed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
