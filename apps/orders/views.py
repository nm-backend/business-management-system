from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from core.permissions import IsOwnerOrAdmin, IsWorker
from rest_framework.permissions import IsAuthenticated
from .models import Order
from .serializers import OrderSerializer

class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['custom_product_name', 'comment', 'client__name']
    filterset_fields = ['status', 'payment_status', 'worker', 'client']
    ordering_fields = ['created_at', 'deadline']

    def get_queryset(self):
        user = self.request.user
        if user.is_owner or user.is_admin:
            return Order.objects.all()
        elif user.is_worker:
            # Worker can only see their own orders/tasks
            return Order.objects.filter(worker=user)
        return Order.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        if user.is_worker:
            # Workers cannot create orders, but let's say they can submit a standalone work?
            # Based on PRD: "Работник получает задачу или добавляет самостоятельную работу."
            # If standalone work, maybe a different API or they just create an order with themselves as worker.
            serializer.save(worker=user)
        else:
            serializer.save()
