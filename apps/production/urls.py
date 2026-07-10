"""
URL configuration for production API.

Этот модуль содержит URL routing для API управления производством.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet, WorkRecordViewSet

router = DefaultRouter()
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'works', WorkRecordViewSet, basename='workrecord')

urlpatterns = [
    path('', include(router.urls)),
]
