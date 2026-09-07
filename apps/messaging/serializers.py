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
    attachment = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            'id', 'conversation', 'sender', 'sender_name', 'content',
            'attachment', 'attachment_name', 'is_mine', 'created_at',
        ]
        read_only_fields = fields

    def get_sender_name(self, obj):
        return obj.sender.full_name or obj.sender.username

    def get_is_mine(self, obj):
        request = self.context.get('request')
        return bool(request and obj.sender_id == request.user.id)

    def get_attachment(self, obj):
        """Абсолютный URL вложения (или null). Относительный — если нет request."""
        if not obj.attachment:
            return None
        url = obj.attachment.url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class ChatMessageCreateSerializer(serializers.ModelSerializer):
    """
    Создание сообщения. Пользователь может писать только в свою беседу
    своей компании (проверяется по участию и company).

    Сообщение может быть текстовым, с вложением или и тем, и другим —
    но не пустым (проверяется в validate()).
    """
    content = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = ChatMessage
        fields = ['conversation', 'content', 'attachment']

    def validate_content(self, value):
        value = (value or '').strip()
        if len(value) > 10000:
            raise serializers.ValidationError('Сообщение слишком длинное (максимум 10000 символов).')
        return value

    def validate(self, attrs):
        # Раньше пустой content отклонялся в validate_content, из-за чего
        # сообщение из одного файла (без подписи) вообще нельзя было отправить.
        if not attrs.get('content') and not attrs.get('attachment'):
            raise serializers.ValidationError(
                {'content': 'Сообщение не может быть пустым.'},
            )
        return attrs

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
        # Быстрый путь: значения посчитаны подзапросом в get_queryset (без N+1).
        if hasattr(obj, 'last_msg_created'):
            if obj.last_msg_created is None:
                return None
            return {
                'content': self._preview(
                    obj.last_msg_content, getattr(obj, 'last_msg_attachment_name', ''),
                ),
                'created_at': obj.last_msg_created.isoformat(),
                'sender': obj.last_msg_sender,
                'sender_name': obj.last_msg_sender_name or obj.last_msg_sender_username,
            }
        # Запасной путь для одиночных объектов (general/start_direct).
        last = obj.messages.order_by('-created_at').select_related('sender').first()
        if not last:
            return None
        return {
            'content': self._preview(last.content, last.attachment_name),
            'created_at': last.created_at.isoformat(),
            'sender': last.sender_id,
            'sender_name': last.sender.full_name or last.sender.username,
        }

    @staticmethod
    def _preview(content, attachment_name):
        """Превью последнего сообщения: текст, а для файла без подписи — имя файла."""
        if content:
            return content[:120]
        if attachment_name:
            return f'📎 {attachment_name}'[:120]
        return ''

    def get_unread_count(self, obj):
        if hasattr(obj, 'unread_total'):
            return obj.unread_total or 0
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
        # Работники скрыты от тех, у кого нет флага can_see_other_workers
        # (owner видит всех) — зеркально списку контактов EmployeeViewSet.
        if other.role == User.Role.WORKER and not me.is_owner and not me.can_see_other_workers:
            raise serializers.ValidationError('Сотрудник не найден.')
        # Работник не может писать хозяину без разрешения.
        if me.role == User.Role.WORKER and other.role == User.Role.OWNER and not me.can_write_to_owner:
            raise serializers.ValidationError('Эгасига ёзиш учун рухсат йўқ.')
        self.context['other_user'] = other
        return value


class NotificationSerializer(serializers.ModelSerializer):
    """
    Сериализатор уведомления.

    Используется для всех ролей.
    """
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    # Компания-источник: для суперадмина это компания, чья подписка истекает,
    # по ней фронтенд строит переход к разделу «Управление бизнесами».
    company = serializers.IntegerField(source='company_id', read_only=True)
    # Клиент связанного заказа — для перехода из уведомления о неоплате
    # сразу на неоплаченные заказы этого клиента (#/orders?client=&payment_status=unpaid).
    related_client = serializers.IntegerField(
        source='related_order.client_id', read_only=True, default=None,
    )
    # Текст рендерится на языке ТЕКУЩЕГО пользователя: сменил язык в
    # настройках — переведётся и лента уведомлений, а не только новые записи.
    title = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'user', 'company', 'type', 'type_display', 'title', 'message',
            'is_read', 'read_at', 'is_unread',
            'related_order', 'related_task', 'related_client',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'read_at']

    def _lang(self):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        return getattr(user, 'language', None) or 'uz_cyrl'

    def get_title(self, obj):
        return obj.localized_title(self._lang())

    def get_message(self, obj):
        return obj.localized_message(self._lang())
