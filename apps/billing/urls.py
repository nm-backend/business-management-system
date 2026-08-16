from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'subscriptions', views.SubscriptionAdminViewSet, basename='subscription-admin')

urlpatterns = [
    path('subscription/', views.SubscriptionView.as_view(), name='subscription'),
    path('subscription/renew/', views.SubscriptionRenewView.as_view(), name='subscription-renew'),
    path('subscription/invoices/', views.SubscriptionInvoicesView.as_view(), name='subscription-invoices'),
    path('', include(router.urls)),
]
