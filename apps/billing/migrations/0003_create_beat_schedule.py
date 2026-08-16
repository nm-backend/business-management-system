"""
Регистрирует расписание Celery Beat для жизненного цикла подписок.

Планировщик — DatabaseScheduler (django_celery_beat), поэтому расписание
живёт в БД, а не в CELERY_BEAT_SCHEDULE. Создаём задачи здесь, в миграции:
после `migrate` в любой среде (dev/prod) задачи уже существуют.

  billing-check-expired    — каждые 60 минут: поиск истёкших + заморозка;
  billing-notify-expiring  — раз в день: напоминания об окончании.
"""
from django.db import migrations


def create_schedules(apps, schema_editor):
    IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    check_interval, _ = IntervalSchedule.objects.get_or_create(
        every=60, period='minutes',
    )
    PeriodicTask.objects.get_or_create(
        name='billing-check-expired',
        defaults={
            'task': 'apps.billing.tasks.check_expired_subscriptions',
            'interval': check_interval,
            'enabled': True,
        },
    )

    daily_interval, _ = IntervalSchedule.objects.get_or_create(
        every=1440, period='minutes',
    )
    PeriodicTask.objects.get_or_create(
        name='billing-notify-expiring',
        defaults={
            'task': 'apps.billing.tasks.notify_expiring_subscriptions',
            'interval': daily_interval,
            'enabled': True,
        },
    )


def remove_schedules(apps, schema_editor):
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    PeriodicTask.objects.filter(
        name__in=['billing-check-expired', 'billing-notify-expiring'],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_backfill_subscriptions'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(create_schedules, remove_schedules),
    ]
