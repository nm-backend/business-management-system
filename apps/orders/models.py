"""
Orders models - заказы клиентов.

Суммы заказа (total_amount, paid_amount) - финансовые поля, через API
они доступны только владельцу.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import TimestampedModel, SoftDeleteModel
from apps.core.validators import validate_file_size
from apps.clients.models import Client
from apps.warehouse.models import FinishedProduct, UnitChoices


class Order(TimestampedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        NEW = 'new', 'Новый'
        AWAITING_MATERIAL = 'awaiting_material', 'Ожидает материала'
        SENT_TO_WORKER = 'sent_to_worker', 'Отправлен работнику'
        ACCEPTED = 'accepted', 'Принят работником'
        WORKER_REFUSED = 'worker_refused', 'Работник отказался'
        IN_PROGRESS = 'in_progress', 'В работе'
        AWAITING_CONFIRMATION = 'awaiting_confirmation', 'Ожидает подтверждения'
        READY = 'ready', 'Готов'
        DELIVERED = 'delivered', 'Выдан клиенту'
        CANCELLED = 'cancelled', 'Отменен'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'Не оплачено'
        PARTIAL = 'partial', 'Частичная оплата'
        PAID = 'paid', 'Оплачено'

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='orders', null=True, verbose_name='Компания')
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='orders', verbose_name='Клиент')
    product = models.ForeignKey(FinishedProduct, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders', verbose_name='Товар')
    custom_product_name = models.CharField(max_length=255, blank=True, verbose_name='Название товара (вручную)')
    quantity = models.DecimalField(max_digits=10, decimal_places=2,
                                   validators=[MinValueValidator(Decimal('0.01'))], verbose_name='Количество')
    unit = models.CharField(max_length=20, choices=UnitChoices.choices,
                            default=UnitChoices.IZDELIE, verbose_name='Единица измерения')
    deadline = models.DateTimeField(null=True, blank=True, verbose_name='Срок выполнения')
    worker = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_orders', verbose_name='Работник')
    comment = models.TextField(blank=True, verbose_name='Комментарий')
    photo = models.ImageField(upload_to='orders/', blank=True, null=True, validators=[validate_file_size], verbose_name='Фото')
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.NEW, db_index=True, verbose_name='Статус')
    payment_status = models.CharField(max_length=50, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, verbose_name='Статус оплаты')

    # Финансовые поля (только owner через API).
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                       validators=[MinValueValidator(Decimal('0'))], verbose_name='Сумма заказа')
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name='Оплачено')

    # Момент первой выдачи клиенту (status -> DELIVERED). Отдельно от updated_at:
    # любая поздняя правка/оплата бампит updated_at, а себестоимость проданного
    # (COGS в reports) должна оставаться в периоде фактической выдачи, иначе
    # поздний платёж задним числом переносил прибыль между месяцами.
    delivered_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name='Выдан клиенту')

    # Снимок себестоимости товара на момент выдачи. Раньше COGS в отчётах
    # брался живым product__cost_price: последующая переоценка товара (новый
    # приход, пересчёт по рецепту) задним числом меняла прибыль уже выданных
    # заказов, а ручные позиции (custom_product_name) приносили COGS=0 и
    # завышали прибыль. Снимок фиксируется один раз — при переходе в DELIVERED.
    cost_price = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                     verbose_name='Себестоимость на момент выдачи')

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.id} - {self.client.name}"

    def save(self, *args, **kwargs):
        # delivered_at проставляется один раз — при первом переходе в DELIVERED,
        # независимо от пути изменения статуса (deliver-action, админка и т.п.).
        # Копируем kwargs, чтобы не мутировать исходный словарь: если вызывающий
        # код переиспользует один dict для нескольких save(), мутация приведёт к
        # неожиданному расширению update_fields (добавится 'delivered_at').
        if self.status == self.Status.DELIVERED and self.delivered_at is None:
            self.delivered_at = timezone.now()
            # Снимок себестоимости в тот же единственный момент перехода.
            # Условие delivered_at is None означает первую выдачу: повторные
            # save() (поздняя оплата и т.п.) снимок не переписывают.
            extra = []
            if self.product_id and not self.cost_price:
                self.cost_price = self.product.cost_price or Decimal('0')
                extra.append('cost_price')
            # Копируем kwargs, чтобы не мутировать исходный словарь: если
            # вызывающий код переиспользует один dict для нескольких save(),
            # мутация приведёт к неожиданному расширению update_fields.
            uf = kwargs.get('update_fields')
            if uf is not None:
                uf = list(uf)
                for field in ['delivered_at'] + extra:
                    if field not in uf:
                        uf.append(field)
                        kwargs = {**kwargs, 'update_fields': uf}
        super().save(*args, **kwargs)

    @property
    def is_paid(self):
        return (self.paid_amount or Decimal('0')) >= (self.total_amount or Decimal('0'))

    @property
    def has_debt(self):
        return not self.is_paid

    @property
    def is_overdue(self):
        return bool(
            self.deadline
            and self.deadline < timezone.now()
            and self.status not in (self.Status.DELIVERED, self.Status.CANCELLED)
        )

    def update_payment_status(self):
        """
        Синхронизирует payment_status с суммами total_amount/paid_amount.

        Первым делом проверяется is_paid (paid >= total): заказ с нулевой
        суммой (total_amount=0 — бесплатный заказ или незаполненная цена
        админом, который сумм не видит) при нулевой оплате не имеет долга,
        а раньше помечался «не оплачено» — ложная тревога в канбане и в
        фильтре неоплаченных.
        """
        if self.is_paid:
            self.payment_status = self.PaymentStatus.PAID
        elif self.paid_amount > 0:
            self.payment_status = self.PaymentStatus.PARTIAL
        else:
            self.payment_status = self.PaymentStatus.UNPAID
        self.save(update_fields=['payment_status', 'updated_at'])

    def reserve_product(self):
        """
        Резервирует товар под заказ: reserved_for_orders += quantity.

        Атомарно (select_for_update), чтобы два параллельных заказа на один
        товар не потеряли резерв друг друга (как в apply_payment_amount).
        Заказ без товара (custom_product_name) ничего не резервирует.
        """
        if not self.product_id or not self.quantity:
            return
        from django.db import transaction

        with transaction.atomic():
            product = FinishedProduct.objects.select_for_update().get(pk=self.product_id)
            product.reserved_for_orders = (product.reserved_for_orders or Decimal('0')) + self.quantity
            product.save(update_fields=['reserved_for_orders', 'updated_at'])

    def release_product(self, product_id=None, quantity=None):
        """
        Снимает резерв товара: reserved_for_orders -= quantity.

        product_id/quantity принимаются явно для пересчёта при смене товара или
        количества заказа (в perform_update старый резерв снимается по старым
        значениям). Без аргументов используются собственные product/quantity.
        Резерв не уходит в минус (заказы, созданные до фичи, резерва не имели).
        """
        pid = product_id if product_id is not None else self.product_id
        qty = quantity if quantity is not None else self.quantity
        if not pid or not qty:
            return
        from django.db import transaction

        with transaction.atomic():
            product = FinishedProduct.objects.select_for_update().get(pk=pid)
            product.reserved_for_orders = max((product.reserved_for_orders or Decimal('0')) - qty, Decimal('0'))
            product.save(update_fields=['reserved_for_orders', 'updated_at'])

    def _recipe_requirements(self, product_id=None, quantity=None):
        """[(material, required_qty), ...] по активному рецепту товара."""
        from apps.warehouse.models import FinishedProduct as FP
        from apps.production.services import get_recipe_requirements

        pid = product_id if product_id is not None else self.product_id
        qty = quantity if quantity is not None else self.quantity
        if not pid or not qty:
            return []
        try:
            product = FP.objects.get(pk=pid)
        except FP.DoesNotExist:
            return []
        return get_recipe_requirements(product, qty)

    def reserve_raw_materials(self):
        """
        Резервирует сырьё под заказ: по активному рецепту товара
        reserved_for_orders += required * quantity.

        Атомарно (select_for_update). Заказ без товара или без активного
        рецепта ничего не резервирует (макет «Хомашё омбори»: у материала
        виден резерв и номер заказа).
        """
        if not self.product_id or not self.quantity:
            return
        from django.db import transaction
        from apps.warehouse.models import RawMaterial

        with transaction.atomic():
            # Сортируем материалы по pk: два параллельных заказа с рецептами,
            # где материалы перечислены в разном порядке, иначе блокировали бы
            # строки в разной последовательности и упирались в дедлок.
            for material, required in sorted(self._recipe_requirements(), key=lambda item: item[0].pk):
                locked = RawMaterial.objects.select_for_update().get(pk=material.pk)
                locked.reserved_for_orders = (
                    (locked.reserved_for_orders or Decimal('0')) + required
                )
                locked.save(update_fields=['reserved_for_orders', 'updated_at'])

    def release_raw_materials(self, product_id=None, quantity=None):
        """
        Снимает резерв сырья по рецепту товара: reserved_for_orders -= required.

        product_id/quantity — явно, для пересчёта при смене товара/количества.
        Резерв не уходит в минус (заказы до фичи резерва не имели).

        Подтверждение производства (confirm_work) уже списало сырьё И сняло его
        резерв. Повторное снятие здесь (выдача, отмена) снимало бы и чужой
        резерв: у заказа B с параллельным заказом A резерв «крался» вдвое.
        Вычитаем уже израсходованное подтверждёнными работами по этому заказу.
        """
        if not self.product_id and not product_id:
            return
        from django.db import transaction
        from apps.warehouse.models import RawMaterial, StockMovement

        # Сколько сырья по каждому материалу уже списано подтверждёнными
        # работами заказа (PRODUCTION_OUT) — их резерв уже снят при confirm.
        consumed_by_material = {}
        if self.id:
            consumed_qs = StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.PRODUCTION_OUT,
                related_order_id=self.id,
                material__isnull=False,
            )
            consumed_qs = consumed_qs.values('material_id').annotate(
                total=Sum('quantity'),
            )
            for row in consumed_qs:
                consumed_by_material[row['material_id']] = row['total'] or Decimal('0')

        with transaction.atomic():
            # Тот же фиксированный порядок блокировок, что и в reserve_raw_materials.
            for material, required in sorted(self._recipe_requirements(product_id, quantity), key=lambda item: item[0].pk):
                locked = RawMaterial.objects.select_for_update().get(pk=material.pk)
                already = consumed_by_material.get(material.pk, Decimal('0'))
                remaining = required - already
                if remaining <= 0:
                    continue
                locked.reserved_for_orders = max(
                    (locked.reserved_for_orders or Decimal('0')) - remaining, Decimal('0')
                )
                locked.save(update_fields=['reserved_for_orders', 'updated_at'])

    def apply_payment_amount(self, amount):
        """
        Атомарно прибавляет сумму оплаты к paid_amount и обновляет payment_status.

        ГОНКА (lost update): раньше оплата шла как read-modify-write
        (paid_amount = paid_amount + amount) без блокировки. Две одновременные
        оплаты одного заказа читали одинаковый paid_amount, и одна перезаписывала
        другую — итог занижался, заказ ошибочно оставался «частично оплачен».
        select_for_update сериализует параллельные оплаты одного заказа.

        ПЕРЕПЛАТА: сумма сверх долга по заказу отклоняется. Проверка стоит ПОД
        блокировкой строки — иначе две одновременные оплаты, каждая в пределах
        долга, вместе могли бы его превысить. Отменённый заказ оплатить нельзя.
        """
        from django.db import transaction


        with transaction.atomic():
            locked = Order.objects.select_for_update().get(pk=self.pk)
            if locked.status == Order.Status.CANCELLED:
                raise ValidationError({'amount': 'Заказ отменён — оплату принять нельзя.'})
            already_paid = locked.paid_amount or Decimal('0')
            debt = (locked.total_amount or Decimal('0')) - already_paid
            if amount > debt:
                raise ValidationError({
                    'amount': f'Сумма больше долга по заказу. Осталось оплатить: {debt}.'
                })
            locked.paid_amount = already_paid + amount
            locked.save(update_fields=['paid_amount'])
            locked.update_payment_status()
        self.refresh_from_db()
