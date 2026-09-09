import datetime
from decimal import Decimal

from rest_framework import mixins, viewsets, filters
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from django.db.models import (
    Case, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value, When,
)
from django_filters.rest_framework import DjangoFilterBackend
from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from apps.core.permissions import IsCompanyMember
from apps.core.validators import parse_date_param, parse_int_param
from core.permissions import IsOwnerOrAdmin, IsOwnerOrAdminOrManager
from .models import (
    FinishedProduct, GoodsReceipt, RawMaterial, Recipe, RecipeItem, StockMovement,
    Warehouse, WarehouseCell,
)
from .serializers import (
    IncomingSerializer, OutgoingSerializer,
    RawMaterialSerializer, RawMaterialOwnerSerializer,
    FinishedProductSerializer, FinishedProductOwnerSerializer,
    StockMovementSerializer, StockMovementLimitedSerializer, RecipeSerializer, RecipeItemSerializer,
    WarehouseSerializer, WarehouseCellSerializer, ReturnSerializer,
    GoodsReceiptSerializer, GoodsReceiptNoMoneySerializer, GoodsReceiptCreateSerializer,
)
from .services import (
    create_goods_receipt, record_incoming, record_outgoing, record_return,
)
from apps.core.views import CompanyScopedViewSet


def _available_expression():
    """Доступный остаток: quantity − required_for_orders (как у RawMaterial)."""
    return ExpressionWrapper(
        F('quantity') - F('required_for_orders'),
        output_field=DecimalField(max_digits=15, decimal_places=3),
    )


def _half_min_expression():
    """Половина минимума — порог «критично» у RawMaterial.stock_severity."""
    return ExpressionWrapper(
        F('min_stock') / Value(Decimal('2')),
        output_field=DecimalField(max_digits=15, decimal_places=3),
    )


def _critical_q():
    """Те же правила, что у RawMaterial.stock_severity == 'critical'."""
    return Q(_available__lte=0) | (Q(min_stock__gt=0) & Q(_available__lt=F('_half_min')))


def _low_band_q():
    """stock_severity == 'low': не выше минимума, но ещё не critical."""
    return Q(_available__lte=F('min_stock')) & ~_critical_q()


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
        serializer = OutgoingSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = data.get('order')
        updated = record_outgoing(
            target=target,
            quantity=data['quantity'],
            movement_type=data.get('movement_type'),
            outgoing_date=data.get('outgoing_date'),
            document_number=data.get('document_number', ''),
            user=request.user,
            reason=data.get('reason', ''),
            purpose=data.get('purpose', ''),
            order_id=order.id if order else None,
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

    # Группы вкладок: какие типы движений попадают в каждую.
    # Возврат пополняет склад, но остаётся отдельной вкладкой — в макете это
    # разные колонки, и смешивать его с поставкой нельзя.
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



class GoodsReceiptViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                          mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Документы прихода: одна поставка — несколько материалов.

    Только создание и чтение. Правка и удаление проведённого документа
    запрещены намеренно: остатки уже изменены, а «редактирование задним
    числом» разошлось бы с историей склада (ТЗ: удаления нет, только архив,
    все изменения склада историзированы). Ошибочную поставку исправляют
    расходом или возвратом — обе операции остаются в истории.
    """
    queryset = GoodsReceipt.objects.all()  # для интроспекции схемы; фильтрация ниже
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['supplier', 'document_number']
    filterset_fields = ['supplier']
    ordering_fields = ['created_at', 'receipt_date']

    def get_permissions(self):
        # Приход по количеству — право администратора (ТЗ). Цены он не увидит:
        # их убирает сериализатор без денег.
        return [IsCompanyMember(), IsOwnerOrAdmin()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return GoodsReceipt.objects.none()
        return (
            GoodsReceipt.objects
            .filter(company_id=self.request.user.company_id)
            .prefetch_related('lines__material')
            .select_related('created_by')
        )

    def get_serializer_class(self):
        if self.action == 'create':
            return GoodsReceiptCreateSerializer
        if getattr(self, 'swagger_fake_view', False) or self.request.user.is_owner:
            return GoodsReceiptSerializer
        return GoodsReceiptNoMoneySerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        receipt = create_goods_receipt(
            company=request.user.company,
            lines=data['lines'],
            supplier=data.get('supplier', ''),
            document_number=data.get('document_number', ''),
            receipt_date=data.get('receipt_date'),
            comment=data.get('comment', ''),
            user=request.user,
            # Цену принимает только владелец — как в приходе одного материала.
            allow_prices=request.user.is_owner,
        )
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=request.user,
            target=receipt,
            metadata={'lines': len(data['lines'])},
            request=request,
        )
        read_serializer = (
            GoodsReceiptSerializer if request.user.is_owner else GoodsReceiptNoMoneySerializer
        )
        return Response(read_serializer(receipt).data, status=201)


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
    # Тур / ҳолат / бирлик — точные поля панели фильтра; цвет и размер —
    # icontains в get_queryset (иначе «бел» не находил «Белый»).
    filterset_fields = [
        'is_archived', 'unit', 'storage_zone', 'warehouse', 'cell',
        'stone_type', 'condition',
    ]
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

        # Считаем одним запросом вместо перебора материалов в Python: на складе
        # из сотен позиций прежний цикл тянул все строки и считал severity по
        # одной. Правила ТЕ ЖЕ, что у RawMaterial.stock_severity:
        #   доступно = quantity - required_for_orders
        #   critical: доступно <= 0 или (есть минимум и доступно < минимум/2)
        #   low:      доступно <= минимум (и не critical)
        # Совпадение SQL и свойства модели закреплено тестом.
        available = ExpressionWrapper(
            F('quantity') - F('required_for_orders'),
            output_field=DecimalField(max_digits=15, decimal_places=3),
        )
        half_min = ExpressionWrapper(
            F('min_stock') / Value(Decimal('2')),
            output_field=DecimalField(max_digits=15, decimal_places=3),
        )
        counters = qs.annotate(_available=available, _half_min=half_min).aggregate(
            materials_count=Count('id'),
            # «Турлари» — сколько РАЗНЫХ видов камня на складе. Пустой
            # stone_type видом не считается: это «тип не заполнен».
            types_count=Count(
                Case(When(~Q(stone_type=''), then=F('stone_type'))),
                distinct=True,
            ),
            critical_count=Count(Case(When(
                Q(_available__lte=0) | (Q(min_stock__gt=0) & Q(_available__lt=F('_half_min'))),
                then=1,
            ))),
            low_count=Count(Case(When(
                Q(_available__lte=F('min_stock'))
                & ~(Q(_available__lte=0) | (Q(min_stock__gt=0) & Q(_available__lt=F('_half_min')))),
                then=1,
            ))),
            recent_arrivals_count=Count(Case(When(arrival_date__gte=recent_since, then=1))),
            reserved_count=Count(Case(When(required_for_orders__gt=0, then=1))),
        )
        quick_stats = {
            'low_stock_count': counters['low_count'],
            'critical_count': counters['critical_count'],
            'recent_arrivals_count': counters['recent_arrivals_count'],
            'reserved_count': counters['reserved_count'],
        }

        # Разрез по видам камня для чипов из макета («Оқ мрамор 250.75 м²»).
        # Количество отдаём только когда все позиции вида в ОДНОЙ единице:
        # складывать м² с кг нельзя, поэтому при смешанных единицах quantity
        # остаётся null, а разбивка лежит в unit_totals вида.
        type_rows = (
            qs.exclude(stone_type='')
            .values('stone_type', 'unit')
            .annotate(quantity=Sum('quantity'), materials_count=Count('id'))
            .order_by('stone_type', 'unit')
        )
        grouped_types = {}
        for row in type_rows:
            entry = grouped_types.setdefault(row['stone_type'], {
                'stone_type': row['stone_type'],
                'materials_count': 0,
                'unit_totals': [],
            })
            entry['materials_count'] += row['materials_count']
            entry['unit_totals'].append({
                'unit': row['unit'], 'quantity': row['quantity'] or 0,
            })
        type_totals = []
        for entry in grouped_types.values():
            single = entry['unit_totals'][0] if len(entry['unit_totals']) == 1 else None
            entry['unit'] = single['unit'] if single else None
            entry['quantity'] = single['quantity'] if single else None
            type_totals.append(entry)
        type_totals.sort(key=lambda item: item['materials_count'], reverse=True)

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
            # «Турлари 28 / Материаллар 156» из шапки макета.
            'types_count': counters['types_count'],
            'materials_count': counters['materials_count'],
            'type_totals': type_totals,
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

        params = self.request.query_params
        color = params.get('color')
        if color:
            qs = qs.filter(color__icontains=color)
        size = params.get('size')
        if size:
            qs = qs.filter(size__icontains=size)

        # Панель фильтра и экран «Минимум қолдиқлар»: градация считается
        # тем же SQL, что и summary.quick_stats / RawMaterial.stock_severity.
        # Неизвестное значение не игнорируем — иначе вкладка выглядела бы
        # рабочей, а показывала бы весь склад.
        severity = params.get('stock_severity')
        if severity:
            known = {'critical', 'low', 'below_min', 'ok'}
            if severity not in known:
                return qs.none()
            qs = qs.annotate(
                _available=_available_expression(),
                _half_min=_half_min_expression(),
            )
            if severity == 'critical':
                qs = qs.filter(_critical_q())
            elif severity == 'low':
                qs = qs.filter(_low_band_q())
            elif severity == 'below_min':
                # is_low_stock: всё, что не выше минимума, включая критичное.
                qs = qs.filter(Q(_available__lte=F('min_stock')))
            else:
                qs = qs.exclude(Q(_available__lte=F('min_stock')))
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
    # Вкладки «Ҳаммаси / Келган / Ишлатилган / Қайтарилган» из макета — это
    # фильтр по movement_type НА СЕРВЕРЕ, а не отбор загруженной страницы:
    # иначе на второй странице вкладка показывала бы неполные данные.
    filterset_fields = [
        'movement_type', 'material', 'product', 'created_by', 'purpose', 'receipt',
    ]
    search_fields = ['reason', 'document_number']
    ordering_fields = ['created_at']

    CATEGORY_TYPES = {
        'incoming': (StockMovement.MovementType.INCOMING,),
        'outgoing': (
            StockMovement.MovementType.OUTGOING,
            StockMovement.MovementType.PRODUCTION_OUT,
            StockMovement.MovementType.LOSS,
        ),
        'returned': (StockMovement.MovementType.RETURN,),
        'production': (
            StockMovement.MovementType.PRODUCTION_IN,
            StockMovement.MovementType.PRODUCTION_OUT,
        ),
    }

    def _apply_history_filters(self, queryset):
        """
        Фильтры вкладок и периода поверх стандартных filterset-полей.

        Неизвестное значение категории НЕ игнорируется молча (иначе вкладка
        показала бы всю историю и выглядела бы рабочей) — отдаём пустой
        результат, а тест это фиксирует.
        """
        params = self.request.query_params

        category = params.get('category')
        if category:
            types = self.CATEGORY_TYPES.get(category)
            queryset = queryset.filter(movement_type__in=types) if types else queryset.none()

        date_from = params.get('date_from')
        if date_from:
            queryset = queryset.filter(
                created_at__date__gte=parse_date_param(date_from, 'date_from'),
            )
        date_to = params.get('date_to')
        if date_to:
            queryset = queryset.filter(
                created_at__date__lte=parse_date_param(date_to, 'date_to'),
            )

        order_id = params.get('order')
        if order_id:
            queryset = queryset.filter(
                related_order_id=parse_int_param(order_id, 'order'),
            )
        return queryset

    @action(detail=False, methods=['get'])
    def totals(self, request):
        """
        Итоги под таблицей истории (макет: «Жами келган / Жами ишлатилган»).

        Считает сервер по ВСЕЙ выборке с учётом фильтров, а не по видимой
        странице: иначе итог менялся бы при листании.
        """
        queryset = self._apply_history_filters(self.filter_queryset(self.get_queryset()))
        incoming = queryset.filter(
            movement_type__in=self.CATEGORY_TYPES['incoming'],
        ).aggregate(total=Sum('quantity'))['total'] or 0
        returned = queryset.filter(
            movement_type__in=self.CATEGORY_TYPES['returned'],
        ).aggregate(total=Sum('quantity'))['total'] or 0
        outgoing = queryset.filter(
            movement_type__in=self.CATEGORY_TYPES['outgoing'],
        ).aggregate(total=Sum('quantity'))['total'] or 0
        return Response({
            'incoming': incoming,
            'returned': returned,
            'outgoing': outgoing,
            # Итог склада за период: приход и возврат пополняют, расход убавляет.
            'net': incoming + returned - outgoing,
            'movements_count': queryset.count(),
        })

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return StockMovement.objects.none()
        # created_by_name дергал created_by.full_name на КАЖДУЮ запись (N+1).
        # select_related сводит к константе; material/product — на будущее.
        queryset = StockMovement.objects.filter(
            company=self.request.user.company_id,
        ).select_related('created_by', 'material', 'product')
        return self._apply_history_filters(queryset)

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
