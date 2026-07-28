"""
Views for clients API.

Клиенты доступны владельцу и администратору (работник клиентов не видит).
Оплаты - только владельцу; создание оплаты обновляет заказ и долг клиента.
"""
from django.db.models import Exists, OuterRef
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from apps.messaging.models import Notification
from apps.messaging.services import notify
from apps.orders.models import Order
from apps.core.permissions import IsCompanyMember
from core.permissions import IsOwner, IsOwnerOrAdmin
from .models import ACTIVE_ORDER_STATUSES, Client, Payment
from .serializers import ClientAdminSerializer, ClientOwnerSerializer, PaymentSerializer
from apps.core.views import CompanyScopedViewSet


class ClientViewSet(CompanyScopedViewSet):
    queryset = Client.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]  # Работник клиентов не видит
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'phone', 'comment']
    filterset_fields = ['is_archived']
    ordering_fields = ['name', 'created_at']

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
        return super().get_queryset().prefetch_related('payments').annotate(
            active_orders_exists=Exists(active_orders),
        )

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
        instance.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )

    # Вкладка «Архив» была только на чтение: положить туда клиента или вернуть
    # его из интерфейса было нечем, наполнялась она лишь автоматическим
    # auto_archive() после оплаты. Идём через archive()/restore(), а не через
    # PATCH is_archived, иначе archived_at остаётся пустым.
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        client = self.get_object()
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

    def perform_create(self, serializer):
        # Оплату можно завести только на клиента своей компании.
        company = self.request.user.company
        client = serializer.validated_data.get('client')
        order = serializer.validated_data.get('order')
        if client and client.company_id != company.id:
            raise PermissionDenied('Client must belong to your company')
        # Заказ (если указан) — тоже строго своей компании и именно этого клиента.
        # Иначе владелец компании A мог передать order компании B и изменить его
        # paid_amount/payment_status (межтенантная запись в чужие финансы).
        if order is not None:
            if order.company_id != company.id:
                raise PermissionDenied('Order must belong to your company')
            if client is not None and order.client_id != client.id:
                raise PermissionDenied('Order does not belong to this client')
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
