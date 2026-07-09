from rest_framework import viewsets, filters
from rest_framework.exceptions import MethodNotAllowed
from django_filters.rest_framework import DjangoFilterBackend
from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from core.permissions import IsOwnerOrAdmin, IsOwnerOrAdminOrWorker
from .models import RawMaterial, FinishedProduct, StockMovement, Recipe, RecipeItem
from .serializers import (
    RawMaterialSerializer, RawMaterialOwnerSerializer,
    FinishedProductSerializer, FinishedProductOwnerSerializer,
    StockMovementSerializer, StockMovementLimitedSerializer, RecipeSerializer, RecipeItemSerializer
)

class RawMaterialViewSet(viewsets.ModelViewSet):
    """
    API склада сырья с разделением финансовых полей по роли.

    DRF ViewSet объединяет list/retrieve/create/update/delete в одном классе.
    Serializer выбирается по роли: owner получает цены, admin/worker получают
    только складские количества, чтобы финансовые данные не уходили через API.
    """
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'stone_type', 'color', 'supplier']
    filterset_fields = ['is_archived', 'unit']
    ordering_fields = ['name', 'quantity', 'created_at']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsOwnerOrAdmin()]
        return [IsOwnerOrAdminOrWorker()]

    def get_queryset(self):
        qs = RawMaterial.objects.all()
        if not self.request.user.is_owner:
            qs = qs.filter(is_archived=False)
        return qs

    def get_serializer_class(self):
        if self.request.user.is_owner:
            return RawMaterialOwnerSerializer
        return RawMaterialSerializer

    def perform_create(self, serializer):
        material = serializer.save()
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

class FinishedProductViewSet(viewsets.ModelViewSet):
    """
    API готовой продукции с тем же правилом RBAC, что и склад сырья.

    Себестоимость и цена продажи остаются только в owner-сериализаторе. Это
    серверная защита: frontend не может случайно показать то, что backend не
    отправил.
    """
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'category']
    filterset_fields = ['is_archived', 'unit']
    ordering_fields = ['name', 'quantity', 'created_at']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsOwnerOrAdmin()]
        return [IsOwnerOrAdminOrWorker()]

    def get_queryset(self):
        qs = FinishedProduct.objects.all()
        if not self.request.user.is_owner:
            qs = qs.filter(is_archived=False)
        return qs

    def get_serializer_class(self):
        if self.request.user.is_owner:
            return FinishedProductOwnerSerializer
        return FinishedProductSerializer

    def perform_create(self, serializer):
        product = serializer.save()
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
    update или delete.
    """
    queryset = StockMovement.objects.all()
    permission_classes = [IsOwnerOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['movement_type', 'material', 'product', 'created_by']
    search_fields = ['reason']
    ordering_fields = ['created_at']

    def get_serializer_class(self):
        if self.request.user.is_owner:
            return StockMovementSerializer
        return StockMovementLimitedSerializer

class RecipeViewSet(viewsets.ModelViewSet):
    """
    Рецепт описывает, сколько сырья нужно для готового товара.

    Удаление рецепта запрещено: если рецепт больше не нужен, его выключают через
    is_active. Так сохраняется история решений и производство не теряет след.
    """
    queryset = Recipe.objects.all()
    serializer_class = RecipeSerializer
    permission_classes = [IsOwnerOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'is_active']
    search_fields = ['name', 'description']

    def perform_create(self, serializer):
        recipe = serializer.save()
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=recipe,
            request=self.request,
        )

    def perform_update(self, serializer):
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

class RecipeItemViewSet(viewsets.ModelViewSet):
    """
    Строка рецепта связывает конкретный материал и нужное количество.

    Удаление строки запрещено по той же причине, что и удаление рецепта: лучше
    обновить рецепт явно, чем потерять историю производственных норм.
    """
    queryset = RecipeItem.objects.all()
    serializer_class = RecipeItemSerializer
    permission_classes = [IsOwnerOrAdmin]
    filterset_fields = ['recipe', 'material']

    def perform_create(self, serializer):
        recipe_item = serializer.save()
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=recipe_item,
            request=self.request,
        )

    def perform_update(self, serializer):
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
