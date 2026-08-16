"""
Админка подписок: супер-админ видит все компании и управляет подписками
(активация, продление, заморозка/разморозка, подтверждение оплаты счёта).

Всё управление идёт через сервисные функции (apps.billing.services) — тот же
код, что и в API, поэтому админка не расходится с API (урок из
accounts/admin.py, где часть логики дублировалась).
"""
from django.contrib import admin, messages
from django.db import transaction

from apps.core.admin_utils import badge, choice_badge

from .models import Invoice, Subscription, SubscriptionEvent
from .services import (
    activate_subscription, confirm_invoice_paid, extend_subscription,
    freeze_subscription, unfreeze_subscription,
)

STATUS_COLORS = {
    Subscription.Status.ACTIVE: 'green',
    Subscription.Status.EXPIRED: 'amber',
    Subscription.Status.FROZEN: 'red',
}
PLAN_COLORS = {
    Subscription.Plan.FREE: 'gray',
    Subscription.Plan.PRO: 'blue',
}
INVOICE_COLORS = {
    Invoice.Status.PENDING: 'amber',
    Invoice.Status.PAID: 'green',
    Invoice.Status.FAILED: 'red',
    Invoice.Status.CANCELLED: 'gray',
}


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'company', 'plan_badge', 'status_badge', 'expires_at', 'days_left_display',
        'last_renewed_at', 'created_at',
    )
    list_filter = ('status', 'plan')
    search_fields = ('company__name',)
    date_hierarchy = 'expires_at'
    readonly_fields = ('created_at', 'updated_at')
    actions = (
        'activate_30_days', 'extend_30_days', 'freeze_selected', 'unfreeze_selected',
    )

    @admin.display(description='Тариф')
    def plan_badge(self, obj):
        return choice_badge(obj.plan, obj.get_plan_display(), PLAN_COLORS)

    @admin.display(description='Статус')
    def status_badge(self, obj):
        return choice_badge(obj.status, obj.get_status_display(), STATUS_COLORS)

    @admin.display(description='Осталось дней')
    def days_left_display(self, obj):
        if obj.is_blocked:
            return badge('заморожена', 'red')
        return f'{obj.days_left} дн.'

    @transaction.atomic
    def _run(self, request, queryset, func, *args, **kwargs):
        count = 0
        for sub in queryset:
            try:
                func(sub, actor=request.user, request=request, *args, **kwargs)
                count += 1
            except Exception as exc:
                self.message_user(request, f'{sub}: {exc}', level=messages.ERROR)
        return count

    @admin.action(description='Активировать на 30 дней')
    def activate_30_days(self, request, queryset):
        count = self._run(request, queryset, activate_subscription)
        self.message_user(request, f'Активировано подписок: {count}.')

    @admin.action(description='Продлить на 30 дней')
    def extend_30_days(self, request, queryset):
        count = self._run(request, queryset, extend_subscription, days=30)
        self.message_user(request, f'Продлено подписок: {count}.')

    @admin.action(description='Заморозить')
    def freeze_selected(self, request, queryset):
        count = 0
        for sub in queryset:
            if freeze_subscription(sub, actor=request.user, request=request):
                count += 1
        self.message_user(request, f'Заморожено компаний: {count}.')

    @admin.action(description='Разморозить')
    def unfreeze_selected(self, request, queryset):
        count = self._run(request, queryset, unfreeze_subscription)
        self.message_user(request, f'Разморожено компаний: {count}.')


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    """История подписок — только просмотр (неизменяемая)."""
    list_display = ('created_at', 'company', 'action', 'actor_role', 'from_status', 'to_status', 'note')
    list_filter = ('action', 'actor_role')
    search_fields = ('company__name', 'note')
    readonly_fields = [f.name for f in SubscriptionEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'status_badge', 'amount', 'currency', 'provider', 'paid_at', 'created_at')
    list_filter = ('status', 'provider')
    search_fields = ('company__name', 'provider_payment_id')
    readonly_fields = [f.name for f in Invoice._meta.fields]
    actions = ('confirm_payment',)

    @admin.display(description='Статус')
    def status_badge(self, obj):
        return choice_badge(obj.status, obj.get_status_display(), INVOICE_COLORS)

    @admin.action(description='Подтвердить оплату (продлить подписку)')
    def confirm_payment(self, request, queryset):
        count = 0
        for invoice in queryset:
            try:
                confirm_invoice_paid(invoice, actor=request.user, request=request)
                count += 1
            except Exception as exc:
                self.message_user(request, f'Счёт #{invoice.id}: {exc}', level=messages.ERROR)
        self.message_user(request, f'Подтверждено счетов: {count}.')
