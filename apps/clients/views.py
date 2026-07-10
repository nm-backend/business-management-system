"""
Views for clients API.

Этот модуль содержит API views для управления клиентами
с защитой финансовых данных для non-owner пользователей.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.core.viewsets import ActionSerializerMixin, OwnerSerializerMixin
from .models import Client
from .serializers import (
    ClientSerializer, ClientLimitedSerializer, ClientCreateSerializer
)


class ClientViewSet(
    ActionSerializerMixin,
    OwnerSerializerMixin,
    viewsets.ModelViewSet,
):
    """
    ViewSet для управления клиентами.

    Разные сериализаторы для разных ролей:
    - Owner: полный доступ с финансовыми данными
    - Admin/Worker: ограниченный доступ без финансовых данных
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ClientLimitedSerializer
    owner_serializer_class = ClientSerializer
    serializer_action_classes = {'create': ClientCreateSerializer}

    def get_queryset(self):
        """
        Возвращает queryset клиентов.

        Фильтрация по активным/архивным клиентам.
        """
        queryset = Client.objects.all()
        is_archived = self.request.query_params.get('is_archived')

        if is_archived is not None:
            queryset = queryset.filter(is_archived=is_archived.lower() == 'true')

        return queryset

    @action(detail=False, methods=['get'])
    def active(self, request):
        """
        Возвращает список активных клиентов.

        GET /api/v1/clients/active/
        """
        active_clients = self.get_queryset().filter(is_active=True, is_archived=False)
        serializer = self.get_serializer(active_clients, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def archived(self, request):
        """
        Возвращает список архивных клиентов.

        GET /api/v1/clients/archived/
        """
        archived_clients = self.get_queryset().filter(is_archived=True)
        serializer = self.get_serializer(archived_clients, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """
        Архивирует клиента.

        POST /api/v1/clients/{id}/archive/
        """
        client = self.get_object()
        if not request.user.is_owner:
            return Response(
                {'detail': 'Only owner can archive clients'},
                status=status.HTTP_403_FORBIDDEN
            )
        client.is_archived = True
        client.save()
        serializer = self.get_serializer(client)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def unarchive(self, request, pk=None):
        """
        Разархивирует клиента.

        POST /api/v1/clients/{id}/unarchive/
        """
        client = self.get_object()
        if not request.user.is_owner:
            return Response(
                {'detail': 'Only owner can unarchive clients'},
                status=status.HTTP_403_FORBIDDEN
            )
        client.is_archived = False
        client.save()
        serializer = self.get_serializer(client)
        return Response(serializer.data)
