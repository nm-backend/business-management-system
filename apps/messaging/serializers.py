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

    Используется при отправке сообщения.
    """
    class Meta:
        model = Message
        fields = [
            'recipient', 'subject', 'content', 'is_group'
        ]

    def create(self, validated_data):
        request = self.context.get('request')
        return Message.objects.create(
            **validated_data,
            sender=request.user if request and request.user.is_authenticated else None
        )


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
