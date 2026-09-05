from django.db import migrations


def drop_stale_constraint(apps, schema_editor):
    """Удаляет «осиротевший» CHECK-constraint только на PostgreSQL.

    Ограничение rawmaterial_reserved_lte_quantity (required_for_orders <= quantity)
    есть в живой PostgreSQL-БД, но отсутствует в миграциях и в модели RawMaterial.
    Модель намеренно допускает overbooking (потребность заказов может превышать
    физический остаток — нехватка помечается has_material_shortage). Из-за лишнего
    ограничения заказ/рецепт на сырьё, которого не хватает, падал бы с 500
    IntegrityError вместо понятной пометки о нехватке.

    На SQLite (тесты) и на «чистой» PostgreSQL-БД такого ограничения нет,
    поэтому здесь выполняется no-op (DROP IF EXISTS безопасен).
    """

    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE warehouse_rawmaterial "
            "DROP CONSTRAINT IF EXISTS rawmaterial_reserved_lte_quantity"
        )


class Migration(migrations.Migration):
    dependencies = [
        ('warehouse', '0015_drop_stale_reserved_lte_quantity'),
    ]

    operations = [
        migrations.RunPython(drop_stale_constraint, migrations.RunPython.noop),
    ]
