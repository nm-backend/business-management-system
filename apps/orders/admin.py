"""Orders admin."""
from django.contrib import admin

from apps.core.admin_utils import choice_badge

from .models import Order

_STATUS_COLORS = {
    'new': 'blue', 'awaiting_material': 'amber', 'sent_to_worker': 'blue',
    'accepted': 'teal', 'worker_refused': 'red', 'in_progress': 'teal',
    'awaiting_confirmation': 'amber', 'ready': 'green', 'delivered': 'gray',
    'cancelled': 'red',
}
_PAY_COLORS = {'unpaid': 'red', 'partial': 'amber', 'paid': 'green'}


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'client', 'status_badge', 'payment_badge', 'quantity', 'deadline', 'created_at')
    list_filter = ('company', 'status', 'payment_status', 'created_at')
    search_fields = ('client__name', 'custom_product_name', 'comment')
    autocomplete_fields = ('company', 'client', 'product', 'worker')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_select_related = ('company', 'client')

    @admin.display(description='Статус', ordering='status')
    def status_badge(self, obj):
        return choice_badge(obj.status, obj.get_status_display(), _STATUS_COLORS)

    @admin.display(description='Оплата', ordering='payment_status')
    def payment_badge(self, obj):
        return choice_badge(obj.payment_status, obj.get_payment_status_display(), _PAY_COLORS)
    fieldsets = (
        (None, {'fields': ('company', 'client', 'product', 'custom_product_name', 'quantity', 'unit')}),
        ('Исполнение', {'fields': ('worker', 'deadline', 'status', 'comment', 'photo')}),
        ('Оплата', {'fields': ('payment_status', 'total_amount', 'paid_amount')}),
        ('Статус', {'fields': ('is_archived', 'archived_at')}),
    )
