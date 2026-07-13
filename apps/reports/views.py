"""
Reports views - аналитика и экспорт отчётов.

- /analytics/owner/  - финансовая аналитика (только владелец).
- /analytics/admin/  - операционная аналитика без денег (владелец и админ).
- /export/...        - экспорт в Excel/PDF по ролям.

Формулы ТЗ:
    Выручка        = сумма оплат клиентов за период.
    Валовая прибыль = выручка - себестоимость проданного товара.
    Чистая прибыль  = выручка - себестоимость - расходы (включая зарплаты,
                      налоги, потери - это категории расходов).
    Касса           = все оплаты - все расходы - выплаты работникам.
"""
import datetime
import io

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.models import Client, Payment
from apps.core.permissions import IsCompanyMember
from apps.finance.models import Expense, ExpenseCategory, WorkerPayment
from apps.orders.models import Order
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial
from core.permissions import IsOwner, IsOwnerOrAdmin

MONEY = DecimalField(max_digits=15, decimal_places=2)


def parse_period(request):
    """Читает ?period= или ?date_from/?date_to; по умолчанию текущий месяц."""
    today = timezone.localdate()
    period = request.query_params.get('period', 'month')
    presets = {
        'today': (today, today),
        'yesterday': (today - datetime.timedelta(days=1), today - datetime.timedelta(days=1)),
        'week': (today - datetime.timedelta(days=7), today),
        'month': (today.replace(day=1), today),
        'quarter': (today - datetime.timedelta(days=91), today),
        'year': (today.replace(month=1, day=1), today),
    }
    date_from, date_to = presets.get(period, presets['month'])
    if request.query_params.get('date_from'):
        date_from = datetime.date.fromisoformat(request.query_params['date_from'])
    if request.query_params.get('date_to'):
        date_to = datetime.date.fromisoformat(request.query_params['date_to'])
    return date_from, date_to


def money(value):
    return value or 0


def pct_change(current, previous):
    """Процент изменения current относительно previous. None, если базы нет."""
    current = float(current or 0)
    previous = float(previous or 0)
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _period_financials(company_id, date_from, date_to):
    """Ключевые финансовые итоги за период (для сравнения периодов)."""
    revenue = money(
        Payment.objects.filter(company_id=company_id, payment_date__date__range=(date_from, date_to))
        .aggregate(s=Sum('amount'))['s']
    )
    cost_of_goods = money(
        Order.objects.filter(company_id=company_id, status=Order.Status.DELIVERED,
                             updated_at__date__range=(date_from, date_to))
        .aggregate(s=Sum(ExpressionWrapper(F('quantity') * F('product__cost_price'), output_field=MONEY)))['s']
    )
    expenses_total = money(
        Expense.objects.filter(company_id=company_id, date__range=(date_from, date_to))
        .aggregate(s=Sum('amount'))['s']
    )
    return {
        'revenue': revenue,
        'expenses_total': expenses_total,
        'net_profit': revenue - cost_of_goods - expenses_total,
    }


def owner_analytics_data(company_id, date_from, date_to):
    """Собирает все финансовые показатели владельца за период (в рамках компании)."""
    # Все выборки строго ограничены компанией владельца.
    payments = Payment.objects.filter(company_id=company_id, payment_date__date__range=(date_from, date_to))
    revenue = money(payments.aggregate(s=Sum('amount'))['s'])

    delivered = Order.objects.filter(
        company_id=company_id,
        status=Order.Status.DELIVERED,
        updated_at__date__range=(date_from, date_to),
    ).select_related('product')
    cost_of_goods = money(delivered.aggregate(
        s=Sum(ExpressionWrapper(F('quantity') * F('product__cost_price'), output_field=MONEY)),
    )['s'])

    expenses_qs = Expense.objects.filter(company_id=company_id, date__range=(date_from, date_to))
    expenses_total = money(expenses_qs.aggregate(s=Sum('amount'))['s'])

    def expenses_by(*categories):
        return money(expenses_qs.filter(category__in=categories).aggregate(s=Sum('amount'))['s'])

    salaries = expenses_by(ExpenseCategory.SALARY, ExpenseCategory.ADVANCE)
    taxes = expenses_by(ExpenseCategory.TAXES)
    losses = expenses_by(ExpenseCategory.MATERIAL_LOSS, ExpenseCategory.DEFECT)
    owner_withdrawal = expenses_by(ExpenseCategory.OWNER_WITHDRAWAL)

    worker_payments = money(
        WorkerPayment.objects.filter(company_id=company_id, payment_date__range=(date_from, date_to))
        .aggregate(s=Sum('amount'))['s']
    )

    client_debts = money(Client.objects.filter(company_id=company_id).aggregate(s=Sum('debt'))['s'])
    worker_earned = money(WorkRecord.objects.filter(
        company_id=company_id, status=WorkRecord.WorkStatus.CONFIRMED,
    ).aggregate(s=Sum('labor_cost'))['s'])
    worker_paid_total = money(
        WorkerPayment.objects.filter(company_id=company_id).aggregate(s=Sum('amount'))['s']
    )
    worker_debts = max(worker_earned - worker_paid_total, 0)

    # Касса считается за всё время (текущий остаток) в рамках компании.
    cash = (
        money(Payment.objects.filter(company_id=company_id).aggregate(s=Sum('amount'))['s'])
        - money(Expense.objects.filter(company_id=company_id).aggregate(s=Sum('amount'))['s'])
        - worker_paid_total
    )

    top_products = list(
        Order.objects.filter(company_id=company_id, status=Order.Status.DELIVERED, product__isnull=False,
                             updated_at__date__range=(date_from, date_to))
        .values(name=F('product__name'))
        .annotate(total_quantity=Sum('quantity'), orders=Count('id'))
        .order_by('-total_quantity')[:5]
    )
    top_worker = (
        WorkRecord.objects.filter(company_id=company_id, status=WorkRecord.WorkStatus.CONFIRMED,
                                  confirmed_at__date__range=(date_from, date_to))
        .values(name=F('worker__full_name'), username=F('worker__username'))
        .annotate(total_quantity=Sum('quantity'), works=Count('id'))
        .order_by('-total_quantity')
        .first()
    )

    orders_qs = Order.objects.filter(company_id=company_id, created_at__date__range=(date_from, date_to))
    raw_qs = RawMaterial.objects.filter(company_id=company_id, is_archived=False)

    # Сравнение с предыдущим равным по длине периодом (для стрелок % на дашборде).
    span = (date_to - date_from).days + 1
    prev_to = date_from - datetime.timedelta(days=1)
    prev_from = prev_to - datetime.timedelta(days=span - 1)
    prev = _period_financials(company_id, prev_from, prev_to)
    net_profit = revenue - cost_of_goods - expenses_total

    return {
        'date_from': date_from,
        'date_to': date_to,
        'revenue': revenue,
        'cost_of_goods': cost_of_goods,
        'gross_profit': revenue - cost_of_goods,
        'expenses_total': expenses_total,
        'deltas': {
            'revenue': pct_change(revenue, prev['revenue']),
            'net_profit': pct_change(net_profit, prev['net_profit']),
            'expenses_total': pct_change(expenses_total, prev['expenses_total']),
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
        'net_profit': revenue - cost_of_goods - expenses_total,
        'cash': cash,
        'client_debts': client_debts,
        'worker_debts': worker_debts,
        'orders_count': orders_qs.count(),
        'orders_delivered': orders_qs.filter(status=Order.Status.DELIVERED).count(),
        'top_products': top_products,
        'most_active_worker': top_worker,
        'stock': {
            'raw_materials': raw_qs.count(),
            'low_stock_materials': sum(1 for m in raw_qs if m.is_low_stock),
            'finished_products': FinishedProduct.objects.filter(
                company_id=company_id, is_archived=False).count(),
        },
    }


def admin_analytics_data(company_id):
    """Операционные показатели без денег (для администратора), в рамках компании."""
    now = timezone.now()
    orders = Order.objects.filter(company_id=company_id, is_archived=False)
    active_statuses = (
        Order.Status.SENT_TO_WORKER, Order.Status.ACCEPTED, Order.Status.IN_PROGRESS,
        Order.Status.AWAITING_CONFIRMATION,
    )
    low_stock = [
        {
            'id': m.id, 'name': m.name, 'quantity': m.quantity,
            'min_stock': m.min_stock, 'unit': m.unit,
        }
        for m in RawMaterial.objects.filter(company_id=company_id, is_archived=False)
        if m.is_low_stock
    ]
    worker_performance = list(
        WorkRecord.objects.filter(company_id=company_id, status=WorkRecord.WorkStatus.CONFIRMED)
        .values(worker_username=F('worker__username'), worker_full_name=F('worker__full_name'))
        .annotate(total_quantity=Sum('quantity'), works=Count('id'))
        .order_by('-total_quantity')
    )
    unpaid_clients = list(
        Client.objects.filter(company_id=company_id, is_archived=False, debt__gt=0).values('id', 'name')
    )
    return {
        'orders_new': orders.filter(status=Order.Status.NEW).count(),
        'orders_in_progress': orders.filter(status__in=active_statuses).count(),
        'orders_ready': orders.filter(status=Order.Status.READY).count(),
        'orders_overdue': orders.filter(
            deadline__lt=now,
        ).exclude(status__in=(Order.Status.DELIVERED, Order.Status.CANCELLED)).count(),
        'awaiting_confirmation': WorkRecord.objects.filter(
            company_id=company_id, status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        ).count(),
        'low_stock_materials': low_stock,
        'worker_performance': worker_performance,
        'unpaid_clients': unpaid_clients,
    }


class OwnerAnalyticsView(APIView):
    """GET /api/v1/reports/analytics/owner/?period=month - только владелец."""
    permission_classes = [IsCompanyMember, IsOwner]

    def get(self, request):
        date_from, date_to = parse_period(request)
        return Response(owner_analytics_data(request.user.company_id, date_from, date_to))


class AdminAnalyticsView(APIView):
    """GET /api/v1/reports/analytics/admin/ - владелец и администратор."""
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]

    def get(self, request):
        return Response(admin_analytics_data(request.user.company_id))


def xlsx_response(rows, filename, sheet_title):
    """Собирает xlsx из списка строк и возвращает как HTTP ответ."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def pdf_response(title, rows, filename):
    """Простой табличный PDF отчёт (reportlab)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    # Arial поддерживает кириллицу; стандартный Helvetica - нет.
    font_name = 'Helvetica'
    try:
        pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
        font_name = 'Arial'
    except Exception:
        pass

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    styles['Title'].fontName = font_name
    table = Table([[str(c) for c in row] for row in rows])
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1c64d9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f6fb')]),
    ]))
    doc.build([Paragraph(title, styles['Title']), Spacer(1, 12), table])
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


class OwnerFinanceExportView(APIView):
    """GET /api/v1/reports/export/finance/?format=xlsx|pdf - полный финансовый отчёт."""
    permission_classes = [IsCompanyMember, IsOwner]

    def get(self, request):
        date_from, date_to = parse_period(request)
        data = owner_analytics_data(request.user.company_id, date_from, date_to)
        rows = [
            ['Кўрсаткич', 'Қиймат'],
            ['Давр', f"{date_from} - {date_to}"],
            ['Даромад', data['revenue']],
            ['Таннарх', data['cost_of_goods']],
            ['Ялпи фойда', data['gross_profit']],
            ['Харажатлар', data['expenses_total']],
            ['Иш ҳақилар', data['salaries']],
            ['Солиқлар', data['taxes']],
            ['Йўқотишлар', data['losses']],
            ['Эгаси чиқими', data['owner_withdrawal']],
            ['Соф фойда', data['net_profit']],
            ['Касса', data['cash']],
            ['Мижозлар қарзи', data['client_debts']],
            ['Ишчилар қарзи', data['worker_debts']],
            ['Буюртмалар', data['orders_count']],
        ]
        if request.query_params.get('format') == 'pdf':
            return pdf_response('SkladPro.Nod - Молиявий ҳисобот', rows, 'finance-report.pdf')
        return xlsx_response(rows, 'finance-report.xlsx', 'Finance')


class AdminStockExportView(APIView):
    """GET /api/v1/reports/export/stock/ - складские остатки без цен (админ/владелец)."""
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]

    def get(self, request):
        company_id = request.user.company_id
        rows = [['Номи', 'Тури', 'Миқдор', 'Бирлик', 'Мин. қолдиқ', 'Етишмайди']]
        for m in RawMaterial.objects.filter(company_id=company_id, is_archived=False).order_by('name'):
            rows.append([
                m.name, m.stone_type, m.quantity, m.get_unit_display(),
                m.min_stock, 'Ха' if m.is_low_stock else '',
            ])
        rows.append([])
        rows.append(['Тайёр маҳсулот', '', '', '', '', ''])
        for p in FinishedProduct.objects.filter(company_id=company_id, is_archived=False).order_by('name'):
            rows.append([
                p.name, p.category, p.quantity, p.get_unit_display(),
                p.min_stock, 'Ха' if p.is_low_stock else '',
            ])
        if request.query_params.get('format') == 'pdf':
            return pdf_response('SkladPro.Nod - Омбор қолдиқлари', rows, 'stock-report.pdf')
        return xlsx_response(rows, 'stock-report.xlsx', 'Stock')


class AdminOrdersExportView(APIView):
    """GET /api/v1/reports/export/orders/ - список заказов без сумм (админ/владелец)."""
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]

    def get(self, request):
        rows = [['#', 'Мижоз', 'Маҳсулот', 'Миқдор', 'Ҳолат', 'Тўлов', 'Муддат']]
        orders = Order.objects.filter(
            company_id=request.user.company_id, is_archived=False,
        ).select_related('client', 'product')
        for o in orders:
            rows.append([
                o.id, o.client.name,
                o.product.name if o.product else o.custom_product_name,
                o.quantity, o.get_status_display(), o.get_payment_status_display(),
                o.deadline.date() if o.deadline else '',
            ])
        if request.query_params.get('format') == 'pdf':
            return pdf_response('SkladPro.Nod - Буюртмалар', rows, 'orders-report.pdf')
        return xlsx_response(rows, 'orders-report.xlsx', 'Orders')


class AdminWorkExportView(APIView):
    """GET /api/v1/reports/export/work/ - выработка работников по количеству."""
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]

    def get(self, request):
        rows = [['Ишчи', 'Тасдиқланган ишлар', 'Умумий миқдор']]
        for row in admin_analytics_data(request.user.company_id)['worker_performance']:
            rows.append([
                row['worker_full_name'] or row['worker_username'],
                row['works'], row['total_quantity'],
            ])
        if request.query_params.get('format') == 'pdf':
            return pdf_response('SkladPro.Nod - Ишчилар иши', rows, 'work-report.pdf')
        return xlsx_response(rows, 'work-report.xlsx', 'Work')
