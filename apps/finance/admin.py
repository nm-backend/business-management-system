"""Finance admin."""
from django.contrib import admin

from .models import Expense, LaborRate, WorkerPayment


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'category', 'amount', 'date', 'created_by')
    list_filter = ('company', 'category', 'date', 'payment_method')
    search_fields = ('comment',)
    autocomplete_fields = ('company', 'created_by')
    date_hierarchy = 'date'
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-date',)


@admin.register(LaborRate)
class LaborRateAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'product', 'operation', 'rate_per_unit', 'unit')
    list_filter = ('company', 'operation')
    search_fields = ('product__name',)
    autocomplete_fields = ('company', 'product')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WorkerPayment)
class WorkerPaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'worker', 'amount', 'payment_type', 'payment_date', 'created_by')
    list_filter = ('company', 'payment_type', 'payment_date')
    search_fields = ('worker__username', 'worker__full_name', 'comment')
    autocomplete_fields = ('company', 'worker', 'created_by')
    date_hierarchy = 'payment_date'
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-payment_date',)
