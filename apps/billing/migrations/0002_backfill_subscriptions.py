"""
Бэкфилл: компании, созданные до появления billing, получают подписку
на 30 дней с момента миграции (как если бы были созданы сейчас).
"""
from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Subscription = apps.get_model('billing', 'Subscription')

    now = timezone.now()
    existing = set(
        Subscription.objects.values_list('company_id', flat=True)
    )
    missing = Company.objects.exclude(id__in=existing)
    if not missing.exists():
        return

    Subscription.objects.bulk_create([
        Subscription(
            company=company,
            plan='free',
            status='active',
            started_at=now,
            expires_at=now + timedelta(days=30),
        )
        for company in missing
    ])


def reverse(apps, schema_editor):
    Subscription = apps.get_model('billing', 'Subscription')
    Subscription.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
