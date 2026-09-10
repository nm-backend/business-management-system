"""
PR-2b: слияние legacy-единицы 'dona' в каноническую 'sht'.

'dona' и 'sht' означают одно и то же («штука»), но дублировались в UnitChoices,
раскалывая агрегаты отчётов (unit_totals) и списки выбора. После заморозки новых
записей (PR-2a) переносим существующие строки во всех 7 таблицах, затем сам выбор
'dona' удаляется из UnitChoices (PR-2c).

Обратная миграция — no-op: разъединить merged-строки невозможно, да и не нужно.
"""
from django.db import migrations


# (app_label, model_name, поле единицы измерения)
DONA_FIELDS = [
    ('warehouse', 'RawMaterial', 'unit'),
    ('warehouse', 'FinishedProduct', 'unit'),
    ('warehouse', 'RecipeItem', 'unit'),
    ('finance', 'LaborRate', 'unit'),
    ('orders', 'Order', 'unit'),
    ('production', 'Task', 'planned_unit'),
    ('production', 'WorkRecord', 'unit'),
]


def merge_dona_into_sht(apps, schema_editor):
    total = 0
    for app_label, model_name, field in DONA_FIELDS:
        model = apps.get_model(app_label, model_name)
        updated = model.objects.filter(**{field: 'dona'}).update(**{field: 'sht'})
        total += updated
        print(f'  {app_label}.{model_name}.{field}: dona -> sht ({updated} строк)')
    print(f'PR-2b: всего перенесено {total} строк dona -> sht.')


def noop_reverse(apps, schema_editor):
    # Слияние необратимо по построению: 'sht' было каноном и до миграции.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('warehouse', '0024_remove_legacy_movement_link_fields'),
        ('finance', '0012_alter_laborrate_rate_per_unit'),
        ('orders', '0014_order_payment_due_date'),
        ('production', '0014_task_planned_quantity_task_planned_unit'),
    ]

    operations = [
        migrations.RunPython(merge_dona_into_sht, noop_reverse),
    ]
