"""
Переносит все существующие (до-мультикомпанийные) данные в одну компанию
по умолчанию, чтобы после включения изоляции ничего не осталось «бесхозным».

Идемпотентна: если легаси-данных нет (чистая установка), ничего не делает.
Обратная миграция намеренно пустая — company остаётся заполненной.
"""
from django.db import migrations

# (app_label, model_name) всех моделей, у которых появилось поле company.
TENANT_MODELS = [
    ('clients', 'Client'),
    ('clients', 'Payment'),
    ('orders', 'Order'),
    ('warehouse', 'RawMaterial'),
    ('warehouse', 'FinishedProduct'),
    ('warehouse', 'StockMovement'),
    ('warehouse', 'Recipe'),
    ('production', 'Task'),
    ('production', 'WorkRecord'),
    ('finance', 'Expense'),
    ('finance', 'LaborRate'),
    ('finance', 'WorkerPayment'),
    ('messaging', 'Message'),
    ('messaging', 'Notification'),
    ('audit', 'AuditLog'),
]

DEFAULT_COMPANY_NAME = 'SkladPro'


def backfill(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    User = apps.get_model('accounts', 'User')

    legacy_users = User.objects.filter(company__isnull=True).exclude(role='superadmin')
    models = [apps.get_model(app, name) for app, name in TENANT_MODELS]

    has_legacy = legacy_users.exists() or any(
        m.objects.filter(company__isnull=True).exists() for m in models
    )
    if not has_legacy:
        return

    company, _ = Company.objects.get_or_create(
        name=DEFAULT_COMPANY_NAME, defaults={'is_active': True},
    )
    legacy_users.update(company=company)
    for model in models:
        model.objects.filter(company__isnull=True).update(company=company)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('companies', '0001_initial'),
        ('accounts', '0003_remove_user_accounts_single_owner_user_company_and_more'),
        ('clients', '0003_client_company_payment_company'),
        ('orders', '0003_order_company'),
        ('warehouse', '0002_finishedproduct_company_rawmaterial_company_and_more'),
        ('production', '0002_task_company_workrecord_company'),
        ('finance', '0002_expense_company_laborrate_company_and_more'),
        ('messaging', '0003_message_company_notification_company'),
        ('audit', '0002_auditlog_company'),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
