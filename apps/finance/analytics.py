"""
Financial analytics service.

Реализует расчёт финансовых показателей по формулам из ТЗ.

Формулы:
- Выручка = сумма всех оплат по выданным заказам за период
- Себестоимость = сумма себестоимости проданных товаров
- Валовая прибыль = Выручка - Себестоимость
- Чистая прибыль = Выручка - Себестоимость - Зарплаты - Расходы - Налоги - Потери
- Деньги в кассе = Оплачено - Расходы - Выплаты - Вывод владельца
- Долги клиентов = сумма неоплаченных продаж
"""
import logging
from datetime import date, timedelta
from decimal import Decimal
from django.db.models import Sum, Q

logger = logging.getLogger(__name__)


def get_period_range(period, custom_start=None, custom_end=None):
    """
    Возвращает (date_from, date_to) для заданного периода.

    Аргументы:
        period: str - 'today', 'yesterday', 'week', 'month', 'quarter', 'year', 'custom'
        custom_start: str - дата начала для custom периода (YYYY-MM-DD)
        custom_end: str - дата конца для custom периода (YYYY-MM-DD)

    Возвращает:
        tuple(date, date) - (date_from, date_to)
    """
    today = date.today()

    if period == 'today':
        return today, today
    elif period == 'yesterday':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif period == 'week':
        week_start = today - timedelta(days=today.weekday())
        return week_start, today
    elif period == 'month':
        month_start = today.replace(day=1)
        return month_start, today
    elif period == 'quarter':
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        quarter_start = today.replace(month=quarter_month, day=1)
        return quarter_start, today
    elif period == 'year':
        year_start = today.replace(month=1, day=1)
        return year_start, today
    elif period == 'custom' and custom_start and custom_end:
        from datetime import datetime
        try:
            return (
                datetime.strptime(custom_start, '%Y-%m-%d').date(),
                datetime.strptime(custom_end, '%Y-%m-%d').date()
            )
        except (ValueError, TypeError):
            return today, today
    else:
        # Default: текущий месяц
        month_start = today.replace(day=1)
        return month_start, today


def calculate_analytics(period='month', custom_start=None, custom_end=None, user=None):
    """
    Рассчитывает все финансовые показатели за указанный период.

    Аргументы:
        period: str - период
        custom_start: str - кастомная дата начала
        custom_end: str - кастомная дата конца
        user: User - текущий пользователь (для RBAC)

    Возвращает:
        dict - финансовые показатели
    """
    date_from, date_to = get_period_range(period, custom_start, custom_end)

    result = {
        'period': {
            'key': period,
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
        },
        'revenue': '0',
        'cost_of_goods': '0',
        'gross_profit': '0',
        'expenses_total': '0',
        'salaries_total': '0',
        'taxes_total': '0',
        'losses_total': '0',
        'client_debts_total': '0',
        'worker_debts_total': '0',
        'owner_withdrawal_total': '0',
        'net_profit': '0',
        'cash_in_register': '0',
        'top_products': [],
        'worker_stats': [],
    }

    try:
        from apps.orders.models import Order, PaymentStatus

        # Выручка = сумма paid_amount заказов со статусом DELIVERED за период
        delivered_orders = Order.objects.filter(
            status='delivered',
            updated_at__date__gte=date_from,
            updated_at__date__lte=date_to,
        )
        revenue = delivered_orders.aggregate(total=Sum('paid_amount'))['total'] or Decimal('0')
        result['revenue'] = str(revenue)

        # Долги клиентов = сумма (total_amount - paid_amount) по неоплаченным заказам
        from django.db.models import F
        client_debts_qs = Order.objects.filter(
            ~Q(payment_status=PaymentStatus.PAID)
        ).annotate(
            debt=F('total_amount') - F('paid_amount')
        )
        client_debts = sum((item.debt for item in client_debts_qs), Decimal('0'))
        result['client_debts_total'] = str(client_debts)

        # Себестоимость проданного = сумма cost_price по доставленным заказам
        cost_of_goods = Decimal('0')
        for order in delivered_orders.select_related('product'):
            if order.product and order.product.cost_price:
                cost_of_goods += order.product.cost_price * order.quantity
        result['cost_of_goods'] = str(cost_of_goods)

    except Exception as e:
        logger.error(f"Analytics orders error: {e}")

    try:
        from apps.finance.models import Expense, ExpenseCategory

        # Расходы = сумма всех расходов за период
        expenses = Expense.objects.filter(date__gte=date_from, date__lte=date_to)
        result['expenses_total'] = str(
            expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        )

        # Налоги = расходы с категорией taxes
        taxes = expenses.filter(category=ExpenseCategory.TAXES)
        result['taxes_total'] = str(
            taxes.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        )

        # Потери = material_loss + defect
        losses = expenses.filter(
            category__in=[ExpenseCategory.MATERIAL_LOSS, ExpenseCategory.DEFECT]
        )
        result['losses_total'] = str(
            losses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        )

        # Личный вывод владельца
        owner_withdrawal = expenses.filter(category=ExpenseCategory.OWNER_WITHDRAWAL)
        result['owner_withdrawal_total'] = str(
            owner_withdrawal.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        )

    except Exception as e:
        logger.error(f"Analytics expenses error: {e}")

    try:
        from apps.finance.models import WorkerPayment

        # Зарплаты = сумма выплат работникам за период
        salaries = WorkerPayment.objects.filter(
            payment_date__gte=date_from,
            payment_date__lte=date_to,
        )
        result['salaries_total'] = str(
            salaries.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        )

    except Exception as e:
        logger.error(f"Analytics salaries error: {e}")

    # Валовая прибыль = Выручка - Себестоимость
    rev = Decimal(result['revenue'])
    cog = Decimal(result['cost_of_goods'])
    result['gross_profit'] = str(rev - cog)

    # Чистая прибыль = Выручка - Себестоимость - Зарплаты - Расходы - Налоги - Потери
    salaries = Decimal(result['salaries_total'])
    expenses = Decimal(result['expenses_total'])
    taxes = Decimal(result['taxes_total'])
    losses = Decimal(result['losses_total'])
    net_profit = rev - cog - salaries - expenses - taxes - losses
    result['net_profit'] = str(net_profit)

    # Деньги в кассе = Оплачено клиентами - Расходы - Выплаты - Вывод владельца
    owner_wd = Decimal(result['owner_withdrawal_total'])
    # total_paid это общая сумма paid_amount по всем заказам (не только за период)
    try:
        all_paid = Order.objects.aggregate(total=Sum('paid_amount'))['total'] or Decimal('0')
    except Exception:
        all_paid = Decimal('0')
    cash = all_paid - expenses - salaries - owner_wd
    result['cash_in_register'] = str(cash)

    # Самые продаваемые товары (за период)
    try:
        from apps.orders.models import Order
        product_sales = {}
        for order in Order.objects.filter(
            status='delivered',
            updated_at__date__gte=date_from,
            updated_at__date__lte=date_to,
        ):
            if order.product:
                product_sales[order.product.name] = product_sales.get(
                    order.product.name, Decimal('0')
                ) + order.quantity
        sorted_products = sorted(
            product_sales.items(), key=lambda x: x[1], reverse=True
        )[:5]
        result['top_products'] = [
            {'name': name, 'quantity': str(qty)}
            for name, qty in sorted_products
        ]
    except Exception as e:
        logger.error(f"Analytics top products error: {e}")

    # Активность работников
    try:
        from apps.production.models import WorkRecord
        worker_stats = {}
        for wr in WorkRecord.objects.filter(
            status='confirmed',
            confirmed_at__date__gte=date_from,
            confirmed_at__date__lte=date_to,
        ).select_related('worker'):
            name = wr.worker.username
            if name not in worker_stats:
                worker_stats[name] = {
                    'username': name,
                    'works_count': 0,
                    'total_quantity': Decimal('0'),
                    'total_earned': Decimal('0'),
                }
            worker_stats[name]['works_count'] += 1
            worker_stats[name]['total_quantity'] += wr.quantity
            worker_stats[name]['total_earned'] += wr.labor_cost

        result['worker_stats'] = sorted(
            [
                {'username': s['username'],
                 'works_count': s['works_count'],
                 'total_quantity': str(s['total_quantity']),
                 'total_earned': str(s['total_earned'])}
                for s in worker_stats.values()
            ],
            key=lambda x: x['works_count'],
            reverse=True
        )
    except Exception as e:
        logger.error(f"Analytics worker stats error: {e}")

    return result
