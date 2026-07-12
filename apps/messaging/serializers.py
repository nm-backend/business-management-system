"""
Serializers for messaging API.

Этот модуль содержит сериализаторы для моделей Message и Notification.
"""
from rest_framework import serializers
from .models import Message, Notification


class MessageSerializer(serializers.ModelSerializer):
    """
    Сериализатор сообщения.

    Используется для всех ролей.
    """
    sender_name = serializers.CharField(source='sender.username', read_only=True)
    recipient_name = serializers.CharField(source='recipient.username', read_only=True)

    class Meta:
        model = Message
        fields = [
            'id', 'sender', 'sender_name', 'recipient', 'recipient_name',
            'subject', 'content', 'is_read', 'is_group',
            'read_at', 'is_unread', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'read_at', 'sender']


class MessageCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания сообщения.

    Правила ТЗ:
    - Владелец пишет кому угодно и всем (is_group).
    - Администратор пишет работникам и владельцу.
    - Работник пишет администраторам, владельцу - только если can_write_to_owner.
    """
    class Meta:
        model = Message
        fields = ['recipient', 'subject', 'content', 'is_group']

    def validate(self, data):
        sender = self.context['request'].user
        recipient = data.get('recipient')
        is_group = data.get('is_group', False)

        if is_group:
            if not sender.is_owner:
                raise serializers.ValidationError('Only the owner can send group messages')
            data['recipient'] = None
            return data

        if not recipient:
            raise serializers.ValidationError({'recipient': 'Recipient is required'})
        if recipient == sender:
            raise serializers.ValidationError({'recipient': 'Cannot send a message to yourself'})

        if sender.is_worker:
            if recipient.is_worker:
                raise serializers.ValidationError({'recipient': 'Workers cannot message other workers'})
            if recipient.is_owner and not sender.can_write_to_owner:
                raise serializers.ValidationError({'recipient': 'You are not allowed to write to the owner'})
        return data

    def create(self, validated_data):
        return Message.objects.create(**validated_data, sender=self.context['request'].user)


class NotificationSerializer(serializers.ModelSerializer):
    """
    Сериализатор уведомления.

    Используется для всех ролей.
    """
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'user', 'type', 'type_display', 'title', 'message',
            'is_read', 'read_at', 'is_unread',
            'related_order', 'related_task',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'read_at']
