"""
Views for clients API.

Клиенты доступны владельцу и администратору (работник клиентов не видит).
Оплаты - только владельцу; создание оплаты обновляет заказ и долг клиента.
"""
from rest_framework import filters, viewsets
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend

from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from apps.messaging.models import Notification
from apps.messaging.services import notify
from apps.core.permissions import IsCompanyMember
from core.permissions import IsOwner, IsOwnerOrAdmin
from .models import Client, Payment
from .serializers import ClientAdminSerializer, ClientOwnerSerializer, PaymentSerializer


class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]  # Работник клиентов не видит
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'phone', 'comment']
    filterset_fields = ['is_archived']
    ordering_fields = ['name', 'created_at']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Client.objects.none()
        return Client.objects.filter(company=self.request.user.company_id)

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


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    serializer_class = PaymentSerializer
    permission_classes = [IsCompanyMember, IsOwner]  # Суммы оплат видит только владелец
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['client', 'order', 'payment_method']
    ordering_fields = ['payment_date', 'amount']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Payment.objects.none()
        return Payment.objects.filter(
            company=self.request.user.company_id,
        ).select_related('client', 'order', 'received_by')

    def perform_create(self, serializer):
        # Оплату можно завести только на клиента своей компании.
        company = self.request.user.company
        client = serializer.validated_data.get('client')
        if client and client.company_id != company.id:
            raise PermissionDenied('Client must belong to your company')
        payment = serializer.save(received_by=self.request.user, company=company)
        if payment.order:
            order = payment.order
            order.paid_amount = (order.paid_amount or 0) + payment.amount
            order.save(update_fields=['paid_amount'])
            order.update_payment_status()
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
