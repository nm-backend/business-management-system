from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from apps.core.permissions import IsCompanyMember, IsSuperAdmin
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

    @action(detail=False, methods=['get'], url_path='platform',
            permission_classes=[IsSuperAdmin])
    def platform_logs(self, request):
        """
        GET /api/v1/audit/logs/platform/ — только платформенные записи.

        Суперадмин не должен видеть бизнес-аудит компаний (изоляция), но
        запись об удалении компании создаётся с company=None и иначе была бы
        недоступна никому. Отдаём только company__isnull=True.
        """
        queryset = AuditLog.objects.filter(company__isnull=True).select_related('actor')
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(self.get_serializer(queryset, many=True).data)
