"""
Views for production API.

Задачи (Task) и работы (WorkRecord) с ролевым доступом:
- Owner/Admin: назначают задачи, подтверждают/отклоняют работы.
- Worker: видит только свои задачи и работы, принимает/отказывается,
  сдаёт работу на подтверждение, видит свой заработок.
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.mixins import CreateModelMixin

from apps.core.permissions import IsCompanyMember, IsOwnerOrAdmin
from apps.messaging.models import Notification
from apps.messaging.services import notify, notify_staff
from .models import RefusalReason, Task, TaskStatus, WorkRecord
from .serializers import (
    TaskSerializer, TaskCreateSerializer,
    WorkRecordSerializer, WorkRecordLimitedSerializer, WorkRecordCreateSerializer,
)
from . import services


class ReadAfterCreateMixin(CreateModelMixin):
    """Возвращает полное представление объекта (с id) после создания."""
    read_serializer_class = None

    def create(self, request, *args, **kwargs):
        write_serializer = self.get_serializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        self.perform_create(write_serializer)
        read_serializer = self.read_serializer_class(
            write_serializer.instance, context=self.get_serializer_context(),
        )
        headers = self.get_success_headers(read_serializer.data)
        return Response(read_serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class TaskViewSet(ReadAfterCreateMixin, viewsets.ModelViewSet):
    """Задачи работников: назначение, принятие, отказ."""
    queryset = Task.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember]
    read_serializer_class = TaskSerializer

    def get_permissions(self):
        # Конечный автомат задачи двигается ТОЛЬКО через действия
        # accept/refuse/cancel/confirm. Прямой update/destroy разрешён лишь
        # owner/admin — иначе работник PATCH'ем поставил бы своей задаче
        # status='confirmed' в обход confirm_work или переназначил бы её на
        # заказ другой компании (поле order на update раньше не проверялось).
        if self.action in ('update', 'partial_update'):
            return [IsCompanyMember(), IsOwnerOrAdmin()]
        return [IsCompanyMember()]

    def destroy(self, request, *args, **kwargs):
        # Задачи не удаляются — история назначений неизменна (ТЗ: только архив).
        raise MethodNotAllowed('DELETE')

    def get_serializer_class(self):
        if self.action == 'create':
            return TaskCreateSerializer
        return TaskSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Task.objects.none()
        queryset = Task.objects.filter(
            company=self.request.user.company_id,
        ).select_related('worker', 'assigned_by', 'order', 'order__client', 'order__product')
        if self.request.user.is_worker:
            queryset = queryset.filter(worker=self.request.user)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        # Работника/заказ нельзя взять из другой компании.
        worker = serializer.validated_data.get('worker')
        order = serializer.validated_data.get('order')
        if worker and worker.company_id != user.company_id:
            raise PermissionDenied('Worker must belong to your company')
        if order and order.company_id != user.company_id:
            raise PermissionDenied('Order must belong to your company')
        if user.is_worker:
            # Работник может создать только самостоятельную работу для себя.
            task = serializer.save(company=user.company, worker=user, assigned_by=user,
                                   is_self_assigned=True, status=TaskStatus.ACCEPTED)
        else:
            task = serializer.save(company=user.company, assigned_by=user)
            if task.order:
                task.order.worker = task.worker
                task.order.status = task.order.Status.SENT_TO_WORKER
                task.order.save(update_fields=['worker', 'status'])
            notify(
                task.worker,
                Notification.NotificationType.TASK_ASSIGNED,
                'Янги вазифа',
                f'Вазифа #{task.id}' + (f' (буюртма #{task.order_id})' if task.order_id else ''),
                order=task.order,
                task=task,
            )

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """Работник принимает задачу. POST /production/tasks/{id}/accept/"""
        task = self.get_object()
        if task.worker != request.user:
            return Response({'detail': 'You can only accept your own tasks'},
                            status=status.HTTP_403_FORBIDDEN)
        if task.status != TaskStatus.PENDING:
            return Response({'detail': 'Task is not pending'}, status=status.HTTP_400_BAD_REQUEST)
        task.accept()
        if task.assigned_by and task.assigned_by != request.user:
            notify(
                task.assigned_by,
                Notification.NotificationType.TASK_CHANGED,
                'Вазифа қабул қилинди',
                f'{request.user.full_name or request.user.username} вазифа #{task.id} ни қабул қилди',
                order=task.order, task=task,
            )
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=['post'])
    def refuse(self, request, pk=None):
        """Работник отказывается: {"reason": "no_time", "comment": "..."}."""
        task = self.get_object()
        if task.worker != request.user:
            return Response({'detail': 'You can only refuse your own tasks'},
                            status=status.HTTP_403_FORBIDDEN)
        reason = request.data.get('reason')
        if reason not in RefusalReason.values:
            return Response({'detail': 'reason is required',
                             'allowed': RefusalReason.values},
                            status=status.HTTP_400_BAD_REQUEST)
        task.refuse(reason, request.data.get('comment', ''))
        notify_staff(
            task.company_id,
            Notification.NotificationType.WORKER_REFUSED,
            'Ишчи рад этди',
            f'{request.user.full_name or request.user.username} вазифа #{task.id} дан бош тортди: '
            f'{RefusalReason(reason).label}',
            order=task.order, task=task,
        )
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Владелец/админ отменяет задачу."""
        if not (request.user.is_owner or request.user.is_admin):
            raise PermissionDenied('Only owner or admin can cancel tasks')
        task = self.get_object()
        task.status = TaskStatus.CANCELLED
        task.save(update_fields=['status'])
        notify(
            task.worker,
            Notification.NotificationType.TASK_CANCELLED,
            'Вазифа бекор қилинди',
            f'Вазифа #{task.id} бекор қилинди',
            order=task.order, task=task,
        )
        return Response(TaskSerializer(task).data)


class WorkRecordViewSet(ReadAfterCreateMixin, viewsets.ModelViewSet):
    """Работы: сдача на подтверждение, подтверждение (меняет склад), отклонение."""
    queryset = WorkRecord.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember]

    def get_permissions(self):
        # КРИТИЧНО: статус и оплата работы меняются ТОЛЬКО через confirm/reject
        # (owner/admin). Раньше WorkRecordViewSet был открытым ModelViewSet, и
        # работник мог PATCH'ем поставить своей записи status='confirmed' и любой
        # labor_cost, минуя confirm_work — без проверки склада, без списания
        # сырья и без audit (раздувая свой заработок). Прямой update разрешаем
        # лишь owner/admin, а чувствительные поля закрыты в сериализаторе.
        if self.action in ('update', 'partial_update'):
            return [IsCompanyMember(), IsOwnerOrAdmin()]
        return [IsCompanyMember()]

    def destroy(self, request, *args, **kwargs):
        # Записи о работе не удаляются: подтверждённая работа уже двигала склад
        # и начисление. Отмена — только через reject (ТЗ: удаление запрещено).
        raise MethodNotAllowed('DELETE')

    def get_serializer_class(self):
        if self.action == 'create':
            return WorkRecordCreateSerializer
        if getattr(self, 'swagger_fake_view', False):
            return WorkRecordSerializer
        user = self.request.user
        # Owner видит labor_cost везде; работник — только в своих записях
        # (queryset уже отфильтрован); администратор денег не видит.
        if user.is_owner or user.is_worker:
            return WorkRecordSerializer
        return WorkRecordLimitedSerializer

    @property
    def read_serializer_class(self):
        user = self.request.user
        if user.is_owner or user.is_worker:
            return WorkRecordSerializer
        return WorkRecordLimitedSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return WorkRecord.objects.none()
        queryset = WorkRecord.objects.filter(
            company=self.request.user.company_id,
        ).select_related('worker', 'product', 'confirmed_by', 'task')
        if self.request.user.is_worker:
            queryset = queryset.filter(worker=self.request.user)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        # Товар/задача должны быть из своей компании.
        product = serializer.validated_data.get('product')
        task = serializer.validated_data.get('task')
        worker = serializer.validated_data.get('worker')
        if product and product.company_id != user.company_id:
            raise PermissionDenied('Product must belong to your company')
        if task and task.company_id != user.company_id:
            raise PermissionDenied('Task must belong to your company')
        # Owner/admin не может записать работу на сотрудника чужой компании.
        if worker and worker.company_id != user.company_id:
            raise PermissionDenied('Worker must belong to your company')
        if user.is_worker:
            work = serializer.save(company=user.company, worker=user)
        else:
            work = serializer.save(company=user.company)
        notify_staff(
            work.company_id,
            Notification.NotificationType.WORK_AWAITING,
            'Иш тасдиқлашни кутмоқда',
            f'{work.worker.full_name or work.worker.username}: '
            f'{work.product.name if work.product else ""} x {work.quantity}',
            task=work.task,
        )
        if work.task and work.task.worker_id == work.worker_id:
            work.task.complete()

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """
        Подтверждает работу: списывает сырьё по рецепту и приходует товар.

        POST /production/works/{id}/confirm/  Body: {"labor_cost": 1000} (только owner)
        """
        if not (request.user.is_owner or request.user.is_admin):
            return Response({'detail': 'Only owner or admin can confirm work'},
                            status=status.HTTP_403_FORBIDDEN)
        work = self.get_object()
        if work.status != WorkRecord.WorkStatus.AWAITING_CONFIRMATION:
            return Response({'detail': 'Work is not awaiting confirmation'},
                            status=status.HTTP_400_BAD_REQUEST)
        # Защита склада: при quantity <= 0 требования по рецепту стали бы
        # отрицательными, проверка нехватки сырья не сработала бы, и склад бы
        # «дорисовался». Отсекаем до расчётов (создание уже валидирует > 0).
        if work.quantity is None or work.quantity <= 0:
            return Response({'detail': 'Некорректное количество работы (должно быть больше нуля)'},
                            status=status.HTTP_400_BAD_REQUEST)

        labor_cost = None
        if request.user.is_owner and request.data.get('labor_cost') not in (None, ''):
            try:
                labor_cost = Decimal(str(request.data['labor_cost']))
            except (InvalidOperation, TypeError):
                return Response({'labor_cost': 'Must be a valid number'},
                                status=status.HTTP_400_BAD_REQUEST)
            if labor_cost < 0:
                return Response({'labor_cost': 'Must not be negative'},
                                status=status.HTTP_400_BAD_REQUEST)

        try:
            work = services.confirm_work(work, request.user, labor_cost=labor_cost, request=request)
        except services.MaterialShortageError as error:
            return Response(
                {'detail': 'Материал етарли эмас', 'shortages': error.shortages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except services.AlreadyProcessedError:
            return Response({'detail': 'Work has already been processed'},
                            status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(work).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Отклоняет работу (склад не меняется). Body: {"reason": "..."}."""
        if not (request.user.is_owner or request.user.is_admin):
            return Response({'detail': 'Only owner or admin can reject work'},
                            status=status.HTTP_403_FORBIDDEN)
        work = self.get_object()
        if work.status != WorkRecord.WorkStatus.AWAITING_CONFIRMATION:
            return Response({'detail': 'Work is not awaiting confirmation'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            work = services.reject_work(work, request.user, request.data.get('reason', ''), request=request)
        except services.AlreadyProcessedError:
            return Response({'detail': 'Work has already been processed'},
                            status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(work).data)

    @action(detail=False, methods=['get'])
    def my_earnings(self, request):
        """Заработок текущего работника: подтверждённые работы и сумма."""
        if not request.user.is_worker and not request.user.is_owner:
            raise PermissionDenied('Earnings are visible to the worker himself')
        confirmed = WorkRecord.objects.filter(
            worker=request.user, status=WorkRecord.WorkStatus.CONFIRMED,
        )
        total = confirmed.aggregate(total=Sum('labor_cost'))['total'] or 0
        from apps.finance.models import WorkerPayment
        paid = WorkerPayment.objects.filter(worker=request.user).aggregate(total=Sum('amount'))['total'] or 0
        return Response({
            'total_earned': total,
            'paid_out': paid,
            'remaining': total - paid,
            'confirmed_count': confirmed.count(),
        })
