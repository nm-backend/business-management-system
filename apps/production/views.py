"""
Views for production API.

Задачи (Task) и работы (WorkRecord) с ролевым доступом:
- Owner/Admin: назначают задачи, подтверждают/отклоняют работы.
- Worker: видит только свои задачи и работы, принимает/отказывается,
  сдаёт работу на подтверждение, видит свой заработок.
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Sum
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.mixins import CreateModelMixin

from apps.core.permissions import IsCompanyMember, IsOwnerOrAdmin, IsOwnerOrAdminOrWorker
from apps.messaging.models import Notification
from apps.messaging.services import notify, notify_staff
from .models import RefusalReason, Task, TaskStatus, WorkRecord
from .serializers import (
    TaskSerializer, TaskCreateSerializer,
    WorkRecordSerializer, WorkRecordLimitedSerializer, WorkRecordCreateSerializer,
)
from . import services
from apps.core.views import CompanyScopedViewSet


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


class TaskViewSet(ReadAfterCreateMixin, CompanyScopedViewSet):
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
        # Создание задачи: owner/admin назначают, worker создаёт свою
        # самостоятельную задачу — manager НЕ создаёт (только просмотр).
        if self.action == 'create':
            return [IsCompanyMember(), IsOwnerOrAdminOrWorker()]
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
        queryset = super().get_queryset().select_related('worker', 'assigned_by', 'order', 'order__client', 'order__product')
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
            raise PermissionDenied('Работник должен принадлежать вашей компании')
        if order and order.company_id != user.company_id:
            raise PermissionDenied('Заказ должен принадлежать вашей компании')
        # Зомби-заказ: задача по выданному/отменённому заказу раньше молча
        # переводила его обратно в sent_to_worker — товар уже списан при
        # выдаче или возвращён при отмене, резервы сняты, а заказ «воскресал»
        # в производство. Та же проверка, что у сдачи работы (WorkRecord).
        if order and order.status in (order.Status.CANCELLED, order.Status.DELIVERED):
            raise DRFValidationError({
                'order': 'Заказ отменён или выдан клиенту — задачу по нему создать нельзя.',
            })
        if user.is_worker:
            # Работник может создать только самостоятельную работу для себя.
            # Привязка к заказу позволяла миновать назначение (order.worker
            # остаётся пустым), а сдача работы по такой задаче двигала
            # неназначенный заказ в awaiting_confirmation -> READY.
            if order:
                raise DRFValidationError({
                    'order': 'Работник может создать только самостоятельную '
                             'задачу без привязки к заказу.',
                })
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
            return Response({'detail': 'Вы можете принимать только свои задачи'},
                            status=status.HTTP_403_FORBIDDEN)
        if task.status != TaskStatus.PENDING:
            return Response({'detail': 'Задача не в статусе «ожидает»'}, status=status.HTTP_400_BAD_REQUEST)
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
            return Response({'detail': 'Вы можете отклонять только свои задачи'},
                            status=status.HTTP_403_FORBIDDEN)
        reason = request.data.get('reason')
        if reason not in RefusalReason.values:
            return Response({'detail': 'reason is required',
                             'allowed': RefusalReason.values},
                            status=status.HTTP_400_BAD_REQUEST)
        # Отказ — решение работника ДО принятия задачи (в интерфейсе кнопка
        # отказа только у pending). Раньше refuse принимался и у сданной
        # задачи: работа висела на подтверждении, а заказ откатывался в
        # worker_refused. Принимался он и повторно у уже отказанной задачи:
        # владелец вернул заказ в new, повторный отказ снова отбросил его в
        # worker_refused — заказ «прыгал» между статусами.
        if task.status != TaskStatus.PENDING:
            return Response({'detail': 'Задача не в статусе «ожидает»'},
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
            raise PermissionDenied('Отменять задачи может только владелец или администратор')
        task = self.get_object()
        # Завершённые стадии задачи — история, её не отменяют. Особенно
        # COMPLETED: работа уже сдана на подтверждение, и cancel «убивал»
        # задачу, а заказ зависал в awaiting_confirmation; затем confirm_work
        # молча воскрешал задачу из CANCELLED обратно в CONFIRMED. Сданную
        # работу отменяют через reject.
        if task.status not in (TaskStatus.PENDING, TaskStatus.ACCEPTED,
                               TaskStatus.IN_PROGRESS):
            return Response({'detail': 'Задача уже завершена'},
                            status=status.HTTP_400_BAD_REQUEST)
        task.status = TaskStatus.CANCELLED
        task.save(update_fields=['status'])
        # Заказ без задачи — тупик: из sent_to_worker/accepted/in_progress
        # обратного перехода нет, а задача отменена — заказ застревал навсегда.
        # Возвращаем его в очередь (new) и снимаем исполнителя.
        if task.order and task.order.status in (
                task.order.Status.SENT_TO_WORKER,
                task.order.Status.ACCEPTED,
                task.order.Status.IN_PROGRESS):
            task.order.status = task.order.Status.NEW
            task.order.worker = None
            task.order.save(update_fields=['status', 'worker'])
        notify(
            task.worker,
            Notification.NotificationType.TASK_CANCELLED,
            'Вазифа бекор қилинди',
            f'Вазифа #{task.id} бекор қилинди',
            order=task.order, task=task,
        )
        return Response(TaskSerializer(task).data)


class WorkRecordViewSet(ReadAfterCreateMixin, CompanyScopedViewSet):
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
        # Создание записи: worker сдаёт свою работу, owner/admin заводят чужую —
        # manager НЕ создаёт (только просмотр).
        if self.action == 'create':
            return [IsCompanyMember(), IsOwnerOrAdminOrWorker()]
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
        queryset = super().get_queryset().select_related('worker', 'product', 'confirmed_by', 'task') \
            .prefetch_related('product__labor_rates')
        if self.request.user.is_worker:
            queryset = queryset.filter(worker=self.request.user)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        order_filter = self.request.query_params.get('order')
        if order_filter:
            # Работы по заказу (связь через задачу) — для карточки заказа,
            # чтобы показать историю выполнения.
            queryset = queryset.filter(task__order_id=order_filter)
        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        # Товар/задача должны быть из своей компании.
        product = serializer.validated_data.get('product')
        task = serializer.validated_data.get('task')
        worker = serializer.validated_data.get('worker')
        if product and product.company_id != user.company_id:
            raise PermissionDenied('Товар должен принадлежать вашей компании')
        if task and task.company_id != user.company_id:
            raise PermissionDenied('Задача должна принадлежать вашей компании')
        # Задача привязана к конкретному работнику; работа — к исполнителю.
        # Работник A, привязавший работу к задаче B, при подтверждении
        # «завершал» бы чужую задачу (заказ уходил в READY), а деньги получал
        # сам. Проверка после подстановки worker (для работника это он сам).
        work_worker = worker or user
        if task and task.worker_id != work_worker.id:
            raise PermissionDenied("Задача должна принадлежать работнику")
        # Зомби-задача: заказ отменён/выдан, а задача осталась живой. Сдача
        # работы по ней «воскрешала» бы заказ в awaiting_confirmation.
        if task and task.order and task.order.status in (
                task.order.Status.CANCELLED, task.order.Status.DELIVERED):
            raise PermissionDenied('Заказ отменён или доставлен — нельзя подать работу')
        # Заказ с товаром требует работы по ЭТОМУ товару: работа без товара
        # раньше создавалась, а подтверждение падало с labor_rate_missing —
        # заказ застревал в awaiting_confirmation, и единственным выходом был
        # reject. Ошибка видна сразу, работник сдаёт работу заново с товаром.
        if (task and task.order and task.order.product_id and not product):
            raise DRFValidationError({
                'product': f'По заказу №{task.order.id} производится товар '
                           f'«{task.order.product.name}» — укажите его в работе.',
            })
        # Работа про товар НЕ из заказа подтверждалась и «производила» чужой
        # товар: заказ на столешницу, а на склад приходовался подоконник
        # (заказ оставался без партии, READY не наступал). Требуем совпадения.
        if (task and task.order and task.order.product_id and product
                and product.id != task.order.product_id):
            raise DRFValidationError({
                'product': f'По заказу №{task.order.id} производится товар '
                           f'«{task.order.product.name}» — укажите в работе его.',
            })
        # Owner/admin не может записать работу на сотрудника чужой компании.
        if worker and worker.company_id != user.company_id:
            raise PermissionDenied('Работник должен принадлежать вашей компании')
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

    def perform_update(self, serializer):
        # Обновление обязано пройти те же проверки, что и создание: PATCH product
        # раньше мог перепривязать работу к товару ДРУГОЙ компании, а confirm_work
        # затем списывал чужое сырьё и приходовал чужой склад (IDOR-запись).
        user = self.request.user
        product = serializer.validated_data.get('product')
        task = serializer.validated_data.get('task') or serializer.instance.task
        if product and product.company_id != user.company_id:
            raise PermissionDenied('Товар должен принадлежать вашей компании')
        if task and task.company_id != user.company_id:
            raise PermissionDenied('Задача должна принадлежать вашей компании')
        # Работа по заказу с товаром обязана быть про ЭТОТ товар (как при создании).
        if task and task.order and task.order.product_id and product:
            if product.id != task.order.product_id:
                raise DRFValidationError({
                    'product': f'По заказу №{task.order.id} производится товар '
                               f'«{task.order.product.name}» — укажите в работе его.',
                })
        serializer.save()

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """
        Подтверждает работу: списывает сырьё по рецепту и приходует товар.

        POST /production/works/{id}/confirm/  Body: {"labor_cost": 1000} (только owner)
        """
        if not (request.user.is_owner or request.user.is_admin):
            return Response({'detail': 'Подтверждать работу может только владелец или администратор'},
                            status=status.HTTP_403_FORBIDDEN)
        work = self.get_object()
        if work.status != WorkRecord.WorkStatus.AWAITING_CONFIRMATION:
            return Response({'detail': 'Работа не ожидает подтверждения'},
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
        except services.MissingLaborRateError as error:
            # Раньше в этом случае молча начислялся ноль: работа
            # подтверждалась, склад пополнялся, а работник не получал ничего.
            return Response(
                {'detail': (
                    f'Для товара «{error.product_name}» не задана ставка оплаты труда. '
                    f'Укажите её в карточке товара и повторите подтверждение.'
                    if error.product_name else
                    'В работе не указан товар — начислить оплату не по чему.'
                ), 'code': 'labor_rate_missing'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except services.AlreadyProcessedError as error:
            return Response(
                {'detail': error.message or 'Работа уже обработана'},
                status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(work).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Отклоняет работу (склад не меняется). Body: {"reason": "..."}."""
        if not (request.user.is_owner or request.user.is_admin):
            return Response({'detail': 'Отклонять работу может только владелец или администратор'},
                            status=status.HTTP_403_FORBIDDEN)
        work = self.get_object()
        if work.status != WorkRecord.WorkStatus.AWAITING_CONFIRMATION:
            return Response({'detail': 'Работа не ожидает подтверждения'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            work = services.reject_work(work, request.user, request.data.get('reason', ''), request=request)
        except services.AlreadyProcessedError:
            return Response({'detail': 'Работа уже обработана'},
                            status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(work).data)

    @action(detail=False, methods=['get'])
    def my_earnings(self, request):
        """Заработок текущего работника: подтверждённые работы и сумма."""
        if not request.user.is_worker and not request.user.is_owner:
            raise PermissionDenied('Заработок виден только самому работнику')
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
