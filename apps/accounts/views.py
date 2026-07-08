from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from core.permissions import IsOwner, IsOwnerOrAdmin
from .models import User
from .serializers import (
    UserSerializer, UserCreateSerializer, UserLimitedSerializer,
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
        return Response(status=status.HTTP_205_RESET_CONTENT)

class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()
        return Response({'message': 'Password changed successfully'})

class ChangeLanguageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LanguageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.language = serializer.validated_data['language']
        request.user.save(update_fields=['language'])
        return Response({'language': request.user.language, 'message': 'Language updated'})

class UserViewSet(viewsets.ModelViewSet):
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
        if user.is_admin and not user.can_create_workers:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You do not have permission to create workers')
        if user.is_admin:
            serializer.save(role='worker')
        else:
            serializer.save()

    @action(detail=True, methods=['post'], permission_classes=[IsOwner])
    def toggle_active(self, request, pk=None):
        user = self.get_object()
        if user.role == 'owner':
            return Response({'error': 'Cannot deactivate owner account'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        return Response({'is_active': user.is_active})

    @action(detail=True, methods=['post'], permission_classes=[IsOwner])
    def reset_password(self, request, pk=None):
        user = self.get_object()
        new_password = request.data.get('new_password')
        if not new_password or len(new_password) < 6:
            return Response({'error': 'Password must be at least 6 characters'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()
        return Response({'message': 'Password reset successfully'})
