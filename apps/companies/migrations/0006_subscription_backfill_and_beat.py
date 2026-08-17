"""
Бэкфилл подписок для существующих компаний + регистрация периодической задачи
автозаморозки истёкших подписок в Celery Beat.

Бэкфилл идемпотентен: трогает только компании без subscription_end (на момент
включения SaaS-функции их нет) и выдаёт им стандартный срок 30 дней от текущего
момента — «grace period», чтобы ни одна компания не оказалась заблокированной
в момент деплоя.

Beat-задача создаётся через get_or_create: повторные запуски миграции
(например, после отката) не дублируют PeriodicTask.
"""
import json

from django.db import migrations
from django.utils import timezone
from datetime import timedelta

DEFAULT_SUBSCRIPTION_DAYS = 30
BEAT_TASK_NAME = 'subscription-auto-freeze'
BEAT_TASK_PATH = 'apps.companies.tasks.auto_freeze_expired_subscriptions'


def backfill_subscriptions(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    now = timezone.now()
    updated = Company.objects.filter(subscription_end__isnull=True).update(
        subscription_status='active',
        subscription_start=now,
        subscription_end=now + timedelta(days=DEFAULT_SUBSCRIPTION_DAYS),
        updated_at=now,
    )
    if updated:
        print(f'    Subscription backfill: {updated} company(ies) got {DEFAULT_SUBSCRIPTION_DAYS} days.')


def register_beat_task(apps, schema_editor):
    IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    # period='minutes' — строковое значение PERIOD_CHOICES: историческая модель
    # из миграций не имеет класс-атрибута IntervalSchedule.MINUTES.
    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=60,
        period='minutes',
    )
    PeriodicTask.objects.get_or_create(
        name=BEAT_TASK_NAME,
        defaults={
            'task': BEAT_TASK_PATH,
            'interval': schedule,
            'args': json.dumps([]),
            'enabled': True,
        },
    )


def unregister_beat_task(apps, schema_editor):
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    PeriodicTask.objects.filter(name=BEAT_TASK_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('companies', '0005_company_last_activity_company_logo_and_more'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(backfill_subscriptions, migrations.RunPython.noop),
        migrations.RunPython(register_beat_task, unregister_beat_task),
    ]
