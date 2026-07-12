"""
Clients models - клиенты и их оплаты.

Финансовые поля клиента (total_orders_amount, total_paid, debt) доступны
через API только владельцу. Администратор получает только булевы статусы.
"""
from decimal import Decimal

from django.db import models
from django.db.models import Sum

from apps.core.models import TimestampedModel, SoftDeleteModel

# Статусы заказа, при которых клиент считается активным.
ACTIVE_ORDER_STATUSES = (
    'new', 'awaiting_material', 'sent_to_worker', 'accepted',
    'worker_refused', 'in_progress', 'awaiting_confirmation', 'ready',
)


class Client(TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    comment = models.TextField(blank=True)

    # Финансовые агрегаты (ФИНАНСОВЫЕ ПОЛЯ - только owner).
    # Пересчитываются в recalculate_financials() из заказов и оплат.
    total_orders_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    debt = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.phone})" if self.phone else self.name

    @property
    def has_debt(self):
        return (self.debt or Decimal('0')) > 0

    @property
    def has_active_orders(self):
        return self.orders.filter(status__in=ACTIVE_ORDER_STATUSES, is_archived=False).exists()

    @property
    def is_active(self):
        """Клиент активен, пока есть долг или незавершённый заказ."""
        return not self.is_archived

    def recalculate_financials(self):
        """Пересчитывает сумму заказов, оплат и долг по данным заказов и платежей."""
        totals = self.orders.filter(is_archived=False).exclude(status='cancelled').aggregate(
            total=Sum('total_amount'),
        )
        paid = self.payments.aggregate(total=Sum('amount'))
        self.total_orders_amount = totals['total'] or Decimal('0')
        self.total_paid = paid['total'] or Decimal('0')
        self.debt = max(self.total_orders_amount - self.total_paid, Decimal('0'))
        self.save(update_fields=['total_orders_amount', 'total_paid', 'debt', 'updated_at'])

    def auto_archive(self):
        """Переводит клиента в архив, когда нет долга и активных заказов (правило ТЗ)."""
        if not self.has_debt and not self.has_active_orders:
            self.archive()
            return True
        return False


class Payment(TimestampedModel):
    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Наличные'
        CARD = 'card', 'Карта'
        TRANSFER = 'transfer', 'Перевод'
        OTHER = 'other', 'Другое'

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='payments')
    order = models.ForeignKey(
        'orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments',
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    comment = models.TextField(blank=True)
    received_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='received_payments')
    payment_date = models.DateTimeField()

    class Meta:
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        ordering = ['-payment_date']

    def __str__(self):
        return f"Payment {self.amount} by {self.client.name} on {self.payment_date}"
