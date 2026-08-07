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
                    document_number=None, user=None, reason=''):
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

    if arrival_date:
        locked.arrival_date = arrival_date
        updated_fields.append('arrival_date')

    if is_material:
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
    elif price > 0:
        # У готовой продукции та же себестоимость, что у сырья — средневзвешенная.
        # Раньше блок цены стоял под if is_material, и приход продукции молча
        # терял cost_price и дату поступления (поле показывается владельцу).
        new_total = previous_quantity + quantity
        if new_total > 0:
            locked.cost_price = (
                (previous_quantity * locked.cost_price + quantity * price) / new_total
            ).quantize(Decimal('0.01'))
            updated_fields.append('cost_price')

    locked.save(update_fields=updated_fields)

    StockMovement.objects.create(
        company_id=locked.company_id,
        movement_type=StockMovement.MovementType.INCOMING,
        material=locked if is_material else None,
        product=None if is_material else locked,
        quantity=quantity,
        price_per_unit=price,
        document_number=document_number or '',
        reason=reason or f'Приход {timezone.localdate().isoformat()}',
        created_by=user,
    )
    return locked


@transaction.atomic
def record_outgoing(*, target, quantity, movement_type=None, outgoing_date=None,
                    document_number=None, user=None, reason='', ignore_reserved=False):
    """
    Расход/списание сырья со склада с записью движения.

    Материал, зарезервированный под заказы (reserved_for_orders), списать
    нельзя: он уже пообещан заказу. Списание ограничено available_quantity
    (quantity - reserved_for_orders).

    ignore_reserved=True — только для выдачи заказа (deliver): собственный
    резерв заказа уже снят, и чужие НЕобеспеченные обещания (reserved больше
    физического остатка) не должны блокировать выдачу физически имеющегося
    товара. Проверяется лишь не уход остатка в минус.
    """
    from rest_framework.exceptions import ValidationError

    is_material = isinstance(target, RawMaterial)
    model = RawMaterial if is_material else FinishedProduct

    locked = model.objects.select_for_update().get(pk=target.pk)
    quantity = Decimal(quantity)

    mtype = movement_type or StockMovement.MovementType.OUTGOING
    if mtype not in (StockMovement.MovementType.OUTGOING,
                     StockMovement.MovementType.LOSS,
                     StockMovement.MovementType.ADJUSTMENT):
        # Проверяем до мутации строки: OutgoingSerializer ловит недопустимый тип
        # ещё на входе, но сервис защищается и сам (дефенс-ин-депс).
        raise ValidationError({'movement_type': 'Недопустимый тип расхода.'})

    if ignore_reserved:
        available = locked.quantity
    else:
        available = locked.quantity - locked.reserved_for_orders
    if quantity > available:
        raise ValidationError({
            'quantity': (
                f'Доступно для списания только {available} '
                f'({locked.reserved_for_orders} зарезервировано под заказы).'
            )
        })

    locked.quantity = locked.quantity - quantity
    locked.save(update_fields=['quantity', 'updated_at'])

    # Дата списания из документа: created_at у движения останется «сейчас»,
    # поэтому пишем её в причину, чтобы история не теряла дату документа.
    reason_text = reason or f'Расход {timezone.localdate().isoformat()}'
    if outgoing_date:
        reason_text = f'{reason_text} (дата документа: {outgoing_date.isoformat()})'

    StockMovement.objects.create(
        company_id=locked.company_id,
        movement_type=mtype,
        material=locked if is_material else None,
        product=None if is_material else locked,
        quantity=quantity,
        document_number=document_number or '',
        reason=reason_text,
        created_by=user,
    )
    return locked
