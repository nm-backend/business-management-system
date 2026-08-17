"""Сериализаторы подписок, истории и счетов."""
from rest_framework import serializers

from .models import Invoice, Subscription, SubscriptionEvent


class SubscriptionEventSerializer(serializers.ModelSerializer):
    """Событие истории подписки (кто, что, когда)."""
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionEvent
        fields = [
            'id', 'action', 'actor_name', 'actor_role',
            'from_status', 'to_status',
            'old_expires_at', 'new_expires_at', 'note', 'created_at',
        ]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if obj.actor is None:
            return 'system' if obj.actor_role == 'system' else ''
        return obj.actor.full_name or obj.actor.username


class SubscriptionSerializer(serializers.ModelSerializer):
    """Подписка для владельца компании и супер-админа."""
    is_blocked = serializers.ReadOnlyField()
    days_left = serializers.ReadOnlyField()
    company_name = serializers.CharField(source='company.name', read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'id', 'company', 'company_name', 'plan', 'status',
            'started_at', 'expires_at', 'last_renewed_at', 'frozen_at',
            'is_blocked', 'days_left',
        ]
        read_only_fields = fields


class SubscriptionSummarySerializer(serializers.ModelSerializer):
    """Краткая сводка подписки (для списка компаний супер-админа)."""
    is_blocked = serializers.ReadOnlyField()
    days_left = serializers.ReadOnlyField()

    class Meta:
        model = Subscription
        fields = ['id', 'plan', 'status', 'started_at', 'expires_at',
                  'is_blocked', 'days_left']
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    """Счёт на оплату."""
    class Meta:
        model = Invoice
        fields = [
            'id', 'amount', 'currency', 'status', 'provider',
            'provider_payment_id', 'metadata', 'paid_at', 'created_at',
        ]
        read_only_fields = fields


class RenewRequestSerializer(serializers.Serializer):
    """Продление: выбор тарифа (опционально)."""
    plan = serializers.ChoiceField(choices=Subscription.Plan.values, required=False)


class ExtendRequestSerializer(serializers.Serializer):
    """Продление супер-админом: число дней + комментарий."""
    days = serializers.IntegerField(min_value=1, max_value=365, required=True)
    note = serializers.CharField(required=False, allow_blank=True, default='')


class ActivateRequestSerializer(serializers.Serializer):
    """Активация супер-админом: число дней + комментарий."""
    days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    note = serializers.CharField(required=False, allow_blank=True, default='')


class NoteRequestSerializer(serializers.Serializer):
    """Комментарий к ручным операциям (freeze/unfreeze)."""
    note = serializers.CharField(required=False, allow_blank=True, default='')


class ConfirmPaymentSerializer(serializers.Serializer):
    """Подтверждение оплаты счёта супер-админом."""
    invoice_id = serializers.IntegerField(required=True)
