# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import logging
from datetime import UTC, datetime
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import StripeWebhookEvent, SubscriptionPlan, UserSubscription


logger = logging.getLogger(__name__)

SUBSCRIPTION_EVENT_TYPES = {
    "customer.subscription.created",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
    "customer.subscription.trial_will_end",
    "customer.subscription.updated",
}


class SubscriptionConfigurationError(Exception):
    pass


def get_active_plan():
    return SubscriptionPlan.objects.filter(is_active=True).first()


def get_user_subscription(user, create=False):
    if create:
        subscription, _ = UserSubscription.objects.get_or_create(user=user)
        return subscription
    return UserSubscription.objects.filter(user=user).select_related("plan").first()


def user_has_subscription_access(user):
    if not settings.SUBSCRIPTIONS_ENABLED or user.is_staff or user.is_superuser:
        return True
    subscription = get_user_subscription(user)
    return subscription is not None and subscription.has_access


def _stripe_timestamp(value):
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def _stripe_id(value):
    if isinstance(value, str) or value is None:
        return value
    return value.get("id")


def _subscription_period_end(payload):
    period_end = payload.get("current_period_end")
    if period_end:
        return period_end

    items = (payload.get("items") or {}).get("data") or []
    item_period_ends = [item.get("current_period_end") for item in items]
    item_period_ends = [value for value in item_period_ends if value]
    return min(item_period_ends) if item_period_ends else None


def _configure_stripe():
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _validate_stripe_price(plan):
    price = stripe.Price.retrieve(plan.stripe_price_id)
    recurring = price.get("recurring") or {}
    actual_amount = Decimal(str(price.get("unit_amount") or 0))
    expected_amount = plan.monthly_price * Decimal("100")
    if (
        not price.get("active")
        or price.get("currency") != plan.currency
        or recurring.get("interval") != "month"
        or recurring.get("interval_count", 1) != 1
        or actual_amount != expected_amount
    ):
        raise SubscriptionConfigurationError(
            "The active Darith plan does not match its Stripe monthly Price."
        )


def create_checkout_session(request, plan):
    _configure_stripe()
    _validate_stripe_price(plan)
    user_subscription = get_user_subscription(request.user, create=True)
    now = timezone.now()

    if (
        user_subscription.checkout_session_id
        and user_subscription.checkout_session_expires_at
        and user_subscription.checkout_session_expires_at > now
    ):
        try:
            session = stripe.checkout.Session.retrieve(
                user_subscription.checkout_session_id
            )
        except stripe.InvalidRequestError:
            user_subscription.checkout_session_id = ""
            user_subscription.checkout_session_expires_at = None
            user_subscription.save(
                update_fields=[
                    "checkout_session_id",
                    "checkout_session_expires_at",
                    "updated_at",
                ]
            )
        else:
            if session.status == "open" and session.url:
                return session

    return_url = request.build_absolute_uri(reverse("subscription_overview"))
    metadata = {
        "darith_user_id": str(request.user.pk),
        "darith_plan_id": str(plan.pk),
    }
    checkout_parameters = {
        "mode": "subscription",
        "line_items": [{"price": plan.stripe_price_id, "quantity": 1}],
        "payment_method_collection": "always",
        "client_reference_id": str(request.user.pk),
        "success_url": f"{return_url}?checkout=success",
        "cancel_url": f"{return_url}?checkout=canceled",
        "metadata": metadata,
        "subscription_data": {"metadata": metadata},
    }
    if plan.trial_days:
        checkout_parameters["subscription_data"]["trial_period_days"] = plan.trial_days
    if user_subscription.stripe_customer_id:
        checkout_parameters["customer"] = user_subscription.stripe_customer_id
    elif request.user.email:
        checkout_parameters["customer_email"] = request.user.email

    session = stripe.checkout.Session.create(**checkout_parameters)
    user_subscription.plan = plan
    user_subscription.status = UserSubscription.STATUS_PENDING
    user_subscription.checkout_session_id = session.id
    user_subscription.checkout_session_expires_at = _stripe_timestamp(session.expires_at)
    user_subscription.save(
        update_fields=[
            "plan",
            "status",
            "checkout_session_id",
            "checkout_session_expires_at",
            "updated_at",
        ]
    )
    return session


def create_customer_portal_session(request, user_subscription):
    _configure_stripe()
    return stripe.billing_portal.Session.create(
        customer=user_subscription.stripe_customer_id,
        return_url=request.build_absolute_uri(reverse("subscription_overview")),
    )


def _event_is_stale(user_subscription, event_time):
    return (
        user_subscription.last_stripe_event_at is not None
        and event_time is not None
        and event_time < user_subscription.last_stripe_event_at
    )


def _user_from_metadata(payload):
    metadata = payload.get("metadata") or {}
    user_id = metadata.get("darith_user_id")
    if not user_id:
        return None
    return User.objects.filter(pk=user_id).first()


def _find_user_subscription(payload):
    user = _user_from_metadata(payload)
    if user:
        return get_user_subscription(user, create=True)

    stripe_subscription_id = _stripe_id(payload.get("subscription")) or payload.get("id")
    stripe_customer_id = _stripe_id(payload.get("customer"))
    query = UserSubscription.objects.all()
    if stripe_subscription_id:
        match = query.filter(stripe_subscription_id=stripe_subscription_id).first()
        if match:
            return match
    if stripe_customer_id:
        return query.filter(stripe_customer_id=stripe_customer_id).first()
    return None


def _plan_from_payload(payload):
    metadata = payload.get("metadata") or {}
    plan_id = metadata.get("darith_plan_id")
    if plan_id:
        plan = SubscriptionPlan.objects.filter(pk=plan_id).first()
        if plan:
            return plan

    items = (payload.get("items") or {}).get("data") or []
    if not items:
        return None
    price = items[0].get("price") or {}
    price_id = _stripe_id(price)
    if not price_id:
        return None
    return SubscriptionPlan.objects.filter(stripe_price_id=price_id).first()


def _sync_checkout_event(payload, event_time):
    user_subscription = _find_user_subscription(payload)
    if user_subscription is None or _event_is_stale(user_subscription, event_time):
        return

    user_subscription.plan = _plan_from_payload(payload) or user_subscription.plan
    user_subscription.stripe_customer_id = _stripe_id(payload.get("customer"))
    user_subscription.stripe_subscription_id = _stripe_id(payload.get("subscription"))
    if not user_subscription.has_stripe_access:
        user_subscription.status = UserSubscription.STATUS_PENDING
    user_subscription.checkout_session_id = ""
    user_subscription.checkout_session_expires_at = None
    user_subscription.last_stripe_event_at = event_time
    user_subscription.save()


def _expire_checkout_event(payload, event_time):
    session_id = payload.get("id")
    user_subscription = UserSubscription.objects.filter(
        checkout_session_id=session_id
    ).first()
    if user_subscription is None or _event_is_stale(user_subscription, event_time):
        return
    user_subscription.status = UserSubscription.STATUS_NOT_STARTED
    user_subscription.checkout_session_id = ""
    user_subscription.checkout_session_expires_at = None
    user_subscription.last_stripe_event_at = event_time
    user_subscription.save()


def _sync_subscription_event(payload, event_type, event_time):
    user_subscription = _find_user_subscription(payload)
    if user_subscription is None:
        logger.warning("Stripe subscription event could not be matched to a Darith user.")
        return
    if _event_is_stale(user_subscription, event_time):
        return

    status = payload.get("status") or UserSubscription.STATUS_INCOMPLETE
    if event_type == "customer.subscription.deleted":
        status = UserSubscription.STATUS_CANCELED

    user_subscription.plan = _plan_from_payload(payload) or user_subscription.plan
    user_subscription.status = status
    user_subscription.stripe_customer_id = _stripe_id(payload.get("customer"))
    user_subscription.stripe_subscription_id = payload.get("id")
    user_subscription.trial_ends_at = _stripe_timestamp(payload.get("trial_end"))
    user_subscription.current_period_end = _stripe_timestamp(
        _subscription_period_end(payload)
    )
    user_subscription.cancel_at_period_end = bool(
        payload.get("cancel_at_period_end", False)
    )
    user_subscription.checkout_session_id = ""
    user_subscription.checkout_session_expires_at = None
    user_subscription.last_stripe_event_at = event_time
    user_subscription.save()


@transaction.atomic
def process_stripe_event(event):
    event_record, created = StripeWebhookEvent.objects.get_or_create(
        event_id=event["id"],
        defaults={"event_type": event["type"]},
    )
    if not created:
        return False

    event_type = event["type"]
    payload = event["data"]["object"]
    event_time = _stripe_timestamp(event.get("created"))

    if event_type == "checkout.session.completed":
        _sync_checkout_event(payload, event_time)
    elif event_type == "checkout.session.expired":
        _expire_checkout_event(payload, event_time)
    elif event_type in SUBSCRIPTION_EVENT_TYPES:
        _sync_subscription_event(payload, event_type, event_time)

    return True
