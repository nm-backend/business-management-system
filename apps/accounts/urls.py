from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

router = DefaultRouter()
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'skills', views.SkillViewSet, basename='skill')

urlpatterns = [
    path('setup/check/', views.SetupCheckView.as_view(), name='setup-check'),
    path('setup/owner/', views.SetupOwnerView.as_view(), name='setup-owner'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('me/', views.MeView.as_view(), name='me'),
    path('me/password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('me/language/', views.ChangeLanguageView.as_view(), name='change-language'),
    # Access Key (активация сотрудника без публичной регистрации)
    path('access-key/verify/', views.AccessKeyVerifyView.as_view(), name='access-key-verify'),
    path('access-key/redeem/', views.AccessKeyRedeemView.as_view(), name='access-key-redeem'),
    path('', include(router.urls)),
]
