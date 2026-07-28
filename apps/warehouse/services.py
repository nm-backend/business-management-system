"""
Складские операции, меняющие остатки.

Приход раньше считался в браузере: страница читала остаток из списка,
прибавляла введённое и отправляла PATCH с АБСОЛЮТНЫМ значением
(static/js/components/warehouse.js). Два прихода с несвежей страницы затирали
друг друга — поставку молча теряли. Здесь то же правило, что в
apps/production/services.py: строка блокируется, прибавление считает сервер.

Заодно приход наконец оставляет след: тип движения StockMovement.INCOMING был
объявлен в модели, но не создавался ни одной строкой кода, поэтому история
склада знала только производство.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import FinishedProduct, RawMaterial, StockMovement


@transaction.atomic
def record_incoming(*, target, quantity, price_per_unit=None, arrival_date=None,
                    user=None, reason=''):
    """
    Приходует количество на склад и записывает движение.

    target — RawMaterial или FinishedProduct. Возвращает обновлённый объект.

    Для сырья с указанной ценой пересчитывается средневзвешенная себестоимость:
        (старый остаток * старая средняя + приход * цена) / новый остаток
    Поле avg_cost_price существует и показывается владельцу на карточке
    материала, но не вычислялось нигде — всегда оставалось нулём.
    """
    is_material = isinstance(target, RawMaterial)
    model = RawMaterial if is_material else FinishedProduct

    # Блокируем строку: прибавление читает и пишет остаток в одной транзакции.
    locked = model.objects.select_for_update().get(pk=target.pk)

    quantity = Decimal(quantity)
    price = Decimal(price_per_unit) if price_per_unit is not None else Decimal('0')
    previous_quantity = locked.quantity

    locked.quantity = previous_quantity + quantity
    updated_fields = ['quantity', 'updated_at']

    if is_material:
        if arrival_date:
            locked.arrival_date = arrival_date
            updated_fields.append('arrival_date')
        if price > 0:
            new_total = previous_quantity + quantity
            if new_total > 0:
                locked.avg_cost_price = (
                    (previous_quantity * locked.avg_cost_price + quantity * price) / new_total
                ).quantize(Decimal('0.01'))
                updated_fields.append('avg_cost_price')
            # Последняя закупочная цена — то, по чему пришла эта партия.
            locked.purchase_price = price
            updated_fields.append('purchase_price')

    locked.save(update_fields=updated_fields)

    StockMovement.objects.create(
        company_id=locked.company_id,
        movement_type=StockMovement.MovementType.INCOMING,
        material=locked if is_material else None,
        product=None if is_material else locked,
        quantity=quantity,
        price_per_unit=price,
        reason=reason or f'Приход {timezone.localdate().isoformat()}',
        created_by=user,
    )
    return locked
