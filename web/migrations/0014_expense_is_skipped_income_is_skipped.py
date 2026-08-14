# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("web", "0013_manual_subscriptions"),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="is_skipped",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name="income",
            name="is_skipped",
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
