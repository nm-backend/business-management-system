"""
Views for clients API.

Этот модуль содержит API views для управления клиентами
с защитой финансовых данных для non-owner пользователей.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from core.permissions import IsOwner, IsOwnerOrAdmin, FinancialDataPermission
from .models import Client
from .serializers import (
    ClientSerializer, ClientLimitedSerializer, ClientCreateSerializer
)


class ClientViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления клиентами.

    Разные сериализаторы для разных ролей:
    - Owner: полный доступ с финансовыми данными
    - Admin/Worker: ограниченный доступ без финансовых данных
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от роли пользователя.

        Owner получает полные данные, остальные - ограниченные.
        Для create используется отдельный входной сериализатор,
        но ответ всегда возвращается через полный сериализатор.
        """
        request = self.request
        if request.user and request.user.is_owner:
            return ClientSerializer
        return ClientLimitedSerializer

    def create(self, request, *args, **kwargs):
        """
        Создает клиента и возвращает полные данные включая id.

        Использует ClientCreateSerializer для валидации входных данных,
        затем возвращает результат через полный сериализатор.
        """
        input_serializer = ClientCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        client = input_serializer.save()
        output_serializer = self.get_serializer(client)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def get_queryset(self):
        """
        Возвращает queryset клиентов с prefetch для производительности.

        Фильтрация по активным/архивным клиентам.
        Использует select_related для оптимизации N+1 запросов.
        """
        queryset = Client.objects.prefetch_related('orders')
        is_archived = self.request.query_params.get('is_archived')

        if is_archived is not None:
            queryset = queryset.filter(is_archived=is_archived.lower() == 'true')

        return queryset

    def perform_create(self, serializer):
        """Создает клиента с текущим пользователем."""
        serializer.save()

    @action(detail=False, methods=['get'])
    def active(self, request):
        """
        Возвращает список активных клиентов.

        GET /api/v1/clients/active/
        """
        active_clients = self.get_queryset().filter(is_active=True, is_archived=False)[:100]
        serializer = self.get_serializer(active_clients, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def archived(self, request):
        """
        Возвращает список архивных клиентов.

        GET /api/v1/clients/archived/
        """
        archived_clients = self.get_queryset().filter(is_archived=True)[:100]
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
