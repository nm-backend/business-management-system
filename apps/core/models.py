from django.db import models
from django.conf import settings

class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class SoftDeleteModel(models.Model):
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def archive(self):
        from django.utils import timezone
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=['is_archived', 'archived_at'])

    def restore(self):
        self.is_archived = False
        self.archived_at = None
        self.save(update_fields=['is_archived', 'archived_at'])

class Currency(TimestampedModel):
    code = models.CharField(max_length=3, unique=True, help_text='ISO 4217 code (e.g. KGS, USD)')
    name = models.CharField(max_length=100, help_text='Currency name')
    symbol = models.CharField(max_length=10, help_text='Currency symbol')
    is_default = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)

    class Meta:
        verbose_name = 'Currency'
        verbose_name_plural = 'Currencies'
        ordering = ['-is_default', 'code']

    def __str__(self):
        return f'{self.code} ({self.symbol})'

    def save(self, *args, **kwargs):
        if self.is_default:
            Currency.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

class ExchangeRate(TimestampedModel):
    from_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_from')
    to_currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates_to')
    rate = models.DecimalField(max_digits=12, decimal_places=6, help_text='Exchange rate')
    effective_date = models.DateField(db_index=True)

    class Meta:
        verbose_name = 'Exchange Rate'
        verbose_name_plural = 'Exchange Rates'
        ordering = ['-effective_date']
        unique_together = ['from_currency', 'to_currency', 'effective_date']

    def __str__(self):
        return f'{self.from_currency.code} -> {self.to_currency.code}: {self.rate} ({self.effective_date})'

    @classmethod
    def get_rate(cls, from_code, to_code, date=None):
        from django.utils import timezone
        if date is None:
            date = timezone.now().date()
        try:
            return cls.objects.filter(
                from_currency__code=from_code,
                to_currency__code=to_code,
                effective_date__lte=date
            ).order_by('-effective_date').first()
        except cls.DoesNotExist:
            return None
