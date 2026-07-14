"""
URL configuration for messaging API — чат и уведомления.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ChatMessageViewSet,
    ConversationViewSet,
    EmployeeViewSet,
    NotificationViewSet,
)

router = DefaultRouter()
router.register(r'conversations', ConversationViewSet, basename='conversation')
router.register(r'messages', ChatMessageViewSet, basename='message')
router.register(r'employees', EmployeeViewSet, basename='employee')
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('', include(router.urls)),
]
