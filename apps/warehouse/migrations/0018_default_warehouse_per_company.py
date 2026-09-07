"""
Склад по умолчанию для существующих компаний.

Модель Warehouse появилась позже данных: у компаний уже есть материалы, у
которых склад не указан. Чтобы фильтр «Қайси омбор» сразу показывал остатки,
а не пустой список, каждой компании создаём «Асосий омбор» и привязываем к
нему все её материалы.

Откат безопасен: связь материалов снимается, автоматически созданные склады
удаляются, сами материалы не трогаются.
"""
from django.db import migrations

DEFAULT_NAME = 'Асосий омбор'


def create_default_warehouses(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Warehouse = apps.get_model('warehouse', 'Warehouse')
    RawMaterial = apps.get_model('warehouse', 'RawMaterial')

    for company in Company.objects.all():
        warehouse, _ = Warehouse.objects.get_or_create(
            company_id=company.id,
            name=DEFAULT_NAME,
            defaults={'is_default': True, 'code': 'MAIN'},
        )
        RawMaterial.objects.filter(
            company_id=company.id, warehouse__isnull=True,
        ).update(warehouse=warehouse)

    # Материалы без компании (данные ранних версий) оставляем без склада:
    # привязать их не к чему, а придумывать компанию нельзя.


def drop_default_warehouses(apps, schema_editor):
    Warehouse = apps.get_model('warehouse', 'Warehouse')
    RawMaterial = apps.get_model('warehouse', 'RawMaterial')

    defaults = Warehouse.objects.filter(name=DEFAULT_NAME, is_default=True)
    RawMaterial.objects.filter(warehouse__in=defaults).update(warehouse=None)
    defaults.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('warehouse', '0017_rawmaterial_occupied_area_warehouse_and_more'),
        ('companies', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_default_warehouses, drop_default_warehouses),
    ]
