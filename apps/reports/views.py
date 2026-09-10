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

from apps.audit.models import AuditLog
from apps.audit.services import write_audit_log
from apps.clients.models import Payment
from apps.core.permissions import IsCompanyMember
from apps.finance.models import ExpenseCategory
from apps.orders.models import Order
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial
from core.permissions import IsOwner, IsOwnerOrAdmin, IsOwnerOrAdminOrManager
from core.utils import translate

# Service layer — all calculations
from .services import (
    get_owner_analytics_data,
    get_quarterly_operational_report,
    get_admin_operational_analytics,
    get_revenue_timeline_data,
    get_quarterly_report_data,
    _quarter_bounds,
)


def _lang(request):
    """
    Язык получателя отчёта.

    По ТЗ отчёты и экспорты локализованы: заголовки и шапки таблиц брались
    из кода (жёстко по-узбекски) независимо от языка пользователя.
    """
    return getattr(request.user, 'language', None) or 'uz_cyrl'


def _report_title(request, key):
    """«SkladPro.Nod — <название отчёта>» на языке пользователя."""
    lang = _lang(request)
    return f"{translate('app.name', lang)} - {translate(key, lang)}"


def _parse_period(request):
    """
    Parse report period from query params.
    Priority: quarter → date_from/date_to → period preset.

    Custom range (ТЗ §18 / макет «хусусий»): оба параметра обязательны.
    Границы считает только сервер; фронт не подставляет today/week сам.
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

    raw_from = request.query_params.get('date_from')
    raw_to = request.query_params.get('date_to')
    # Пара пришла неполной: один конец без другого — не подставляем
    # «текущий месяц» молча, иначе custom-фильтр врёт.
    if bool(raw_from) ^ bool(raw_to):
        missing = 'date_to' if raw_from else 'date_from'
        raise ValidationError({missing: 'Both date_from and date_to are required.'})

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
    if raw_from:
        date_from = parse_date_param(raw_from, 'date_from')
    if raw_to:
        date_to = parse_date_param(raw_to, 'date_to')
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
        return Response(get_revenue_timeline_data(request.user.company_id, _lang(request)))


class SalesHistoryView(APIView):
    """
    GET /api/v1/reports/analytics/sales/?period=month|today|...|&date_from&date_to

    Экран «Продажи» (ТЗ: список главных экранов хозяина): выданные клиенту
    заказы за период с деньгами — только владелец (IsOwner, как и вся
    финансовая аналитика). Показатели:
      * count       — количество продаж (выдач) за период;
      * total_amount— сумма продаж (Σ total_amount выданных заказов);
      * paid        — оплачено по ним (Σ paid_amount);
      * debt        — остаток долга (Σ max(total − paid, 0));
    плюс сам список выдач в хронологическом порядке.
    Периоды считает только сервер (_parse_period): today/yesterday/week/
    month/quarter/year + custom date_from/date_to.
    """
    permission_classes = [IsCompanyMember, IsOwner]

    def get(self, request):
        date_from, date_to = _parse_period(request)
        orders = (
            Order.objects.filter(
                company_id=request.user.company_id,
                status=Order.Status.DELIVERED,
                is_archived=False,
                delivered_at__date__gte=date_from,
                delivered_at__date__lte=date_to,
            )
            .select_related('client', 'product')
            .order_by('-delivered_at', '-id')
        )
        total_amount = sum((o.total_amount or 0) for o in orders)
        paid = sum((o.paid_amount or 0) for o in orders)
        return Response({
            'date_from': date_from,
            'date_to': date_to,
            'count': orders.count(),
            'total_amount': total_amount,
            'paid': paid,
            'debt': max(total_amount - paid, 0),
            'orders': [
                {
                    'id': o.id,
                    'client': o.client_id,
                    'delivered_at': o.delivered_at,
                    'client_name': o.client.name,
                    'product_name': (o.product.name if o.product else o.custom_product_name),
                    'quantity': o.quantity,
                    'unit': o.unit,
                    'total_amount': o.total_amount,
                    'paid_amount': o.paid_amount,
                    'debt': max((o.total_amount or 0) - (o.paid_amount or 0), 0),
                    'payment_status': o.payment_status,
                }
                for o in orders
            ],
        })


class QuarterlyReportView(APIView):
    """
    GET /api/v1/reports/analytics/quarterly/?year=2026&quarter=3

    Квартальный отчёт в двух вариантах, как требует ТЗ:
      * владелец — финансовый (выручка, себестоимость, прибыль, расходы);
      * администратор — операционный, без единой денежной цифры.

    Раньше квартальный расчёт существовал только в services и наружу не
    выходил: фронтенд собирал квартал сам из шести обычных периодов, а
    администратору квартальный отчёт был недоступен вовсе.
    """
    permission_classes = [IsCompanyMember, IsOwnerOrAdminOrManager]

    def get(self, request):
        today = datetime.date.today()
        year = parse_int_param(request.query_params.get('year', today.year), 'year')
        quarter = parse_int_param(
            request.query_params.get('quarter', (today.month - 1) // 3 + 1), 'quarter',
        )
        if quarter < 1 or quarter > 4:
            raise ValidationError({'quarter': 'Quarter must be 1..4'})
        if year < 2000 or year > today.year + 1:
            raise ValidationError({'year': 'Year is out of range'})

        company_id = request.user.company_id
        if request.user.is_owner:
            data = get_quarterly_report_data(company_id, year, quarter)
            data['kind'] = 'financial'
            # «Отчёт готов» (ТЗ: уведомление владельца). Создаём один раз на
            # пару год/квартал — повторные открытия отчёта не спамят ленту.
            self._notify_report_ready(request, year, quarter)
            return Response(data)

        # Администратор и менеджер: только операционные показатели.
        data = get_quarterly_operational_report(company_id, year, quarter)
        data['kind'] = 'operational'
        return Response(data)

    @staticmethod
    def _notify_report_ready(request, year, quarter):
        """Уведомление владельцу «Отчёт готов» (один раз на квартал)."""
        from apps.messaging.models import Notification
        from apps.messaging.services import notify
        already_sent = Notification.objects.filter(
            user=request.user,
            type=Notification.NotificationType.REPORT_READY,
            company_id=request.user.company_id,
            params__year=year,
            params__quarter=quarter,
        ).exists()
        if already_sent:
            return
        notify(
            request.user,
            Notification.NotificationType.REPORT_READY,
            title_key='notifications.report_ready',
            message_key='notifications.msg_report_ready',
            params={'year': year, 'quarter': quarter},
            company=request.user.company,
        )


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


def export_options(request):
    """
    Параметры выгрузки из макета «Ҳисобот экспорти».

    Три тумблера: «График ва диаграммаларни қўшиш», «Изоҳ ва ёрдамчиларни
    қўшиш», «Детallashtirilgan маълумот». Каждый ДОЛЖЕН менять файл — тумблер,
    который ничего не делает, хуже его отсутствия.

    Права параметры не расширяют: детализация администратора остаётся без
    сумм, потому что данные для него собираются тем же кодом.
    """
    def flag(name):
        value = request.query_params.get(name, '')
        return str(value).lower() in ('1', 'true', 'yes', 'on')

    return {
        'charts': flag('charts'),
        'notes': flag('notes'),
        'detailed': flag('detailed'),
    }


def _bar_chart(chart_data, font_name):
    """
    Столбчатая диаграмма для PDF (reportlab.graphics).

    chart_data: [(подпись, число), ...]. Рисуется только по числовым строкам
    отчёта — рисовать «график» из текста бессмысленно.
    """
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors

    drawing = Drawing(460, 200)
    chart = VerticalBarChart()
    chart.x, chart.y = 40, 40
    chart.width, chart.height = 380, 130
    chart.data = [[float(value) for _, value in chart_data]]
    chart.categoryAxis.categoryNames = [str(label)[:14] for label, _ in chart_data]
    chart.categoryAxis.labels.fontName = font_name
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.dy = -12
    chart.valueAxis.labels.fontName = font_name
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.valueMin = min([0] + [float(v) for _, v in chart_data])
    chart.bars[0].fillColor = colors.HexColor('#1c64d9')
    drawing.add(chart)
    drawing.add(String(0, 185, '', fontName=font_name))
    return drawing


def pdf_response(title, rows, filename, options=None, notes=None, chart_data=None):
    """
    Табличный PDF отчёт (reportlab).

    options — словарь из export_options(). Влияние параметров:
      * charts — добавляет столбчатую диаграмму по числовым строкам;
      * notes  — добавляет блок пояснений (formulas/подсказки) после таблицы.
    Детализацию (detailed) собирает сама вьюха: она меняет СОСТАВ строк.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    options = options or {}
    font_name = register_report_font()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    styles['Title'].fontName = font_name
    styles['Normal'].fontName = font_name
    table = Table([[str(c) for c in row] for row in rows])
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1c64d9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f6fb')]),
    ]))

    story = [Paragraph(title, styles['Title']), Spacer(1, 12), table]

    if options.get('charts') and chart_data:
        story += [Spacer(1, 16), _bar_chart(chart_data, font_name)]

    if options.get('notes') and notes:
        story += [Spacer(1, 16)]
        for note in notes:
            story.append(Paragraph(str(note), styles['Normal']))
            story.append(Spacer(1, 4))

    doc.build(story)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response



def multi_sheet_xlsx_response(sheets, filename):
    """
    Книга Excel из нескольких листов: [{'title', 'header', 'rows'}, ...].

    Существующий xlsx_response делает один лист и остаётся как есть — выгрузка
    компании просто требует нескольких разделов.
    """
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for item in sheets:
        # Excel не принимает имена длиннее 31 символа и некоторые знаки.
        title = (item['title'] or 'Sheet')[:31].replace('/', '-').replace('\\', '-')
        sheet = workbook.create_sheet(title=title)
        sheet.append([_sanitize_xlsx_cell(cell) for cell in item['header']])
        for row in item['rows']:
            sheet.append([_sanitize_xlsx_cell(cell) for cell in row])
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


class OwnerFinanceExportView(APIView):
    """GET /api/v1/reports/export/finance/?format=xlsx|pdf - полный финансовый отчёт."""
    permission_classes = [IsCompanyMember, IsOwner]

    def get(self, request):
        date_from, date_to = _parse_period(request)
        data = get_owner_analytics_data(request.user.company_id, date_from, date_to)
        lang = _lang(request)
        t = lambda key: translate(key, lang)  # noqa: E731 — короткая локальная обёртка
        rows = [
            [t('export.col_indicator'), t('export.col_value')],
            [t('export.col_period'), f"{date_from} - {date_to}"],
            [t('finance.revenue'), data['revenue']],
            [t('finance.cost_of_goods'), data['cost_of_goods']],
            [t('finance.gross_profit'), data['gross_profit']],
            [t('finance.expenses'), data['expenses_total']],
            [t('finance.salaries'), data['salaries']],
            # Выплаты работникам — отдельный отток (не Expense): без этой строки
            # «Харажатлар» + «Иш ҳақилар» не сходились с «Соф фойда», которая их
            # вычитает (см. owner_analytics_data: net_profit = revenue - cogs -
            # expenses - worker_payments).
            [t('export.worker_payments'), data['worker_payments']],
            [t('finance.taxes'), data['taxes']],
            [t('finance.losses'), data['losses']],
            [t('finance.owner_withdrawal'), data['owner_withdrawal']],
            [t('finance.net_profit'), data['net_profit']],
            [t('finance.cash_in_register'), data['cash']],
            [t('finance.client_debts'), data['client_debts']],
            [t('finance.worker_debts'), data['worker_debts']],
            [t('export.orders_count'), data['orders_count']],
        ]
        options = export_options(request)

        # «Детallashtirilgan маълумот»: под итогами появляются сами операции —
        # расходы и оплаты периода. Без параметра отчёт остаётся сводным.
        if options['detailed']:
            from apps.clients.models import Payment
            from apps.finance.models import Expense

            rows.append([])
            rows.append([t('export.section_details'), '', ''])
            rows.append([t('export.col_period'), t('finance.category'), t('common.amount')])
            for expense in Expense.objects.filter(
                company_id=request.user.company_id,
                date__gte=date_from, date__lte=date_to,
            ).order_by('date'):
                rows.append([
                    expense.date.isoformat() if expense.date else '',
                    expense.get_category_display(), expense.amount,
                ])
            for payment in Payment.objects.filter(
                company_id=request.user.company_id,
                payment_date__date__gte=date_from, payment_date__date__lte=date_to,
            ).select_related('client').order_by('payment_date'):
                rows.append([
                    payment.payment_date.date().isoformat(),
                    payment.client.name, payment.amount,
                ])

        # «Изоҳ ва ёрдамчиларни қўшиш»: формулы показателей.
        notes = [
            t('export.note_period'),
            t('export.note_net_profit'),
            t('export.note_cash'),
        ] if options['notes'] else None

        # «График ва диаграммаларни қўшиш»: диаграмма по ключевым суммам.
        chart_data = [
            (t('finance.revenue'), data['revenue']),
            (t('finance.cost_of_goods'), data['cost_of_goods']),
            (t('finance.expenses'), data['expenses_total']),
            (t('finance.net_profit'), data['net_profit']),
        ] if options['charts'] else None

        if request.query_params.get('format') == 'pdf':
            return pdf_response(
                _report_title(request, 'export.report_finance'), rows, 'finance-report.pdf',
                options=options, notes=notes, chart_data=chart_data,
            )
        if request.query_params.get('format') == 'csv':
            if notes:
                rows = rows + [[]] + [[note] for note in notes]
            return csv_response(rows, 'finance-report.csv')
        if notes:
            rows = rows + [[]] + [[note] for note in notes]
        return xlsx_response(rows, 'finance-report.xlsx', 'Finance')



class CompanyDataExportView(APIView):
    """
    GET /api/v1/reports/export/company-data/ — выгрузка данных СВОЕЙ компании.

    Это НЕ платформенный backup. Тот делает pg_dump всей базы (данные всех
    арендаторов) и остаётся исключительно у супер-администратора —
    apps/backup не тронут. Здесь владелец забирает только собственные записи.

    Границы намеренно жёсткие:
      * компания берётся ИСКЛЮЧИТЕЛЬНО из request.user.company_id; параметры
        company/company_id/tenant в запросе игнорируются — подменить чужой
        tenant нечем;
      * доступ только владельцу: выгрузка содержит суммы, а администратору
        финансовые данные запрещены по ТЗ (для него есть складские и
        операционные экспорты без цен);
      * каждая выгрузка пишется в журнал аудита — это вынос всей базы клиента,
        след обязателен.
    """
    permission_classes = [IsCompanyMember, IsOwner]

    def get(self, request):
        from apps.clients.models import Client, Payment
        from apps.finance.models import Expense
        from apps.warehouse.models import FinishedProduct, RawMaterial, StockMovement

        company_id = request.user.company_id
        lang = _lang(request)
        t = lambda key: translate(key, lang)  # noqa: E731

        def sheet(title_key, header_keys, rows):
            return {'title': t(title_key), 'header': [t(k) for k in header_keys], 'rows': rows}

        clients = [
            [c.name, c.phone, c.address, c.get_client_type_display(),
             c.total_orders_amount, c.total_paid, c.debt]
            for c in Client.objects.filter(company_id=company_id).order_by('name')
        ]
        orders = [
            [o.id, o.client.name, o.product.name if o.product else o.custom_product_name,
             o.quantity, t(f'units.{o.unit}'), t(f'statuses.{o.status}'),
             o.total_amount, o.paid_amount,
             o.deadline.date().isoformat() if o.deadline else '']
            for o in Order.objects.filter(company_id=company_id)
            .select_related('client', 'product').order_by('id')
        ]
        payments = [
            [p.payment_date.date().isoformat() if p.payment_date else '',
             p.client.name, p.order_id or '', p.amount, p.get_payment_method_display()]
            for p in Payment.objects.filter(company_id=company_id)
            .select_related('client').order_by('payment_date')
        ]
        materials = [
            [m.name, m.stone_type, t(f'units.{m.unit}'), m.quantity, m.min_stock,
             m.purchase_price, m.avg_cost_price]
            for m in RawMaterial.objects.filter(company_id=company_id).order_by('name')
        ]
        products = [
            [p.name, p.category, t(f'units.{p.unit}'), p.quantity, p.cost_price, p.sale_price]
            for p in FinishedProduct.objects.filter(company_id=company_id).order_by('name')
        ]
        movements = [
            [m.created_at.date().isoformat(),
             t(f'movement_types.{m.movement_type}'),
             (m.material.name if m.material else (m.product.name if m.product else '')),
             m.quantity, m.document_number, m.reason]
            for m in StockMovement.objects.filter(company_id=company_id)
            .select_related('material', 'product').order_by('created_at')
        ]
        expenses = [
            [e.date.isoformat() if e.date else '', e.get_category_display(),
             e.amount, e.comment]
            for e in Expense.objects.filter(company_id=company_id).order_by('date')
        ]

        sheets = [
            sheet('clients.title', ['clients.name', 'clients.phone', 'clients.address',
                                    'clients.client_type', 'clients.total_amount',
                                    'clients.paid', 'clients.debt'], clients),
            sheet('orders.title', ['export.col_number', 'export.col_client', 'export.col_product',
                                   'export.col_quantity', 'export.col_unit', 'export.col_status',
                                   'finance.revenue', 'clients.paid', 'export.col_deadline'], orders),
            sheet('clients.payment_history', ['export.col_period', 'export.col_client',
                                              'export.col_number', 'common.amount',
                                              'finance.payment_type'], payments),
            sheet('warehouse.title', ['export.col_name', 'export.col_type', 'export.col_unit',
                                      'export.col_quantity', 'export.col_min_stock',
                                      'warehouse.purchase_price', 'warehouse.avg_cost'], materials),
            sheet('warehouse.finished_title', ['export.col_name', 'export.col_type',
                                               'export.col_unit', 'export.col_quantity',
                                               'warehouse.cost_price', 'warehouse.sale_price'],
                  products),
            sheet('warehouse.stock_movement', ['export.col_period', 'export.col_type',
                                               'export.col_name', 'export.col_quantity',
                                               'warehouse.document_number', 'warehouse.comment'],
                  movements),
            sheet('finance.expenses', ['export.col_period', 'finance.category',
                                       'common.amount', 'warehouse.comment'], expenses),
        ]

        write_audit_log(
            action=AuditLog.Action.EXPORT,
            actor=request.user,
            target=request.user.company,
            metadata={'export': 'company_data',
                      'rows': sum(len(item['rows']) for item in sheets)},
            request=request,
        )
        return multi_sheet_xlsx_response(sheets, 'company-data.xlsx')


class AdminStockExportView(APIView):
    """GET /api/v1/reports/export/stock/ - складские остатки без цен (админ/владелец)."""
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]

    def get(self, request):
        company_id = request.user.company_id
        lang = _lang(request)
        t = lambda key: translate(key, lang)  # noqa: E731
        yes = t('export.yes')
        rows = [[
            t('export.col_name'), t('export.col_type'), t('export.col_quantity'),
            t('export.col_unit'), t('export.col_min_stock'), t('export.col_is_low'),
        ]]
        for m in RawMaterial.objects.filter(company_id=company_id, is_archived=False).order_by('name'):
            rows.append([
                m.name, m.stone_type, m.quantity, t(f'units.{m.unit}'),
                m.min_stock, yes if m.is_low_stock else '',
            ])
        rows.append([])
        rows.append([t('export.section_finished'), '', '', '', '', ''])
        for p in FinishedProduct.objects.filter(company_id=company_id, is_archived=False).order_by('name'):
            rows.append([
                p.name, p.category, p.quantity, t(f'units.{p.unit}'),
                p.min_stock, yes if p.is_low_stock else '',
            ])
        options = export_options(request)

        # Детализация складского отчёта — это операционные подробности
        # (зона, ячейка, состояние, поставщик), а НЕ суммы: отчёт доступен
        # администратору, и цены ему запрещены при любых параметрах.
        if options['detailed']:
            rows[0] += [
                t('warehouse.storage_zone'), t('warehouse.cell'),
                t('warehouse.condition'), t('warehouse.supplier'),
            ]
            materials = {
                m.id: m for m in RawMaterial.objects.filter(
                    company_id=company_id, is_archived=False,
                ).select_related('cell')
            }
            index = 1
            for material in RawMaterial.objects.filter(
                company_id=company_id, is_archived=False,
            ).select_related('cell').order_by('name'):
                rows[index] += [
                    material.get_storage_zone_display() if material.storage_zone else '',
                    material.cell.code if material.cell else '',
                    material.get_condition_display() if material.condition else '',
                    material.supplier or '',
                ]
                index += 1

        notes = [t('export.note_stock_severity')] if options['notes'] else None
        chart_data = None
        if options['charts']:
            # По количеству остатка — без денег, чтобы диаграмма годилась и
            # администратору.
            chart_data = [
                (m.name[:14], m.quantity)
                for m in RawMaterial.objects.filter(
                    company_id=company_id, is_archived=False,
                ).order_by('-quantity')[:8]
            ]

        if request.query_params.get('format') == 'pdf':
            return pdf_response(
                _report_title(request, 'export.report_stock'), rows, 'stock-report.pdf',
                options=options, notes=notes, chart_data=chart_data,
            )
        if notes:
            rows = rows + [[]] + [[note] for note in notes]
        if request.query_params.get('format') == 'csv':
            return csv_response(rows, 'stock-report.csv')
        return xlsx_response(rows, 'stock-report.xlsx', 'Stock')


class AdminOrdersExportView(APIView):
    """GET /api/v1/reports/export/orders/ - список заказов без сумм (админ/владелец)."""
    permission_classes = [IsCompanyMember, IsOwnerOrAdmin]

    def get(self, request):
        is_owner = request.user.is_owner
        lang = _lang(request)
        t = lambda key: translate(key, lang)  # noqa: E731
        rows = [[
            t('export.col_number'), t('export.col_client'), t('export.col_product'),
            t('export.col_quantity'), t('export.col_status'), t('export.col_payment'),
            t('export.col_deadline'),
        ]]
        # Колонка долга — только для владельца: суммы (total_amount, paid_amount)
        # администратору не видны нигде в системе, и в отчёте их быть не должно.
        # Раньше в экспорте не было и для владельца — «сколько клиент ещё
        # должен по этому заказу» приходилось считать вручную из двух других
        # отчётов. Долг = сумма заказа минус фактически оплаченное.
        if is_owner:
            rows[0].append(t('export.col_debt'))
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
                o.quantity, t(f'statuses.{o.status}'), t(f'payment_statuses.{o.payment_status}'),
                o.deadline.date() if o.deadline else '',
            ]
            if is_owner:
                row.append(o.total_amount - (paid_by_order.get(o.id) or 0))
            rows.append(row)
        if request.query_params.get('format') == 'pdf':
            return pdf_response(_report_title(request, 'export.report_orders'), rows, 'orders-report.pdf')
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
        lang = _lang(request)
        t = lambda key: translate(key, lang)  # noqa: E731
        rows = [[
            t('export.col_worker'), t('export.col_confirmed_works'),
            t('export.col_total_quantity'),
        ]]
        if is_owner:
            rows[0].append(t('export.col_accrued'))
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
            return pdf_response(_report_title(request, 'export.report_work'), rows, 'work-report.pdf')
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
            lang = _lang(request)
            t = lambda key: translate(key, lang)  # noqa: E731
            rows = [[
                t('export.col_name'), t('export.col_type'), t('export.col_quantity'),
                t('export.col_unit'), t('export.col_min_stock'), t('export.col_shortage'),
            ]]
            # Считаем по ДОСТУПНОМУ остатку (минус потребность под заказы), как
            # карточка склада (is_low_stock): иначе материал «в норме» по
            # физическому остатку, но целиком требуемый под заказы, не попадает
            # в отчёт о нехватке.
            for m in RawMaterial.objects.filter(
                company_id=company_id, is_archived=False,
            ).annotate(available=F('quantity') - F('required_for_orders')).filter(available__lt=F('min_stock')).order_by('name'):
                rows.append([
                    m.name, m.stone_type, m.quantity, t(f'units.{m.unit}'),
                    m.min_stock, m.min_stock - m.available
                ])
            format_type = request.query_params.get('format_type', 'xlsx')
            if format_type == 'pdf':
                return pdf_response(_report_title(request, 'export.report_shortage'), rows, 'shortage-report.pdf')
            if format_type == 'csv':
                return csv_response(rows, 'shortage-report.csv')
            return xlsx_response(rows, 'shortage-report.xlsx', 'Shortage')
        return Response({"error": "Unsupported report type"}, status=400)
