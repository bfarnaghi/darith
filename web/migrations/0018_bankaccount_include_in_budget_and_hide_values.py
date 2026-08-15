# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0017_budgetpreference_profile_picture_and_deletion_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankaccount",
            name="include_in_budget",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Include this account in free-to-spend and monthly dashboard "
                    "totals."
                ),
            ),
        ),
        migrations.AddField(
            model_name="budgetpreference",
            name="hide_financial_values",
            field=models.BooleanField(default=False),
        ),
    ]
