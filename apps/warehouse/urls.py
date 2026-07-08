from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'raw-materials', views.RawMaterialViewSet, basename='raw-material')
router.register(r'finished-products', views.FinishedProductViewSet, basename='finished-product')
router.register(r'stock-movements', views.StockMovementViewSet, basename='stock-movement')
router.register(r'recipes', views.RecipeViewSet, basename='recipe')
router.register(r'recipe-items', views.RecipeItemViewSet, basename='recipe-item')

urlpatterns = [
    path('', include(router.urls)),
]
