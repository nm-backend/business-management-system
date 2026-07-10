"""
Views for finance API.

Этот модуль содержит API views для управления финансами.
Все финансовые данные доступны только владельцу (owner).
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.core.permissions import IsOwner, FinancialDataPermission
from .models import Expense, LaborRate, WorkerPayment
from .serializers import (
    ExpenseSerializer, ExpenseCreateSerializer,
    LaborRateSerializer, LaborRateCreateSerializer,
    WorkerPaymentSerializer, WorkerPaymentCreateSerializer
)


class ExpenseViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления расходами.

    Доступен только владельцу (owner).
    """
    permission_classes = [IsAuthenticated, FinancialDataPermission]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от действия.
        """
        return ExpenseSerializer

    def create(self, request, *args, **kwargs):
        """Создает расход и возвращает полные данные с id."""
        input_serializer = ExpenseCreateSerializer(data=request.data, context={'request': request})
        input_serializer.is_valid(raise_exception=True)
        expense = input_serializer.save()
        output_serializer = ExpenseSerializer(expense)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

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


class LaborRateViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления ставками оплаты труда.

    Доступен только владельцу (owner).
    """
    permission_classes = [IsAuthenticated, FinancialDataPermission]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от действия.
        """
        return LaborRateSerializer

    def create(self, request, *args, **kwargs):
        """Создает ставку и возвращает полные данные с id."""
        input_serializer = LaborRateCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        labor_rate = input_serializer.save()
        output_serializer = LaborRateSerializer(labor_rate)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def get_queryset(self):
        """
        Возвращает queryset ставок оплаты.
        """
        return LaborRate.objects.select_related('product')


class WorkerPaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления выплатами работникам.

    Доступен только владельцу (owner).
    """
    permission_classes = [IsAuthenticated, FinancialDataPermission]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от действия.
        """
        return WorkerPaymentSerializer

    def create(self, request, *args, **kwargs):
        """Создает выплату и возвращает полные данные с id."""
        input_serializer = WorkerPaymentCreateSerializer(data=request.data, context={'request': request})
        input_serializer.is_valid(raise_exception=True)
        payment = input_serializer.save()
        output_serializer = WorkerPaymentSerializer(payment)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

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
