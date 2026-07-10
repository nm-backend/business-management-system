from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from core.permissions import IsOwnerOrAdmin
from .models import Client, Payment
from .serializers import ClientAdminSerializer, ClientOwnerSerializer, PaymentSerializer

class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.all()
    permission_classes = [IsOwnerOrAdmin] # Worker cannot access clients
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'phone', 'comment']
    filterset_fields = ['is_archived']
    ordering_fields = ['name', 'created_at']

    def get_serializer_class(self):
        if self.request.user.is_owner:
            return ClientOwnerSerializer
        return ClientAdminSerializer

class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['client', 'payment_method']
    ordering_fields = ['payment_date', 'amount']

    def get_permissions(self):
        # Only Owner can see or manage payments directly.
        # Wait, can Admin add payments? TBD. For now Owner only to be safe.
        from core.permissions import IsOwner
        return [IsOwner()]
