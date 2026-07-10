from django.db import models
from apps.core.models import TimestampedModel, SoftDeleteModel
from apps.clients.models import Client
from apps.warehouse.models import FinishedProduct

class Order(TimestampedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        NEW = 'new', 'Новый'
        AWAITING_MATERIAL = 'awaiting_material', 'Ожидает материала'
        SENT_TO_WORKER = 'sent_to_worker', 'Отправлен работнику'
        ACCEPTED = 'accepted', 'Принят работником'
        WORKER_REJECTED = 'worker_rejected', 'Работник отказался'
        IN_PROGRESS = 'in_progress', 'В работе'
        AWAITING_CONFIRMATION = 'awaiting_confirmation', 'Ожидает подтверждения'
        READY = 'ready', 'Готов'
        DELIVERED = 'delivered', 'Выдан клиенту'
        CANCELLED = 'cancelled', 'Отменен'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'Не оплачено'
        PARTIAL = 'partial', 'Частичная оплата'
        PAID = 'paid', 'Оплачено'

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='orders')
    product = models.ForeignKey(FinishedProduct, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    custom_product_name = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=20)
    deadline = models.DateTimeField(null=True, blank=True)
    worker = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_orders')
    comment = models.TextField(blank=True)
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.NEW)
    payment_status = models.CharField(max_length=50, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    class Meta:
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.id} - {self.client.name}"
