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

from apps.core.validators import parse_date_param, parse_int_param
import io

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models.functions import TruncMonth

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.core.permissions import IsCompanyMember
from apps.finance.models import Expense, ExpenseCategory, WorkerPayment
from apps.orders.models import Order
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial
from core.permissions import IsOwner, IsOwnerOrAdmin, IsOwnerOrAdminOrManager

MONEY = DecimalField(max_digits=15, decimal_places=2)


def _quarter_bounds(year, quarter):
    """Границы КАЛЕНДАРНОГО квартала: Q1=янв–мар, Q2=апр–июн, Q3=июл–сен, Q4=окт–дек."""
    start_month = 3 * (quarter - 1) + 1
    start = datetime.date(year, start_month, 1)
    if start_month + 2 >= 12:
        end = datetime.date(year, 12, 31)
    else:
        end = datetime.date(year, start_month + 3, 1) - datetime.timedelta(days=1)
    return start, end


def parse_period(request):
    """
    Читает период отчёта. Приоритет:
      1) ?quarter=1..4 [&year=YYYY] — КАЛЕНДАРНЫЙ квартал Q1–Q4;
      2) ?date_from / ?date_to — явные границы (переопределяют пресет);
      3) ?period= (today|yesterday|week|month|quarter|year), по умолчанию month.
    Пресет 'quarter' = ТЕКУЩИЙ календарный квартал (его начало → сегодня),
    раньше это было «последние 91 день» (скользящее окно, не совпадало с ТЗ).
    """
    today = timezone.localdate()

    # (1) Явный календарный квартал имеет приоритет над всем остальным.
    if request.query_params.get('quarter'):
        quarter = parse_int_param(request.query_params['quarter'], 'quarter')
        if quarter < 1 or quarter > 4:
            raise ValidationError({'quarter': 'Квартал должен быть в диапазоне 1..4.'})
        year = today.year
        if request.query_params.get('year'):
            year = parse_int_param(request.query_params['year'], 'year')
        return _quarter_bounds(year, quarter)

    current_quarter = (today.month - 1) // 3 + 1
    quarter_start, _ = _quarter_bounds(today.year, current_quarter)
    presets = {
        'today': (today, today),
        'yesterday': (today - datetime.timedelta(days=1), today - datetime.timedelta(days=1)),
        # Календарная неделя (понедельник → сегодня), а не скользящие 7 дней:
        # скользящее окно почти всегда пересекало границу месяца, и «неделя»
        # стабильно показывала БОЛЬШЕ, чем «месяц» в начале месяца — тестеры
        # справедливо видели в этом поломанную математику. Теперь неделя и
        # месяц — сопоставимые календарные окна (неделя ⊆ месяц, когда она
        # началась в этом месяце).
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
            'date_from': 'Дата начала позже даты конца периода.',
            'date_to': 'Дата конца раньше даты начала периода.',
        })
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
                             delivered_at__date__range=(date_from, date_to))
        .aggregate(s=Sum(ExpressionWrapper(F('quantity') * F('product__cost_price'), output_field=MONEY)))['s']
    )
    expenses_total = money(
        Expense.objects.filter(company_id=company_id, date__range=(date_from, date_to))
        .aggregate(s=Sum('amount'))['s']
    )
    # Выплаты работникам — отдельный отток денег, они НЕ попадают в Expense
    # (это разные журналы: Expense заполняют вручную, WorkerPayment создаётся
    # при выплате). Касса ниже уже вычитает их отдельной строкой, а чистая
    # прибыль — не вычитала, и на сумму всех выплат была завышена.
    worker_payments = money(
        WorkerPayment.objects.filter(company_id=company_id,
                                     payment_date__range=(date_from, date_to))
        .aggregate(s=Sum('amount'))['s']
    )
    return {
        'revenue': revenue,
        'expenses_total': expenses_total,
        'worker_payments': worker_payments,
        'net_profit': revenue - cost_of_goods - expenses_total - worker_payments,
    }


def owner_analytics_data(company_id, date_from, date_to):
    """Собирает все финансовые показатели владельца за период (в рамках компании)."""
    # Все выборки строго ограничены компанией владельца.
    payments = Payment.objects.filter(company_id=company_id, payment_date__date__range=(date_from, date_to))
    revenue = money(payments.aggregate(s=Sum('amount'))['s'])

    delivered = Order.objects.filter(
        company_id=company_id,
        status=Order.Status.DELIVERED,
        delivered_at__date__range=(date_from, date_to),
    ).select_related('product')
    cost_of_goods = money(delivered.aggregate(
        s=Sum(ExpressionWrapper(F('quantity') * F('product__cost_price'), output_field=MONEY)),
    )['s'])

    expenses_qs = Expense.objects.filter(company_id=company_id, date__range=(date_from, date_to))
    expenses_total = money(expenses_qs.aggregate(s=Sum('amount'))['s'])

    def expenses_by(*categories):
        return money(expenses_qs.filter(category__in=categories).aggregate(s=Sum('amount'))['s'])

    # ВНИМАНИЕ: Expense с категориями SALARY/ADVANCE И WorkerPayment — разные сущности.
    # Если владелец проведёт выплату работнику через ОБА канала (и Expense, и
    # WorkerPayment), сумма вычтется дважды. Это не кодовая ошибка, а UX-аспект:
    # при создании Expense с категорией SALARY или WorkerPayment система не
    # проверяет дублирование. Рекомендуется использовать ТОЛЬКО WorkerPayment
    # для выплат работникам, а Expense.SALARY — для дополнительных проводок.
    salaries = expenses_by(ExpenseCategory.SALARY, ExpenseCategory.ADVANCE)
    taxes = expenses_by(ExpenseCategory.TAXES)
    losses = expenses_by(ExpenseCategory.MATERIAL_LOSS, ExpenseCategory.DEFECT)
    owner_withdrawal = expenses_by(ExpenseCategory.OWNER_WITHDRAWAL)

    worker_payments = money(
        WorkerPayment.objects.filter(company_id=company_id, payment_date__range=(date_from, date_to))
        .aggregate(s=Sum('amount'))['s']
    )

    client_debts = money(Client.objects.filter(
        company_id=company_id, is_archived=False,
    ).aggregate(s=Sum('debt'))['s'])
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

    # Группировка по id, а не по имени: два товара с одинаковым именем иначе
    # сливались в одну строку с суммированием, а переименованный товар/работник
    # раздваивался на две строки.
    top_products = list(
        Order.objects.filter(company_id=company_id, status=Order.Status.DELIVERED, product__isnull=False,
                             delivered_at__date__range=(date_from, date_to))
        .values('product_id')
        .annotate(name=Max('product__name'), total_quantity=Sum('quantity'), orders=Count('id'))
        .order_by('-total_quantity')[:5]
    )
    top_worker = (
        WorkRecord.objects.filter(company_id=company_id, status=WorkRecord.WorkStatus.CONFIRMED,
                                  confirmed_at__date__range=(date_from, date_to))
        .values('worker_id')
        .annotate(name=Max('worker__full_name'), username=Max('worker__username'),
                  total_quantity=Sum('quantity'), works=Count('id'))
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
    # Выплаты работникам вычитаются наравне с расходами: это реальные деньги,
    # ушедшие из кассы за период (см. worker_payments выше и расчёт cash).
    net_profit = revenue - cost_of_goods - expenses_total - worker_payments

    # Активные сотрудники (админы + работники, не заблокированы, не в архиве)
    active_employees = User.objects.filter(
        company_id=company_id,
        role__in=(User.Role.ADMIN, User.Role.WORKER),
        is_active=True,
        status=User.Status.ACTIVE,
    ).count()

    # Процент просроченных заказов
    total_active_orders = orders_qs.exclude(
        status__in=(Order.Status.DELIVERED, Order.Status.CANCELLED)
    ).count()
    overdue_orders = orders_qs.filter(
        deadline__lt=timezone.now(),
    ).exclude(
        status__in=(Order.Status.DELIVERED, Order.Status.CANCELLED)
    ).count()
    overdue_percentage = round(
        (overdue_orders / total_active_orders) * 100, 1
    ) if total_active_orders > 0 else 0

    # Товары с низким остатком (сырьё + готовая продукция)
    low_stock_materials_count = sum(1 for m in raw_qs if m.is_low_stock)
    low_stock_products_count = sum(
        1 for p in FinishedProduct.objects.filter(
            company_id=company_id, is_archived=False
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


class RevenueTimelineView(APIView):
    """
    GET /api/v1/reports/analytics/revenue-timeline/
    Возвращает помесячную выручку и чистую прибыль за последние 6 месяцев.
    Только для владельца.
    """
    permission_classes = [IsCompanyMember, IsOwner]

    def get(self, request):
        company_id = request.user.company_id
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
            )
            .annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total=Sum('amount'))
            .order_by('month')
        )

        delivered = (
            Order.objects.filter(
                company_id=company_id,
                status=Order.Status.DELIVERED,
                delivered_at__gte=six_months_ago,
                product__isnull=False,
            )
            .annotate(month=TruncMonth('delivered_at'))
            .values('month')
            .annotate(
                cogs=Sum(ExpressionWrapper(
                    F('quantity') * F('product__cost_price'), output_field=MONEY
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

        def month_key(value):
            """
            Первое число месяца как date.

            TruncMonth над DateTimeField (оплаты) отдаёт datetime, над DateField
            (расходы, выплаты) — date. Без приведения к одному типу один и тот же
            месяц становился ДВУМЯ разными ключами, а sorted() по смеси date и
            datetime падал с TypeError — график на дашборде отдавал 500, как
            только в компании появлялись и оплата, и расход.
            """
            return value.date() if isinstance(value, datetime.datetime) else value

        # Собираем все месяцы
        months_set = set()
        rev_map = {}
        for p in payments:
            m = month_key(p['month'])
            months_set.add(m)
            rev_map[m] = money(p['total'])

        exp_map = {}
        for e in expenses:
            m = month_key(e['month'])
            months_set.add(m)
            exp_map[m] = money(e['total'])

        cogs_map = {}
        for d in delivered:
            m = month_key(d['month'])
            months_set.add(m)
            cogs_map[m] = money(d['cogs'])

        payout_map = {}
        for w in payouts:
            m = month_key(w['month'])
            months_set.add(m)
            payout_map[m] = money(w['total'])

        months = sorted(months_set, reverse=True)[:6]
        months.reverse()

        month_names = {
            1: 'Янв', 2: 'Фев', 3: 'Мар', 4: 'Апр', 5: 'Май', 6: 'Июн',
            7: 'Июл', 8: 'Авг', 9: 'Сен', 10: 'Окт', 11: 'Ноя', 12: 'Дек',
        }

        labels = []
        revenues = []
        net_profits = []
        for m in months:
            label = f"{month_names.get(m.month, m.month)}'{str(m.year)[2:]}"
            labels.append(label)
            rev = rev_map.get(m, 0)
            exp = exp_map.get(m, 0)
            cogs = cogs_map.get(m, 0)
            payout = payout_map.get(m, 0)
            revenues.append(rev)
            # Та же формула, что и у карточки «Чистая прибыль» (owner_analytics_data):
            # выплаты работникам вычитаются. Иначе график показывал прибыль выше,
            # чем карточка над ним, — на сумму выплат.
            net_profits.append(rev - cogs - exp - payout)

        return Response({
            'labels': labels,
            'revenues': revenues,
            'net_profits': net_profits,
        })


class AdminAnalyticsView(APIView):
    """
    GET /api/v1/reports/analytics/admin/ - операционная аналитика без денег.

    Доступ: владелец, администратор и менеджер (manager видит только
    операционные показатели, без финансовых сумм).
    """
    permission_classes = [IsCompanyMember, IsOwnerOrAdminOrManager]

    def get(self, request):
        return Response(admin_analytics_data(request.user.company_id))


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
                row.append(money(o.total_amount - money(paid_by_order.get(o.id))))
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
            # Считаем по ДОСТУПНОМУ остатку (минус резерв под заказы), как
            # карточка склада (is_low_stock): иначе материал «в норме» по
            # физическому остатку, но целиком зарезервированный, не попадает
            # в отчёт о нехватке.
            for m in RawMaterial.objects.filter(
                company_id=company_id, is_archived=False,
            ).annotate(available=F('quantity') - F('reserved_for_orders')).filter(available__lt=F('min_stock')).order_by('name'):
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
