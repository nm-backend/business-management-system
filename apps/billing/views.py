"""
API подписок.

Owner (своя компания):
    GET  /api/v1/billing/subscription/          — статус, срок, история, тарифы
    POST /api/v1/billing/subscription/renew/    — продление (создаёт счёт)
    GET  /api/v1/billing/subscription/invoices/ — свои счета

Superadmin (платформа):
    GET/POST... /api/v1/billing/subscriptions/         — все подписки (CRUD без удаления)
    POST /subscriptions/{id}/activate/  — активация свежего периода
    POST /subscriptions/{id}/extend/    — продление от max(now, expires_at)
    POST /subscriptions/{id}/freeze/    — ручная заморозка
    POST /subscriptions/{id}/unfreeze/  — ручная разморозка (срок должен быть в будущем)
    POST /subscriptions/{id}/confirm_payment/ — подтверждение оплаты счёта

Эндпоинты billing входят в whitelist subscription gate: продление/активация
доступны и в замороженном состоянии.
"""
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsSuperAdmin
from core.permissions import IsOwner
from rest_framework.permissions import IsAuthenticated

from .models import Invoice, Subscription
from .serializers import (
    ActivateRequestSerializer, ConfirmPaymentSerializer, ExtendRequestSerializer,
    InvoiceSerializer, NoteRequestSerializer, RenewRequestSerializer,
    SubscriptionEventSerializer, SubscriptionSerializer,
)
from .services import (
    activate_subscription, confirm_invoice_paid, create_invoice, extend_subscription,
    unfreeze_subscription,
)


def _plans_catalog():
    from django.conf import settings
    return [
        {
            'key': item['key'],
            'label': item.get('label', item['key']),
            'price': item.get('price', 0),
            'note': item.get('note', ''),
        }
        for item in getattr(settings, 'SUBSCRIPTION_PLANS', [])
    ]


class SubscriptionView(APIView):
    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request):
        sub = Subscription.objects.filter(company_id=request.user.company_id).first()
        if sub is None:
            return Response(
                {'detail': 'Подписка для компании не найдена. Обратитесь к администратору платформы.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        data = SubscriptionSerializer(sub).data
        data['history'] = SubscriptionEventSerializer(
            sub.events.all()[:50], many=True,
        ).data
        data['invoices'] = InvoiceSerializer(sub.invoices.all()[:10], many=True).data
        data['plans'] = _plans_catalog()
        return Response(data)


class SubscriptionRenewView(APIView):
    permission_classes = [IsAuthenticated, IsOwner]

    def post(self, request):
        serializer = RenewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub = Subscription.objects.filter(company_id=request.user.company_id).first()
        if sub is None:
            return Response(
                {'detail': 'Подписка для компании не найдена. Обратитесь к администратору платформы.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        invoice, created = create_invoice(
            sub, plan=serializer.validated_data.get('plan'), actor=request.user, request=request,
        )
        return Response(InvoiceSerializer(invoice).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class SubscriptionInvoicesView(APIView):
    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request):
        invoices = Invoice.objects.filter(
            company_id=request.user.company_id,
        )[:20]
        return Response(InvoiceSerializer(invoices, many=True).data)


@extend_schema(tags=['Subscriptions (superadmin)'])
class SubscriptionAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Управление подписками всех компаний — только супер-админ.

    Чтение: список с поиском по компании и фильтром по статусу/тарифу,
    детали с историей и счетами. Изменения — только через экшены ниже.
    """
    permission_classes = [IsSuperAdmin]
    serializer_class = SubscriptionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['company__name']
    ordering_fields = ['expires_at', 'created_at', 'company__name']
    ordering = ['expires_at']
    filterset_fields = ['status', 'plan']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Subscription.objects.none()
        return Subscription.objects.select_related('company').all()

    def retrieve(self, request, *args, **kwargs):
        sub = self.get_object()
        data = SubscriptionSerializer(sub).data
        data['history'] = SubscriptionEventSerializer(sub.events.all()[:50], many=True).data
        data['invoices'] = InvoiceSerializer(
            sub.invoices.all()[:20], many=True,
        ).data
        return Response(data)

    def _get_subscription(self, request):
        return self.get_object()

    @extend_schema(request=ActivateRequestSerializer)
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Активация: свежий период N дней (по умолчанию 30) + разморозка."""
        serializer = ActivateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub = activate_subscription(
            self._get_subscription(request),
            days=serializer.validated_data.get('days'),
            actor=request.user, request=request,
            note=serializer.validated_data.get('note', ''),
        )
        return Response(SubscriptionSerializer(sub).data)

    @extend_schema(request=ExtendRequestSerializer)
    @action(detail=True, methods=['post'])
    def extend(self, request, pk=None):
        """Продление от max(now, expires_at) на N дней + разморозка."""
        serializer = ExtendRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub = extend_subscription(
            self._get_subscription(request),
            days=serializer.validated_data['days'],
            actor=request.user, request=request,
            note=serializer.validated_data.get('note', ''),
        )
        return Response(SubscriptionSerializer(sub).data)

    @extend_schema(request=NoteRequestSerializer)
    @action(detail=True, methods=['post'])
    def freeze(self, request, pk=None):
        """
        Ручная заморозка компании (любой статус -> FROZEN).

        Идёт через компании-контур (companies.subscriptions.freeze_company),
        который сериализует параллельные заморозки блокировкой строки Company и
        зеркалит статус в billing.Subscription. Прежний вызов
        billing.services.freeze_subscription был «заморозкой по истечению»
        (срабатывал только на active+просроченной подписке и возвращал bool) —
        кнопка «Заморозить» в API не работала для уже истёкших компаний и
        роняла сериализатор на bool.
        """
        serializer = NoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub = self._get_subscription(request)
        from apps.companies import subscriptions as company_subs
        company_subs.freeze_company(
            sub.company, actor=request.user,
            note=serializer.validated_data.get('note', ''),
        )
        sub.refresh_from_db()
        return Response(SubscriptionSerializer(sub).data)

    @extend_schema(request=NoteRequestSerializer)
    @action(detail=True, methods=['post'])
    def unfreeze(self, request, pk=None):
        """Ручная разморозка (срок должен быть в будущем, иначе 400)."""
        serializer = NoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub = unfreeze_subscription(
            self._get_subscription(request), actor=request.user, request=request,
            note=serializer.validated_data.get('note', ''),
        )
        return Response(SubscriptionSerializer(sub).data)

    @extend_schema(request=ConfirmPaymentSerializer)
    @action(detail=True, methods=['post'])
    def confirm_payment(self, request, pk=None):
        """Подтверждение оплаты счёта → подписка продлевается автоматически."""
        serializer = ConfirmPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub = self._get_subscription(request)
        invoice = get_object_or_404(Invoice, pk=serializer.validated_data['invoice_id'],
                                    subscription=sub)
        invoice = confirm_invoice_paid(invoice, actor=request.user, request=request)
        return Response(InvoiceSerializer(invoice).data)
