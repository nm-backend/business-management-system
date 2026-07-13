from rest_framework import filters, viewsets
from django_filters.rest_framework import DjangoFilterBackend
from apps.core.permissions import IsCompanyMember
from core.permissions import IsOwner
from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnlyModelViewSet даёт владельцу список и детали audit_logs своей компании.

    Это именно read-only ViewSet: по ТЗ журнал действий должен быть надёжной
    историей, поэтому API не предоставляет create/update/delete для логов.
    Доступ открыт только owner-роли своей компании.
    """

    queryset = AuditLog.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    serializer_class = AuditLogSerializer
    permission_classes = [IsCompanyMember, IsOwner]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['actor', 'actor_role', 'action', 'object_type']
    search_fields = ['actor_username', 'object_repr', 'object_id']
    ordering_fields = ['created_at']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return AuditLog.objects.none()
        return AuditLog.objects.filter(
            company_id=self.request.user.company_id,
        ).select_related('actor')
