# Generated for Darith public planning defaults and PIN hardening.
from django.contrib.auth.hashers import identify_hasher, make_password
from django.db import migrations, models


def hash_legacy_plaintext_pins(apps, schema_editor):
    BudgetPreference = apps.get_model("web", "BudgetPreference")
    for preference in BudgetPreference.objects.exclude(darith_pin_hash="").iterator():
        value = preference.darith_pin_hash
        try:
            identify_hasher(value)
        except ValueError:
            preference.darith_pin_hash = make_password(value)
            preference.save(update_fields=["darith_pin_hash"])


class Migration(migrations.Migration):
    dependencies = [
        ("web", "0022_flexible_plans_occurrences_and_balance_freshness"),
    ]

    operations = [
        migrations.AlterField(
            model_name="budgetpreference",
            name="forecast_months",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, "Current month"),
                    (1, "1 month ahead"),
                    (2, "2 months ahead"),
                    (3, "3 months ahead"),
                ],
                default=0,
            ),
        ),
        migrations.AlterField(
            model_name="budgetpreference",
            name="show_money_timeline",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(hash_legacy_plaintext_pins, migrations.RunPython.noop),
    ]
