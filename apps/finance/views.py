"""
Views for finance API.

Этот модуль содержит API views для управления финансами.
Все финансовые данные доступны только владельцу (owner).
"""
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from apps.core.permissions import IsCompanyMember, FinancialDataPermission
from apps.core.validators import parse_date_param, parse_int_param
from .models import Expense, LaborRate, WorkerPayment
from .serializers import (
    ExpenseSerializer, ExpenseCreateSerializer,
    LaborRateSerializer, LaborRateCreateSerializer,
    WorkerPaymentSerializer, WorkerPaymentCreateSerializer
)
from apps.core.views import CompanyScopedViewSet


class ExpenseViewSet(CompanyScopedViewSet):
    """
    ViewSet для управления расходами.

    Доступен только владельцу (owner).
    """
    queryset = Expense.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember, FinancialDataPermission]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от действия.
        """
        if self.action == 'create':
            return ExpenseCreateSerializer
        return ExpenseSerializer

    def get_queryset(self):
        """
        Возвращает queryset расходов.

        Фильтрация по категории и дате.
        """
        if getattr(self, 'swagger_fake_view', False):
            return Expense.objects.none()
        queryset = super().get_queryset().select_related('created_by')
        category = self.request.query_params.get('category')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if category:
            queryset = queryset.filter(category=category)
        if date_from:
            queryset = queryset.filter(date__gte=parse_date_param(date_from, 'date_from'))
        if date_to:
            queryset = queryset.filter(date__lte=parse_date_param(date_to, 'date_to'))

        return queryset

    def perform_create(self, serializer):
        from apps.messaging.models import Notification
        from apps.messaging.services import notify

        expense = serializer.save(created_by=self.request.user, company=self.request.user.company)
        notify(
            self.request.user,
            Notification.NotificationType.NEW_EXPENSE,
            'Янги харажат',
            f'{expense.get_category_display()}: {expense.amount}',
        )


class LaborRateViewSet(CompanyScopedViewSet):
    """
    ViewSet для управления ставками оплаты труда.

    Доступен только владельцу (owner).
    """
    queryset = LaborRate.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember, FinancialDataPermission]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от действия.
        """
        if self.action == 'create':
            return LaborRateCreateSerializer
        return LaborRateSerializer

    def get_queryset(self):
        """
        Возвращает queryset ставок оплаты.
        """
        if getattr(self, 'swagger_fake_view', False):
            return LaborRate.objects.none()
        return super().get_queryset().select_related('product')

    def perform_create(self, serializer):
        product = serializer.validated_data.get('product')
        if product and product.company_id != self.request.user.company_id:
            raise PermissionDenied('Product must belong to your company')
        serializer.save(company=self.request.user.company)

    def perform_update(self, serializer):
        # Без этой проверки PATCH мог перепривязать ставку к product ЧУЖОЙ
        # компании (IDOR-запись + утечка чужого product_name в ответе).
        product = serializer.validated_data.get('product')
        if product and product.company_id != self.request.user.company_id:
            raise PermissionDenied('Product must belong to your company')
        serializer.save()


class WorkerPaymentViewSet(CompanyScopedViewSet):
    """
    ViewSet для управления выплатами работникам.

    Доступен только владельцу (owner).
    """
    queryset = WorkerPayment.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember, FinancialDataPermission]

    def get_serializer_class(self):
        """
        Возвращает сериализатор в зависимости от действия.
        """
        if self.action == 'create':
            return WorkerPaymentCreateSerializer
        return WorkerPaymentSerializer

    def get_queryset(self):
        """
        Возвращает queryset выплат.

        Фильтрация по работнику и дате.
        """
        if getattr(self, 'swagger_fake_view', False):
            return WorkerPayment.objects.none()
        queryset = super().get_queryset().select_related('worker', 'created_by')
        worker_id = self.request.query_params.get('worker')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if worker_id:
            # Нечисловое значение раньше доходило до ORM и давало 500.
            queryset = queryset.filter(worker_id=parse_int_param(worker_id, 'worker'))
        if date_from:
            queryset = queryset.filter(payment_date__gte=parse_date_param(date_from, 'date_from'))
        if date_to:
            queryset = queryset.filter(payment_date__lte=parse_date_param(date_to, 'date_to'))

        return queryset

    def perform_create(self, serializer):
        worker = serializer.validated_data.get('worker')
        if worker and worker.company_id != self.request.user.company_id:
            raise PermissionDenied('Worker must belong to your company')
        serializer.save(created_by=self.request.user, company=self.request.user.company)

    def perform_update(self, serializer):
        # Без этой проверки PATCH мог перепривязать выплату к worker ЧУЖОЙ
        # компании (IDOR-запись + утечка чужого worker_name; чужой работник
        # начинал видеть выплату в своих my_earnings).
        worker = serializer.validated_data.get('worker')
        if worker and worker.company_id != self.request.user.company_id:
            raise PermissionDenied('Worker must belong to your company')
        serializer.save()
