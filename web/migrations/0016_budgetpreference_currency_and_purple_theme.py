# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0015_budgetpreference_theme_savingsgoal_is_archived"),
    ]

    operations = [
        migrations.AddField(
            model_name="budgetpreference",
            name="currency",
            field=models.CharField(
                choices=[
                    ("EUR", "Euro (EUR)"),
                    ("USD", "US dollar (USD)"),
                    ("GBP", "British pound (GBP)"),
                    ("CHF", "Swiss franc (CHF)"),
                    ("CAD", "Canadian dollar (CAD)"),
                    ("AUD", "Australian dollar (AUD)"),
                ],
                default="EUR",
                max_length=3,
            ),
        ),
        migrations.AlterField(
            model_name="budgetpreference",
            name="theme",
            field=models.CharField(
                choices=[
                    ("ocean", "Ocean"),
                    ("forest", "Forest"),
                    ("graphite", "Graphite"),
                    ("purple", "Purple"),
                ],
                default="ocean",
                max_length=16,
            ),
        ),
    ]
