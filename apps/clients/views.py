"""
Views for clients API.

Клиенты доступны владельцу и администратору (работник клиентов не видит).
Оплаты - только владельцу; создание оплаты обновляет заказ и долг клиента.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import (DecimalField, Exists, ExpressionWrapper, F, Q,
                              OuterRef, Subquery, Sum, Value)
from django.utils import timezone
from django.db.models.functions import Coalesce
from django.db import transaction
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from apps.messaging.models import Notification
from apps.messaging.services import notify
from apps.orders.models import Order
from rest_framework.permissions import SAFE_METHODS

from apps.core.permissions import IsCompanyMember
from core.permissions import IsOwner, IsOwnerOrAdmin, IsOwnerOrAdminOrManager
from .models import ACTIVE_ORDER_STATUSES, Client, Payment
from .serializers import ClientAdminSerializer, ClientOwnerSerializer, PaymentSerializer
from apps.core.views import CompanyScopedViewSet


class ClientViewSet(CompanyScopedViewSet):
    queryset = Client.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]  # Работник клиентов не видит

    def get_permissions(self):
        """
        Менеджер видит клиентов (только чтение), но не управляет ими.

        Чтение (list/retrieve): owner/admin/manager. Изменения (create/update/
        archive/restore): только owner/admin. Работник клиентов не видит вовсе.
        """
        if self.request.method in SAFE_METHODS:
            # Сводка по долгам — финансовые суммы, только владельцу.
            # (permission_classes у @action не применяются: get_permissions
            # перекрывает их целиком, поэтому проверяем action явно.)
            if getattr(self, 'action', None) == 'debt_summary':
                return [IsCompanyMember(), IsOwner()]
            return [IsCompanyMember(), IsOwnerOrAdminOrManager()]
        return [IsCompanyMember(), IsOwnerOrAdmin()]

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    # SearchFilter убираем: поиск по имени должен понимать транслит
    # («Gulnora» -> «Гулнора»). Для этого строим OR-фильтр по вариантам
    # запроса сами (apps/core/translit.py).
    # Тип и ответственный — рабочие фильтры карточки клиента из макета.
    filterset_fields = ['is_archived', 'client_type', 'responsible_employee']
    ordering_fields = ['name', 'created_at', 'debt', 'total_orders_amount']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Client.objects.none()
        # payments сериализуются вложенно -> без prefetch был запрос на каждого клиента.
        # active_orders_exists: раньше свойство has_active_orders делало .exists()
        # по заказам на КАЖДОГО клиента (N+1). Считаем одним подзапросом Exists.
        # Имя annotation отличается от property has_active_orders (иначе property
        # затеняет его на инстансе), сериализатор читает именно annotation.
        active_orders = Order.objects.filter(
            client=OuterRef('pk'),
            status__in=ACTIVE_ORDER_STATUSES,
            is_archived=False,
        )
        queryset = super().get_queryset().prefetch_related('payments').annotate(
            active_orders_exists=Exists(active_orders),
        )
        # Прибыль по клиенту — только владельцу и только по ВЫДАННЫМ заказам:
        # себестоимость считается по снимку cost_price на момент выдачи (как
        # COGS в отчётах), невыданные/отменённые заказы прибыли не дают.
        # Два коррелированных подзапроса + вычитание на уровне SQL: один
        # запрос на весь список вместо per-client aggregate (N+1). Админу
        # аннотация не нужна: поле живёт только в ClientOwnerSerializer.
        if self.request.user.is_owner:
            delivered = Order.objects.filter(
                client=OuterRef('pk'),
                status=Order.Status.DELIVERED,
                is_archived=False,
            )
            revenue_sq = delivered.values('client').annotate(
                s=Sum('total_amount'),
            ).values('s')[:1]
            cogs_sq = delivered.values('client').annotate(
                s=Sum(ExpressionWrapper(
                    F('quantity') * F('cost_price'),
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                )),
            ).values('s')[:1]
            queryset = queryset.annotate(
                _client_revenue=Subquery(
                    revenue_sq,
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                ),
                _client_cogs=Subquery(
                    cogs_sq,
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                ),
            ).annotate(
                profit=Coalesce(
                    F('_client_revenue') - F('_client_cogs'),
                    Value(Decimal('0'), output_field=DecimalField(max_digits=15, decimal_places=2)),
                ),
            )
        # Вкладки списка из макета «Мижозлар»: «Қарзи бор» и «Фаол».
        # Это БУЛЕВЫ фильтры, а не суммы, поэтому доступны и администратору:
        # факт долга он видеть должен (красная карточка), сумму — нет.
        has_debt = self.request.query_params.get('has_debt')
        if has_debt is not None:
            wants_debt = has_debt.lower() == 'true'
            queryset = queryset.filter(debt__gt=0) if wants_debt else queryset.filter(debt__lte=0)

        # «Фаол» по правилу ТЗ: есть долг ИЛИ есть незавершённый заказ.
        is_active_client = self.request.query_params.get('is_active_client')
        if is_active_client is not None:
            condition = Q(debt__gt=0) | Q(active_orders_exists=True)
            queryset = (
                queryset.filter(condition)
                if is_active_client.lower() == 'true'
                else queryset.exclude(condition)
            )

        # Вкладка «Янги» из макета «Мижозлар»: клиенты, заведённые за
        # последние 7 дней. Критерий на сервере — иначе вторая страница
        # списка «новых» содержала бы кого попало.
        is_new = self.request.query_params.get('is_new')
        if is_new is not None and is_new.lower() == 'true':
            queryset = queryset.filter(
                created_at__gte=timezone.now() - timedelta(days=7),
            )

        search = self.request.query_params.get('search')
        if search:
            from apps.core.translit import translit_search_qs
            queryset = translit_search_qs(queryset, search, ['name', 'phone', 'comment'])
        return queryset

    def get_serializer_class(self):
        if getattr(self, 'swagger_fake_view', False) or self.request.user.is_owner:
            return ClientOwnerSerializer
        return ClientAdminSerializer

    @action(detail=False, methods=['get'], permission_classes=[IsCompanyMember, IsOwner])
    def debt_summary(self, request):
        """
        GET /api/v1/clients/clients/debt_summary/ — сводка по долгам (владелец).

        Панель «Қарз назорати» раньше считалась на фронте: он брал ПЕРВУЮ
        страницу списка клиентов (20 из N) и складывал c.debt в JS. Debt
        приходит из DRF строкой, поэтому сложение превращалось в конкатенацию
        («0» + «100.00» + «500.00») и на экране выводилось NaN, а счётчик
        учитывал только первую страницу. Считаем в SQL по всем неархивным
        клиентам компании.
        """
        qs = Client.objects.filter(company_id=request.user.company_id, is_archived=False)
        debtors = qs.filter(debt__gt=0)
        zero = Value(Decimal('0'), output_field=DecimalField(max_digits=15, decimal_places=2))
        totals = debtors.aggregate(total=Coalesce(Sum('debt'), zero))
        top = list(
            debtors.order_by('-debt')
            .values('id', 'name', 'phone', 'debt')[:10]
        )
        # Бакеты просрочки из макета «Қарз назорати»: «Муддати ўтган» с
        # подписями «7/10/15 кундан ошган» против «Муддати бор». Возраст долга
        # считаем по сроку ОПЛАТЫ заказа (payment_due_date), а если он не
        # задан — по сроку изготовления, как было раньше.
        from apps.orders.models import Order

        unpaid_orders = (
            Order.objects.filter(
                company_id=request.user.company_id,
                is_archived=False,
                paid_amount__lt=F('total_amount'),
            )
            .exclude(status=Order.Status.CANCELLED)
            .select_related('client')
        )

        buckets = {'not_due': [], 'overdue_1_7': [], 'overdue_8_14': [], 'overdue_15_plus': []}
        overdue_total = Decimal('0')
        for order in unpaid_orders:
            days = order.payment_overdue_days
            debt = (order.total_amount or Decimal('0')) - (order.paid_amount or Decimal('0'))
            if days <= 0:
                buckets['not_due'].append((order, days, debt))
                continue
            overdue_total += debt
            if days >= 15:
                buckets['overdue_15_plus'].append((order, days, debt))
            elif days >= 8:
                buckets['overdue_8_14'].append((order, days, debt))
            else:
                buckets['overdue_1_7'].append((order, days, debt))

        def bucket_payload(rows):
            return {
                'count': len(rows),
                'total': sum((debt for _, _, debt in rows), Decimal('0')),
                'orders': [
                    {
                        'order': order.id,
                        'client': order.client_id,
                        'client_name': order.client.name,
                        'days_overdue': days,
                        'debt': debt,
                    }
                    # Самые старые долги первыми — с них и начинают работу.
                    for order, days, debt in sorted(rows, key=lambda r: -r[1])[:20]
                ],
            }

        return Response({
            'debtors_count': debtors.count(),
            'total_debt': totals['total'],
            'no_debt_count': qs.filter(debt__lte=0).count(),
            'top_debtors': top,
            'overdue_total': overdue_total,
            'buckets': {name: bucket_payload(rows) for name, rows in buckets.items()},
        })

    def perform_create(self, serializer):
        client = serializer.save(company=self.request.user.company)
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=client,
            request=self.request,
        )

    def perform_update(self, serializer):
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        client = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=client,
                changes=changes,
                request=self.request,
            )

    def perform_destroy(self, instance):
        """Удаление запрещено - клиент архивируется."""
        self._assert_no_debt(instance)
        instance.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )

    def _assert_no_debt(self, client):
        """
        Условия архивации из ТЗ: заказ завершён, товар выдан, долг закрыт.

        Проверка долга была и раньше (архивные клиенты выпадают из отчётов, и
        долг «пропадал» без следа), но незавершённый заказ архивации не мешал:
        клиент с товаром в производстве уезжал в архив, и заказ терялся из
        активного учёта.
        """
        from apps.orders.models import Order

        if (client.debt or 0) > 0:
            raise DRFValidationError({
                'detail': 'У клиента есть долг — архивировать нельзя. '
                          'Сначала закройте долг оплатой.',
            })
        unfinished = client.orders.exclude(
            status__in=(Order.Status.DELIVERED, Order.Status.CANCELLED),
        ).filter(is_archived=False)
        if unfinished.exists():
            raise DRFValidationError({
                'detail': 'У клиента есть незавершённые заказы — архивировать нельзя. '
                          'Сначала выдайте товар или отмените заказ.',
            })

    # Вкладка «Архив» была только на чтение: положить туда клиента или вернуть
    # его из интерфейса было нечем, наполнялась она лишь автоматическим
    # auto_archive() после оплаты. Идём через archive()/restore(), а не через
    # PATCH is_archived, иначе archived_at остаётся пустым.
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        client = self.get_object()
        self._assert_no_debt(client)
        client.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE,
            actor=request.user,
            target=client,
            request=request,
        )
        return Response(self.get_serializer(client).data)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        client = self.get_object()
        client.restore()
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=client,
            changes={'is_archived': [True, False]},
            request=request,
        )
        return Response(self.get_serializer(client).data)


class PaymentViewSet(CompanyScopedViewSet):
    queryset = Payment.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    serializer_class = PaymentSerializer
    permission_classes = [IsCompanyMember, IsOwner]  # Суммы оплат видит только владелец
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['client', 'order', 'payment_method']
    ordering_fields = ['payment_date', 'amount']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Payment.objects.none()
        return super().get_queryset().select_related('client', 'order', 'received_by')

    @transaction.atomic
    def perform_create(self, serializer):
        # Оплату можно завести только на клиента своей компании.
        # Транзакция оборачивает и создание Payment, и apply_payment_amount:
        # раньше при ошибке (переплата, оплата отменённого заказа) Payment
        # уже был сохранён — деньги записывались в кассу, а долг и paid_amount
        # не менялись («сирота»).
        company = self.request.user.company
        client = serializer.validated_data.get('client')
        order = serializer.validated_data.get('order')
        if client and client.company_id != company.id:
            raise PermissionDenied('Клиент должен принадлежать вашей компании')
        # Заказ (если указан) — тоже строго своей компании и именно этого клиента.
        # Иначе владелец компании A мог передать order компании B и изменить его
        # paid_amount/payment_status (межтенантная запись в чужие финансы).
        if order is not None:
            if order.company_id != company.id:
                raise PermissionDenied('Заказ должен принадлежать вашей компании')
            if client is not None and order.client_id != client.id:
                raise PermissionDenied('Заказ не принадлежит этому клиенту')
        payment = serializer.save(received_by=self.request.user, company=company)
        if payment.order:
            # Атомарно (select_for_update) — защита от потери обновления при
            # одновременных оплатах одного заказа.
            payment.order.apply_payment_amount(payment.amount)
        payment.client.recalculate_financials()
        payment.client.auto_archive()
        notify(
            self.request.user,
            Notification.NotificationType.CASH_CHANGE,
            title_key='notifications.cash_change',
            message_key='notifications.msg_cash_change',
            params={'client': payment.client.name, 'amount': str(payment.amount)},
            order=payment.order,
        )
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=payment,
            request=self.request,
        )

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed('PUT/PATCH', detail='Payments are immutable. Create a correcting payment instead.')

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Payment deletion is prohibited.')
