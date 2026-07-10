"""
URL configuration for clients API.

Этот модуль содержит URL routing для API управления клиентами.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ClientViewSet

router = DefaultRouter()
router.register(r'', ClientViewSet, basename='client')

urlpatterns = [
    path('', include(router.urls)),
]
