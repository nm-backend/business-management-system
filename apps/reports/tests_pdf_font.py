"""
Этап D — регрессия PDF-экспорта (кириллический шрифт кроссплатформенно).

Было: путь к шрифту жёстко 'C:/Windows/Fonts/arial.ttf' — на Linux/Docker его
нет, reportlab молча брал Helvetica, и кириллица в PDF не рендерилась. Стало:
resolve_report_font_path() ищет шрифт по кроссплатформенным путям (+ env), в
Docker-образ ставится fonts-dejavu-core.

Доказываем: (1) на текущей машине находится реальный TTF (не Helvetica);
(2) найденный шрифт СОДЕРЖИТ кириллицу; (3) PDF с кириллицей реально строится.
"""
from django.test import TestCase

from apps.reports.views import (
    pdf_response, register_report_font, resolve_report_font_path,
)


class PdfFontTests(TestCase):
    def test_a_real_unicode_font_is_found(self):
        # На машинах разработки/CI (Windows/Linux) должен найтись TTF, а не
        # деградация в Helvetica.
        self.assertEqual(register_report_font(), 'ReportFont')

    def test_resolved_font_contains_cyrillic_glyph(self):
        path = resolve_report_font_path()
        self.assertIsNotNone(path, 'Не найден ни один Unicode-шрифт для PDF')
        from reportlab.pdfbase.ttfonts import TTFont
        face = TTFont('probe', path).face
        # У шрифта должен быть глиф для кириллической «А» (U+0410).
        self.assertIn(0x0410, face.charToGlyph,
                      f'Шрифт {path} не содержит кириллицу')

    def test_pdf_with_cyrillic_builds(self):
        resp = pdf_response('Молия ҳисоботи (кириллица)',
                            [['Кўрсаткич', 'Қиймат'], ['Даромад', '125 000']],
                            'test.pdf')
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))
        self.assertGreater(len(resp.content), 500)
