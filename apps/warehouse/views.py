from rest_framework import viewsets, filters
from rest_framework.exceptions import MethodNotAllowed
from django_filters.rest_framework import DjangoFilterBackend
from apps.audit.mixins import AuditCreateUpdateMixin, AuditedArchiveMixin
from apps.core.permissions import IsOwnerOrAdmin, IsOwnerOrAdminOrWorker
from apps.core.viewsets import (
    HideArchivedFromNonOwnersMixin,
    OwnerSerializerMixin,
    ReadWritePermissionMixin,
)
from .models import RawMaterial, FinishedProduct, StockMovement, Recipe, RecipeItem
from .serializers import (
    RawMaterialSerializer, RawMaterialOwnerSerializer,
    FinishedProductSerializer, FinishedProductOwnerSerializer,
    StockMovementSerializer, StockMovementLimitedSerializer, RecipeSerializer, RecipeItemSerializer
)

class RawMaterialViewSet(
    OwnerSerializerMixin,
    ReadWritePermissionMixin,
    HideArchivedFromNonOwnersMixin,
    AuditedArchiveMixin,
    viewsets.ModelViewSet,
):
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
    queryset = RawMaterial.objects.all()
    serializer_class = RawMaterialSerializer
    owner_serializer_class = RawMaterialOwnerSerializer
    read_permission_classes = (IsOwnerOrAdminOrWorker,)
    write_permission_classes = (IsOwnerOrAdmin,)


class FinishedProductViewSet(
    OwnerSerializerMixin,
    ReadWritePermissionMixin,
    HideArchivedFromNonOwnersMixin,
    AuditedArchiveMixin,
    viewsets.ModelViewSet,
):
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
    queryset = FinishedProduct.objects.all()
    serializer_class = FinishedProductSerializer
    owner_serializer_class = FinishedProductOwnerSerializer
    read_permission_classes = (IsOwnerOrAdminOrWorker,)
    write_permission_classes = (IsOwnerOrAdmin,)


class StockMovementViewSet(OwnerSerializerMixin, viewsets.ReadOnlyModelViewSet):
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
    serializer_class = StockMovementLimitedSerializer
    owner_serializer_class = StockMovementSerializer


class RecipeViewSet(AuditCreateUpdateMixin, viewsets.ModelViewSet):
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

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Recipe deletion is prohibited. Mark the recipe inactive instead.')


class RecipeItemViewSet(AuditCreateUpdateMixin, viewsets.ModelViewSet):
    """
    Строка рецепта связывает конкретный материал и нужное количество.

    Удаление строки запрещено по той же причине, что и удаление рецепта: лучше
    обновить рецепт явно, чем потерять историю производственных норм.
    """
    queryset = RecipeItem.objects.all()
    serializer_class = RecipeItemSerializer
    permission_classes = [IsOwnerOrAdmin]
    filterset_fields = ['recipe', 'material']

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Recipe item deletion is prohibited. Update the recipe instead.')
