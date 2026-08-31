from __future__ import annotations
"""
Reports services — business logic and financial calculations.

Separated from views.py per SOLID (SRP): views handle HTTP,
services handle math. This file contains zero Django HTTP imports.
"""
import datetime
import calendar

from decimal import Decimal
from typing import Any, TypedDict

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.finance.models import Expense, ExpenseCategory, WorkerPayment
from apps.orders.models import Order
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial


# ── Typed dicts for return values ────────────────────────────────────────────

class PeriodFinancials(TypedDict):
    revenue: Decimal | int
    expenses_total: Decimal | int
    worker_payments: Decimal | int
    net_profit: Decimal | int


class DeltaDict(TypedDict, total=False):
    revenue: float | None
    net_profit: float | None
    expenses_total: float | None


class OwnerAnalyticsData(TypedDict):
    date_from: datetime.date
    date_to: datetime.date
    revenue: Decimal | int
    cost_of_goods: Decimal | int
    gross_profit: Decimal | int
    expenses_total: Decimal | int
    deltas: DeltaDict
    expenses_by_category: dict[str, Decimal | int]
    salaries: Decimal | int
    taxes: Decimal | int
    losses: Decimal | int
    owner_withdrawal: Decimal | int
    worker_payments: Decimal | int
    net_profit: Decimal | int
    cash: Decimal | int
    client_debts: Decimal | int
    worker_debts: Decimal | int
    orders_count: int
    orders_delivered: int
    top_products: list[dict[str, Any]]
    most_active_worker: dict[str, Any] | None
    active_employees_count: int
    overdue_percentage: float
    low_stock_count: int
    stock: dict[str, int]


class AdminAnalyticsData(TypedDict):
    orders_new: int
    orders_in_progress: int
    orders_ready: int
    orders_overdue: int
    awaiting_confirmation: int
    low_stock_materials: list[dict[str, Any]]
    worker_performance: list[dict[str, Any]]
    unpaid_clients: list[dict[str, Any]]


class RevenueTimelineData(TypedDict):
    labels: list[str]
    revenues: list[Decimal | int]
    net_profits: list[Decimal | int]


class QuarterlyReportData(TypedDict):
    year: int
    quarter: int
    date_from: datetime.date
    date_to: datetime.date
    months: list[OwnerAnalyticsData]
    total_revenue: Decimal | int
    total_cogs: Decimal | int
    total_gross_profit: Decimal | int
    total_expenses: Decimal | int
    total_worker_payments: Decimal | int
    total_net_profit: Decimal | int


# ── Helpers ──────────────────────────────────────────────────────────────────

def _money(value: Decimal | int | float | None) -> Decimal | int:
    """Coerce None/NULL aggregate results to 0."""
    return value or 0


def _pct_change(current: Decimal | int, previous: Decimal | int) -> float | None:
    """Percentage change of *current* relative to *previous*. None if base is 0."""
    current_f = float(current or 0)
    previous_f = float(previous or 0)
    if previous_f == 0:
        return None
    return round((current_f - previous_f) / previous_f * 100, 1)


def _quarter_bounds(year: int, quarter: int) -> tuple[datetime.date, datetime.date]:
    """Calendar quarter boundaries: Q1=Jan–Mar, Q2=Apr–Jun, Q3=Jul–Sep, Q4=Oct–Dec."""
    start_month = 3 * (quarter - 1) + 1
    start = datetime.date(year, start_month, 1)
    if start_month + 2 >= 12:
        end = datetime.date(year, 12, 31)
    else:
        end = datetime.date(year, start_month + 3, 1) - datetime.timedelta(days=1)
    return start, end


# ── Owner analytics (full financial data) ────────────────────────────────────

def get_period_financials(
    company_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
) -> PeriodFinancials:
    """Key financial totals for a period (used for period-over-period comparison)."""
    revenue = _money(
        Payment.objects.filter(
            company_id=company_id,
            payment_date__date__range=(date_from, date_to),
        ).aggregate(s=Sum('amount'))['s']
    )
    cost_of_goods = _money(
        Order.objects.filter(
            company_id=company_id,
            status=Order.Status.DELIVERED,
            delivered_at__date__range=(date_from, date_to),
        ).aggregate(
            s=Sum(ExpressionWrapper(
                F('quantity') * F('cost_price'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ))
        )['s']
    )
    expenses_total = _money(
        Expense.objects.filter(
            company_id=company_id,
            date__range=(date_from, date_to),
        ).aggregate(s=Sum('amount'))['s']
    )
    worker_payments = _money(
        WorkerPayment.objects.filter(
            company_id=company_id,
            payment_date__range=(date_from, date_to),
        ).aggregate(s=Sum('amount'))['s']
    )
    salaries = _money(
        Expense.objects.filter(
            company_id=company_id,
            date__range=(date_from, date_to),
            category__in=(ExpenseCategory.SALARY, ExpenseCategory.ADVANCE),
        ).aggregate(s=Sum('amount'))['s']
    )
    return {
        'revenue': revenue,
        'expenses_total': expenses_total,
        'worker_payments': worker_payments,
        'net_profit': revenue - cost_of_goods - (expenses_total - salaries) - worker_payments,
    }


def get_owner_analytics_data(
    company_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
) -> OwnerAnalyticsData:
    """
    Full financial analytics for the business owner.

    Formulas:
        Revenue       = SUM(Payment.amount) by delivered orders
        COGS          = SUM(Order.quantity × Order.cost_price) for delivered
        Gross Profit  = Revenue − COGS
        Net Profit    = Revenue − COGS − Expenses − WorkerPayments
        Cash          = Payments − NonSalaryExpenses − WorkerPayments
        Client Debt   = SUM(Client.debt)
        Worker Debt   = Σ confirmed labor_cost − Σ payments (accumulative)
    """
    # --- Revenue ---
    payments = Payment.objects.filter(
        company_id=company_id,
        payment_date__date__range=(date_from, date_to),
    )
    revenue = _money(payments.aggregate(s=Sum('amount'))['s'])

    # --- COGS (cost of goods sold) ---
    delivered = Order.objects.filter(
        company_id=company_id,
        status=Order.Status.DELIVERED,
        delivered_at__date__range=(date_from, date_to),
    ).select_related('product')
    cost_of_goods = _money(delivered.aggregate(
        s=Sum(ExpressionWrapper(
            F('quantity') * F('cost_price'),
            output_field=DecimalField(max_digits=15, decimal_places=2),
        )),
    )['s'])

    # --- Expenses breakdown ---
    expenses_qs = Expense.objects.filter(
        company_id=company_id,
        date__range=(date_from, date_to),
    )
    expenses_total = _money(expenses_qs.aggregate(s=Sum('amount'))['s'])

    def _expenses_by(*categories: ExpenseCategory) -> Decimal | int:
        return _money(
            expenses_qs.filter(category__in=categories)
            .aggregate(s=Sum('amount'))['s']
        )

    salaries = _expenses_by(ExpenseCategory.SALARY, ExpenseCategory.ADVANCE)
    taxes = _expenses_by(ExpenseCategory.TAXES)
    losses = _expenses_by(ExpenseCategory.MATERIAL_LOSS, ExpenseCategory.DEFECT)
    owner_withdrawal = _expenses_by(ExpenseCategory.OWNER_WITHDRAWAL)

    # --- Worker payments ---
    worker_payments = _money(
        WorkerPayment.objects.filter(
            company_id=company_id,
            payment_date__range=(date_from, date_to),
        ).aggregate(s=Sum('amount'))['s']
    )

    # --- Debts (accumulative, not period-bound) ---
    client_debts = _money(
        Client.objects.filter(company_id=company_id, is_archived=False)
        .aggregate(s=Sum('debt'))['s']
    )
    worker_earned = _money(
        WorkRecord.objects.filter(
            company_id=company_id,
            status=WorkRecord.WorkStatus.CONFIRMED,
        ).aggregate(s=Sum('labor_cost'))['s']
    )
    worker_paid_total = _money(
        WorkerPayment.objects.filter(company_id=company_id)
        .aggregate(s=Sum('amount'))['s']
    )
    worker_debts = max(worker_earned - worker_paid_total, 0)

    # --- Cash ---
    non_salary_expenses = _money(
        Expense.objects.filter(
            company_id=company_id,
            date__range=(date_from, date_to),
        ).exclude(category__in=(ExpenseCategory.SALARY, ExpenseCategory.ADVANCE))
        .aggregate(s=Sum('amount'))['s']
    )
    cash = revenue - non_salary_expenses - worker_payments

    # --- Top products & workers ---
    top_products = list(
        Order.objects.filter(
            company_id=company_id,
            status=Order.Status.DELIVERED,
            product__isnull=False,
            delivered_at__date__range=(date_from, date_to),
        ).values('product_id')
        .annotate(
            name=Max('product__name'),
            total_quantity=Sum('quantity'),
            orders=Count('id'),
        )
        .order_by('-total_quantity')[:5]
    )
    top_worker: dict[str, Any] | None = (
        WorkRecord.objects.filter(
            company_id=company_id,
            status=WorkRecord.WorkStatus.CONFIRMED,
            confirmed_at__date__range=(date_from, date_to),
        ).values('worker_id')
        .annotate(
            name=Max('worker__full_name'),
            username=Max('worker__username'),
            total_quantity=Sum('quantity'),
            works=Count('id'),
        )
        .order_by('-total_quantity')
        .first()
    )

    # --- Period comparison (for delta % arrows) ---
    orders_qs = Order.objects.filter(
        company_id=company_id,
        created_at__date__range=(date_from, date_to),
    )
    raw_qs = RawMaterial.objects.filter(company_id=company_id, is_archived=False)

    span = (date_to - date_from).days + 1
    prev_to = date_from - datetime.timedelta(days=1)
    prev_from = prev_to - datetime.timedelta(days=span - 1)
    prev = get_period_financials(company_id, prev_from, prev_to)
    net_profit = revenue - cost_of_goods - (expenses_total - salaries) - worker_payments

    # --- Employee counts ---
    active_employees = User.objects.filter(
        company_id=company_id,
        role__in=(User.Role.ADMIN, User.Role.WORKER),
        is_active=True,
        status=User.Status.ACTIVE,
    ).count()

    # --- Overdue percentage ---
    total_active_orders = orders_qs.exclude(
        status__in=(Order.Status.DELIVERED, Order.Status.CANCELLED),
    ).count()
    overdue_orders = orders_qs.filter(
        deadline__lt=timezone.now(),
    ).exclude(
        status__in=(Order.Status.DELIVERED, Order.Status.CANCELLED),
    ).count()
    overdue_percentage = (
        round((overdue_orders / total_active_orders) * 100, 1)
        if total_active_orders > 0 else 0
    )

    # --- Low stock ---
    low_stock_materials_count = sum(1 for m in raw_qs if m.is_low_stock)
    low_stock_products_count = sum(
        1 for p in FinishedProduct.objects.filter(
            company_id=company_id, is_archived=False,
        ) if p.is_low_stock
    )

    return {
        'date_from': date_from,
        'date_to': date_to,
        'revenue': revenue,
        'cost_of_goods': cost_of_goods,
        'gross_profit': revenue - cost_of_goods,
        'expenses_total': expenses_total,
        'deltas': {
            'revenue': _pct_change(revenue, prev['revenue']),
            'net_profit': _pct_change(net_profit, prev['net_profit']),
            'expenses_total': _pct_change(expenses_total, prev['expenses_total']),
        },
        'expenses_by_category': {
            row['category']: row['s']
            for row in expenses_qs.values('category').annotate(s=Sum('amount'))
        },
        'salaries': salaries,
        'taxes': taxes,
        'losses': losses,
        'owner_withdrawal': owner_withdrawal,
        'worker_payments': worker_payments,
        'net_profit': net_profit,
        'cash': cash,
        'client_debts': client_debts,
        'worker_debts': worker_debts,
        'orders_count': orders_qs.count(),
        'orders_delivered': orders_qs.filter(status=Order.Status.DELIVERED).count(),
        'top_products': top_products,
        'most_active_worker': top_worker,
        'active_employees_count': active_employees,
        'overdue_percentage': overdue_percentage,
        'low_stock_count': low_stock_materials_count + low_stock_products_count,
        'stock': {
            'raw_materials': raw_qs.count(),
            'low_stock_materials': low_stock_materials_count,
            'finished_products': FinishedProduct.objects.filter(
                company_id=company_id, is_archived=False,
            ).count(),
        },
    }


# ── Admin analytics (operational, no financial sums) ─────────────────────────

def get_admin_operational_analytics(company_id: int) -> AdminAnalyticsData:
    """Operational metrics for the administrator — NO financial data."""
    now = timezone.now()
    orders = Order.objects.filter(company_id=company_id, is_archived=False)
    active_statuses = (
        Order.Status.SENT_TO_WORKER,
        Order.Status.ACCEPTED,
        Order.Status.IN_PROGRESS,
        Order.Status.AWAITING_CONFIRMATION,
    )

    low_stock = [
        {
            'id': m.id, 'name': m.name, 'quantity': m.quantity,
            'min_stock': m.min_stock, 'unit': m.unit,
        }
        for m in RawMaterial.objects.filter(
            company_id=company_id, is_archived=False,
        ) if m.is_low_stock
    ]

    worker_performance = list(
        WorkRecord.objects.filter(
            company_id=company_id,
            status=WorkRecord.WorkStatus.CONFIRMED,
        ).values(
            worker_username=F('worker__username'),
            worker_full_name=F('worker__full_name'),
        )
        .annotate(total_quantity=Sum('quantity'), works=Count('id'))
        .order_by('-total_quantity')
    )

    unpaid_clients = list(
        Client.objects.filter(
            company_id=company_id, is_archived=False, debt__gt=0,
        ).values('id', 'name')
    )

    return {
        'orders_new': orders.filter(status=Order.Status.NEW).count(),
        'orders_in_progress': orders.filter(status__in=active_statuses).count(),
        'orders_ready': orders.filter(status=Order.Status.READY).count(),
        'orders_overdue': orders.filter(
            deadline__lt=now,
        ).exclude(
            status__in=(Order.Status.DELIVERED, Order.Status.CANCELLED),
        ).count(),
        'awaiting_confirmation': WorkRecord.objects.filter(
            company_id=company_id,
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        ).count(),
        'low_stock_materials': low_stock,
        'worker_performance': worker_performance,
        'unpaid_clients': unpaid_clients,
    }


# ── Revenue timeline (6-month chart data) ────────────────────────────────────

def get_revenue_timeline_data(company_id: int) -> RevenueTimelineData:
    """Monthly revenue and net profit for the last 6 months (chart data)."""
    today = timezone.localdate()
    six_months_ago = today - datetime.timedelta(days=180)

    payments = (
        Payment.objects.filter(
            company_id=company_id,
            payment_date__date__gte=six_months_ago,
        )
        .annotate(month=TruncMonth('payment_date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    expenses = (
        Expense.objects.filter(
            company_id=company_id,
            date__gte=six_months_ago,
        ).exclude(category__in=(ExpenseCategory.SALARY, ExpenseCategory.ADVANCE))
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    delivered = (
        Order.objects.filter(
            company_id=company_id,
            status=Order.Status.DELIVERED,
            delivered_at__date__gte=six_months_ago,
        )
        .annotate(month=TruncMonth('delivered_at'))
        .values('month')
        .annotate(
            cogs=Sum(ExpressionWrapper(
                F('quantity') * F('cost_price'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ))
        )
        .order_by('month')
    )

    payouts = (
        WorkerPayment.objects.filter(
            company_id=company_id,
            payment_date__gte=six_months_ago,
        )
        .annotate(month=TruncMonth('payment_date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    def _month_key(value: datetime.date | datetime.datetime) -> datetime.date:
        """Normalize TruncMonth result to a date (handles datetime vs date)."""
        return value.date() if isinstance(value, datetime.datetime) else value

    months_set: set[datetime.date] = set()
    rev_map: dict[datetime.date, Decimal | int] = {}
    for p in payments:
        m = _month_key(p['month'])
        months_set.add(m)
        rev_map[m] = _money(p['total'])

    exp_map: dict[datetime.date, Decimal | int] = {}
    for e in expenses:
        m = _month_key(e['month'])
        months_set.add(m)
        exp_map[m] = _money(e['total'])

    cogs_map: dict[datetime.date, Decimal | int] = {}
    for d in delivered:
        m = _month_key(d['month'])
        months_set.add(m)
        cogs_map[m] = _money(d['cogs'])

    payout_map: dict[datetime.date, Decimal | int] = {}
    for w in payouts:
        m = _month_key(w['month'])
        months_set.add(m)
        payout_map[m] = _money(w['total'])

    months = sorted(months_set, reverse=True)[:6]
    months.reverse()

    MONTH_NAMES: dict[int, str] = {
        1: 'Янв', 2: 'Фев', 3: 'Мар', 4: 'Апр', 5: 'Май', 6: 'Июн',
        7: 'Июл', 8: 'Авг', 9: 'Сен', 10: 'Окт', 11: 'Ноя', 12: 'Дек',
    }

    labels: list[str] = []
    revenues: list[Decimal | int] = []
    net_profits: list[Decimal | int] = []
    for m in months:
        label = f"{MONTH_NAMES.get(m.month, m.month)}'{str(m.year)[2:]}"
        labels.append(label)
        rev = rev_map.get(m, 0)
        exp = exp_map.get(m, 0)
        cogs = cogs_map.get(m, 0)
        payout = payout_map.get(m, 0)
        revenues.append(rev)
        net_profits.append(rev - cogs - exp - payout)

    return {
        'labels': labels,
        'revenues': revenues,
        'net_profits': net_profits,
    }


# ── Quarterly report data ────────────────────────────────────────────────────

def get_quarterly_report_data(
    company_id: int,
    year: int,
    quarter: int,
) -> QuarterlyReportData:
    """
    Quarterly financial summary combining owner analytics + period comparison.
    Returns data for Q1–Q4 with month-by-month breakdown.
    """
    date_from, date_to = _quarter_bounds(year, quarter)
    months_data: list[OwnerAnalyticsData] = []
    current = date_from
    while current <= date_to:
        month_end = min(
            current + datetime.timedelta(days=31),
            date_to,
        )
        # Clamp to end of month
        if month_end.month != current.month:
            month_end = datetime.date(
                current.year, current.month,
                calendar.monthrange(current.year, current.month)[1],
            )
        month_data = get_owner_analytics_data(company_id, current, month_end)
        months_data.append(month_data)
        # Advance to next month
        if current.month == 12:
            current = datetime.date(current.year + 1, 1, 1)
        else:
            current = datetime.date(current.year, current.month + 1, 1)

    # Aggregate quarter totals
    total_revenue = sum(m['revenue'] for m in months_data)
    total_cogs = sum(m['cost_of_goods'] for m in months_data)
    total_expenses = sum(m['expenses_total'] for m in months_data)
    total_worker_payments = sum(m['worker_payments'] for m in months_data)

    return {
        'year': year,
        'quarter': quarter,
        'date_from': date_from,
        'date_to': date_to,
        'months': months_data,
        'total_revenue': total_revenue,
        'total_cogs': total_cogs,
        'total_gross_profit': total_revenue - total_cogs,
        'total_expenses': total_expenses,
        'total_worker_payments': total_worker_payments,
        'total_net_profit': total_revenue - total_cogs - total_expenses - total_worker_payments,
    }
