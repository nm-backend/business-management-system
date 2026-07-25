from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .fingerprint_jwt import FingerprintTokenRefreshView

router = DefaultRouter()
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'skills', views.SkillViewSet, basename='skill')

urlpatterns = [
    path('setup/check/', views.SetupCheckView.as_view(), name='setup-check'),
    path('setup/owner/', views.SetupOwnerView.as_view(), name='setup-owner'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('token/refresh/', FingerprintTokenRefreshView.as_view(), name='token-refresh'),
    path('me/', views.MeView.as_view(), name='me'),
    path('me/password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('me/language/', views.ChangeLanguageView.as_view(), name='change-language'),
    # Двухэтапное подтверждение (2FA)
    path('me/2fa/', views.TwoFactorStatusView.as_view(), name='two-factor-status'),
    path('me/2fa/setup/', views.TwoFactorSetupView.as_view(), name='two-factor-setup'),
    path('me/2fa/confirm/', views.TwoFactorConfirmView.as_view(), name='two-factor-confirm'),
    path('me/2fa/disable/', views.TwoFactorDisableView.as_view(), name='two-factor-disable'),
    path('me/2fa/recovery-codes/', views.TwoFactorRecoveryCodesView.as_view(),
         name='two-factor-recovery-codes'),
    # Access Key (активация сотрудника без публичной регистрации)
    path('access-key/verify/', views.AccessKeyVerifyView.as_view(), name='access-key-verify'),
    path('access-key/redeem/', views.AccessKeyRedeemView.as_view(), name='access-key-redeem'),
    path('push/subscribe/', views.PushSubscriptionView.as_view(), name='push-subscribe'),
    path('', include(router.urls)),
]
