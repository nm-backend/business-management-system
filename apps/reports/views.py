"""
Views for reports API.

Обеспечивает генерацию и скачивание отчётов в PDF и Excel форматах.

Endpoints:
- GET /api/v1/reports/financial/?period=month&format=pdf — финансовый отчёт (owner)
- GET /api/v1/reports/financial/?period=month&format=xlsx — финансовый отчёт (owner)
- GET /api/v1/reports/operational/?period=month&format=pdf — операционный отчёт (admin)
- GET /api/v1/reports/operational/?period=month&format=xlsx — операционный отчёт (admin)

Права доступа:
- financial: FinancialDataPermission (только owner)
- operational: IsOwnerOrAdmin (owner и admin)
"""
import logging
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.permissions import FinancialDataPermission, IsOwnerOrAdmin


logger = logging.getLogger(__name__)


class BaseReportView(APIView):
    """Базовый класс для report views с общими параметрами."""

    def get_params(self, request):
        """Извлекает period, format, custom_start, custom_end из query params."""
        return {
            'period': request.query_params.get('period', 'month'),
            'format': request.query_params.get('format', 'pdf').lower(),
            'custom_start': request.query_params.get('date_from'),
            'custom_end': request.query_params.get('date_to'),
        }


class FinancialReportView(BaseReportView):
    """
    Полный финансовый отчёт для владельца.

    GET /api/v1/reports/financial/?period=month&format=pdf

    Параметры:
        period: str - today, yesterday, week, month, quarter, year, custom
        format: str - pdf или xlsx
        date_from: str - дата начала (для custom периода)
        date_to: str - дата конца (для custom периода)

    Формат ответа:
        PDF — application/pdf
        XLSX — application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    """
    permission_classes = [IsAuthenticated, FinancialDataPermission]

    def get(self, request):
        params = self.get_params(request)
        fmt = params['format']

        try:
            from .services import generate_financial_pdf, generate_financial_excel

            if fmt == 'xlsx':
                buffer = generate_financial_excel(
                    period=params['period'],
                    custom_start=params['custom_start'],
                    custom_end=params['custom_end'],
                )
                content_type = (
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
                filename = (
                    f"financial_report_{params['period']}_{params['custom_start'] or ''}"
                    f"_{params['custom_end'] or ''}.xlsx"
                ).replace('__', '_').strip('_')
            else:
                buffer = generate_financial_pdf(
                    period=params['period'],
                    custom_start=params['custom_start'],
                    custom_end=params['custom_end'],
                )
                content_type = 'application/pdf'
                filename = (
                    f"financial_report_{params['period']}_{params['custom_start'] or ''}"
                    f"_{params['custom_end'] or ''}.pdf"
                ).replace('__', '_').strip('_')

            response = HttpResponse(
                buffer.read(),
                content_type=content_type,
                status=200,
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Access-Control-Expose-Headers'] = 'Content-Disposition'
            return response

        except Exception as e:
            logger.exception("Financial report generation failed")
            return HttpResponse(
                f'{{"error": "Report generation failed", "detail": "{str(e)}"}}',
                content_type='application/json',
                status=500,
            )


class OperationalReportView(BaseReportView):
    """
    Операционный отчёт для администратора (без финансовых данных).

    GET /api/v1/reports/operational/?period=month&format=pdf

    Параметры:
        period: str - today, yesterday, week, month, quarter, year, custom
        format: str - pdf или xlsx
        date_from: str - дата начала (для custom периода)
        date_to: str - дата конца (для custom периода)

    Формат ответа:
        PDF — application/pdf
        XLSX — application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    """
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get(self, request):
        params = self.get_params(request)
        fmt = params['format']

        try:
            from .services import generate_operational_pdf, generate_operational_excel

            if fmt == 'xlsx':
                buffer = generate_operational_excel(
                    period=params['period'],
                    custom_start=params['custom_start'],
                    custom_end=params['custom_end'],
                )
                content_type = (
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
                filename = (
                    f"operational_report_{params['period']}_{params['custom_start'] or ''}"
                    f"_{params['custom_end'] or ''}.xlsx"
                ).replace('__', '_').strip('_')
            else:
                buffer = generate_operational_pdf(
                    period=params['period'],
                    custom_start=params['custom_start'],
                    custom_end=params['custom_end'],
                )
                content_type = 'application/pdf'
                filename = (
                    f"operational_report_{params['period']}_{params['custom_start'] or ''}"
                    f"_{params['custom_end'] or ''}.pdf"
                ).replace('__', '_').strip('_')

            response = HttpResponse(
                buffer.read(),
                content_type=content_type,
                status=200,
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Access-Control-Expose-Headers'] = 'Content-Disposition'
            return response

        except Exception as e:
            logger.exception("Operational report generation failed")
            return HttpResponse(
                f'{{"error": "Report generation failed", "detail": "{str(e)}"}}',
                content_type='application/json',
                status=500,
            )
