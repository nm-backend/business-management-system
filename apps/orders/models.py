"""
Orders models - заказы клиентов.

Суммы заказа (total_amount, paid_amount) - финансовые поля, через API
они доступны только владельцу.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel, SoftDeleteModel
from apps.core.validators import validate_file_size
from apps.clients.models import Client
from apps.warehouse.models import FinishedProduct


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

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='orders', null=True)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='orders')
    product = models.ForeignKey(FinishedProduct, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    custom_product_name = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2,
                                   validators=[MinValueValidator(Decimal('0.01'))])
    unit = models.CharField(max_length=20)
    deadline = models.DateTimeField(null=True, blank=True)
    worker = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_orders')
    comment = models.TextField(blank=True)
    photo = models.ImageField(upload_to='orders/', blank=True, null=True, validators=[validate_file_size])
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.NEW, db_index=True)
    payment_status = models.CharField(max_length=50, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    # Финансовые поля (только owner через API).
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                       validators=[MinValueValidator(Decimal('0'))])
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.id} - {self.client.name}"

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
        """Синхронизирует payment_status с суммами total_amount/paid_amount."""
        if self.paid_amount <= 0:
            self.payment_status = self.PaymentStatus.UNPAID
        elif self.is_paid:
            self.payment_status = self.PaymentStatus.PAID
        else:
            self.payment_status = self.PaymentStatus.PARTIAL
        self.save(update_fields=['payment_status', 'updated_at'])

    def apply_payment_amount(self, amount):
        """
        Атомарно прибавляет сумму оплаты к paid_amount и обновляет payment_status.

        ГОНКА (lost update): раньше оплата шла как read-modify-write
        (paid_amount = paid_amount + amount) без блокировки. Две одновременные
        оплаты одного заказа читали одинаковый paid_amount, и одна перезаписывала
        другую — итог занижался, заказ ошибочно оставался «частично оплачен».
        select_for_update сериализует параллельные оплаты одного заказа.
        """
        from django.db import transaction
        with transaction.atomic():
            locked = Order.objects.select_for_update().get(pk=self.pk)
            locked.paid_amount = (locked.paid_amount or Decimal('0')) + amount
            locked.save(update_fields=['paid_amount'])
            locked.update_payment_status()
        self.refresh_from_db()
