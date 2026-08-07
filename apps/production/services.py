"""
Production services - подтверждение и отклонение выполненной работы.

Подтверждение работы - единственная операция, которая меняет склад
(правило ТЗ: склад меняется только после подтверждения):

1. Проверяется активный рецепт товара.
2. Проверяется наличие сырья по рецепту.
3. Сырьё списывается со склада (+ записи StockMovement).
4. Готовый товар приходуется на склад (+ запись StockMovement).
5. Работнику начисляется оплата по ставке LaborRate.
6. Работник получает уведомление, заказ меняет статус.

Всё выполняется в одной транзакции: при нехватке сырья ничего не меняется.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.services import write_audit_log
from apps.messaging.models import Notification
from apps.messaging.services import notify
from apps.warehouse.models import StockMovement

from .models import TaskStatus, WorkRecord


class MaterialShortageError(Exception):
    """Сырья на складе меньше, чем требует рецепт."""

    def __init__(self, shortages):
        self.shortages = shortages  # [{material, required, available}, ...]
        super().__init__('Not enough raw material to confirm the work')


def get_recipe_requirements(product, quantity):
    """Возвращает [(material, required_qty), ...] по активному рецепту товара."""
    if not product:
        return []
    # Итерируем .all() (использует prefetch-кэш product.recipes, если он есть,
    # см. OrderViewSet.prefetch_related), а активный рецепт отбираем в Python.
    # Раньше .filter(is_active=True) шёл в обход prefetch -> 3 запроса на КАЖДЫЙ
    # заказ (recipe + recipeitem + rawmaterial) = N+1.
    recipe = next((r for r in product.recipes.all() if r.is_active), None)
    if not recipe:
        return []
    return [
        (item.material, item.quantity_required * Decimal(quantity))
        for item in recipe.items.all()
    ]


def check_material_shortages(product, quantity):
    """Возвращает список нехваток сырья для производства quantity товара."""
    shortages = []
    for material, required in get_recipe_requirements(product, quantity):
        if material.quantity < required:
            shortages.append({
                'material_id': material.id,
                'material_name': material.name,
                'required': required,
                'available': material.quantity,
                'missing': required - material.quantity,
            })
    return shortages


class MissingLaborRateError(Exception):
    """
    Для товара не задана ставка оплаты труда.

    Раньше в этом случае начислялся ноль — молча. Работа подтверждалась, склад
    пополнялся, администратор видел «подтверждено» и был уверен, что всё в
    порядке, а работник не получал ничего и узнавал об этом только из своей
    карточки. Для SaaS это тихая потеря денег сотрудника, поэтому подтверждение
    теперь останавливается с понятным текстом.
    """

    def __init__(self, product_name=''):
        self.product_name = product_name
        super().__init__(product_name)


def calculate_labor_cost(work):
    """
    Начислено = количество работы x ставка за единицу.

    Ставка выбирается по операции, которую указал работник (work.operation):
    у товара может быть несколько ставок — по одной на операцию. Раньше бралась
    ставка «по алфавиту» (order_by('operation')), и работник получал деньги
    за чужую операцию. Если операция не указана, ставка берётся только когда
    она одна; при нескольких ставках без операции угадывать нельзя — работа
    отклоняется, админ видит товар и понимает, что нужно указать операцию.

    Ноль возвращается только когда ставка действительно нулевая: отсутствие
    ставки — это не «бесплатно», а незаполненный справочник, и такую работу
    подтверждать нельзя (см. MissingLaborRateError).
    """
    from apps.finance.models import LaborRate
    if not work.product:
        raise MissingLaborRateError('')
    rates = list(LaborRate.objects.filter(product=work.product))
    if not rates:
        raise MissingLaborRateError(work.product.name)
    if work.operation:
        rate = next((r for r in rates if r.operation == work.operation), None)
        if rate is None:
            raise MissingLaborRateError(work.product.name)
    elif len(rates) == 1:
        rate = rates[0]
    else:
        raise MissingLaborRateError(work.product.name)
    return rate.rate_per_unit * work.quantity


class AlreadyProcessedError(Exception):
    """Работа уже подтверждена или отклонена другим запросом."""

    def __init__(self, message=None):
        self.message = message
        super().__init__(message or 'Work is already processed')


@transaction.atomic
def confirm_work(work, confirmed_by, labor_cost=None, request=None):
    """
    Подтверждает работу: списывает сырьё, приходует товар, начисляет оплату.

    Бросает MaterialShortageError, если сырья не хватает (склад не меняется).
    Бросает AlreadyProcessedError при повторном подтверждении (защита от гонки).
    """
    # Блокируем строку работы и перепроверяем статус внутри транзакции,
    # чтобы два одновременных подтверждения не списали склад дважды.
    work = WorkRecord.objects.select_for_update().get(pk=work.pk)
    if work.status != WorkRecord.WorkStatus.AWAITING_CONFIRMATION:
        raise AlreadyProcessedError()
    # Зомби-задача: заказ отменён после сдачи работы (или сдан по отменённому
    # заказу в обход валидации). Подтверждение воскрешало бы заказ в READY и
    # приходовало товар по отменённой сделке.
    if work.task and work.task.order and work.task.order.status == work.task.order.Status.CANCELLED:
        raise AlreadyProcessedError('Заказ отменён - работу подтвердить нельзя')

    product = work.product
    # Сырьё уходит и на брак: рабочий его уже израсходовал, годным оно не
    # стало. Считали только по годному — материал, ушедший в брак, оставался
    # на складе и остаток был завышен (макет «Ишни якунлаш», поле «Брак»).
    consumed_quantity = work.quantity + (work.defect_quantity or Decimal('0'))
    requirements = get_recipe_requirements(product, consumed_quantity)

    # 1-2. Рецепт и наличие сырья (блокируем строки от параллельных подтверждений).
    shortages = []
    locked_materials = []
    for material, required in requirements:
        material = type(material).objects.select_for_update().get(pk=material.pk)
        if material.quantity < required:
            shortages.append({
                'material_id': material.id,
                'material_name': material.name,
                'required': required,
                'available': material.quantity,
                'missing': required - material.quantity,
            })
        locked_materials.append((material, required))
    if shortages:
        raise MaterialShortageError(shortages)

    # Сумму труда считаем здесь (после проверки сырья, до прихода товара):
    # она входит в себестоимость партии, а порядок ошибок сохранён —
    # нехватка сырья важнее отсутствующей ставки.
    if labor_cost is None:
        labor_cost = calculate_labor_cost(work)

    # 3. Списание сырья. Заодно снимаем резерв под заказ: сырьё физически
    # израсходовано, обещание заказу исполнено — reserved_for_orders падает.
    for material, required in locked_materials:
        material.quantity -= required
        if work.task and work.task.order_id:
            material.reserved_for_orders = max(
                (material.reserved_for_orders or Decimal('0')) - required, Decimal('0')
            )
            material.save(update_fields=['quantity', 'reserved_for_orders', 'updated_at'])
        else:
            material.save(update_fields=['quantity', 'updated_at'])
        StockMovement.objects.create(
            company_id=work.company_id,
            movement_type=StockMovement.MovementType.PRODUCTION_OUT,
            material=material,
            quantity=required,
            reason=f'Work #{work.id} confirmed',
            created_by=confirmed_by,
            related_production_id=work.id,
            related_order_id=work.task.order_id if work.task else None,
        )

    # 4. Приход готового товара (блокируем строку от параллельного read-modify-write).
    if product:
        product = type(product).objects.select_for_update().get(pk=product.pk)
        previous_quantity = product.quantity or Decimal('0')
        previous_cost = product.cost_price or Decimal('0')
        product.quantity = previous_quantity + work.quantity
        # Себестоимость партии = сырьё по рецепту (по средней закупочной цене)
        # + оплата труда. Раньше cost_price после производства не трогался и
        # оставался нулём (обновлялся только при закупке через record_incoming):
        # себестоимость продаж в аналитике и отчётах была 0, и прибыль
        # «дорисовывалась». Брак считается в стоимости партии: материал на
        # брак уже списан со склада, это реальные затраты производства.
        if work.quantity > 0:
            materials_cost = sum(
                (required * (material.avg_cost_price or Decimal('0')))
                for material, required in locked_materials
            )
            unit_batch_cost = (
                (materials_cost + labor_cost) / work.quantity
            ).quantize(Decimal('0.01'))
            new_total = previous_quantity + work.quantity
            product.cost_price = (
                (previous_quantity * previous_cost + work.quantity * unit_batch_cost) / new_total
            ).quantize(Decimal('0.01'))
        product.save(update_fields=['quantity', 'cost_price', 'updated_at'])
        StockMovement.objects.create(
            company_id=work.company_id,
            movement_type=StockMovement.MovementType.PRODUCTION_IN,
            product=product,
            quantity=work.quantity,
            reason=f'Work #{work.id} confirmed',
            created_by=confirmed_by,
            related_production_id=work.id,
            related_order_id=work.task.order_id if work.task else None,
        )

    # 5. Начисление работнику.
    work.status = WorkRecord.WorkStatus.CONFIRMED
    work.confirmed_by = confirmed_by
    work.confirmed_at = timezone.now()
    work.labor_cost = labor_cost
    work.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'labor_cost', 'updated_at'])

    # 6. Статус задачи/заказа и уведомление работнику.
    if work.task:
        work.task.confirm(confirmed_by)
    notify(
        work.worker,
        Notification.NotificationType.WORK_CONFIRMED,
        'Иш тасдиқланди',
        f'Иш #{work.id} тасдиқланди: {product.name if product else ""} x {work.quantity}',
        task=work.task,
    )
    write_audit_log(
        action=AuditLog.Action.UPDATE,
        actor=confirmed_by,
        target=work,
        changes={'status': {'old': 'awaiting_confirmation', 'new': 'confirmed'}},
        request=request,
    )
    return work


@transaction.atomic
def reject_work(work, rejected_by, reason, request=None):
    """
    Отклоняет работу: склад не меняется, работник получает причину.

    Связанная задача возвращается в работу (ACCEPTED), а заказ — в IN_PROGRESS,
    чтобы работник мог переделать и повторно сдать работу (иначе задача зависла бы).
    """
    work = WorkRecord.objects.select_for_update().get(pk=work.pk)
    if work.status != WorkRecord.WorkStatus.AWAITING_CONFIRMATION:
        raise AlreadyProcessedError()

    work.status = WorkRecord.WorkStatus.REJECTED
    work.rejection_reason = reason
    work.confirmed_by = rejected_by
    work.save(update_fields=['status', 'rejection_reason', 'confirmed_by', 'updated_at'])

    task = work.task
    if task and task.status == TaskStatus.COMPLETED:
        task.status = TaskStatus.ACCEPTED
        task.completed_at = None
        task.save(update_fields=['status', 'completed_at'])
        if task.order and task.order.status == task.order.Status.AWAITING_CONFIRMATION:
            task.order.status = task.order.Status.IN_PROGRESS
            task.order.save(update_fields=['status'])

    notify(
        work.worker,
        Notification.NotificationType.WORK_REJECTED,
        'Иш рад этилди',
        reason or f'Иш #{work.id} рад этилди',
        task=work.task,
    )
    write_audit_log(
        action=AuditLog.Action.UPDATE,
        actor=rejected_by,
        target=work,
        changes={'status': {'old': 'awaiting_confirmation', 'new': 'rejected'}},
        request=request,
    )
    return work
