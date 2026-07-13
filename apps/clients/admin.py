"""Clients admin."""
from django.contrib import admin

from .models import Client, Payment


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'phone', 'debt', 'is_archived', 'created_at')
    list_filter = ('company', 'is_archived')
    search_fields = ('name', 'phone', 'comment')
    autocomplete_fields = ('company',)
    readonly_fields = ('total_orders_amount', 'total_paid', 'debt', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    ordering = ('name',)
    fieldsets = (
        (None, {'fields': ('company', 'name', 'phone', 'address', 'comment')}),
        ('Финансы', {'fields': ('total_orders_amount', 'total_paid', 'debt')}),
        ('Статус', {'fields': ('is_archived', 'archived_at')}),
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('client', 'company', 'amount', 'payment_method', 'payment_date', 'received_by')
    list_filter = ('company', 'payment_method', 'payment_date')
    search_fields = ('client__name', 'comment')
    autocomplete_fields = ('company', 'client', 'order', 'received_by')
    date_hierarchy = 'payment_date'
    readonly_fields = ('created_at', 'updated_at')
