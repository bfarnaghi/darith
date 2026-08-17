# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("web", "0019_budgetpreference_darith_pin_hash_and_more")]

    operations = [
        migrations.AddField(
            model_name="budgetpreference",
            name="language",
            field=models.CharField(
                choices=[
                    ("en", "English"),
                    ("fa", "Persian"),
                    ("it", "Italian"),
                    ("fr", "French"),
                    ("es", "Spanish"),
                    ("nl", "Dutch"),
                ],
                default="en",
                max_length=5,
            ),
        ),
    ]
