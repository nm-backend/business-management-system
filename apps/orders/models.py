"""
Orders models - управление заказами.

Этот модуль содержит модель для управления заказами клиентов,
отслеживания статусов и связи с производством.

ВАЖНО: Финансовые поля доступны только владельцу (owner).
"""
from django.db import models
from apps.core.models import TimestampedModel


class OrderStatus(models.TextChoices):
    """
    Статусы заказа.

    NEW: новый заказ
    AWAITING_MATERIAL: ожидает материал
    SENT_TO_WORKER: отправлен работнику
    ACCEPTED_BY_WORKER: принят работником
    WORKER_REFUSED: работник отказался
    IN_PROGRESS: в работе
    AWAITING_CONFIRMATION: ожидает подтверждения
    READY: готов
    DELIVERED: выдан клиенту
    CANCELLED: отменён
    """
    NEW = 'new', 'Янги'
    AWAITING_MATERIAL = 'awaiting_material', 'Материал кутилмоқда'
    SENT_TO_WORKER = 'sent_to_worker', 'Ишчига юборилган'
    ACCEPTED_BY_WORKER = 'accepted_by_worker', 'Ишчи қабул қилди'
    WORKER_REFUSED = 'worker_refused', 'Ишчи рад этди'
    IN_PROGRESS = 'in_progress', 'Иш жараёнида'
    AWAITING_CONFIRMATION = 'awaiting_confirmation', 'Тасдиқлаш кутилмоқда'
    READY = 'ready', 'Тайёр'
    DELIVERED = 'delivered', 'Мижозга берилди'
    CANCELLED = 'cancelled', 'Бекор қилинди'


class PaymentStatus(models.TextChoices):
    """
    Статусы оплаты.

    UNPAID: не оплачено
    PARTIAL: частично оплачено
    PAID: оплачено
    """
    UNPAID = 'unpaid', 'Тўлов қилинмаган'
    PARTIAL = 'partial', 'Қисман тўланган'
    PAID = 'paid', 'Тўланган'


class Order(TimestampedModel):
    """
    Модель заказа.

    Хранит информацию о заказах клиентов, связывает с клиентами,
    товарами, работниками и производством.

    Поля:
        client: ForeignKey - клиент
        product: ForeignKey - готовый товар (опционально, если заказ на производство)
        product_name: CharField - название товара (для производства)
        quantity: DecimalField - количество
        unit: CharField - единица измерения
        deadline: DateField - срок выполнения
        material: CharField - материал (для производства)
        worker: ForeignKey - назначенный работник
        comment: TextField - комментарий
        drawing: ImageField - фото или чертёж
        status: CharField - статус заказа
        payment_status: CharField - статус оплаты
        total_amount: DecimalField - сумма заказа (ФИНАНСОВОЕ ПОЛЕ)
        paid_amount: DecimalField - оплаченная сумма (ФИНАНСОВОЕ ПОЛЕ)
        material_shortage: BooleanField - нехватка материала
        is_overdue: BooleanField - просрочен ли заказ

    Свойства:
        is_paid: bool - True если полностью оплачен
        has_debt: bool - True если есть долг
        days_until_deadline: int - дней до дедлайна

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Связь с клиентом и работником
        - Отслеживание статусов заказа и оплаты
    """
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='orders')
    product = models.ForeignKey('warehouse.FinishedProduct', on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    product_name = models.CharField(max_length=255, blank=True, default='')
    quantity = models.DecimalField(max_digits=15, decimal_places=3)
    unit = models.CharField(max_length=20, choices='warehouse.models.UnitChoices.choices')
    deadline = models.DateField()
    material = models.CharField(max_length=100, blank=True, default='')
    worker = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_orders')
    comment = models.TextField(blank=True, default='')
    drawing = models.ImageField(upload_to='orders/drawings/', blank=True, null=True)
    status = models.CharField(max_length=30, choices=OrderStatus.choices, default=OrderStatus.NEW, db_index=True)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # ФИНАНСОВОЕ ПОЛЕ
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # ФИНАНСОВОЕ ПОЛЕ
    material_shortage = models.BooleanField(default=False)
    is_overdue = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'deadline']),
            models.Index(fields=['client', 'status']),
            models.Index(fields=['worker', 'status']),
        ]

    def __str__(self):
        """
        Строковое представление заказа.

        Возвращает информацию о заказе с клиентом и статусом.
        """
        return f"Order #{self.id} - {self.client.name} ({self.get_status_display()})"

    @property
    def is_paid(self):
        """
        Проверяет, полностью ли оплачен заказ.

        Возвращает:
            bool - True если paid_amount >= total_amount
        """
        return self.paid_amount >= self.total_amount

    @property
    def has_debt(self):
        """
        Проверяет, есть ли долг по заказу.

        Возвращает:
            bool - True если total_amount > paid_amount
        """
        return self.total_amount > self.paid_amount
