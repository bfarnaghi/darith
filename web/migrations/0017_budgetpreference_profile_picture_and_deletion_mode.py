# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import django.core.validators
from django.db import migrations, models

import web.models
import web.validators


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0016_budgetpreference_currency_and_purple_theme"),
    ]

    operations = [
        migrations.AlterField(
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
                    ("IRT", "Iranian Toman (IRT)"),
                ],
                default="EUR",
                max_length=3,
            ),
        ),
        migrations.AddField(
            model_name="budgetpreference",
            name="profile_picture",
            field=models.FileField(
                blank=True,
                upload_to=web.models.profile_picture_upload_to,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        ["jpg", "jpeg", "png", "webp"]
                    ),
                    web.validators.validate_profile_image,
                ],
            ),
        ),
        migrations.AddField(
            model_name="budgetpreference",
            name="transaction_deletion_mode",
            field=models.CharField(
                choices=[
                    ("automatic", "Update balances automatically"),
                    ("manual", "Leave balances unchanged"),
                ],
                default="automatic",
                max_length=16,
            ),
        ),
    ]
