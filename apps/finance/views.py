"""
Views for finance API.

Этот модуль содержит API views для управления финансами.
Все финансовые данные доступны только владельцу (owner).
"""
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.core.permissions import FinancialDataPermission
from apps.core.viewsets import ActionSerializerMixin
from .models import Expense, LaborRate, WorkerPayment
from .serializers import (
    ExpenseSerializer, ExpenseCreateSerializer,
    LaborRateSerializer, LaborRateCreateSerializer,
    WorkerPaymentSerializer, WorkerPaymentCreateSerializer
)


class ExpenseViewSet(ActionSerializerMixin, viewsets.ModelViewSet):
    """
    ViewSet для управления расходами.

    Доступен только владельцу (owner).
    """
    permission_classes = [IsAuthenticated, FinancialDataPermission]
    serializer_class = ExpenseSerializer
    serializer_action_classes = {'create': ExpenseCreateSerializer}

    def get_queryset(self):
        """
        Возвращает queryset расходов.

        Фильтрация по категории и дате.
        """
        queryset = Expense.objects.select_related('created_by')
        category = self.request.query_params.get('category')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if category:
            queryset = queryset.filter(category=category)
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)

        return queryset


class LaborRateViewSet(ActionSerializerMixin, viewsets.ModelViewSet):
    """
    ViewSet для управления ставками оплаты труда.

    Доступен только владельцу (owner).
    """
    permission_classes = [IsAuthenticated, FinancialDataPermission]
    serializer_class = LaborRateSerializer
    serializer_action_classes = {'create': LaborRateCreateSerializer}

    def get_queryset(self):
        """
        Возвращает queryset ставок оплаты.
        """
        return LaborRate.objects.select_related('product')


class WorkerPaymentViewSet(ActionSerializerMixin, viewsets.ModelViewSet):
    """
    ViewSet для управления выплатами работникам.

    Доступен только владельцу (owner).
    """
    permission_classes = [IsAuthenticated, FinancialDataPermission]
    serializer_class = WorkerPaymentSerializer
    serializer_action_classes = {'create': WorkerPaymentCreateSerializer}

    def get_queryset(self):
        """
        Возвращает queryset выплат.

        Фильтрация по работнику и дате.
        """
        queryset = WorkerPayment.objects.select_related('worker', 'created_by')
        worker_id = self.request.query_params.get('worker')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if worker_id:
            queryset = queryset.filter(worker_id=worker_id)
        if date_from:
            queryset = queryset.filter(payment_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(payment_date__lte=date_to)

        return queryset
