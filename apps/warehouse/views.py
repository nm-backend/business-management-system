from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.response import Response
from django.db.models import Sum
from django_filters.rest_framework import DjangoFilterBackend
from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from apps.core.permissions import IsCompanyMember
from core.permissions import IsOwnerOrAdmin, IsOwnerOrAdminOrManager
from .models import RawMaterial, FinishedProduct, StockMovement, Recipe, RecipeItem
from .serializers import (
    IncomingSerializer, OutgoingSerializer,
    RawMaterialSerializer, RawMaterialOwnerSerializer,
    FinishedProductSerializer, FinishedProductOwnerSerializer,
    StockMovementSerializer, StockMovementLimitedSerializer, RecipeSerializer, RecipeItemSerializer
)
from .services import record_incoming, record_outgoing
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
    filterset_fields = ['is_archived', 'unit', 'storage_zone']
    ordering_fields = ['name', 'quantity', 'created_at']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy',
                           'incoming', 'outgoing', 'archive', 'restore']:
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
        Возвращает общий остаток (жами қолдиқ) и, для владельца, общую
        стоимость (умумий қиймат = остаток * средняя себестоимость).
        """
        qs = RawMaterial.objects.filter(company_id=request.user.company_id, is_archived=False)
        total_quantity = qs.aggregate(s=Sum('quantity'))['s'] or 0
        data = {'total_quantity': total_quantity}
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
                           'incoming', 'outgoing', 'archive', 'restore']:
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
            raise PermissionDenied('Product must belong to your company')

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
            raise PermissionDenied('Recipe and material must belong to your company')
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
            raise PermissionDenied('Recipe and material must belong to your company')
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
