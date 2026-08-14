# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import SubscriptionPlan, UserSubscription


def get_active_plan():
    return SubscriptionPlan.objects.filter(is_active=True).first()


def _refresh_expired_status(subscription):
    if subscription.is_expired and subscription.status in {
        UserSubscription.STATUS_ACTIVE,
        UserSubscription.STATUS_TRIALING,
    }:
        subscription.status = UserSubscription.STATUS_EXPIRED
        subscription.save(update_fields=["status", "updated_at"])
    return subscription


def initialize_user_subscription(user):
    plan = get_active_plan()
    subscription, created = UserSubscription.objects.get_or_create(
        user=user,
        defaults={"plan": plan},
    )
    if created and plan and plan.trial_days:
        trial_start = timezone.localdate(user.date_joined)
        trial_end = trial_start + timedelta(days=plan.trial_days)
        if trial_end >= timezone.localdate():
            subscription.status = UserSubscription.STATUS_TRIALING
            subscription.access_until = trial_end
            subscription.save(
                update_fields=["status", "access_until", "updated_at"]
            )
    return _refresh_expired_status(subscription)


def get_user_subscription(user, create=False):
    if create:
        return initialize_user_subscription(user)
    subscription = (
        UserSubscription.objects.filter(user=user).select_related("plan").first()
    )
    return _refresh_expired_status(subscription) if subscription else None


def report_manual_payment(user):
    subscription = initialize_user_subscription(user)
    subscription.plan = get_active_plan() or subscription.plan
    subscription.status = UserSubscription.STATUS_PENDING
    subscription.payment_reported_at = timezone.now()
    subscription.save(
        update_fields=["plan", "status", "payment_reported_at", "updated_at"]
    )
    return subscription


def user_has_subscription_access(user):
    if not settings.SUBSCRIPTIONS_ENABLED or user.is_staff or user.is_superuser:
        return True
    return initialize_user_subscription(user).has_access
