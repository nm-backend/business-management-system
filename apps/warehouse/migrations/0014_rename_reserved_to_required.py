# Migration: переименование reserved_for_orders -> required_for_orders.
#
# Поле хранит НЕ физический резерв, а ПОТРЕБНОСТЬ заказов (demand): сколько
# товара/сырья требуется активным заказам. Потребность может превышать
# физический остаток (overbooking) — нехватка помечается полями
# has_product_shortage / has_material_shortage и проверяется по физическому
# остатку в момент выдачи/подтверждения. Прежнее имя «reserved» описывало
# логически невозможное состояние (reserved > quantity), поэтому поле
# переименовано.
#
# CHECK-ограничения *_reserved_nonnegative (созданы в 0013 и ссылались на
# старое имя поля) пересоздаются под новым именем *_required_nonnegative:
# при RenameField Django не переписывает выражение ограничений автоматически.

from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('warehouse', '0013_finishedproduct_finishedproduct_quantity_nonnegative_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='rawmaterial',
            name='rawmaterial_reserved_nonnegative',
        ),
        migrations.RemoveConstraint(
            model_name='finishedproduct',
            name='finishedproduct_reserved_nonnegative',
        ),
        migrations.RenameField(
            model_name='rawmaterial',
            old_name='reserved_for_orders',
            new_name='required_for_orders',
        ),
        migrations.RenameField(
            model_name='finishedproduct',
            old_name='reserved_for_orders',
            new_name='required_for_orders',
        ),
        migrations.AlterField(
            model_name='rawmaterial',
            name='required_for_orders',
            field=models.DecimalField(
                decimal_places=3,
                default=0,
                max_digits=15,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
                verbose_name='Требуется под заказы',
            ),
        ),
        migrations.AlterField(
            model_name='finishedproduct',
            name='required_for_orders',
            field=models.DecimalField(
                decimal_places=3,
                default=0,
                max_digits=15,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
                verbose_name='Требуется под заказы',
            ),
        ),
        migrations.AddConstraint(
            model_name='rawmaterial',
            constraint=models.CheckConstraint(
                condition=models.Q(('required_for_orders__gte', 0)),
                name='rawmaterial_required_nonnegative',
            ),
        ),
        migrations.AddConstraint(
            model_name='finishedproduct',
            constraint=models.CheckConstraint(
                condition=models.Q(('required_for_orders__gte', 0)),
                name='finishedproduct_required_nonnegative',
            ),
        ),
    ]
