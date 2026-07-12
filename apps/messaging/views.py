"""
Views for messaging API.

Этот модуль содержит API views для управления сообщениями и уведомлениями.
"""
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Message, Notification
from .serializers import MessageSerializer, MessageCreateSerializer, NotificationSerializer


class MessageViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления сообщениями.

    Доступен для всех аутентифицированных пользователей.
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от действия.
        """
        if self.action == 'create':
            return MessageCreateSerializer
        return MessageSerializer

    def get_queryset(self):
        """
        Пользователь видит свои отправленные, полученные и групповые сообщения.

        ?box=inbox|sent сужает выборку до входящих или отправленных.
        """
        from django.db.models import Q
        user = self.request.user
        queryset = Message.objects.select_related('sender', 'recipient')

        box = self.request.query_params.get('box')
        if box == 'sent':
            queryset = queryset.filter(sender=user)
        elif box == 'inbox':
            queryset = queryset.filter(Q(recipient=user) | Q(is_group=True)).exclude(sender=user)
        else:
            queryset = queryset.filter(Q(sender=user) | Q(recipient=user) | Q(is_group=True))

        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == 'true')

        return queryset

    def perform_create(self, serializer):
        from .services import notify, notify_staff
        from apps.accounts.models import User

        message = serializer.save()
        title = 'Янги хабар'
        preview = message.content[:80]
        if message.is_group:
            recipients = User.objects.filter(is_active=True).exclude(pk=message.sender_id)
            notify(list(recipients), Notification.NotificationType.NEW_MESSAGE, title, preview)
        elif message.recipient:
            notify(message.recipient, Notification.NotificationType.NEW_MESSAGE, title, preview)

    @action(detail=False, methods=['get'])
    def recipients(self, request):
        """Список пользователей, которым текущий пользователь может писать."""
        from apps.accounts.models import User

        user = request.user
        queryset = User.objects.filter(is_active=True).exclude(pk=user.pk)
        if user.is_worker:
            allowed_roles = ['admin']
            if user.can_write_to_owner:
                allowed_roles.append('owner')
            queryset = queryset.filter(role__in=allowed_roles)
        elif user.is_admin:
            queryset = queryset.filter(role__in=['worker', 'owner'])
        data = [
            {'id': u.id, 'username': u.username, 'full_name': u.full_name, 'role': u.role}
            for u in queryset
        ]
        return Response(data)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """
        Помечает сообщение как прочитанное.

        POST /api/v1/messaging/messages/{id}/mark_read/
        """
        message = self.get_object()
        if message.recipient != request.user:
            return Response(
                {'detail': 'You can only mark your own messages as read'},
                status=status.HTTP_403_FORBIDDEN
            )

        message.is_read = True
        message.read_at = timezone.now()
        message.save()

        serializer = self.get_serializer(message)
        return Response(serializer.data)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet для просмотра уведомлений.

    Только чтение, уведомления создаются автоматически системой.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        """
        Возвращает queryset уведомлений.

        Пользователь видит только свои уведомления.
        """
        queryset = Notification.objects.select_related('user', 'related_order', 'related_task')
        user = self.request.user

        if user:
            queryset = queryset.filter(user=user)

        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == 'true')

        return queryset

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """
        Помечает уведомление как прочитанное.

        POST /api/v1/messaging/notifications/{id}/mark_read/
        """
        notification = self.get_object()
        if notification.user != request.user:
            return Response(
                {'detail': 'You can only mark your own notifications as read'},
                status=status.HTTP_403_FORBIDDEN
            )

        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()

        serializer = self.get_serializer(notification)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """
        Помечает все уведомления как прочитанные.

        POST /api/v1/messaging/notifications/mark_all_read/
        """
        user = request.user
        if user:
            user.notifications.filter(is_read=False).update(
                is_read=True,
                read_at=timezone.now()
            )

        return Response({'detail': 'All notifications marked as read'})
