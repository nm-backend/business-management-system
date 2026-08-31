"""
Reports views - HTTP layer only (DRF validation + service calls).

All business logic and financial calculations live in services.py
(Thin Controller pattern).
"""
import datetime
import io

from apps.core.validators import parse_date_param, parse_int_param
from django.db.models import Count, F, Sum
from django.http import HttpResponse
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.models import Payment
from apps.core.permissions import IsCompanyMember
from apps.finance.models import ExpenseCategory
from apps.orders.models import Order
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial
from core.permissions import IsOwner, IsOwnerOrAdmin, IsOwnerOrAdminOrManager

# Service layer — all calculations
from .services import (
    get_owner_analytics_data,
    get_admin_operational_analytics,
    get_revenue_timeline_data,
    get_quarterly_report_data,
    _quarter_bounds,
)


def _parse_period(request):
    """
    Parse report period from query params.
    Priority: quarter → date_from/date_to → period preset.
    """
    from django.utils import timezone
    today = timezone.localdate()

    if request.query_params.get('quarter'):
        quarter = parse_int_param(request.query_params['quarter'], 'quarter')
        if quarter < 1 or quarter > 4:
            raise ValidationError({'quarter': 'Quarter must be 1..4'})
        year = today.year
        if request.query_params.get('year'):
            year = parse_int_param(request.query_params['year'], 'year')
        return _quarter_bounds(year, quarter)

    from django.utils import timezone
    current_quarter = (today.month - 1) // 3 + 1
    quarter_start, _ = _quarter_bounds(today.year, current_quarter)
    presets = {
        'today': (today, today),
        'yesterday': (today - datetime.timedelta(days=1), today - datetime.timedelta(days=1)),
        'week': (today - datetime.timedelta(days=today.weekday()), today),
        'month': (today.replace(day=1), today),
        'quarter': (quarter_start, today),
        'year': (today.replace(month=1, day=1), today),
    }
    period = request.query_params.get('period', 'month')
    date_from, date_to = presets.get(period, presets['month'])
    if request.query_params.get('date_from'):
        date_from = parse_date_param(request.query_params['date_from'], 'date_from')
    if request.query_params.get('date_to'):
        date_to = parse_date_param(request.query_params['date_to'], 'date_to')
    if date_from > date_to:
        raise ValidationError({
            'date_from': 'Start date is after end date.',
            'date_to': 'End date is before start date.',
        })
    return date_from, date_to


class OwnerAnalyticsView(APIView):
    """GET /api/v1/reports/analytics/owner/?period=month — owner only."""
    permission_classes = [IsCompanyMember, IsOwner]

    def get(self, request):
        date_from, date_to = _parse_period(request)
        return Response(get_owner_analytics_data(request.user.company_id, date_from, date_to))


class RevenueTimelineView(APIView):
    """GET /api/v1/reports/analytics/revenue-timeline/ — 6-month chart, owner only."""
    permission_classes = [IsCompanyMember, IsOwner]

    def get(self, request):
        return Response(get_revenue_timeline_data(request.user.company_id))


class AdminAnalyticsView(APIView):
    """GET /api/v1/reports/analytics/admin/ — operational, no financial sums."""
    permission_classes = [IsCompanyMember, IsOwnerOrAdminOrManager]

    def get(self, request):
        return Response(get_admin_operational_analytics(request.user.company_id))


def _sanitize_xlsx_cell(value):
    """
    Защита от Formula Injection (CSV/Excel injection).

    Значение-строка, начинающееся с = + - @ (или tab/CR/LF), в Excel/LibreOffice
    трактуется как формула: например имя клиента '=HYPERLINK(...)' или
    '=1+2' исполнилось бы при открытии отчёта. Префиксуем апострофом — тогда
    ячейка показывается как обычный текст. Числа (Decimal/int) не трогаем.
    """
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r', '\n'):
        return "'" + value
    return value


def xlsx_response(rows, filename, sheet_title):
    """Собирает xlsx из списка строк и возвращает как HTTP ответ."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title
    for row in rows:
        sheet.append([_sanitize_xlsx_cell(cell) for cell in row])
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _csv_safe_cell(cell):
    """Защита от Formula Injection для CSV.

    В отличие от xlsx, Excel интерпретирует и '-' как начало формулы, но
    отрицательные суммы в отчётах — числа (Decimal/int), их не трогаем.
    Строки ('=HYPERLINK(...)', '=1+2', '-1+2' и т.п.) префиксуем апострофом.
    """
    if cell is None:
        return ''
    if isinstance(cell, str):
        starts_formula = (
            cell[:1] in ('=', '+', '@', '\t', '\r', '\n')
            or (cell[:1] == '-' and len(cell) > 1 and cell[1].isdigit())
        )
        if starts_formula:
            return "'" + cell
        return cell
    return str(cell)


def csv_response(rows, filename):
    """Собирает CSV из списка строк и возвращает как HTTP ответ.

    CSV с разделителем «;» — Excel открывает его сразу без ручного выбора
    разделителя. Раньше запрос ?format=csv молча отдавал xlsx (иного формата
    в этих вьюхах не было) — теперь формат честно поддерживается.
    """
    import csv

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=';')
    writer.writerows([_csv_safe_cell(cell) for cell in row] for row in rows)
    response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def register_report_font():
    """
    Регистрирует Unicode-шрифт с кириллицей кроссплатформенно и возвращает его имя.

    Раньше путь был жёстко задан как 'C:/Windows/Fonts/arial.ttf' — на Linux/Docker
    его нет, reportlab молча падал в Helvetica, и кириллица в PDF не рендерилась.
    Теперь ищем шрифт по списку типичных путей (Linux/Windows/macOS) + переменная
    окружения PDF_FONT_PATH. В Docker-образ ставится fonts-dejavu-core, поэтому на
    Linux берётся DejaVuSans (полная кириллица). Если ничего не нашли — Helvetica
    (без кириллицы, но генерация PDF не падает).
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if 'ReportFont' in pdfmetrics.getRegisteredFontNames():
        return 'ReportFont'

    path = resolve_report_font_path()
    if path:
        try:
            pdfmetrics.registerFont(TTFont('ReportFont', path))
            return 'ReportFont'
        except Exception:
            pass
    return 'Helvetica'


def resolve_report_font_path():
    """
    Возвращает путь к первому найденному Unicode-шрифту (с кириллицей) или None.

    Порядок: PDF_FONT_PATH -> DejaVu (Linux) -> Liberation -> Arial (Win) -> macOS.
    Все перечисленные шрифты содержат кириллицу; в Docker-образ ставится
    fonts-dejavu-core, поэтому на Linux путь DejaVu существует.
    """
    import os

    candidates = [os.environ.get('PDF_FONT_PATH')]
    candidates += [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',   # Debian/Ubuntu (fonts-dejavu-core)
        '/usr/share/fonts/dejavu/DejaVuSans.ttf',            # Fedora/RHEL
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        'C:/Windows/Fonts/arial.ttf',                        # Windows
        '/Library/Fonts/Arial.ttf',                          # macOS
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def pdf_response(title, rows, filename):
    """Простой табличный PDF отчёт (reportlab)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    font_name = register_report_font()

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
        date_from, date_to = _parse_period(request)
        data = get_owner_analytics_data(request.user.company_id, date_from, date_to)
        rows = [
            ['Кўрсаткич', 'Қиймат'],
            ['Давр', f"{date_from} - {date_to}"],
            ['Даромад', data['revenue']],
            ['Таннарх', data['cost_of_goods']],
            ['Ялпи фойда', data['gross_profit']],
            ['Харажатлар', data['expenses_total']],
            ['Иш ҳақилар', data['salaries']],
            # Выплаты работникам — отдельный отток (не Expense): без этой строки
            # «Харажатлар» + «Иш ҳақилар» не сходились с «Соф фойда», которая их
            # вычитает (см. owner_analytics_data: net_profit = revenue - cogs -
            # expenses - worker_payments).
            ['Ишчиларга тўловлар', data['worker_payments']],
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
        if request.query_params.get('format') == 'csv':
            return csv_response(rows, 'finance-report.csv')
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
        if request.query_params.get('format') == 'csv':
            return csv_response(rows, 'stock-report.csv')
        return xlsx_response(rows, 'stock-report.xlsx', 'Stock')


class AdminOrdersExportView(APIView):
    """GET /api/v1/reports/export/orders/ - список заказов без сумм (админ/владелец)."""
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]

    def get(self, request):
        is_owner = request.user.is_owner
        rows = [['#', 'Мижоз', 'Маҳсулот', 'Миқдор', 'Ҳолат', 'Тўлов', 'Муддат']]
        # Колонка долга — только для владельца: суммы (total_amount, paid_amount)
        # администратору не видны нигде в системе, и в отчёте их быть не должно.
        # Раньше в экспорте не было и для владельца — «сколько клиент ещё
        # должен по этому заказу» приходилось считать вручную из двух других
        # отчётов. Долг = сумма заказа минус фактически оплаченное.
        if is_owner:
            rows[0].append('Қарз')
        orders = Order.objects.filter(
            company_id=request.user.company_id, is_archived=False,
        ).select_related('client', 'product')
        paid_by_order = {}
        if is_owner:
            paid_by_order = dict(
                Payment.objects.filter(
                    company_id=request.user.company_id, order__isnull=False,
                ).values('order').annotate(total=Sum('amount'))
                .values_list('order', 'total')
            )
        for o in orders:
            row = [
                o.id, o.client.name,
                o.product.name if o.product else o.custom_product_name,
                o.quantity, o.get_status_display(), o.get_payment_status_display(),
                o.deadline.date() if o.deadline else '',
            ]
            if is_owner:
                row.append(o.total_amount - (paid_by_order.get(o.id) or 0))
            rows.append(row)
        if request.query_params.get('format') == 'pdf':
            return pdf_response('SkladPro.Nod - Буюртмалар', rows, 'orders-report.pdf')
        if request.query_params.get('format') == 'csv':
            return csv_response(rows, 'orders-report.csv')
        return xlsx_response(rows, 'orders-report.xlsx', 'Orders')


class AdminWorkExportView(APIView):
    """GET /api/v1/reports/export/work/ - выработка работников.

    Админ получает количества (без денег). Для владельца отчёт по сотрудникам
    обязан показывать и деньги: сколько начислено за подтверждённые работы
    (labor_cost). Раньше владелец видел в этом отчёте ровно то же, что и админ,
    — суммы пришлось бы собирать вручную из другой страницы.
    """
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]

    def get(self, request):
        company_id = request.user.company_id
        is_owner = request.user.is_owner
        rows = [['Ишчи', 'Тасдиқланган ишлар', 'Умумий миқдор']]
        if is_owner:
            rows[0].append('Начислено')
        qs = (
            WorkRecord.objects.filter(company_id=company_id, status=WorkRecord.WorkStatus.CONFIRMED)
            .values(worker_username=F('worker__username'), worker_full_name=F('worker__full_name'))
            .annotate(total_quantity=Sum('quantity'), works=Count('id'))
            .order_by('-total_quantity')
        )
        if is_owner:
            qs = qs.annotate(labor=Sum('labor_cost'))
        for row in qs:
            line = [
                row['worker_full_name'] or row['worker_username'],
                row['works'], row['total_quantity'],
            ]
            if is_owner:
                line.append(row.get('labor') or 0)
            rows.append(line)
        if request.query_params.get('format') == 'pdf':
            return pdf_response('SkladPro.Nod - Ишчилар иши', rows, 'work-report.pdf')
        if request.query_params.get('format') == 'csv':
            return csv_response(rows, 'work-report.csv')
        return xlsx_response(rows, 'work-report.xlsx', 'Work')


class ExportReportAPIView(APIView):
    """GET /api/v1/reports/export/?report_type=material_shortage&format_type=pdf"""
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]

    def get(self, request):
        report_type = request.query_params.get('report_type')
        if report_type == 'material_shortage':
            company_id = request.user.company_id
            rows = [['Номи', 'Тури', 'Миқдор', 'Бирлик', 'Мин. қолдиқ', 'Камомад']]
            # Считаем по ДОСТУПНОМУ остатку (минус потребность под заказы), как
            # карточка склада (is_low_stock): иначе материал «в норме» по
            # физическому остатку, но целиком требуемый под заказы, не попадает
            # в отчёт о нехватке.
            for m in RawMaterial.objects.filter(
                company_id=company_id, is_archived=False,
            ).annotate(available=F('quantity') - F('required_for_orders')).filter(available__lt=F('min_stock')).order_by('name'):
                rows.append([
                    m.name, m.stone_type, m.quantity, m.get_unit_display(),
                    m.min_stock, m.min_stock - m.available
                ])
            format_type = request.query_params.get('format_type', 'xlsx')
            if format_type == 'pdf':
                return pdf_response('SkladPro.Nod - Материал етишмовчилиги', rows, 'shortage-report.pdf')
            if format_type == 'csv':
                return csv_response(rows, 'shortage-report.csv')
            return xlsx_response(rows, 'shortage-report.xlsx', 'Shortage')
        return Response({"error": "Unsupported report type"}, status=400)
