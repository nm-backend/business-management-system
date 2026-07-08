from django.contrib import admin
from .models import RawMaterial, FinishedProduct, StockMovement, Recipe, RecipeItem

@admin.register(RawMaterial)
class RawMaterialAdmin(admin.ModelAdmin):
    list_display = ['name', 'stone_type', 'quantity', 'unit', 'min_stock', 'is_low_stock']
    list_filter = ['stone_type', 'unit', 'is_archived']
    search_fields = ['name', 'supplier', 'comment']

@admin.register(FinishedProduct)
class FinishedProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'quantity', 'available_quantity', 'unit']
    list_filter = ['category', 'unit', 'is_archived']
    search_fields = ['name', 'description']

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ['movement_type', 'material', 'product', 'quantity', 'created_at']
    list_filter = ['movement_type', 'created_at']
    search_fields = ['reason', 'material__name', 'product__name']

class RecipeItemInline(admin.TabularInline):
    model = RecipeItem
    extra = 1

@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ['name', 'product', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'product__name']
    inlines = [RecipeItemInline]
