from django.db import models
from apps.core.models import TimestampedModel, SoftDeleteModel

class Client(TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'
        ordering = ['name']

    def __str__(self):
        return self.name

class Payment(TimestampedModel):
    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Наличные'
        CARD = 'card', 'Карта'
        TRANSFER = 'transfer', 'Перевод'
        OTHER = 'other', 'Другое'

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='payments')
    order_id = models.IntegerField(null=True, blank=True) # Linking to Order (will use generic or simple int to avoid circular imports for now)
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
