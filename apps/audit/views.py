from rest_framework import filters, viewsets
from django_filters.rest_framework import DjangoFilterBackend
from apps.core.permissions import IsOwner
from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnlyModelViewSet даёт владельцу список и детали audit_logs.

    Это именно read-only ViewSet: по ТЗ журнал действий должен быть надёжной
    историей, поэтому API не предоставляет create/update/delete для логов.
    Доступ открыт только owner-роли через RBAC permission IsOwner.
    """

    queryset = AuditLog.objects.select_related('actor')
    serializer_class = AuditLogSerializer
    permission_classes = [IsOwner]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['actor', 'actor_role', 'action', 'object_type']
    search_fields = ['actor_username', 'object_repr', 'object_id']
    ordering_fields = ['created_at']
