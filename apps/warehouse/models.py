from django.db import models
from django.core.exceptions import ValidationError
from apps.core.models import TimestampedModel, SoftDeleteModel

class UnitChoices(models.TextChoices):
    SHT = 'sht', 'Штук'
    M = 'm', 'Метр'
    M2 = 'm2', 'Квадратный метр'
    IZDELIE = 'izdelie', 'Изделие'
    DONA = 'dona', 'Дона'

class RawMaterial(TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    stone_type = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=100, blank=True)
    size = models.CharField(max_length=100, blank=True)
    thickness = models.CharField(max_length=50, blank=True)
    unit = models.CharField(max_length=20, choices=UnitChoices.choices, default=UnitChoices.SHT)
    quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    storage_location = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(upload_to='materials/', blank=True, null=True)
    min_stock = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    supplier = models.CharField(max_length=255, blank=True)
    arrival_date = models.DateField(null=True, blank=True)
    comment = models.TextField(blank=True)
    purchase_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    avg_cost_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Raw Material'
        verbose_name_plural = 'Raw Materials'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.quantity} {self.get_unit_display()})"

    @property
    def is_low_stock(self):
        return self.quantity <= self.min_stock

class FinishedProduct(TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=20, choices=UnitChoices.choices, default=UnitChoices.IZDELIE)
    quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    photo = models.ImageField(upload_to='products/', blank=True, null=True)
    description = models.TextField(blank=True)
    min_stock = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    reserved_for_orders = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    cost_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sale_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Finished Product'
        verbose_name_plural = 'Finished Products'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.quantity} {self.get_unit_display()})"

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_for_orders

    @property
    def is_low_stock(self):
        return self.available_quantity <= self.min_stock

class StockMovement(TimestampedModel):
    class MovementType(models.TextChoices):
        INCOMING = 'incoming', 'Приход'
        OUTGOING = 'outgoing', 'Расход'
        PRODUCTION_IN = 'production_in', 'Приход с производства'
        PRODUCTION_OUT = 'production_out', 'Расход на производство'
        ADJUSTMENT = 'adjustment', 'Корректировка'
        LOSS = 'loss', 'Потеря/Брак'

    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    material = models.ForeignKey(RawMaterial, on_delete=models.CASCADE, null=True, blank=True, related_name='movements')
    product = models.ForeignKey(FinishedProduct, on_delete=models.CASCADE, null=True, blank=True, related_name='movements')
    quantity = models.DecimalField(max_digits=15, decimal_places=3)
    price_per_unit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='stock_movements')
    related_order_id = models.IntegerField(null=True, blank=True)
    related_production_id = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'Stock Movement'
        verbose_name_plural = 'Stock Movements'
        ordering = ['-created_at']

    def clean(self):
        if self.material and self.product:
            raise ValidationError("Movement must be associated with either material or product, not both.")
        if not self.material and not self.product:
            raise ValidationError("Movement must be associated with a material or a product.")

class Recipe(TimestampedModel):
    product = models.ForeignKey(FinishedProduct, on_delete=models.CASCADE, related_name='recipes')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Recipe'
        verbose_name_plural = 'Recipes'
        ordering = ['name']

    def __str__(self):
        return f"Recipe for {self.product.name}: {self.name}"

class RecipeItem(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='items')
    material = models.ForeignKey(RawMaterial, on_delete=models.RESTRICT)
    quantity_required = models.DecimalField(max_digits=15, decimal_places=3)
    unit = models.CharField(max_length=20, choices=UnitChoices.choices, default=UnitChoices.SHT)

    class Meta:
        verbose_name = 'Recipe Item'
        verbose_name_plural = 'Recipe Items'

    def __str__(self):
        return f"{self.quantity_required} {self.get_unit_display()} of {self.material.name}"
