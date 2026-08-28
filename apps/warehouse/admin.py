from django.contrib import admin

from apps.core.admin_utils import badge

from .models import RawMaterial, FinishedProduct, StockMovement, Recipe, RecipeItem


@admin.register(RawMaterial)
class RawMaterialAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'stone_type', 'quantity', 'unit', 'min_stock', 'stock_badge', 'is_archived')
    list_filter = ('company', 'stone_type', 'unit', 'is_archived')
    search_fields = ('name', 'supplier', 'comment')
    autocomplete_fields = ('company',)
    # Остаток и резерв меняются только движениями (record_incoming/outgoing):
    # правка мимо журнала ломает инвариант «остаток = стартовый + приходы −
    # расходы» (коммит 0c32033 закрыл это на API, но не в админке).
    readonly_fields = ('created_at', 'updated_at', 'quantity', 'required_for_orders')
    ordering = ('name',)
    list_select_related = ('company',)

    @admin.display(description='Остаток')
    def stock_badge(self, obj):
        return badge('Мало', 'red') if obj.is_low_stock else badge('В норме', 'green')


@admin.register(FinishedProduct)
class FinishedProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'category', 'quantity', 'available_quantity', 'unit', 'stock_badge', 'is_archived')
    list_filter = ('company', 'category', 'unit', 'is_archived')
    search_fields = ('name', 'description')
    autocomplete_fields = ('company',)
    readonly_fields = ('created_at', 'updated_at', 'quantity', 'required_for_orders')
    ordering = ('name',)
    list_select_related = ('company',)

    @admin.display(description='Остаток')
    def stock_badge(self, obj):
        return badge('Мало', 'red') if obj.is_low_stock else badge('В норме', 'green')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'movement_type', 'material', 'product', 'quantity', 'created_at')
    list_filter = ('company', 'movement_type', 'created_at')
    search_fields = ('reason', 'material__name', 'product__name')
    autocomplete_fields = ('company', 'material', 'product', 'created_by')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')


class RecipeItemInline(admin.TabularInline):
    model = RecipeItem
    extra = 1
    autocomplete_fields = ('material',)


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'product', 'is_active')
    list_filter = ('company', 'is_active')
    search_fields = ('name', 'product__name')
    autocomplete_fields = ('company', 'product')
    inlines = [RecipeItemInline]
    readonly_fields = ('created_at', 'updated_at')
