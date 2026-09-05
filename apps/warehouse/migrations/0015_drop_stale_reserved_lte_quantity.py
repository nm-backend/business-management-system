from django.db import migrations


def drop_stale_constraint(apps, schema_editor):
    """Удаляет «осиротевший» CHECK-constraint только на PostgreSQL.

    Ограничение finishedproduct_reserved_lte_quantity (required_for_orders <= quantity)
    есть в живой PostgreSQL-БД, но отсутствует в миграциях и в модели FinishedProduct.
    Модель намеренно допускает overbooking (потребность может превышать физический
    остаток — нехватка помечается has_product_shortage). Из-за лишнего ограничения
    создание заказа на товар с остатком 0 падало с 500 IntegrityError.

    На SQLite (тесты) и на «чистой» PostgreSQL-БД, построенной только из миграций,
    такого ограничения нет, поэтому здесь выполняется no-op (DROP IF EXISTS безопасен).
    """

    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE warehouse_finishedproduct "
            "DROP CONSTRAINT IF EXISTS finishedproduct_reserved_lte_quantity"
        )


class Migration(migrations.Migration):
    dependencies = [
        ('warehouse', '0014_rename_reserved_to_required'),
    ]

    operations = [
        migrations.RunPython(drop_stale_constraint, migrations.RunPython.noop),
    ]
