"""
Регистрация периодической задачи предупреждений об истечении подписки
в Celery Beat.

Задача notify_subscription_expiry оповещает владельца/админов компании и
супер-админов за 7 и за 1 день до окончания подписки (колокольчик + push).
Расписание то же, что и у автозаморозки (каждый час) — IntervalSchedule
переиспользуется через get_or_create, поэтому дубликатов не создаётся.

Задача создаётся через get_or_create: повторные запуски миграции (например,
после отката) не дублируют PeriodicTask.
"""
import json

from django.db import migrations

BEAT_TASK_NAME = 'subscription-expiry-notify'
BEAT_TASK_PATH = 'apps.companies.tasks.notify_subscription_expiry'


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
        ('companies', '0006_subscription_backfill_and_beat'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(register_beat_task, unregister_beat_task),
    ]
