"""
API управления компаниями - только для платформенного супер-администратора.

Супер-админ создаёт компании (вместе с владельцем), блокирует/разблокирует их,
управляет подписками (активация, продление, заморозка, разморозка, установка
срока) и видит platform-level статистику и историю изменений.

Блокировка компании (toggle_active) деактивирует всех её пользователей — вход
становится невозможен. Заморозка подписки (subscription_freeze) НЕ трогает
аккаунты: владелец может войти и увидеть экран «Подписка истекла», а бизнес-
доступ блокируется permission'ом SubscriptionAccessPermission.

Только супер-администратор: владелец/admin/manager/worker не могут менять
подписку (и вообще обращаться к этим эндпоинтам).
"""
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.token_utils import blacklist_all_tokens
from apps.audit.models import AuditLog
from apps.audit.services import write_audit_log
from apps.core.permissions import IsOwnerOrAdmin, IsSuperAdmin
from .models import Company, SubscriptionChange, SubscriptionPlan
from .serializers import CompanySerializer, CompanyCreateSerializer
from .subscriptions import (
    SubscriptionError,
    activate_subscription,
    change_plan,
    extend_subscription,
    freeze_company,
    set_subscription_end,
    unfreeze_company,
)

# «Истекают скоро» — активные компании со сроком в ближайшие N дней.
EXPIRING_SOON_DAYS = 7
# «Недавние» события для dashboard: компании и продления за последние N дней.
RECENT_DAYS = 7


class CompanyViewSet(viewsets.ModelViewSet):
    """CRUD компаний для супер-администратора (без удаления - только блокировка)."""
    queryset = Company.objects.all()
    permission_classes = [IsSuperAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'users__username', 'users__full_name']
    ordering_fields = ['name', 'created_at', 'subscription_end', 'last_activity']

    def get_queryset(self):
        # Убираем N+1 в списке: счётчики через annotate (distinct=True — иначе
        # JOIN с клиентами и заказами размножает строки users_count), владелец —
        # через prefetch в obj._owner_list (1 запрос на всю страницу), тариф —
        # через select_related. Флаг «есть непрочитанный запрос на продление» —
        # по нему интерфейс супер-админа показывает бейдж/кнопку «Обработать».
        # Подзапрос Exists (без N+1). Импорт моделей локальный: messaging тянет companies.
        from apps.messaging.models import Notification
        renewal_request_exists = Notification.objects.filter(
            company=OuterRef('pk'),
            type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
            is_read=False,
        )
        queryset = (
            Company.objects.all()
            .select_related('plan')
            .annotate(
                users_count=Count('users', distinct=True),
                clients_count=Count('clients', distinct=True),
                orders_count=Count('orders', distinct=True),
                has_renewal_request=Exists(renewal_request_exists),
            )
            .prefetch_related(Prefetch(
                'users',
                queryset=User.objects.filter(role=User.Role.OWNER),
                to_attr='_owner_list',
            ))
        )
        # distinct(): поиск по users__username/full_name делает JOIN с users и
        # мог бы размножить строки (у компании несколько сотрудников).
        # select_for_update/annotate-счётчики уже используют distinct=True.
        queryset = queryset.distinct()

        # Быстрые фильтры раздела «Управление бизнесами» (?status=...).
        # request может отсутствовать при интроспекции (swagger, тесты N+1).
        if getattr(self, 'swagger_fake_view', False) or not hasattr(self, 'request'):
            return queryset
        req = self.request
        now = timezone.now()
        status_filter = req.query_params.get('status')
        if status_filter:
            valid = set(Company.SubscriptionStatus.values) | {'trial'}
            if status_filter not in valid:
                raise ValidationError({'status': f'Допустимые значения: {", ".join(sorted(valid))}'})
            if status_filter == 'trial':
                # Триалы = активные компании с флагом is_trial (не продлевались).
                queryset = queryset.filter(
                    is_trial=True,
                    subscription_status=Company.SubscriptionStatus.ACTIVE,
                ).filter(
                    Q(subscription_end__isnull=True) | Q(subscription_end__gt=now),
                )
            elif status_filter == Company.SubscriptionStatus.ACTIVE:
                # Активные = формально active И срок в будущем (или не задан).
                queryset = queryset.filter(
                    subscription_status=Company.SubscriptionStatus.ACTIVE,
                ).filter(
                    Q(subscription_end__isnull=True) | Q(subscription_end__gt=now),
                )
            elif status_filter == Company.SubscriptionStatus.EXPIRED:
                # Истёкшие — формальный статус expired: задача Celery переводит
                # active -> grace -> expired каждый час, поэтому формальный статус
                # отстаёт от фактического не больше чем на час (бейдж в списке
                # при этом показывает effective-статус).
                queryset = queryset.filter(subscription_status=Company.SubscriptionStatus.EXPIRED)
            else:
                queryset = queryset.filter(subscription_status=status_filter)
        elif req.query_params.get('expiring_soon') in ('1', 'true', 'True'):
            queryset = queryset.filter(
                subscription_status=Company.SubscriptionStatus.ACTIVE,
                subscription_end__gt=now,
                subscription_end__lte=now + timezone.timedelta(days=EXPIRING_SOON_DAYS),
            )

        return queryset

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

    # ── Platform-level статистика ──────────────────────────────────

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Сводка по платформе для dashboard супер-администратора.

        GET /api/v1/companies/stats/ -> { total, active, trial, grace, frozen,
        expired, expiring_soon, cancelled, recent_subscriptions,
        recent_renewals }
        """
        now = timezone.now()
        active_qs = Company.objects.filter(
            subscription_status=Company.SubscriptionStatus.ACTIVE,
        ).filter(
            Q(subscription_end__isnull=True) | Q(subscription_end__gt=now),
        )
        # Счётчики — по ФОРМАЛЬНЫМ статусам (задача Celery обновляет их
        # каждый час; бейджи в списке показывают effective-статус).
        expired_qs = Company.objects.filter(
            subscription_status=Company.SubscriptionStatus.EXPIRED,
        )
        recent_since = now - timezone.timedelta(days=RECENT_DAYS)
        return Response({
            'total': Company.objects.count(),
            'active': active_qs.count(),
            'trial': active_qs.filter(is_trial=True).count(),
            'grace': Company.objects.filter(
                subscription_status=Company.SubscriptionStatus.GRACE,
            ).count(),
            'frozen': Company.objects.filter(
                subscription_status=Company.SubscriptionStatus.FROZEN,
            ).count(),
            'expired': expired_qs.count(),
            'expiring_soon': Company.objects.filter(
                subscription_status=Company.SubscriptionStatus.ACTIVE,
                subscription_end__gt=now,
                subscription_end__lte=now + timezone.timedelta(days=EXPIRING_SOON_DAYS),
            ).count(),
            'cancelled': Company.objects.filter(
                subscription_status=Company.SubscriptionStatus.CANCELLED,
            ).count(),
            # Новые компании (новые подписки) за последние 7 дней.
            'recent_subscriptions': Company.objects.filter(
                created_at__gte=recent_since,
            ).count(),
            # Продления/активации за последние 7 дней (по истории подписок).
            'recent_renewals': SubscriptionChange.objects.filter(
                action__in=(
                    SubscriptionChange.Action.EXTENDED,
                    SubscriptionChange.Action.ACTIVATED,
                    SubscriptionChange.Action.END_SET,
                ),
                created_at__gte=recent_since,
            ).count(),
        })

    # ── Управление подпиской (только супер-админ) ──────────────────

    def _run_subscription_action(self, request, pk, func, **kwargs):
        """Общий обработчик: get_object + сервис + человекочитаемая ошибка."""
        company = self.get_object()
        try:
            result = func(company, actor=request.user, **kwargs)
        except SubscriptionError as exc:
            raise ValidationError({'detail': str(exc)})
        return Response({
            'id': result.id,
            'subscription_status': result.effective_subscription_status,
            'subscription_start': result.subscription_start,
            'subscription_end': result.subscription_end,
            'plan_id': result.plan_id,
            'plan_name': result.plan.name if result.plan else None,
            'is_trial': result.is_trial,
        })

    @action(detail=False, methods=['get'])
    def plans(self, request):
        """GET /companies/plans/ — каталог активных тарифов (для смены плана)."""
        plans = SubscriptionPlan.objects.filter(is_active=True).order_by('sort_order', 'id')
        return Response([{
            'id': p.id,
            'name': p.name,
            'code': p.code,
            'duration_days': p.duration_days,
            'price': str(p.price),
            'description': p.description,
            'is_default': p.is_default,
        } for p in plans])

    @action(detail=True, methods=['post'])
    def subscription_change_plan(self, request, pk=None):
        """
        POST /companies/{id}/subscription_change_plan/ — сменить тариф.

        Тело: {"plan_id": N}. Сроки подписки не меняются — только тариф
        (история + аудит + уведомление владельцу).
        """
        raw = request.data.get('plan_id')
        try:
            plan_id = int(raw)
        except (TypeError, ValueError):
            raise ValidationError({'plan_id': 'Укажите идентификатор тарифа.'})
        plan = SubscriptionPlan.objects.filter(pk=plan_id).first()
        if plan is None:
            raise ValidationError({'plan_id': 'Тариф не найден.'})
        return self._run_subscription_action(request, pk, change_plan, plan=plan)

    @action(detail=True, methods=['post'])
    def subscription_activate(self, request, pk=None):
        """POST /companies/{id}/subscription_activate/ — активировать подписку."""
        return self._run_subscription_action(request, pk, activate_subscription)

    @action(detail=True, methods=['post'])
    def subscription_extend(self, request, pk=None):
        """
        POST /companies/{id}/subscription_extend/ — продлить на N дней.

        Тело: {"days": 30}. Активная подписка продлевается от текущей даты
        окончания (остаток сохраняется); истёкшая/замороженная — от текущего
        момента и автоматически активируется.
        """
        days = request.data.get('days')
        if isinstance(days, str):
            try:
                days = int(days)
            except (TypeError, ValueError):
                raise ValidationError({'days': 'Ожидается целое число дней.'})
        return self._run_subscription_action(request, pk, extend_subscription, days=days)

    @action(detail=True, methods=['post'])
    def subscription_set_end(self, request, pk=None):
        """
        POST /companies/{id}/subscription_set_end/ — установить дату окончания.

        Тело: {"end": "2026-12-31T23:59:59+06:00"}. Дата обязана быть в будущем.
        """
        raw = request.data.get('end')
        end = parse_datetime(str(raw)) if raw else None
        if end is None:
            raise ValidationError({'end': 'Укажите дату окончания (ISO-8601).'})
        return self._run_subscription_action(request, pk, set_subscription_end, end=end)

    @action(detail=True, methods=['post'])
    def subscription_freeze(self, request, pk=None):
        """
        POST /companies/{id}/subscription_freeze/ — вручную заморозить компанию.

        Бизнес-доступ блокируется; аккаунты пользователей не деактивируются —
        владелец видит экран «Подписка истекла» и может продлить подписку.
        """
        return self._run_subscription_action(request, pk, freeze_company)

    @action(detail=True, methods=['post'])
    def subscription_unfreeze(self, request, pk=None):
        """
        POST /companies/{id}/subscription_unfreeze/ — разморозить компанию.

        Если срок уже прошёл — выдаётся стандартный срок 30 дней, иначе компания
        возвращается в active с прежним сроком.
        """
        return self._run_subscription_action(request, pk, unfreeze_company)

    def _history_row(self, c):
        return {
            'id': c.id,
            'action': c.action,
            'old_status': c.old_status,
            'new_status': c.new_status,
            'old_end': c.old_end.isoformat() if c.old_end else None,
            'new_end': c.new_end.isoformat() if c.new_end else None,
            'days_added': c.days_added,
            'old_plan': c.old_plan,
            'new_plan': c.new_plan,
            'actor': (c.actor.full_name or c.actor.username) if c.actor else 'system',
            'note': c.note,
            'created_at': c.created_at.isoformat() if c.created_at else None,
        }

    @action(detail=True, methods=['get'])
    def subscription_history(self, request, pk=None):
        """GET /companies/{id}/subscription_history/ — история изменений подписки."""
        company = self.get_object()
        changes = (
            SubscriptionChange.objects
            .filter(company=company)
            .select_related('actor')
            [:50]
        )
        return Response([self._history_row(c) for c in changes])

    # ── Собственная подписка компании (владелец/админ) ───────────────

    @action(detail=False, methods=['get'], url_path='my-subscription',
            permission_classes=[IsOwnerOrAdmin])
    def my_subscription(self, request):
        """
        GET /companies/my-subscription/ — собственная подписка владельца/админа.

        Компания берётся из request.user: указать чужую компанию невозможно
        (в URL нет pk). Отдаются только состояние подписки и история её
        изменений — никаких бизнес- и финансовых данных компании.
        """
        company = request.user.company
        now = timezone.now()
        days_left = None
        if company.subscription_end is not None:
            days_left = max((company.subscription_end - now).days, 0)

        from apps.messaging.models import Notification
        renewal_pending = Notification.objects.filter(
            company_id=company.id,
            type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
            is_read=False,
        ).exists()

        changes = (
            SubscriptionChange.objects
            .filter(company=company)
            .select_related('actor')
            [:50]
        )
        return Response({
            'company_name': company.name,
            'plan_id': company.plan_id,
            'plan_name': company.plan.name if company.plan else None,
            'is_trial': company.is_trial,
            'grace_period_days': company.grace_period_days,
            'subscription_status': company.effective_subscription_status,
            'subscription_status_display': dict(Company.SubscriptionStatus.choices).get(
                company.effective_subscription_status, company.subscription_status,
            ),
            'subscription_start': company.subscription_start,
            'subscription_end': company.subscription_end,
            'grace_end': company.grace_end.isoformat() if company.grace_end else None,
            'days_left': days_left,
            'grace_days_left': company.subscription_grace_days_left,
            'renewal_request_pending': renewal_pending,
            'history': [self._history_row(c) for c in changes],
        })

    @action(detail=False, methods=['post'], url_path='my-subscription/request-renewal',
            permission_classes=[IsOwnerOrAdmin])
    def my_subscription_request_renewal(self, request):
        """
        POST /companies/my-subscription/request-renewal/ — запросить продление.

        Создаёт уведомление всем суперадминам (колокольчик + push) о том,
        что владелец просит продлить подписку, и пишет запись в audit.
        Дедупликация: пока по компании есть непрочитанный запрос, повторный
        запрос не создаёт нового уведомления.
        """
        company = request.user.company
        from apps.accounts.push_service import send_push_to_user
        from apps.messaging.models import Notification
        from apps.messaging.services import notify

        if Notification.objects.filter(
            company_id=company.id,
            type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
            is_read=False,
        ).exists():
            return Response({
                'created': False,
                'detail': 'Запрос на продление уже отправлен администратору платформы.',
            })

        end_text = (
            company.subscription_end.strftime('%d.%m.%Y')
            if company.subscription_end else '—'
        )
        superadmins = list(User.objects.filter(
            role=User.Role.SUPERADMIN, is_active=True,
        ))
        notify(
            superadmins,
            Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
            company.name,
            f'{company.name} — {end_text}',
            company=company,
        )
        for admin in superadmins:
            send_push_to_user(
                admin,
                company.name,
                f'Запрос на продление подписки — {end_text}',
                data={'url': '/#/companies'},
            )
        write_audit_log(
            action=AuditLog.Action.SUBSCRIPTION_RENEWAL_REQUESTED,
            actor=request.user,
            target=company,
            company=company,
            changes={'request': {'type': 'subscription_renewal'}},
            metadata={'end': end_text},
            request=request,
        )
        return Response({
            'created': True,
            'detail': 'Запрос на продление отправлен администратору платформы.',
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def audit(self, request, pk=None):
        """
        GET /companies/{id}/audit/ — недавние действия по компании.

        Супер-админ видит историю действий (кто, когда, что делал), но не
        бизнес-данные компании — только операции платформенного уровня.
        """
        company = self.get_object()
        logs = AuditLog.objects.filter(company=company).order_by('-created_at')[:50]
        return Response([{
            'id': log.id,
            'action': log.action,
            'actor': log.actor_username or 'system',
            'object_repr': log.object_repr,
            'created_at': log.created_at.isoformat() if log.created_at else None,
        } for log in logs])
