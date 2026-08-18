# Generated for Darith planning settings.
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0020_budgetpreference_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="budgetpreference",
            name="emergency_buffer",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=14,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
        migrations.AddField(
            model_name="budgetpreference",
            name="forecast_months",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, "1 month ahead"),
                    (2, "2 months ahead"),
                    (3, "3 months ahead"),
                ],
                default=1,
            ),
        ),
        migrations.AddField(
            model_name="budgetpreference",
            name="show_money_timeline",
            field=models.BooleanField(default=True),
        ),
    ]
