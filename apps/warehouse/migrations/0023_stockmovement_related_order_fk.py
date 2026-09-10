"""StockMovement.related_order: IntegerField -> честный FK на orders.Order.

Старая колонка переименовывается (данные сохраняются), новый FK заполняется
из неё; ссылки на несуществующие заказы обнуляются (история переживает
удаление заказа — on_delete=SET_NULL).
"""
from django.db import migrations, models
from django.db.models import F


def copy_order_links(apps, schema_editor):
    StockMovement = apps.get_model('warehouse', 'StockMovement')
    Order = apps.get_model('orders', 'Order')
    order_ids = Order.objects.values('pk')
    qs = StockMovement.objects.exclude(legacy_related_order_id__isnull=True)
    linked = qs.filter(legacy_related_order_id__in=order_ids).update(
        related_order_id=F('legacy_related_order_id'),
    )
    orphaned = qs.exclude(legacy_related_order_id__in=order_ids).count()
    print(f'  related_order backfill: linked={linked} orphan_nulled={orphaned}')


def copy_order_links_back(apps, schema_editor):
    StockMovement = apps.get_model('warehouse', 'StockMovement')
    StockMovement.objects.exclude(related_order__isnull=True).update(
        legacy_related_order_id=F('related_order_id'),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0014_order_payment_due_date'),
        ('warehouse', '0022_goodsreceipt_stockmovement_receipt_goodsreceiptline_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='stockmovement',
            old_name='related_order_id',
            new_name='legacy_related_order_id',
        ),
        migrations.AddField(
            model_name='stockmovement',
            name='related_order',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.SET_NULL,
                related_name='stock_movements',
                to='orders.order',
                verbose_name='Связанный заказ',
            ),
        ),
        migrations.RunPython(copy_order_links, copy_order_links_back),
    ]
