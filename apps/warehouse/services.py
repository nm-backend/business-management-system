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
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    FinishedProduct, GoodsReceipt, GoodsReceiptLine, RawMaterial, StockMovement,
)


@transaction.atomic
def record_incoming(
    *,
    target: RawMaterial | FinishedProduct,
    quantity: Decimal | int | float,
    price_per_unit: Decimal | int | float | None = None,
    arrival_date: Any | None = None,
    document_number: str | None = None,
    user: Any | None = None,
    reason: str = '',
) -> RawMaterial | FinishedProduct:
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
def record_return(
    *,
    target: RawMaterial | FinishedProduct,
    quantity: Decimal | int | float,
    return_date: Any | None = None,
    document_number: str | None = None,
    user: Any | None = None,
    reason: str = '',
) -> RawMaterial | FinishedProduct:
    """
    Возврат материала на склад (макет «Материал ҳаракатлари» → «Қайтарилган»).

    Цех вернул неиспользованный остаток — количество возвращается на склад,
    но в истории это ОТДЕЛЬНЫЙ тип движения, а не приход: возврат не является
    поставкой, он не должен влиять на среднюю себестоимость и попадать в
    отчёты как новая закупка. Раньше возврат проводили обычным приходом, и в
    истории он был неотличим от поставки.
    """
    is_material = isinstance(target, RawMaterial)
    model = RawMaterial if is_material else FinishedProduct

    locked = model.objects.select_for_update().get(pk=target.pk)
    quantity = Decimal(quantity)

    locked.quantity = locked.quantity + quantity
    locked.save(update_fields=['quantity', 'updated_at'])

    reason_text = reason or f'Возврат {timezone.localdate().isoformat()}'
    if return_date:
        reason_text = f'{reason_text} (дата документа: {return_date.isoformat()})'

    StockMovement.objects.create(
        company_id=locked.company_id,
        movement_type=StockMovement.MovementType.RETURN,
        material=locked if is_material else None,
        product=None if is_material else locked,
        quantity=quantity,
        document_number=document_number or '',
        reason=reason_text,
        created_by=user,
    )
    return locked


@transaction.atomic
def record_outgoing(
    *,
    target: RawMaterial | FinishedProduct,
    quantity: Decimal | int | float,
    movement_type: str | None = None,
    outgoing_date: Any | None = None,
    document_number: str | None = None,
    user: Any | None = None,
    reason: str = '',
    ignore_required: bool = False,
    purpose: str = '',
    order_id: int | None = None,
) -> RawMaterial | FinishedProduct:
    """
    Расход/списание сырья со склада с записью движения.

    Материал, зарезервированный под заказы (required_for_orders), списать
    нельзя: он уже пообещан заказу. Списание ограничено available_quantity
    (quantity - required_for_orders).

    ignore_required=True — только для выдачи заказа (deliver): собственный
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

    if ignore_required:
        available = locked.quantity
    else:
        available = locked.quantity - locked.required_for_orders
    if quantity > available:
        raise ValidationError({
            'quantity': (
                f'Доступно для списания только {available} '
                f'({locked.required_for_orders} требуется под заказы).'
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
        # Назначение и заказ (макет «Қайси мақсадда» + «Буюртма №1256»):
        # поле related_order_id в модели было, но ручной расход его не
        # заполнял — в истории нельзя было понять, на какой заказ ушло сырьё.
        purpose=purpose or '',
        related_order_id=order_id,
    )
    return locked


@transaction.atomic
def create_goods_receipt(
    *,
    company,
    lines: list[dict[str, Any]],
    supplier: str = '',
    document_number: str = '',
    receipt_date: Any | None = None,
    comment: str = '',
    user: Any | None = None,
    allow_prices: bool = False,
) -> GoodsReceipt:
    """
    Проводит документ прихода: несколько материалов одной операцией.

    Гарантии (всё внутри одной транзакции):

    * атомарность — ошибка в любой позиции откатывает документ целиком,
      частично оприходованной поставки не бывает;
    * остатки меняет тот же record_incoming, что и одиночный приход, то есть
      средневзвешенная себестоимость считается по одному правилу;
    * каждое движение склада ссылается на документ (StockMovement.receipt) —
      историю можно свернуть до операции, а не собирать по номеру строкой;
    * материал каждой позиции проверяется на принадлежность компании
      документа: чужой материал в свой приход не попадёт;
    * цену принимает только владелец (allow_prices) — как в операции прихода
      одного материала.

    lines: [{'material': RawMaterial, 'quantity': Decimal, 'price_per_unit': Decimal|None}]
    """
    from rest_framework.exceptions import PermissionDenied, ValidationError

    if not lines:
        raise ValidationError({'lines': 'Документ прихода без позиций не проводится.'})

    company_id = getattr(company, 'id', company)

    # Идемпотентность документа: повтор той же формы (двойной клик, ретрай
    # мобильной сети) не должен приходовать поставку второй раз.
    #
    # Проверка в два слоя. Первый — обычный SELECT: даёт понятную ошибку 400.
    # Второй — перехват IntegrityError на уникальном индексе: под гонкой оба
    # запроса проходят SELECT одновременно, и без перехвата проигравший
    # возвращал бы 500 вместо бизнес-ошибки.
    duplicate_message = {
        'document_number': (
            f'Документ №{document_number} от «{supplier}» уже проведён. '
            'Повторный приход по тому же документу не создаётся.'
        ),
    }
    if document_number and GoodsReceipt.objects.filter(
        company_id=company_id, supplier=supplier or '', document_number=document_number,
    ).exists():
        raise ValidationError(duplicate_message)

    try:
        # Вложенный atomic = точка сохранения: ошибка вставки не рвёт всю
        # транзакцию, и мы успеваем превратить её в 400.
        with transaction.atomic():
            receipt = GoodsReceipt.objects.create(
                company_id=company_id,
                supplier=supplier or '',
                document_number=document_number or '',
                receipt_date=receipt_date,
                comment=comment or '',
                created_by=user,
            )
    except IntegrityError:
        raise ValidationError(duplicate_message)

    for line in lines:
        material = line['material']
        if material.company_id != company_id:
            # Не ValidationError: это попытка тронуть чужой tenant.
            raise PermissionDenied('Материал другой компании.')

        price = line.get('price_per_unit') if allow_prices else None
        GoodsReceiptLine.objects.create(
            receipt=receipt,
            material=material,
            quantity=line['quantity'],
            price_per_unit=price or Decimal('0'),
        )
        updated = record_incoming(
            target=material,
            quantity=line['quantity'],
            price_per_unit=price,
            arrival_date=receipt_date,
            document_number=document_number,
            user=user,
            reason=comment,
        )
        # Привязываем созданное движение к документу: record_incoming пишет
        # ровно одно движение INCOMING, берём последнее по id.
        last_movement_id = (
            StockMovement.objects
            .filter(material=updated, movement_type=StockMovement.MovementType.INCOMING)
            .order_by('-id')
            .values_list('pk', flat=True)
            .first()
        )
        if last_movement_id:
            StockMovement.objects.filter(pk=last_movement_id).update(receipt=receipt)

    return receipt
