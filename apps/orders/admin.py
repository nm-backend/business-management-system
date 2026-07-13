"""Orders admin."""
from django.contrib import admin

from .models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'client', 'status', 'payment_status', 'quantity', 'deadline', 'created_at')
    list_filter = ('company', 'status', 'payment_status', 'created_at')
    search_fields = ('client__name', 'custom_product_name', 'comment')
    autocomplete_fields = ('company', 'client', 'product', 'worker')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    fieldsets = (
        (None, {'fields': ('company', 'client', 'product', 'custom_product_name', 'quantity', 'unit')}),
        ('Исполнение', {'fields': ('worker', 'deadline', 'status', 'comment', 'photo')}),
        ('Оплата', {'fields': ('payment_status', 'total_amount', 'paid_amount')}),
        ('Статус', {'fields': ('is_archived', 'archived_at')}),
    )
