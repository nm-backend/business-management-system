"""
Views for orders API.

Заказы создают владелец и администратор. Работник видит только заказы,
назначенные ему. Owner дополнительно видит суммы заказа.
"""
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from apps.messaging.models import Notification
from apps.messaging.services import notify_staff
from apps.core.permissions import IsCompanyMember
from core.permissions import IsOwnerOrAdmin
from .models import Order
from .serializers import OrderSerializer, OrderOwnerSerializer


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['custom_product_name', 'comment', 'client__name']
    filterset_fields = ['status', 'payment_status', 'worker', 'client']
    ordering_fields = ['created_at', 'deadline']

    def get_serializer_class(self):
        if getattr(self, 'swagger_fake_view', False) or self.request.user.is_owner:
            return OrderOwnerSerializer
        return OrderSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Order.objects.none()
        user = self.request.user
        # Рецепты продукта нужны для расчёта нехватки материалов в сериализаторе —
        # без prefetch это был отдельный запрос на каждый заказ (N+1).
        queryset = (
            Order.objects.filter(company=user.company_id)
            .select_related('client', 'product', 'worker')
            .prefetch_related('product__recipes__items__material')
        )
        if user.is_owner or user.is_admin:
            return queryset
        return queryset.filter(worker=user)

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy',
                           'deliver', 'cancel'):
            return [IsCompanyMember(), IsOwnerOrAdmin()]
        return [IsCompanyMember()]

    def perform_create(self, serializer):
        # Заказ можно создать только на клиента/товар своей компании.
        company = self.request.user.company
        client = serializer.validated_data.get('client')
        product = serializer.validated_data.get('product')
        if client and client.company_id != company.id:
            raise PermissionDenied('Client must belong to your company')
        if product and product.company_id != company.id:
            raise PermissionDenied('Product must belong to your company')
        order = serializer.save(company=company)
        order.client.recalculate_financials()
        notify_staff(
            company,
            Notification.NotificationType.NEW_ORDER,
            'Янги буюртма',
            f'#{order.id} {order.client.name}: '
            f'{order.product.name if order.product else order.custom_product_name} x {order.quantity}',
            order=order,
        )
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=order,
            request=self.request,
        )

    def perform_update(self, serializer):
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        order = serializer.save()
        if 'total_amount' in changes:
            order.update_payment_status()
        order.client.recalculate_financials()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=order,
                changes=changes,
                request=self.request,
            )

    def perform_destroy(self, instance):
        """Удаление запрещено - заказ отменяется и архивируется."""
        instance.status = Order.Status.CANCELLED
        instance.save(update_fields=['status'])
        instance.archive()
        instance.client.recalculate_financials()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )

    @action(detail=True, methods=['post'])
    def deliver(self, request, pk=None):
        """Выдаёт заказ клиенту; при полной оплате клиент уходит в архив."""
        order = self.get_object()
        if order.status == Order.Status.CANCELLED:
            return Response({'detail': 'Order is cancelled'}, status=status.HTTP_400_BAD_REQUEST)
        order.status = Order.Status.DELIVERED
        order.save(update_fields=['status'])
        order.client.recalculate_financials()
        order.client.auto_archive()
        if order.payment_status != Order.PaymentStatus.PAID:
            # Без сумм: администратор видит только факт неоплаты.
            notify_staff(
                order.company_id,
                Notification.NotificationType.UNPAID_CLIENT,
                'Мижоз тўлов қилмади',
                f'Буюртма #{order.id}, мижоз: {order.client.name}',
                order=order,
            )
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=order,
            changes={'status': {'old': 'ready', 'new': 'delivered'}},
            request=request,
        )
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Отменяет заказ."""
        order = self.get_object()
        order.status = Order.Status.CANCELLED
        order.save(update_fields=['status'])
        order.client.recalculate_financials()
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=order,
            changes={'status': {'new': 'cancelled'}},
            request=request,
        )
        return Response(self.get_serializer(order).data)
