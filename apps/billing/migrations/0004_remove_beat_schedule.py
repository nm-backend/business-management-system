# Удаляет расписание Celery Beat billing-задач жизненного цикла.
#
# Жизненный цикл подписки теперь ведётся ТОЛЬКО контуром companies
# (apps.companies.tasks.auto_freeze_expired_subscriptions и
# notify_subscription_expiry, зарегистрированы миграциями
# companies/0006 и 0007). Эти задачи учитывают льготный период (grace).
#
# Прежние billing-задачи (check_expired_subscriptions и
# notify_expiring_subscriptions) работали по billing.Subscription без понятия
# grace и могли заморозить компанию в льготном периоде (Company=GRACE,
# billing=FROZEN). Их расписание удаляется; сами функции остаются тонкими
# делегатами на companies-задачи (см. apps/billing/tasks.py), чтобы прямой
# вызов тоже был grace-aware.

from django.db import migrations

BILLING_BEAT_TASKS = (
    'billing-check-expired',
    'billing-notify-expiring',
)


def remove_schedules(apps, schema_editor):
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    PeriodicTask.objects.filter(name__in=BILLING_BEAT_TASKS).delete()


def restore_schedules(apps, schema_editor):
    # Обратная миграция только пересоздаёт задачи с прежними параметрами:
    # она не должна «воскрешать» поведение, которое намеренно удалено.
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
            'enabled': False,
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
            'enabled': False,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0003_create_beat_schedule'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(remove_schedules, restore_schedules),
    ]
