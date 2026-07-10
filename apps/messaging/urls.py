"""
URL configuration for messaging API.

Этот модуль содержит URL routing для API управления сообщениями и уведомлениями.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MessageViewSet, NotificationViewSet

router = DefaultRouter()
router.register(r'messages', MessageViewSet, basename='message')
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('', include(router.urls)),
]
