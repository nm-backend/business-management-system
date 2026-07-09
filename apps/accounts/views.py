from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from core.permissions import IsOwner, IsOwnerOrAdmin
from .models import User
from .serializers import (
    UserSerializer, UserSelfUpdateSerializer, UserCreateSerializer, UserLimitedSerializer,
    LoginSerializer, ChangePasswordSerializer, SetupOwnerSerializer,
    LanguageSerializer,
)

class SetupCheckView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        owner_exists = User.objects.filter(role='owner').exists()
        return Response({'setup_required': not owner_exists})

class SetupOwnerView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if User.objects.filter(role='owner').exists():
            return Response({'error': 'Owner already exists. Setup is complete.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = SetupOwnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        write_audit_log(
            action=AuditLog.Action.SETUP_OWNER,
            actor=user,
            target=user,
            request=request,
        )
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'tokens': {'refresh': str(refresh), 'access': str(refresh.access_token)}
        }, status=status.HTTP_201_CREATED)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        write_audit_log(
            action=AuditLog.Action.LOGIN,
            actor=user,
            target=user,
            request=request,
        )
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'tokens': {'refresh': str(refresh), 'access': str(refresh.access_token)}
        })

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass
        write_audit_log(
            action=AuditLog.Action.LOGOUT,
            actor=request.user,
            target=request.user,
            request=request,
        )
        return Response(status=status.HTTP_205_RESET_CONTENT)

class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSelfUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = collect_model_changes(request.user, serializer.validated_data)
        serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=request.user,
                target=request.user,
                changes=changes,
                request=request,
            )
        return Response(UserSerializer(request.user).data)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()
        write_audit_log(
            action=AuditLog.Action.CHANGE_PASSWORD,
            actor=request.user,
            target=request.user,
            request=request,
        )
        return Response({'message': 'Password changed successfully'})

class ChangeLanguageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LanguageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        old_language = request.user.language
        request.user.language = serializer.validated_data['language']
        request.user.save(update_fields=['language'])
        write_audit_log(
            action=AuditLog.Action.CHANGE_LANGUAGE,
            actor=request.user,
            target=request.user,
            changes={
                'language': {
                    'old': old_language,
                    'new': request.user.language,
                }
            },
            request=request,
        )
        return Response({'language': request.user.language, 'message': 'Language updated'})

class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet управляет аккаунтами через RBAC.

    RBAC означает role-based access control: доступ зависит от роли пользователя.
    В этом ViewSet владелец может управлять администраторами и работниками, а
    администратор может создать только работника и только при разрешении owner.
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_owner:
            return User.objects.all()
        elif user.is_admin:
            return User.objects.filter(role='worker')
        return User.objects.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        if self.request.user.is_owner:
            return UserSerializer
        return UserLimitedSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [IsOwnerOrAdmin()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsOwner()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        user = self.request.user
        requested_role = serializer.validated_data.get('role', User.Role.WORKER)

        if user.is_owner:
            if requested_role == User.Role.OWNER:
                raise ValidationError({'role': 'Owner account already exists'})
            created_user = serializer.save()
            write_audit_log(
                action=AuditLog.Action.CREATE,
                actor=user,
                target=created_user,
                metadata={'created_role': created_user.role},
                request=self.request,
            )
            return

        if user.is_admin:
            if not user.can_create_workers:
                raise PermissionDenied('You do not have permission to create workers')
            if requested_role != User.Role.WORKER:
                raise PermissionDenied('Administrators can create only worker accounts')
            created_user = serializer.save(
                role=User.Role.WORKER,
                can_write_to_owner=False,
                can_create_workers=False,
                can_see_other_workers=False,
            )
            write_audit_log(
                action=AuditLog.Action.CREATE,
                actor=user,
                target=created_user,
                metadata={'created_role': created_user.role},
                request=self.request,
            )
            return

        raise PermissionDenied('You do not have permission to create accounts')

    def perform_update(self, serializer):
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        updated_user = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=updated_user,
                changes=changes,
                request=self.request,
            )

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Account deletion is prohibited. Block the account instead.')

    @action(detail=True, methods=['post'], permission_classes=[IsOwner])
    def toggle_active(self, request, pk=None):
        user = self.get_object()
        if user.role == 'owner':
            return Response({'error': 'Cannot deactivate owner account'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        write_audit_log(
            action=AuditLog.Action.ACTIVATE if user.is_active else AuditLog.Action.DEACTIVATE,
            actor=request.user,
            target=user,
            changes={'is_active': {'old': not user.is_active, 'new': user.is_active}},
            request=request,
        )
        return Response({'is_active': user.is_active})

    @action(detail=True, methods=['post'], permission_classes=[IsOwner])
    def reset_password(self, request, pk=None):
        user = self.get_object()
        new_password = request.data.get('new_password')
        if not new_password or len(new_password) < 6:
            return Response({'error': 'Password must be at least 6 characters'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()
        write_audit_log(
            action=AuditLog.Action.RESET_PASSWORD,
            actor=request.user,
            target=user,
            request=request,
        )
        return Response({'message': 'Password reset successfully'})
