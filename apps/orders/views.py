"""
Views for orders API.

Этот модуль содержит API views для управления заказами
с защитой финансовых данных для non-owner пользователей.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.core.viewsets import ActionSerializerMixin, OwnerSerializerMixin
from .models import Order, OrderStatus, PaymentStatus
from .serializers import (
    OrderSerializer, OrderLimitedSerializer, OrderCreateSerializer
)


class OrderViewSet(
    ActionSerializerMixin,
    OwnerSerializerMixin,
    viewsets.ModelViewSet,
):
    """
    ViewSet для управления заказами.

    Разные сериализаторы для разных ролей:
    - Owner: полный доступ с финансовыми данными
    - Admin/Worker: ограниченный доступ без финансовых данных
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OrderLimitedSerializer
    owner_serializer_class = OrderSerializer
    serializer_action_classes = {'create': OrderCreateSerializer}

    def get_queryset(self):
        """
        Возвращает queryset заказов.

        Фильтрация по статусу, клиенту, работнику.
        """
        queryset = Order.objects.select_related('client', 'worker', 'product')
        status_filter = self.request.query_params.get('status')
        client_id = self.request.query_params.get('client')
        worker_id = self.request.query_params.get('worker')

        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if client_id:
            queryset = queryset.filter(client_id=client_id)
        if worker_id:
            queryset = queryset.filter(worker_id=worker_id)

        return queryset

    @action(detail=True, methods=['post'])
    def assign_worker(self, request, pk=None):
        """
        Назначает работника на заказ.

        POST /api/v1/orders/{id}/assign_worker/
        Body: {"worker_id": 1}
        """
        order = self.get_object()
        if not (request.user.is_owner or request.user.is_admin):
            return Response(
                {'detail': 'Only owner or admin can assign workers'},
                status=status.HTTP_403_FORBIDDEN
            )

        worker_id = request.data.get('worker_id')
        if not worker_id:
            return Response(
                {'detail': 'worker_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from apps.accounts.models import User
        try:
            worker = User.objects.get(id=worker_id, role=User.Role.WORKER)
        except User.DoesNotExist:
            return Response(
                {'detail': 'Worker not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        order.worker = worker
        order.status = OrderStatus.SENT_TO_WORKER
        order.save()

        serializer = self.get_serializer(order)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def update_payment(self, request, pk=None):
        """
        Обновляет статус оплаты заказа.

        POST /api/v1/orders/{id}/update_payment/
        Body: {"payment_status": "paid", "amount": 1000}
        """
        order = self.get_object()
        if not request.user.is_owner:
            return Response(
                {'detail': 'Only owner can update payment'},
                status=status.HTTP_403_FORBIDDEN
            )

        payment_status = request.data.get('payment_status')
        amount = request.data.get('amount', 0)

        if payment_status:
            order.payment_status = payment_status

        if amount:
            order.paid_amount = amount
            if order.paid_amount >= order.total_amount:
                order.payment_status = PaymentStatus.PAID
            elif order.paid_amount > 0:
                order.payment_status = PaymentStatus.PARTIAL

        order.save()
        serializer = self.get_serializer(order)
        return Response(serializer.data)
