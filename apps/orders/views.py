"""
Views for orders API.

Заказы создают владелец и администратор. Работник видит только заказы,
назначенные ему. Owner дополнительно видит суммы заказа.
"""
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction

from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from apps.messaging.models import Notification
from apps.messaging.services import notify_staff
from apps.core.permissions import IsCompanyMember
from core.permissions import IsOwnerOrAdmin
from apps.warehouse.services import record_incoming, record_outgoing
from apps.production.models import Task, TaskStatus
from .models import Order
from .serializers import OrderSerializer, OrderOwnerSerializer
from apps.core.views import CompanyScopedViewSet


class OrderViewSet(CompanyScopedViewSet):
    queryset = Order.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    # Поиск руками в get_queryset: SearchFilter не умеет транслит, а клиента
    # «Гулнора» должны находить по «Gulnora» (и наоборот).
    filterset_fields = ['status', 'payment_status', 'worker', 'client', 'id']
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
            super().get_queryset()
            .select_related('client', 'product', 'worker')
            .prefetch_related('product__recipes__items__material')
        )
        # Менеджер видит ВСЕ заказы компании (только чтение), как owner/admin;
        # работник — только назначенные ему. Изменения разрешены лишь owner/admin
        # (get_permissions ниже), поэтому manager не может их двигать.
        if user.is_owner or user.is_admin or user.is_manager:
            qs = queryset
        else:
            qs = queryset.filter(worker=user)
        search = self.request.query_params.get('search')
        if search:
            # product__name — заказ на товар из каталога хранит имя в связанном
            # продукте; транслит-варианты покрывают ввод латиницей/кириллицей.
            from apps.core.translit import translit_search_qs
            qs = translit_search_qs(
                qs, search,
                ['custom_product_name', 'comment', 'client__name', 'product__name'],
            )
        return qs

    def get_permissions(self):
        # transition — тот же «запись», что и deliver/cancel: Kanban двигает
        # заказы именно через него (PATCH status). Раньше он оставался открытым
        # для любого сотрудника компании; с появлением manager (queryset видит
        # ВСЕ заказы) это стало бы путём записи для роли «только чтение».
        if self.action in ('create', 'update', 'partial_update', 'destroy',
                           'deliver', 'cancel', 'transition'):
            return [IsCompanyMember(), IsOwnerOrAdmin()]
        return [IsCompanyMember()]

    def _assert_related_own_company(self, validated_data):
        # client/product/worker — все строго своей компании, и на create, и на
        # update. Раньше worker вообще не проверялся, а update не проверял ничего:
        # можно было привязать заказ к сотруднику/клиенту/товару чужой компании.
        company_id = self.request.user.company_id
        for field in ('client', 'product', 'worker'):
            obj = validated_data.get(field)
            if obj is not None and obj.company_id != company_id:
                raise PermissionDenied(f'{field.capitalize()} must belong to your company')

    def perform_create(self, serializer):
        company = self.request.user.company
        self._assert_related_own_company(serializer.validated_data)
        # Всё в одной транзакции: раньше заказ сохранялся, а резерв сырья падал
        # (например, материал удалили между валидацией и резервированием) — 500
        # после коммита, заказ оставался без резерва, клиент ретраил и плодил
        # дубликаты. Теперь сбой откатывает создание целиком.
        with transaction.atomic():
            order = serializer.save(company=company)
            # Сразу синхронизируем payment_status: дефолт модели — 'unpaid',
            # и заказ с нулевой суммой (бесплатный, или заведённый админом,
            # который сумм не видит) до первой правки/оплаты «не оплачен»
            # при нулевом долге.
            order.update_payment_status()
            # Товар и сырьё по его рецепту резервируются под заказ сразу при создании.
            order.reserve_product()
            order.reserve_raw_materials()
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
        self._assert_related_own_company(serializer.validated_data)
        # Строка заказа блокируется на всю правку: release/reserve — check-then-act,
        # и два параллельных PATCH (смена товара/количества) иначе снимали бы
        # резерв по одному снапшоту — старый резерв «прилипал» навсегда, а
        # total_amount в гонке с apply_payment_amount позволял оплату сверх долга.
        with transaction.atomic():
            locked = Order.objects.select_for_update().get(pk=serializer.instance.pk)
            # Выданный заказ уже списал товар и снял резервы. Правка количества
            # раньше проходила: заказ «становился» 5 шт, а склад был списан на 2 —
            # COGS, журнал и отчёты расходились.
            if locked.status == Order.Status.DELIVERED:
                raise DRFValidationError({
                    'detail': 'Выданный заказ нельзя редактировать — оформите '
                              'возврат расходом, если товар вернули.',
                })
            # Оплаты привязаны к клиенту: смена клиента оставляла Payment на
            # старом клиенте, а долг нового считался без уже принятых денег.
            if 'client' in serializer.validated_data:
                from apps.clients.models import Payment
                if Payment.objects.filter(order=locked).exists():
                    raise DRFValidationError({
                        'client': 'По заказу есть оплаты — сменить клиента нельзя.',
                    })
            old_product_id = locked.product_id
            old_quantity = locked.quantity
            old_client_id = locked.client_id
            changes = collect_model_changes(locked, serializer.validated_data)
            order = serializer.save()
            # Старый резерв снимаем по прежним product/quantity: если товар или
            # количество изменились, иначе резерв «прилипнет» к старому значению.
            if order.product_id != old_product_id or order.quantity != old_quantity:
                order.release_product(product_id=old_product_id, quantity=old_quantity)
                order.release_raw_materials(product_id=old_product_id, quantity=old_quantity)
                # Выданный/отменённый заказ резерв не «заводит» заново: deliver/cancel
                # уже сняли его, и правка количества не должна воскрешать резерв.
                if order.status not in (Order.Status.DELIVERED, Order.Status.CANCELLED):
                    order.reserve_product()
                    order.reserve_raw_materials()
            if 'total_amount' in changes:
                order.update_payment_status()
            order.client.recalculate_financials()
            # Смена клиента заказа переносит сумму долга: без пересчёта старого
            # клиента его total_orders_amount/debt «висели» с ушедшим заказом до
            # любого следующего события.
            if old_client_id and old_client_id != order.client_id:
                from apps.clients.models import Client
                try:
                    old_client = Client.objects.get(pk=old_client_id)
                except Client.DoesNotExist:
                    old_client = None
                if old_client:
                    old_client.recalculate_financials()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=order,
                changes=changes,
                request=self.request,
            )

    def _unwind_order(self, order, actor):
        """
        Общий разбор заказа для отмены и удаления.

        Удаление делает то же, что отмена (переводит в «отменён»), поэтому
        правила обязаны совпадать. Раньше они разошлись: destroy не проверял
        оплату и не возвращал товар — удалением можно было обойти запрет
        отменять оплаченный заказ и потерять списанное.

        Строка заказа блокируется (select_for_update): два параллельных cancel
        выданного заказа иначе оба видели status=DELIVERED и каждый приходовал
        товар обратно (record_incoming) — остаток завышался вдвое.

        Возвращает текст ошибки, если разбирать нельзя, иначе None.
        """
        with transaction.atomic():
            locked = Order.objects.select_for_update().get(pk=order.pk)
            if (locked.paid_amount or 0) > 0:
                return ('По заказу есть оплата — отменить нельзя. '
                        'Оформите возврат расходом «Возврат клиенту».')
            if locked.status == Order.Status.CANCELLED:
                return 'Заказ уже отменён.'
            # Выданный заказ уже списал товар. Отмена означает возврат от клиента:
            # приходуем обратно со следом в журнале, иначе товар исчезает с бумаги.
            if locked.status == Order.Status.DELIVERED and locked.product_id:
                record_incoming(
                    target=locked.product,
                    quantity=locked.quantity,
                    user=actor,
                    reason=f'Возврат по отмене заказа #{locked.id}',
                )
            else:
                # Невыданный заказ ничего не списывал — возвращаем только резерв.
                locked.release_product()
            locked.release_raw_materials()
            locked.status = Order.Status.CANCELLED
            locked.save(update_fields=['status'])
            # Задача — продолжение заказа: после отмены она превращалась в «зомби».
            # Работник сдавал по ней работу, confirm_work приходовал товар, а заказ
            # «воскресал» в awaiting_confirmation -> READY — отменённый заказ выдавал
            # себя сам. Отменяем только живые задачи (в работе); подтверждённые и
            # отклонённые остаются историей.
            Task.objects.filter(
                order_id=locked.pk,
                status__in=(TaskStatus.PENDING, TaskStatus.ACCEPTED,
                            TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED),
            ).update(status=TaskStatus.CANCELLED)
            locked.client.recalculate_financials()
            # Синхронизируем переданный инстанс, чтобы ответ сериализатора
            # показывал актуальный статус.
            order.status = Order.Status.CANCELLED
            return None

    def perform_destroy(self, instance):
        """Удаление запрещено - заказ отменяется и архивируется."""
        error = self._unwind_order(instance, self.request.user)
        if error:
            raise DRFValidationError({'detail': error})
        instance.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )

    @action(detail=True, methods=['patch'])
    def transition(self, request, pk=None):
        """
        Переводит заказ в указанный статус (только разрешённые переходы).

        POST /api/v1/orders/orders/{id}/transition/
        Тело: {"status": "new_status"}

        Разрешённые переходы (конечный автомат заказа):
          new ↔ awaiting_material
          new → sent_to_worker
          awaiting_material → sent_to_worker
          sent_to_worker → accepted, worker_refused
          accepted → in_progress, worker_refused
          worker_refused → new, sent_to_worker
          in_progress → awaiting_confirmation
          awaiting_confirmation → ready
          ready → delivered (через deliver action)
          * → cancelled (через cancel action)
        """
        order = self.get_object()
        new_status = request.data.get('status')
        if not new_status:
            return Response({'error': 'status is required'}, status=status.HTTP_400_BAD_REQUEST)

        allowed_transitions = {
            Order.Status.NEW: [Order.Status.AWAITING_MATERIAL, Order.Status.SENT_TO_WORKER],
            Order.Status.AWAITING_MATERIAL: [Order.Status.NEW, Order.Status.SENT_TO_WORKER],
            Order.Status.SENT_TO_WORKER: [Order.Status.ACCEPTED, Order.Status.WORKER_REFUSED],
            Order.Status.ACCEPTED: [Order.Status.IN_PROGRESS, Order.Status.WORKER_REFUSED],
            Order.Status.WORKER_REFUSED: [Order.Status.NEW, Order.Status.SENT_TO_WORKER],
            Order.Status.IN_PROGRESS: [Order.Status.AWAITING_CONFIRMATION],
            Order.Status.AWAITING_CONFIRMATION: [Order.Status.READY],
        }

        # Строка блокируется, как в deliver/cancel: параллельные transition,
        # deliver и cancel иначе читали один статус и писали поверх друг друга —
        # отменённый заказ «воскресал» в рабочем статусе (резервы уже сняты,
        # финансы пересчитаны), а выданный возвращался из DELIVERED в работу.
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            allowed = allowed_transitions.get(order.status, [])
            if new_status not in allowed:
                return Response(
                    {'error': f'Cannot transition from {order.status} to {new_status}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            old_status = order.status
            order.status = new_status
            order.save(update_fields=['status', 'updated_at'])
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=order,
            changes={'status': {'old': old_status, 'new': new_status}},
            request=request,
        )
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=['post'])
    def deliver(self, request, pk=None):
        """Выдаёт заказ клиенту; при полной оплате клиент уходит в архив."""
        order = self.get_object()
        old_status = order.status
        # Строка заказа блокируется на всё время выдачи: два параллельных
        # deliver иначе оба проходили проверку статуса и каждый списывал товар
        # (record_outgoing) — остаток падал вдвое, в журнале дублировалась
        # «Выдача заказа №…». Под блокировкой повторный запрос видит
        # DELIVERED и останавливается.
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            if order.status == Order.Status.CANCELLED:
                return Response({'detail': 'Order is cancelled'},
                                status=status.HTTP_400_BAD_REQUEST)
            # Повторная выдача блокируется: заказ уже отдан клиенту, второй раз
            # списать резерв/начислить долг нельзя (раньше выдачу можно было
            # дёргать сколько угодно — дубли в audit и лишний пересчёт финансов).
            if order.status == Order.Status.DELIVERED:
                return Response({'detail': 'Order is already delivered'},
                                status=status.HTTP_400_BAD_REQUEST)
            # Товар и сырьё ушли — резервы снимаем.
            # Резерв снимаем ДО списания: record_outgoing разрешает списывать
            # только доступное (остаток минус резерв), и собственный резерв заказа
            # иначе заблокировал бы его же выдачу.
            order.release_product()
            order.release_raw_materials()

            # Списание со склада. Раньше выдача только снимала резерв: товар
            # физически уезжал к клиенту, а остаток продолжал его показывать, и в
            # журнале движений выдачи не было вообще. Отсюда расхождение остатков,
            # журнала и статистики (замечание тестировщика).
            if order.product_id:
                try:
                    record_outgoing(
                        target=order.product,
                        quantity=order.quantity,
                        user=request.user,
                        reason=f'Выдача заказа #{order.id}',
                        # Собственный резерв уже снят (release_product выше);
                        # чужие НЕобеспеченные обещания (reserved > остатка)
                        # иначе блокировали бы выдачу физически имеющегося
                        # товара (см. record_outgoing).
                        ignore_reserved=True,
                    )
                except DRFValidationError:
                    # Считаем доступное ДО возврата резерва: резерв этого же заказа
                    # иначе занизил бы цифру в сообщении — он отложен как раз под него.
                    order.product.refresh_from_db()
                    available = order.product.quantity - (order.product.reserved_for_orders or 0)
                    # Не хватило товара — возвращаем резервы (и товара, и сырья по
                    # рецепту) и не выдаём: иначе остаток ушёл бы в минус, а клиент
                    # получил бы то, чего нет. Раньше возвращался только резерв
                    # товара — сырьё оставалось «зарезервированным» навсегда, и
                    # следующие заказы не могли перебронировать материал.
                    order.reserve_product()
                    order.reserve_raw_materials()
                    # Сообщение из record_outgoing говорит про «списание» и
                    # «резерв» — на выдаче это непонятно. Особенно когда клиент
                    # уже оплатил и пришёл забирать раньше срока: он видит отказ
                    # и не понимает, что делать. Объясняем ситуацию по-человечески.
                    return Response({
                        'detail': (
                            f'На складе недостаточно товара «{order.product.name}»: '
                            f'нужно {order.quantity}, доступно {max(available, 0)}. '
                            f'Подтвердите производство этой партии или оприходуйте товар '
                            f'приходом — после этого выдача пройдёт.'
                        ),
                        'code': 'not_enough_stock',
                        'required': str(order.quantity),
                        'available': str(max(available, 0)),
                    }, status=status.HTTP_400_BAD_REQUEST)

            order.status = Order.Status.DELIVERED
            order.save(update_fields=['status'])
            order.client.recalculate_financials()
            # «Не оплатил» — только когда долг реально есть. Клиент, оплативший
            # авансом (оплата без привязки к заказу), при выдаче имел долг 0,
            # но получал ложную тревогу «Мижоз тўлов қилмади» и не архивировался.
            if order.client.debt > 0:
                notify_staff(
                    order.company_id,
                    Notification.NotificationType.UNPAID_CLIENT,
                    'Мижоз тўлов қилмади',
                    f'Буюртма #{order.id}, мижоз: {order.client.name}',
                    order=order,
                )
            else:
                order.client.auto_archive()
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=order,
            # Фактический исходный статус, а не хардкод 'ready': выдача доступна
            # из любого терминального-кроме-выданного статуса (решение e8fc29b),
            # и журнал обязан отражать реальный переход.
            changes={'status': {'old': old_status, 'new': 'delivered'}},
            request=request,
        )
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        Отменяет заказ.

        Оплаченный заказ отменить нельзя: отмена не возвращает деньги, долг
        клиента пересчитывается — и уже принятая оплата просто повисала бы
        ни на чём. Возврат оформляется расходом категории «Возврат клиенту».
        """
        order = self.get_object()
        error = self._unwind_order(order, request.user)
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=order,
            changes={'status': {'new': 'cancelled'}},
            request=request,
        )
        return Response(self.get_serializer(order).data)
