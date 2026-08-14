# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from datetime import date

from django.db import migrations, models


def preserve_existing_access(apps, schema_editor):
    UserSubscription = apps.get_model("web", "UserSubscription")
    today = date.today()

    for subscription in UserSubscription.objects.all().iterator():
        access_until = None
        status = subscription.status

        if subscription.admin_bypass:
            access_until = (
                subscription.admin_bypass_until.date()
                if subscription.admin_bypass_until
                else date(2099, 12, 31)
            )
            status = "active" if access_until >= today else "expired"
            if not subscription.admin_note:
                subscription.admin_note = "Migrated from administrator access bypass."
        elif status == "trialing" and subscription.trial_ends_at:
            access_until = subscription.trial_ends_at.date()
            status = "trialing" if access_until >= today else "expired"
        elif status in {"active", "canceled"} and subscription.current_period_end:
            access_until = subscription.current_period_end.date()
            status = "active" if access_until >= today else "expired"
        elif status == "canceled":
            status = "canceled"
        elif status == "not_started":
            status = "not_started"
        else:
            status = "expired"

        subscription.access_until = access_until
        subscription.status = status
        subscription.save(update_fields=["access_until", "status", "admin_note"])


class Migration(migrations.Migration):
    dependencies = [
        ("web", "0012_budgetpreference_danger_gif_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionplan",
            name="payment_instructions",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Explain how to pay manually, for example by bank transfer, "
                    "PayPal, Revolut, or Wise. These instructions are shown to users."
                ),
            ),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="access_until",
            field=models.DateField(
                blank=True,
                help_text=(
                    "The last calendar date on which this user can access Darith."
                ),
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="last_payment_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="payment_reported_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(preserve_existing_access, migrations.RunPython.noop),
        migrations.RenameField(
            model_name="usersubscription",
            old_name="admin_note",
            new_name="payment_note",
        ),
        migrations.AlterField(
            model_name="usersubscription",
            name="payment_note",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Private note for payment reference, method, or complimentary "
                    "access."
                ),
                max_length=255,
            ),
        ),
        migrations.RemoveField(
            model_name="subscriptionplan",
            name="stripe_price_id",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="admin_bypass",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="admin_bypass_until",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="cancel_at_period_end",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="checkout_session_expires_at",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="checkout_session_id",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="current_period_end",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="last_stripe_event_at",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="stripe_customer_id",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="stripe_subscription_id",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="trial_ends_at",
        ),
        migrations.AlterField(
            model_name="usersubscription",
            name="status",
            field=models.CharField(
                choices=[
                    ("not_started", "Not started"),
                    ("pending", "Payment reported"),
                    ("trialing", "Free trial"),
                    ("active", "Active"),
                    ("expired", "Expired"),
                    ("canceled", "Canceled"),
                ],
                default="not_started",
                max_length=24,
            ),
        ),
        migrations.DeleteModel(
            name="StripeWebhookEvent",
        ),
    ]
