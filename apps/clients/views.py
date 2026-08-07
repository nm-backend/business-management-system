"""
Views for clients API.

Клиенты доступны владельцу и администратору (работник клиентов не видит).
Оплаты - только владельцу; создание оплаты обновляет заказ и долг клиента.
"""
from django.db.models import Exists, OuterRef
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
            return [IsCompanyMember(), IsOwnerOrAdminOrManager()]
        return [IsCompanyMember(), IsOwnerOrAdmin()]

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    # SearchFilter убираем: поиск по имени должен понимать транслит
    # («Gulnora» -> «Гулнора»). Для этого строим OR-фильтр по вариантам
    # запроса сами (apps/core/translit.py).
    filterset_fields = ['is_archived']
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
        search = self.request.query_params.get('search')
        if search:
            from apps.core.translit import translit_search_qs
            queryset = translit_search_qs(queryset, search, ['name', 'phone', 'comment'])
        return queryset

    def get_serializer_class(self):
        if getattr(self, 'swagger_fake_view', False) or self.request.user.is_owner:
            return ClientOwnerSerializer
        return ClientAdminSerializer

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
        # Клиент с долгом исчезал из активного учёта: архивные клиенты
        # исключаются из отчётов, и долг «пропадал» без следа.
        if (client.debt or 0) > 0:
            raise DRFValidationError({
                'detail': 'У клиента есть долг — архивировать нельзя. '
                          'Сначала закройте долг оплатой.',
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
            'Касса ўзгариши',
            f'{payment.client.name}: +{payment.amount}',
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
