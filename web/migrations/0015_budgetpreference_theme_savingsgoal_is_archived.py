# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0014_expense_is_skipped_income_is_skipped"),
    ]

    operations = [
        migrations.AddField(
            model_name="budgetpreference",
            name="theme",
            field=models.CharField(
                choices=[
                    ("ocean", "Ocean"),
                    ("forest", "Forest"),
                    ("graphite", "Graphite"),
                ],
                default="ocean",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="savingsgoal",
            name="is_archived",
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
