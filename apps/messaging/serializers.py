"""
Serializers for messaging API — чат (беседы, сообщения, сотрудники)
и уведомления.
"""
from rest_framework import serializers

from apps.accounts.models import User

from .models import ChatMessage, Conversation, Notification
from .services import GENERAL_TITLE, unread_count


class EmployeeSerializer(serializers.ModelSerializer):
    """Сотрудник компании — для списка контактов и старта диалога."""
    display_role = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'full_name', 'role', 'display_role', 'avatar']


class ChatMessageSerializer(serializers.ModelSerializer):
    """Сообщение чата для чтения."""
    sender_name = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ['id', 'conversation', 'sender', 'sender_name', 'content', 'is_mine', 'created_at']
        read_only_fields = fields

    def get_sender_name(self, obj):
        return obj.sender.full_name or obj.sender.username

    def get_is_mine(self, obj):
        request = self.context.get('request')
        return bool(request and obj.sender_id == request.user.id)


class ChatMessageCreateSerializer(serializers.ModelSerializer):
    """
    Создание сообщения. Пользователь может писать только в свою беседу
    своей компании (проверяется по участию и company).
    """
    class Meta:
        model = ChatMessage
        fields = ['conversation', 'content']

    def validate_content(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError('Сообщение не может быть пустым.')
        return value

    def validate_conversation(self, conversation):
        user = self.context['request'].user
        if conversation.company_id != user.company_id:
            # Не раскрываем существование чужой беседы.
            raise serializers.ValidationError('Беседа не найдена.')
        is_general = conversation.kind == Conversation.Kind.GENERAL
        is_member = conversation.participants.filter(user=user).exists()
        if not is_general and not is_member:
            raise serializers.ValidationError('Вы не участник этой беседы.')
        return conversation


class ConversationSerializer(serializers.ModelSerializer):
    """
    Беседа для списка чатов: отображаемое имя, собеседник (для DIRECT),
    последнее сообщение и число непрочитанных.
    """
    display_title = serializers.SerializerMethodField()
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'kind', 'display_title', 'other_user',
            'last_message', 'unread_count', 'updated_at',
        ]

    def _request_user(self):
        request = self.context.get('request')
        return request.user if request else None

    def _other_participant(self, obj):
        """Собеседник в личном диалоге (не текущий пользователь)."""
        user = self._request_user()
        if obj.kind != Conversation.Kind.DIRECT or not user:
            return None
        for participant in obj.participants.all():
            if participant.user_id != user.id:
                return participant.user
        return None

    def get_display_title(self, obj):
        if obj.kind == Conversation.Kind.GENERAL:
            return obj.title or GENERAL_TITLE
        if obj.kind == Conversation.Kind.DIRECT:
            other = self._other_participant(obj)
            if other:
                return other.full_name or other.username
        return obj.title

    def get_other_user(self, obj):
        other = self._other_participant(obj)
        if not other:
            return None
        return {
            'id': other.id,
            'username': other.username,
            'full_name': other.full_name,
            'role': other.role,
        }

    def get_last_message(self, obj):
        last = obj.messages.order_by('-created_at').select_related('sender').first()
        if not last:
            return None
        return {
            'content': last.content[:120],
            'created_at': last.created_at.isoformat(),
            'sender': last.sender_id,
            'sender_name': last.sender.full_name or last.sender.username,
        }

    def get_unread_count(self, obj):
        user = self._request_user()
        if not user:
            return 0
        return unread_count(obj, user)


class StartDirectSerializer(serializers.Serializer):
    """Вход для старта личного диалога: id сотрудника своей компании."""
    user_id = serializers.IntegerField()

    def validate_user_id(self, value):
        request = self.context['request']
        me = request.user
        if value == me.id:
            raise serializers.ValidationError('Нельзя начать диалог с самим собой.')
        try:
            other = User.objects.get(pk=value, is_active=True)
        except User.DoesNotExist:
            raise serializers.ValidationError('Сотрудник не найден.')
        if other.company_id != me.company_id or other.is_superadmin:
            raise serializers.ValidationError('Сотрудник не найден.')
        self.context['other_user'] = other
        return value


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
