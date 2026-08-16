"""
API управления компаниями - только для платформенного супер-администратора.

Супер-админ создаёт компании (вместе с владельцем), блокирует/разблокирует их.
Блокировка компании деактивирует всех её пользователей (вход становится невозможен).
"""
from django.db.models import Count, Prefetch
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.token_utils import blacklist_all_tokens
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

    def get_queryset(self):
        # Убираем N+1 в списке: users_count через annotate, а владелец —
        # через prefetch в obj._owner_list (1 запрос на всю страницу вместо
        # 3 на каждую компанию: count + owner дважды).
        return (
            Company.objects.all()
            .annotate(users_count=Count('users'))
            .select_related('subscription')  # сводка подписки без N+1
            .prefetch_related(Prefetch(
                'users',
                queryset=User.objects.filter(role=User.Role.OWNER),
                to_attr='_owner_list',
            ))
        )

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
        # read-modify-write под блокировкой: два параллельных toggle иначе
        # читали одно значение и писали одно и то же (потерянное обновление).
        from django.db import transaction
        with transaction.atomic():
            company = Company.objects.select_for_update().get(pk=self.get_object().pk)
            company.is_active = not company.is_active
            company.save(update_fields=['is_active'])
            company_users = User.objects.filter(company=company)
            if company.is_active:
                # Разблокировка: восстанавливаем только тех, кого НЕ блокировал
                # владелец индивидуально (иначе снятая компания-блокировка молча
                # вернула бы доступ уволенному/отстранённому сотруднику).
                company_users.filter(blocked_by_owner=False).update(is_active=True)
            else:
                # Блокировка: гасим всех и обрываем их активные сессии.
                company_users.update(is_active=False)
                for u in company_users:
                    blacklist_all_tokens(u)
        write_audit_log(
            action=AuditLog.Action.ACTIVATE if company.is_active else AuditLog.Action.DEACTIVATE,
            actor=request.user,
            target=company,
            changes={'is_active': {'old': not company.is_active, 'new': company.is_active}},
            request=request,
        )
        return Response({'is_active': company.is_active})
