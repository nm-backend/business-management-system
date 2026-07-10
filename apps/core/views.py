from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from core.utils import get_locale
from .models import Currency, ExchangeRate
from .serializers import CurrencySerializer, ExchangeRateSerializer


class CurrencyViewSet(viewsets.ModelViewSet):
    queryset = Currency.objects.filter(is_active=True)
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticated]


class ExchangeRateViewSet(viewsets.ModelViewSet):
    queryset = ExchangeRate.objects.all()
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAuthenticated]


class LocaleView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, lang_code):
        allowed_languages = ['uz_cyrl', 'ru']
        if lang_code not in allowed_languages:
            return JsonResponse({'error': 'Language not supported'}, status=400)

        data = get_locale(lang_code)
        return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


class DashboardStatsView(APIView):
    """
    API для получения статистики дашборда.

    Возвращает ключевые метрики бизнеса в зависимости от роли пользователя:
    - Owner: все метрики включая финансовые
    - Admin: операционные метрики без финансовых данных
    - Worker: только свои задачи

    Endpoint: GET /api/v1/core/dashboard/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Возвращает статистику для дашборда.

        Собирает данные из разных моделей в зависимости от роли пользователя.
        """
        user = request.user
        today = timezone.now().date()
        data = {}

        try:
            from apps.orders.models import Order, OrderStatus
            # Заказы
            orders_qs = Order.objects.all()
            if user.is_worker:
                orders_qs = orders_qs.filter(worker=user)

            data['new_orders_count'] = orders_qs.filter(status=OrderStatus.NEW).count()
            data['in_progress_orders_count'] = orders_qs.filter(
                status__in=[OrderStatus.IN_PROGRESS, OrderStatus.SENT_TO_WORKER, OrderStatus.ACCEPTED_BY_WORKER]
            ).count()
            data['ready_orders_count'] = orders_qs.filter(status=OrderStatus.READY).count()
            data['overdue_orders_count'] = orders_qs.filter(is_overdue=True).count()
            data['total_orders_today'] = orders_qs.filter(created_at__date=today).count()
        except Exception:
            pass

        try:
            from apps.warehouse.models import RawMaterial, FinishedProduct
            from django.db.models import F
            # Склад
            data['low_stock_materials'] = RawMaterial.objects.filter(
                is_archived=False, quantity__lte=F('min_stock')
            ).count()
            data['total_materials'] = RawMaterial.objects.filter(is_archived=False).count()
            data['total_finished_products'] = FinishedProduct.objects.filter(is_archived=False).count()
        except Exception:
            pass

        try:
            from apps.production.models import Task, TaskStatus
            # Производство
            tasks_qs = Task.objects.all()
            if user.is_worker:
                tasks_qs = tasks_qs.filter(worker=user)

            data['pending_tasks'] = tasks_qs.filter(status=TaskStatus.PENDING).count()
            data['in_progress_tasks'] = tasks_qs.filter(status=TaskStatus.IN_PROGRESS).count()
            data['today_tasks'] = tasks_qs.filter(created_at__date=today).count()
        except Exception:
            pass

        try:
            from apps.clients.models import Client
            # Клиенты
            data['total_clients'] = Client.objects.filter(is_archived=False).count()
            data['clients_with_debt'] = Client.objects.filter(is_archived=False, debt__gt=0).count()
        except Exception:
            pass

        # Финансовые данные только для owner
        if user.is_owner:
            try:
                from apps.finance.models import Expense
                from apps.orders.models import Order

                # Доходы (оплаченные заказы)
                month_start = today.replace(day=1)
                monthly_income = Order.objects.filter(
                    updated_at__date__gte=month_start
                ).aggregate(total=Sum('paid_amount'))['total'] or 0
                data['monthly_income'] = str(monthly_income)

                # Расходы за месяц
                monthly_expenses = Expense.objects.filter(
                    date__gte=month_start
                ).aggregate(total=Sum('amount'))['total'] or 0
                data['monthly_expenses'] = str(monthly_expenses)

                # Общий долг клиентов
                from apps.clients.models import Client
                total_debt = Client.objects.filter(
                    is_archived=False
                ).aggregate(total=Sum('debt'))['total'] or 0
                data['total_client_debt'] = str(total_debt)

            except Exception:
                pass

        try:
            from apps.messaging.models import Notification
            # Непрочитанные уведомления
            data['unread_notifications'] = Notification.objects.filter(
                user=user, is_read=False
            ).count()
        except Exception:
            pass

        return Response(data)

