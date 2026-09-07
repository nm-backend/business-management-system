import datetime
from decimal import Decimal

from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum
from django_filters.rest_framework import DjangoFilterBackend
from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from apps.core.permissions import IsCompanyMember
from core.permissions import IsOwnerOrAdmin, IsOwnerOrAdminOrManager
from .models import (
    FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement,
    Warehouse, WarehouseCell,
)
from .serializers import (
    IncomingSerializer, OutgoingSerializer,
    RawMaterialSerializer, RawMaterialOwnerSerializer,
    FinishedProductSerializer, FinishedProductOwnerSerializer,
    StockMovementSerializer, StockMovementLimitedSerializer, RecipeSerializer, RecipeItemSerializer,
    WarehouseSerializer, WarehouseCellSerializer, ReturnSerializer,
)
from .services import record_incoming, record_outgoing, record_return
from apps.core.views import CompanyScopedViewSet


class StockOperationsMixin:
    """
    Приход и архивация — общие операции склада сырья и готовой продукции.

    Приход считает сервер (см. services.record_incoming): раньше количество
    складывал браузер и присылал абсолютное значение, из-за чего два прихода с
    несвежей страницы затирали друг друга.

    Архивация идёт через SoftDeleteModel.archive()/restore(), а не прямым
    PATCH-ем is_archived: иначе archived_at остаётся пустым и «когда убрали в
    архив» узнать негде.
    """

    @action(detail=True, methods=['post'])
    def incoming(self, request, pk=None):
        target = self.get_object()
        serializer = IncomingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # Цена — финансовое поле: её задаёт только владелец. У админа приход
        # проходит, но цену и среднюю себестоимость он не меняет.
        price = data.get('price_per_unit') if request.user.is_owner else None

        updated = record_incoming(
            target=target,
            quantity=data['quantity'],
            price_per_unit=price,
            arrival_date=data.get('arrival_date'),
            document_number=data.get('document_number', ''),
            user=request.user,
            reason=data.get('reason', ''),
        )
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=updated,
            changes={'quantity': [str(target.quantity), str(updated.quantity)]},
            request=request,
        )
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=['post'])
    def outgoing(self, request, pk=None):
        """
        Расход/списание сырья или товара (макет «Материални чиқариш»).

        POST .../{id}/outgoing/
        Тело: {"quantity": 5, "movement_type": "outgoing|loss|adjustment",
               "outgoing_date": "2024-05-25", "document_number": "№К-1258",
               "reason": "..."}
        Списывается только доступное количество (остаток минус резерв).
        """
        target = self.get_object()
        serializer = OutgoingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        updated = record_outgoing(
            target=target,
            quantity=data['quantity'],
            movement_type=data.get('movement_type'),
            outgoing_date=data.get('outgoing_date'),
            document_number=data.get('document_number', ''),
            user=request.user,
            reason=data.get('reason', ''),
        )
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=updated,
            changes={'quantity': [str(target.quantity), str(updated.quantity)]},
            request=request,
        )
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=['post'])
    def returned(self, request, pk=None):
        """
        Возврат на склад (макет «Материал ҳаракатлари» → вкладка «Қайтарилган»).

        POST .../{id}/returned/
        Тело: {"quantity": 5, "return_date": "2026-09-07",
               "document_number": "К-1258", "reason": "..."}
        Отдельный тип движения: возврат неиспользованного остатка из цеха —
        не поставка, среднюю себестоимость он не меняет.
        """
        target = self.get_object()
        serializer = ReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        updated = record_return(
            target=target,
            quantity=data['quantity'],
            return_date=data.get('return_date'),
            document_number=data.get('document_number', ''),
            user=request.user,
            reason=data.get('reason', ''),
        )
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=updated,
            changes={'quantity': [str(target.quantity), str(updated.quantity)]},
            request=request,
        )
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        obj = self.get_object()
        obj.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE,
            actor=request.user,
            target=obj,
            request=request,
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        obj = self.get_object()
        obj.restore()
        # Отдельного действия RESTORE в AuditLog нет; пишем как изменение поля,
        # чтобы не заводить миграцию ради ярлыка.
        write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=request.user,
            target=obj,
            changes={'is_archived': [True, False]},
            request=request,
        )
        return Response(self.get_serializer(obj).data)

class WarehouseViewSet(CompanyScopedViewSet):
    """
    Склады компании (макет «Асосий омбор» с переключателем складов).

    Читают все сотрудники компании — им нужно знать, где лежит материал.
    Меняют владелец и администратор: склад и его ячейки — часть учёта, а не
    справочник «на каждый день».
    """
    queryset = Warehouse.objects.all()  # для интроспекции схемы; фильтрация ниже
    serializer_class = WarehouseSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code', 'address']
    filterset_fields = ['is_archived', 'is_default']
    ordering_fields = ['name', 'created_at']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsCompanyMember(), IsOwnerOrAdmin()]
        return [IsCompanyMember()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Warehouse.objects.none()
        qs = super().get_queryset().prefetch_related('cells__materials')
        # Архивные склады видит владелец (ему их и восстанавливать).
        if not self.request.user.is_owner:
            qs = qs.filter(is_archived=False)
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            # Флаг у прежнего склада снимаем ДО сохранения: иначе на мгновение
            # существуют два склада по умолчанию и срабатывает констрейнт.
            if serializer.validated_data.get('is_default'):
                self._clear_default(self.request.user.company_id)
            warehouse = serializer.save(company=self.request.user.company)
        write_audit_log(
            action=AuditLog.Action.CREATE, actor=self.request.user,
            target=warehouse, request=self.request,
        )

    def perform_update(self, serializer):
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        with transaction.atomic():
            if serializer.validated_data.get('is_default'):
                self._clear_default(serializer.instance.company_id, exclude_pk=serializer.instance.pk)
            warehouse = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE, actor=self.request.user,
                target=warehouse, changes=changes, request=self.request,
            )

    def perform_destroy(self, instance):
        """
        Склад архивируется, а не удаляется (ТЗ: удаления нет).

        Склад с материалами не архивируем: остатки повисли бы в невидимом
        месте, и «где лежит материал» перестало бы отвечать.
        """
        if instance.materials.filter(is_archived=False).exists():
            raise PermissionDenied(
                'На складе есть материалы — сначала переместите их на другой склад.'
            )
        instance.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE, actor=self.request.user,
            target=instance, request=self.request,
        )

    def _clear_default(self, company_id, exclude_pk=None):
        """Склад по умолчанию ровно один: назначили новый — сняли флаг у старого."""
        qs = Warehouse.objects.filter(company_id=company_id, is_default=True)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        qs.update(is_default=False)

    @action(detail=True, methods=['get'])
    def occupancy(self, request, pk=None):
        """
        Карта занятости склада (макет: «Жами майдон 420 м², банд 86.1 %»).

        GET /api/v1/warehouse/warehouses/{id}/occupancy/
        Отдаёт общую площадь, занятую площадь, проценты занято/свободно и
        список ячеек А-01…А-08 с их загрузкой. Занятость считает сервер по
        размещённым материалам — вводить её руками нельзя.
        """
        warehouse = self.get_object()
        cells = warehouse.cells.filter(is_archived=False).prefetch_related('materials')
        occupied = sum((cell.occupied_area for cell in cells), Decimal('0'))
        base = warehouse.total_area or sum(
            (cell.capacity_area for cell in cells), Decimal('0')
        )
        percent = (occupied / base * 100).quantize(Decimal('0.1')) if base else Decimal('0')
        return Response({
            'warehouse': warehouse.id,
            'name': warehouse.name,
            'total_area': warehouse.total_area,
            'capacity_area': sum((cell.capacity_area for cell in cells), Decimal('0')),
            'occupied_area': occupied,
            'occupancy_percent': percent,
            'free_percent': max(Decimal('100') - percent, Decimal('0')).quantize(Decimal('0.1')),
            'cells': WarehouseCellSerializer(cells, many=True).data,
        })


class WarehouseCellViewSet(CompanyScopedViewSet):
    """Ячейки хранения А-01…А-08 (макет «Омбордаги жойлашув»)."""
    queryset = WarehouseCell.objects.all()  # для интроспекции схемы; фильтрация ниже
    serializer_class = WarehouseCellSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code']
    filterset_fields = ['warehouse', 'zone', 'is_archived']
    ordering_fields = ['code', 'created_at']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsCompanyMember(), IsOwnerOrAdmin()]
        return [IsCompanyMember()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return WarehouseCell.objects.none()
        qs = super().get_queryset().select_related('warehouse').prefetch_related('materials')
        if not self.request.user.is_owner:
            qs = qs.filter(is_archived=False)
        return qs

    def perform_create(self, serializer):
        warehouse = serializer.validated_data.get('warehouse')
        if warehouse and warehouse.company_id != self.request.user.company_id:
            raise PermissionDenied('Склад другой компании')
        cell = serializer.save(company=self.request.user.company)
        write_audit_log(
            action=AuditLog.Action.CREATE, actor=self.request.user,
            target=cell, request=self.request,
        )

    def perform_update(self, serializer):
        warehouse = serializer.validated_data.get('warehouse')
        if warehouse and warehouse.company_id != self.request.user.company_id:
            raise PermissionDenied('Склад другой компании')
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        cell = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE, actor=self.request.user,
                target=cell, changes=changes, request=self.request,
            )

    def perform_destroy(self, instance):
        """Ячейку с материалами не архивируем — сначала их надо переложить."""
        if instance.materials.filter(is_archived=False).exists():
            raise PermissionDenied(
                'В ячейке есть материалы — сначала переместите их в другую ячейку.'
            )
        instance.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE, actor=self.request.user,
            target=instance, request=self.request,
        )


class RawMaterialViewSet(StockOperationsMixin, CompanyScopedViewSet):
    """
    API склада сырья с разделением финансовых полей по роли.

    DRF ViewSet объединяет list/retrieve/create/update/delete в одном классе.
    Serializer выбирается по роли: owner получает цены, admin/worker получают
    только складские количества, чтобы финансовые данные не уходили через API.
    """
    queryset = RawMaterial.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'stone_type', 'color', 'supplier', 'barcode']
    # Фильтр «Қайси омбор» из макета: остатки конкретного склада и ячейки.
    filterset_fields = ['is_archived', 'unit', 'storage_zone', 'warehouse', 'cell']
    ordering_fields = ['name', 'quantity', 'created_at']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy',
                           'incoming', 'outgoing', 'returned', 'archive', 'restore']:
            return [IsCompanyMember(), IsOwnerOrAdmin()]
        # Чтение склада: все сотрудники компании (owner/admin/worker/manager) —
        # цены (purchase_price/avg_cost_price) скрыты не-owner сериализатором,
        # финансовых сумм manager не видит.
        return [IsCompanyMember()]

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """
        Итоговые показатели склада сырья (макет «Хомашё омбори»).

        GET /api/v1/warehouse/raw-materials/summary/
        Возвращает остатки, сгруппированные по единице измерения, и, для
        владельца, общую стоимость (умумий қиймат = остаток * средняя
        себестоимость).

        Складывать количество в РАЗНЫХ единицах нельзя (кг + м² + шт —
        бессмысленное число), поэтому «общий остаток» (total_quantity)
        отдаётся только когда всё сырьё в ОДНОЙ единице; при смешанных
        единицах отдаём разбивку unit_totals, а total_quantity = null.
        """
        qs = RawMaterial.objects.filter(company_id=request.user.company_id, is_archived=False)
        unit_rows = (
            qs.values('unit')
            .annotate(quantity=Sum('quantity'))
            .order_by('-quantity', 'unit')
        )
        unit_totals = [
            {'unit': row['unit'], 'quantity': row['quantity'] or 0}
            for row in unit_rows
        ]
        # «Тезкор маълумот» из макета: сколько позиций на минимуме, сколько
        # критично мало, сколько пришло недавно и сколько зарезервировано под
        # заказы. Считаем по тем же правилам, что и карточка материала
        # (stock_severity), иначе цифры в шапке и в списке расходятся.
        recent_since = timezone.localdate() - datetime.timedelta(days=7)
        low_count = critical_count = 0
        for material in qs.only('quantity', 'min_stock', 'required_for_orders'):
            severity = material.stock_severity
            if severity == 'critical':
                critical_count += 1
            elif severity == 'low':
                low_count += 1
        quick_stats = {
            'low_stock_count': low_count,
            'critical_count': critical_count,
            'recent_arrivals_count': qs.filter(arrival_date__gte=recent_since).count(),
            'reserved_count': qs.filter(required_for_orders__gt=0).count(),
        }

        # «Склад якуний (бугун)»: сколько сегодня пришло и сколько ушло.
        # Возврат считаем приходом склада, но он остаётся отдельным типом
        # движения — в истории видно, что это возврат, а не поставка.
        today = timezone.localdate()
        movements = StockMovement.objects.filter(
            company_id=request.user.company_id,
            material__isnull=False,
            created_at__date=today,
        )
        incoming_types = (
            StockMovement.MovementType.INCOMING,
            StockMovement.MovementType.RETURN,
        )
        outgoing_types = (
            StockMovement.MovementType.OUTGOING,
            StockMovement.MovementType.PRODUCTION_OUT,
            StockMovement.MovementType.LOSS,
        )
        today_in = movements.filter(movement_type__in=incoming_types).aggregate(
            total=Sum('quantity'))['total'] or 0
        today_out = movements.filter(movement_type__in=outgoing_types).aggregate(
            total=Sum('quantity'))['total'] or 0

        data = {
            'unit_totals': unit_totals,
            'total_quantity': (
                unit_totals[0]['quantity'] if len(unit_totals) == 1 else None
            ),
            'quick_stats': quick_stats,
            'today': {
                'incoming': today_in,
                'outgoing': today_out,
                'net': today_in - today_out,
            },
        }
        if request.user.is_owner:
            data['total_value'] = sum(
                (m.quantity or 0) * (m.avg_cost_price or 0) for m in qs.only('quantity', 'avg_cost_price')
            )
        return Response(data)

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return RawMaterial.objects.none()
        qs = super().get_queryset()
        # Архив виден владельцу; остальным — только действующие позиции.
        # Работать с архивной записью (в т.ч. вернуть её) тоже может владелец.
        if not self.request.user.is_owner:
            qs = qs.filter(is_archived=False)
        return qs

    def get_serializer_class(self):
        if getattr(self, 'swagger_fake_view', False) or self.request.user.is_owner:
            return RawMaterialOwnerSerializer
        return RawMaterialSerializer

    def perform_create(self, serializer):
        material = serializer.save(company=self.request.user.company)
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=material,
            request=self.request,
        )

    def perform_update(self, serializer):
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        material = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=material,
                changes=changes,
                request=self.request,
            )

    def perform_destroy(self, instance):
        instance.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )

class FinishedProductViewSet(StockOperationsMixin, CompanyScopedViewSet):
    """
    API готовой продукции с тем же правилом RBAC, что и склад сырья.

    Себестоимость и цена продажи остаются только в owner-сериализаторе. Это
    серверная защита: frontend не может случайно показать то, что backend не
    отправил.
    """
    queryset = FinishedProduct.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'category']
    filterset_fields = ['is_archived', 'unit']
    ordering_fields = ['name', 'quantity', 'created_at']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy',
                           'incoming', 'outgoing', 'returned', 'archive', 'restore']:
            return [IsCompanyMember(), IsOwnerOrAdmin()]
        # Чтение склада: все сотрудники компании (owner/admin/worker/manager) —
        # цены (purchase_price/avg_cost_price) скрыты не-owner сериализатором,
        # финансовых сумм manager не видит.
        return [IsCompanyMember()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return FinishedProduct.objects.none()
        qs = super().get_queryset()
        if not self.request.user.is_owner:
            qs = qs.filter(is_archived=False)
        return qs

    def get_serializer_class(self):
        if getattr(self, 'swagger_fake_view', False) or self.request.user.is_owner:
            return FinishedProductOwnerSerializer
        return FinishedProductSerializer

    def perform_create(self, serializer):
        product = serializer.save(company=self.request.user.company)
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=product,
            request=self.request,
        )

    def perform_update(self, serializer):
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        product = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=product,
                changes=changes,
                request=self.request,
            )

    def perform_destroy(self, instance):
        instance.archive()
        write_audit_log(
            action=AuditLog.Action.ARCHIVE,
            actor=self.request.user,
            target=instance,
            request=self.request,
        )

class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    """
    История движения склада доступна только на чтение.

    Важное правило ТЗ: склад меняется через бизнес-операции и подтверждения, а
    история должна быть следом этих операций. Поэтому здесь нет ручного create,
    update или delete. Чтение — owner/admin/manager (worker историю не видит:
    см. test_worker_cannot_read_history); цена единицы (price_per_unit)
    скрывается limited-сериализатором для не-owner ролей, поэтому финансовых
    сумм manager не видит.
    """
    queryset = StockMovement.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsCompanyMember, IsOwnerOrAdminOrManager]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['movement_type', 'material', 'product', 'created_by']
    search_fields = ['reason']
    ordering_fields = ['created_at']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return StockMovement.objects.none()
        # created_by_name дергал created_by.full_name на КАЖДУЮ запись (N+1).
        # select_related сводит к константе; material/product — на будущее.
        return StockMovement.objects.filter(
            company=self.request.user.company_id,
        ).select_related('created_by', 'material', 'product')

    def get_serializer_class(self):
        if getattr(self, 'swagger_fake_view', False) or self.request.user.is_owner:
            return StockMovementSerializer
        return StockMovementLimitedSerializer

class RecipeViewSet(CompanyScopedViewSet):
    """
    Рецепт описывает, сколько сырья нужно для готового товара.

    Удаление рецепта запрещено: если рецепт больше не нужен, его выключают через
    is_active. Так сохраняется история решений и производство не теряет след.
    """
    queryset = Recipe.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    serializer_class = RecipeSerializer
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'is_active']
    search_fields = ['name', 'description']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Recipe.objects.none()
        return super().get_queryset().prefetch_related('items__material')

    def _check_product_company(self, serializer):
        product = serializer.validated_data.get('product')
        if product and product.company_id != self.request.user.company_id:
            raise PermissionDenied('Товар должен принадлежать вашей компании')

    def perform_create(self, serializer):
        self._check_product_company(serializer)
        recipe = serializer.save(company=self.request.user.company)
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=recipe,
            request=self.request,
        )

    def perform_update(self, serializer):
        self._check_product_company(serializer)
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        recipe = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=recipe,
                changes=changes,
                request=self.request,
            )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Recipe deletion is prohibited. Mark the recipe inactive instead.')

class RecipeItemViewSet(CompanyScopedViewSet):
    """
    Строка рецепта связывает конкретный материал и нужное количество.

    Удаление строки запрещено по той же причине, что и удаление рецепта: лучше
    обновить рецепт явно, чем потерять историю производственных норм.
    """
    queryset = RecipeItem.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    serializer_class = RecipeItemSerializer
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]
    filterset_fields = ['recipe', 'material']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return RecipeItem.objects.none()
        # material_name дергал material.name на каждую строку (N+1).
        # order_by('id') — детерминированная пагинация (без него пагинатор
        # предупреждал о возможных пропусках/дублях между страницами).
        return RecipeItem.objects.filter(
            recipe__company=self.request.user.company_id,
        ).select_related('material', 'recipe').order_by('id')

    def perform_create(self, serializer):
        # Нельзя добавить строку в чужой рецепт/материал.
        company_id = self.request.user.company_id
        recipe = serializer.validated_data.get('recipe')
        material = serializer.validated_data.get('material')
        if (recipe and recipe.company_id != company_id) or (material and material.company_id != company_id):
            raise PermissionDenied('Рецепт и материал должны принадлежать вашей компании')
        recipe_item = serializer.save()
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=recipe_item,
            request=self.request,
        )

    def perform_update(self, serializer):
        # На update проверяем принадлежность так же, как на create — иначе строку
        # можно было перепривязать к рецепту/материалу чужой компании.
        company_id = self.request.user.company_id
        recipe = serializer.validated_data.get('recipe')
        material = serializer.validated_data.get('material')
        if (recipe and recipe.company_id != company_id) or (material and material.company_id != company_id):
            raise PermissionDenied('Рецепт и материал должны принадлежать вашей компании')
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        recipe_item = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=recipe_item,
                changes=changes,
                request=self.request,
            )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Recipe item deletion is prohibited. Update the recipe instead.')
