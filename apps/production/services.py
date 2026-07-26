"""
Production pipeline service.

Реализует полный производственный цикл при подтверждении работы:
1. Проверяет рецепт товара
2. Проверяет наличие сырья
3. Списывает сырьё со склада
4. Добавляет готовый товар на склад
5. Начисляет работнику оплату
6. Создаёт историю движения склада
7. Меняет статус заказа
"""
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class ProductionPipelineError(Exception):
    """Ошибка в производственном пайплайне."""
    pass


class InsufficientMaterialError(ProductionPipelineError):
    """Недостаточно сырья для производства."""
    def __init__(self, material_name, available, required):
        self.material_name = material_name
        self.available = available
        self.required = required
        super().__init__(
            f"Недостаточно '{material_name}': нужно {required}, доступно {available}"
        )


def process_work_confirmation(work_record, confirmed_by, labor_cost=None):
    """
    Обрабатывает подтверждение выполненной работы.

    Алгоритм (по ТЗ):
    1. Проверяет рецепт товара
    2. Проверяет наличие сырья
    3. Списывает сырьё со склада
    4. Добавляет готовый товар на склад
    5. Начисляет работнику оплату
    6. Создаёт историю движения склада
    7. Меняет статус заказа

    Аргументы:
        work_record: WorkRecord - подтверждаемая работа
        confirmed_by: User - кто подтвердил
        labor_cost: Decimal - стоимость труда (опционально)

    Возвращает:
        dict - результат обработки

    Исключения:
        InsufficientMaterialError - если сырья не хватает
        ProductionPipelineError - если нет рецепта или товара
    """
    from apps.warehouse.models import RawMaterial, FinishedProduct, StockMovement, Recipe
    from apps.orders.models import Order, OrderStatus

    with transaction.atomic():
        product = work_record.product
        if not product:
            raise ProductionPipelineError("Работа не связана с продуктом")

        quantity = work_record.quantity

        # 1. Проверка рецепта
        recipe = Recipe.objects.filter(
            product=product, is_active=True
        ).first()

        if recipe and recipe.items.exists():
            # 2. Проверка наличия сырья по рецепту
            for item in recipe.items.all():
                material = item.material
                required_qty = item.quantity_required * quantity
                if material.quantity < required_qty:
                    raise InsufficientMaterialError(
                        material_name=material.name,
                        available=material.quantity,
                        required=required_qty,
                    )

            # 3. Списание сырья со склада
            for item in recipe.items.all():
                material = item.material
                required_qty = item.quantity_required * quantity
                material.quantity -= required_qty
                material.save(update_fields=['quantity'])

                # Создаём запись движения (расход на производство)
                StockMovement.objects.create(
                    movement_type=StockMovement.MovementType.PRODUCTION_OUT,
                    material=material,
                    quantity=-required_qty,
                    reason=f"Производство: {product.name} x{quantity}",
                    created_by=confirmed_by,
                    related_production_id=work_record.id,
                )
                logger.info(
                    f"Списано сырьё: {material.name} x{required_qty} "
                    f"для {product.name} (задача #{work_record.task_id})"
                )

        # 4. Добавление готовой продукции на склад
        product.quantity += quantity
        product.save(update_fields=['quantity'])

        # Создаём запись движения (приход с производства)
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.PRODUCTION_IN,
            product=product,
            quantity=quantity,
            reason=f"Производство подтверждено: {work_record.comment or product.name}",
            created_by=confirmed_by,
            related_production_id=work_record.id,
        )
        logger.info(
            f"Добавлена продукция: {product.name} x{quantity} "
            f"(задача #{work_record.task_id})"
        )

        # 5. Начисление работнику оплаты
        final_labor_cost = labor_cost
        if final_labor_cost is None and recipe:
            final_labor_cost = work_record.calculate_labor_cost()

        if final_labor_cost is not None and Decimal(str(final_labor_cost)) > 0:
            from apps.finance.models import WorkerPayment
            WorkerPayment.objects.create(
                worker=work_record.worker,
                amount=final_labor_cost,
                payment_date=timezone.now().date(),
                payment_type=WorkerPayment.PaymentType.SALARY,
                comment=f"Оплата за {product.name} x{quantity}",
                created_by=confirmed_by,
            )
            logger.info(
                f"Начислено работнику {work_record.worker.username}: "
                f"{final_labor_cost} за {product.name} x{quantity}"
            )

        # 6. Обновление статуса заказа
        task = work_record.task
        if task and task.order:
            order = task.order
            if order.status in (
                OrderStatus.IN_PROGRESS,
                OrderStatus.ACCEPTED_BY_WORKER,
                OrderStatus.AWAITING_CONFIRMATION,
            ):
                # Если все работы по заказу подтверждены -> READY
                all_confirmed = not order.tasks.filter(
                    work_records__status__in=[
                        'awaiting_confirmation', 'rejected'
                    ]
                ).exists()
                if all_confirmed:
                    order.status = OrderStatus.READY
                else:
                    order.status = OrderStatus.IN_PROGRESS
                order.save(update_fields=['status'])
                logger.info(
                    f"Статус заказа #{order.id} обновлён: {order.status}"
                )

        # 7. Создание уведомлений
        _create_production_notifications(work_record, confirmed_by)

    return {
        'product': product.name,
        'quantity': quantity,
        'labor_cost': final_labor_cost or 0,
        'status': 'confirmed',
    }


def _create_production_notifications(work_record, confirmed_by):
    """
    Создаёт уведомления о подтверждении работы.

    Уведомления:
    - Работнику: работа подтверждена
    - Администратору: работа подтверждена (если подтвердил owner)
    """
    from apps.messaging.models import Notification

    # Уведомление работнику
    Notification.objects.create(
        user=work_record.worker,
        type=Notification.NotificationType.WORK_CONFIRMED,
        title="Иш тасдиқланди",
        message=f"Ваша работа '{work_record.product.name if work_record.product else ''}' "
                f"x{work_record.quantity} подтверждена.",
        related_task=work_record.task,
    )

    # Уведомление администратору (если подтвердил owner)
    if confirmed_by.is_owner:
        from apps.accounts.models import User
        admins = User.objects.filter(role='admin', is_active=True)
        for admin in admins:
            Notification.objects.create(
                user=admin,
                type=Notification.NotificationType.WORK_CONFIRMED,
                title="Иш тасдиқланди",
                message=f"Работа '{work_record.product.name if work_record.product else ''}' "
                        f"от {work_record.worker.username} подтверждена.",
                related_task=work_record.task,
            )
