# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from datetime import timedelta

from django.contrib import admin
from django.utils import timezone

from .models import (
    SubscriptionPlan,
    UserSubscription,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "monthly_price",
        "currency",
        "trial_days",
        "is_active",
        "instructions_configured",
    )
    list_filter = ("is_active", "currency")
    search_fields = ("name", "payment_instructions")

    @admin.display(boolean=True, description="Payment instructions")
    def instructions_configured(self, obj):
        return bool(obj.payment_instructions.strip())


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "status",
        "plan",
        "payment_reported_at",
        "access_until",
        "payment_reference_display",
    )
    list_filter = ("status", "plan")
    list_editable = ("status", "access_until")
    actions = ("activate_for_30_days", "mark_expired")
    search_fields = (
        "user__username",
        "user__email",
        "payment_note",
    )
    readonly_fields = (
        "payment_reference_display",
        "payment_reported_at",
        "last_payment_verified_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Account", {"fields": ("user", "plan")}),
        (
            "Access",
            {"fields": ("status", "access_until")},
        ),
        (
            "Manual payment",
            {
                "fields": (
                    "payment_reference_display",
                    "payment_reported_at",
                    "last_payment_verified_at",
                    "payment_note",
                )
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Payment reference")
    def payment_reference_display(self, obj):
        return obj.payment_reference if obj and obj.pk else "Saved after creation"

    @admin.action(description="Activate or extend selected users by 30 days")
    def activate_for_30_days(self, request, queryset):
        today = timezone.localdate()
        for subscription in queryset:
            start = max(subscription.access_until or today, today)
            subscription.access_until = start + timedelta(days=30)
            subscription.status = subscription.STATUS_ACTIVE
            subscription.save()

    @admin.action(description="Expire selected users now")
    def mark_expired(self, request, queryset):
        queryset.update(
            status=UserSubscription.STATUS_EXPIRED,
            access_until=timezone.localdate() - timedelta(days=1),
            updated_at=timezone.now(),
        )
