"""
Синхронизация billing.Subscription с полями Company + очистка расписания.

Подписка описана двумя моделями: полями на Company (источник состояния —
полный жизненный цикл active/grace/expired/frozen) и apps.billing.Subscription
(счета, события, экран владельца). До этого фикса синхронизация шла только из
billing в Company, поэтому компании, продлённые/замороженные через companies-API,
имели устаревшую billing-запись: владелец видел неверный статус, а subscription
gate по старой записи блокировал уже продлённую компанию.

Здесь:
1. Для каждой компании приводим billing.Subscription в согласие с Company
   (создаём, если записи нет; иначе обновляем статус/срок/план/заморозку).
2. Удаляем дублирующие beat-задачи billing-check-expired/billing-notify-expiring:
   жизненным циклом (expiry/grace/напоминания) управляют задачи companies
   (subscription-auto-freeze / subscription-expiry-notify), которые учитывают
   льготный период. Параллельный billing-воркер морозил компанию сразу по
   истечении срока, обходя grace, — поведение зависело от того, какая задача
   отработала первой.
"""
from django.db import migrations


def _billing_status(apps, company):
    Company = apps.get_model('companies', 'Company')
    Subscription = apps.get_model('billing', 'Subscription')
    return {
        Company.SubscriptionStatus.GRACE: Subscription.Status.ACTIVE,
        Company.SubscriptionStatus.EXPIRED: Subscription.Status.EXPIRED,
        Company.SubscriptionStatus.FROZEN: Subscription.Status.FROZEN,
        Company.SubscriptionStatus.CANCELLED: Subscription.Status.EXPIRED,
    }.get(company.subscription_status, Subscription.Status.ACTIVE)


def _billing_expires(company):
    return company.grace_end if company.subscription_status == 'grace' else company.subscription_end


def sync_subscriptions(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Subscription = apps.get_model('billing', 'Subscription')
    SubscriptionEvent = apps.get_model('billing', 'SubscriptionEvent')
    from datetime import timedelta
    from django.utils import timezone

    now = timezone.now()
    existing = {
        sub.company_id: sub
        for sub in Subscription.objects.all()
    }
    for company in Company.objects.all().iterator():
        sub = existing.get(company.pk)
        target_status = _billing_status(apps, company)
        target_expires = _billing_expires(company) or (now + timedelta(days=30))
        if sub is None:
            sub = Subscription.objects.create(
                company=company,
                plan='free',
                status=target_status,
                started_at=company.subscription_start or now,
                expires_at=target_expires,
                frozen_at=now if target_status == 'frozen' else None,
            )
            SubscriptionEvent.objects.create(
                subscription=sub, company=company,
                action='created', actor_role='system',
                to_status=target_status, new_expires_at=sub.expires_at,
                note='Создана бэкфиллом из полей Company',
            )
            continue
        fields = {}
        if sub.status != target_status:
            fields['status'] = target_status
        if sub.expires_at != target_expires:
            fields['expires_at'] = target_expires
        if target_status == 'frozen' and sub.frozen_at is None:
            fields['frozen_at'] = now
        elif target_status != 'frozen' and sub.frozen_at is not None:
            fields['frozen_at'] = None
        if fields:
            for field, value in fields.items():
                setattr(sub, field, value)
            sub.save(update_fields=[*fields.keys(), 'updated_at'])
            SubscriptionEvent.objects.create(
                subscription=sub, company=company,
                action='expired' if target_status == 'expired' else
                       ('frozen' if target_status == 'frozen' else 'activated'),
                actor_role='system',
                from_status='',
                to_status=target_status,
                new_expires_at=sub.expires_at,
                note='Синхронизирована с полями Company (бэкфилл)',
            )


def remove_billing_beat(apps, schema_editor):
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    PeriodicTask.objects.filter(
        name__in=['billing-check-expired', 'billing-notify-expiring'],
    ).delete()


def restore_billing_beat(apps, schema_editor):
    IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    check_interval, _ = IntervalSchedule.objects.get_or_create(every=60, period='minutes')
    PeriodicTask.objects.get_or_create(
        name='billing-check-expired',
        defaults={
            'task': 'apps.billing.tasks.check_expired_subscriptions',
            'interval': check_interval,
            'enabled': True,
        },
    )
    daily_interval, _ = IntervalSchedule.objects.get_or_create(every=1440, period='minutes')
    PeriodicTask.objects.get_or_create(
        name='billing-notify-expiring',
        defaults={
            'task': 'apps.billing.tasks.notify_expiring_subscriptions',
            'interval': daily_interval,
            'enabled': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0003_create_beat_schedule'),
    ]

    operations = [
        migrations.RunPython(sync_subscriptions, migrations.RunPython.noop),
        migrations.RunPython(remove_billing_beat, restore_billing_beat),
    ]
