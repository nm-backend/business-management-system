"""
Views for finance API.

Этот модуль содержит API views для управления финансами.
Все финансовые данные доступны только владельцу (owner).
"""
from decimal import Decimal

from django.db.models import Sum
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from apps.accounts.models import User
from apps.core.permissions import IsCompanyMember, FinancialDataPermission
from apps.core.validators import parse_date_param, parse_int_param
from apps.production.models import WorkRecord
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
        from apps.audit.models import AuditLog
        from apps.audit.services import write_audit_log
        from apps.messaging.models import Notification
        from apps.messaging.services import notify

        expense = serializer.save(created_by=self.request.user, company=self.request.user.company)
        notify(
            self.request.user,
            Notification.NotificationType.NEW_EXPENSE,
            'Янги харажат',
            f'{expense.get_category_display()}: {expense.amount}',
        )
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=expense,
            request=self.request,
        )

    def perform_update(self, serializer):
        from apps.audit.models import AuditLog
        from apps.audit.services import collect_model_changes, write_audit_log

        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        expense = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=expense,
                changes=changes,
                request=self.request,
            )

    def perform_destroy(self, instance):
        from apps.audit.models import AuditLog
        from apps.audit.services import write_audit_log

        write_audit_log(
            action=AuditLog.Action.DELETE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )
        instance.delete()


class LaborRateViewSet(CompanyScopedViewSet):
    """
    ViewSet для управления ставками оплаты труда.

    Доступен только владельцу (owner).
    """
    queryset = LaborRate.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember, FinancialDataPermission]
    # Форма «Ишни якунлаш» подтягивает ставки выбранного товара, чтобы
    # показать работнику список операций.
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['product']

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
        rate = serializer.save(company=self.request.user.company)
        from apps.audit.models import AuditLog
        from apps.audit.services import write_audit_log
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=rate,
            request=self.request,
        )

    def perform_update(self, serializer):
        # Без этой проверки PATCH мог перепривязать ставку к product ЧУЖОЙ
        # компании (IDOR-запись + утечка чужого product_name в ответе).
        product = serializer.validated_data.get('product')
        if product and product.company_id != self.request.user.company_id:
            raise PermissionDenied('Product must belong to your company')
        from apps.audit.models import AuditLog
        from apps.audit.services import collect_model_changes, write_audit_log
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        rate = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=rate,
                changes=changes,
                request=self.request,
            )

    def perform_destroy(self, instance):
        from apps.audit.models import AuditLog
        from apps.audit.services import write_audit_log
        write_audit_log(
            action=AuditLog.Action.DELETE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )
        instance.delete()


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

    @action(detail=False, methods=['get'])
    def settlements(self, request):
        """
        Расчёты с работниками: начислено, выплачено, остаток — по каждому.

        Вкладка «Оплата работников» показывала только сами выплаты. Работник,
        который выполнил подтверждённые работы, но денег ещё не получил, в ней
        не появлялся вовсе — владелец не видел, кому и сколько должен
        (замечание тестировщика: «работы произведены и оплачены, а тут пусто»).

        Формула та же, что у показателя «Долги работникам» в отчётах
        (apps/reports/views.py): начислено — сумма labor_cost подтверждённых
        работ, выплачено — сумма выплат. Иначе экраны противоречили бы друг
        другу.

        Два сгруппированных запроса вместо обхода работников по одному:
        список сотрудников растёт, а число запросов остаётся постоянным.
        """
        company_id = request.user.company_id

        earned = {
            row['worker_id']: row['total']
            for row in WorkRecord.objects
            .filter(company_id=company_id, status=WorkRecord.WorkStatus.CONFIRMED)
            .values('worker_id')
            .annotate(total=Sum('labor_cost'))
        }
        paid = {
            row['worker_id']: row['total']
            for row in WorkerPayment.objects
            .filter(company_id=company_id)
            .values('worker_id')
            .annotate(total=Sum('amount'))
        }

        worker_ids = set(earned) | set(paid)
        names = {
            user.id: (user.full_name or user.username)
            for user in User.objects.filter(id__in=worker_ids).only('id', 'full_name', 'username')
        }

        rows = []
        for worker_id in worker_ids:
            accrued = earned.get(worker_id) or Decimal('0')
            payout = paid.get(worker_id) or Decimal('0')
            rows.append({
                'worker': worker_id,
                'worker_name': names.get(worker_id, ''),
                'accrued': accrued,
                'paid': payout,
                'balance': accrued - payout,
            })
        rows.sort(key=lambda row: (-row['balance'], row['worker_name']))

        return Response({
            'results': rows,
            'total_accrued': sum((row['accrued'] for row in rows), Decimal('0')),
            'total_paid': sum((row['paid'] for row in rows), Decimal('0')),
            'total_balance': sum((row['balance'] for row in rows), Decimal('0')),
        })

    def perform_create(self, serializer):
        worker = serializer.validated_data.get('worker')
        if worker and worker.company_id != self.request.user.company_id:
            raise PermissionDenied('Worker must belong to your company')
        payment = serializer.save(created_by=self.request.user, company=self.request.user.company)
        from apps.audit.models import AuditLog
        from apps.audit.services import write_audit_log
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=payment,
            request=self.request,
        )

    def perform_update(self, serializer):
        # Без этой проверки PATCH мог перепривязать выплату к worker ЧУЖОЙ
        # компании (IDOR-запись + утечка чужого worker_name; чужой работник
        # начинал видеть выплату в своих my_earnings).
        worker = serializer.validated_data.get('worker')
        if worker and worker.company_id != self.request.user.company_id:
            raise PermissionDenied('Worker must belong to your company')
        from apps.audit.models import AuditLog
        from apps.audit.services import collect_model_changes, write_audit_log
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        payment = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=payment,
                changes=changes,
                request=self.request,
            )

    def perform_destroy(self, instance):
        from apps.audit.models import AuditLog
        from apps.audit.services import write_audit_log
        write_audit_log(
            action=AuditLog.Action.DELETE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )
        instance.delete()
