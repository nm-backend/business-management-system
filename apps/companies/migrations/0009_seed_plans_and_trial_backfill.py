"""
Сидирование тарифов (планов) подписки + бэкфилл компаний.

Тарифы: Free Trial (по умолчанию, триал-план), Basic, Business, Enterprise.
Все активны — супер-администратор может переводить компании между ними;
оплата внешним шлюзом не подключена, цена носит справочный характер и
подтверждается продление вручную. Бэкфилл идемпотентен: get_or_create
по коду плана.

is_trial для существующих компаний: True, если компания не продлевалась
(нет записей истории EXTENDED/END_SET/UNFROZEN) — такие компании формально
ещё «на триале». Иначе False (компания уже продлевалась супер-администратором).
"""

from decimal import Decimal

from django.db import migrations

PLANS = [
    # code, name, duration_days, price, description, is_default, sort_order
    ('free_trial', 'Free Trial', 30, Decimal('0'), 'Бесплатный пробный период на 30 дней', True, 0),
    ('basic', 'Basic', 30, Decimal('29'), 'Базовый тариф на 30 дней', False, 10),
    ('business', 'Business', 90, Decimal('79'), 'Бизнес-тариф на 90 дней', False, 20),
    ('enterprise', 'Enterprise', 365, Decimal('199'), 'Корпоративный тариф на 365 дней', False, 30),
]

RENEWAL_ACTIONS = ('extended', 'end_set', 'unfrozen', 'plan_changed')


def seed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model('companies', 'SubscriptionPlan')
    Company = apps.get_model('companies', 'Company')
    SubscriptionChange = apps.get_model('companies', 'SubscriptionChange')

    plan_by_code = {}
    for code, name, duration_days, price, description, is_default, sort_order in PLANS:
        plan, created = SubscriptionPlan.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'duration_days': duration_days,
                'price': price,
                'description': description,
                'is_default': is_default,
                'is_active': True,
                'sort_order': sort_order,
            },
        )
        plan_by_code[code] = plan

    # Назначить план всем компаниям (по умолчанию — Free Trial).
    default_plan = SubscriptionPlan.objects.filter(is_default=True).first()
    if default_plan is not None:
        Company.objects.filter(plan__isnull=True).update(plan_id=default_plan.pk)

    # is_trial: False у компаний, которые уже продлевались вручную.
    renewed_ids = list(
        SubscriptionChange.objects.filter(action__in=RENEWAL_ACTIONS)
        .values_list('company_id', flat=True).distinct()
    )
    Company.objects.filter(pk__in=renewed_ids).update(is_trial=False)


def unseed_plans(apps, schema_editor):
    """Откат: снимаем план, возвращаем is_trial=True (новые компании — триалы)."""
    SubscriptionPlan = apps.get_model('companies', 'SubscriptionPlan')
    Company = apps.get_model('companies', 'Company')
    Company.objects.update(plan_id=None, is_trial=True)
    SubscriptionPlan.objects.filter(code__in=[p[0] for p in PLANS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('companies', '0008_subscriptionplan_company_grace_period_days_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_plans, unseed_plans),
    ]
