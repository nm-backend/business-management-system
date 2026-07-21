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
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='clients', null=True)
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
        verbose_name = 'Клиент'
        verbose_name_plural = 'Клиенты'
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
        """
        Пересчитывает сумму заказов, оплат и долг по действующим заказам.

        Оплаты и суммы считаются по одному и тому же набору заказов (не отменённых
        и не архивных). Оплата по отменённому заказу не гасит долг по другим заказам;
        платежи без привязки к заказу (order=None) считаются как аванс клиента.
        """
        active_orders = self.orders.filter(is_archived=False).exclude(status='cancelled')
        orders_total = active_orders.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        active_ids = list(active_orders.values_list('id', flat=True))
        paid = self.payments.filter(
            models.Q(order_id__in=active_ids) | models.Q(order__isnull=True),
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        self.total_orders_amount = orders_total
        self.total_paid = paid
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

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='payments', null=True)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='payments')
    order = models.ForeignKey(
        'orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments',
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    comment = models.TextField(blank=True)
    received_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='received_payments')
    # db_index: Meta.ordering сортирует ВСЕ выборки платежей по payment_date,
    # поэтому индекс убирает полную сортировку на больших объёмах.
    payment_date = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = 'Оплата'
        verbose_name_plural = 'Оплаты'
        ordering = ['-payment_date']

    def __str__(self):
        return f"Payment {self.amount} by {self.client.name} on {self.payment_date}"
