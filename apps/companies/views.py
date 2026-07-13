"""
API управления компаниями - только для платформенного супер-администратора.

Супер-админ создаёт компании (вместе с владельцем), блокирует/разблокирует их.
Блокировка компании деактивирует всех её пользователей (вход становится невозможен).
"""
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import write_audit_log
from apps.core.permissions import IsSuperAdmin
from .models import Company
from .serializers import CompanySerializer, CompanyCreateSerializer


class CompanyViewSet(viewsets.ModelViewSet):
    """CRUD компаний для супер-администратора (без удаления - только блокировка)."""
    queryset = Company.objects.all()
    permission_classes = [IsSuperAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['name', 'created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return CompanyCreateSerializer
        return CompanySerializer

    def perform_create(self, serializer):
        company = serializer.save()
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=company,
            request=self.request,
        )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Company deletion is prohibited. Block it instead.')

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Блокирует/разблокирует компанию вместе со всеми её пользователями."""
        company = self.get_object()
        company.is_active = not company.is_active
        company.save(update_fields=['is_active'])
        # Блокировка/разблокировка каскадом на пользователей компании.
        User.objects.filter(company=company).update(is_active=company.is_active)
        write_audit_log(
            action=AuditLog.Action.ACTIVATE if company.is_active else AuditLog.Action.DEACTIVATE,
            actor=request.user,
            target=company,
            changes={'is_active': {'old': not company.is_active, 'new': company.is_active}},
            request=request,
        )
        return Response({'is_active': company.is_active})
