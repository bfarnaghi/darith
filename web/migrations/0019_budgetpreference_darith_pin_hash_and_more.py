# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('web', '0018_bankaccount_include_in_budget_and_hide_values'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='budgetpreference',
            name='darith_pin_hash',
            field=models.CharField(blank=True, editable=False, max_length=128),
        ),
        migrations.AddField(
            model_name='budgetpreference',
            name='lock_timeout_minutes',
            field=models.PositiveSmallIntegerField(choices=[(0, 'Off'), (1, '1 minute'), (5, '5 minutes'), (15, '15 minutes'), (30, '30 minutes')], default=0),
        ),
        migrations.CreateModel(
            name='PasskeyCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='My passkey', max_length=80)),
                ('credential_id', models.BinaryField(unique=True)),
                ('public_key', models.BinaryField()),
                ('sign_count', models.PositiveBigIntegerField(default=0)),
                ('transports', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='passkey_credentials', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='UserFeedback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.TextField(max_length=2000)),
                ('page', models.CharField(blank=True, max_length=80)),
                ('status', models.CharField(choices=[('new', 'New'), ('reviewed', 'Reviewed')], default='new', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='darith_feedback', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
