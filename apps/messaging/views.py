"""
Views for messaging API.

Этот модуль содержит API views для управления сообщениями и уведомлениями.
"""
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
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
        Возвращает queryset сообщений.

        Пользователь видит только свои отправленные и полученные сообщения.
        """
        queryset = Message.objects.select_related('sender', 'recipient')
        user = self.request.user

        if user:
            queryset = queryset.filter(sender=user) | queryset.filter(recipient=user)

        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == 'true')

        return queryset

    def perform_update(self, serializer):
        if serializer.instance.sender != self.request.user:
            raise PermissionDenied('Only the sender can update a message.')
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Message deletion is prohibited.')

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
