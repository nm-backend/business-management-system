"""
Мобильная прокрутка и масштаб (жалоба с телефона: «скроллится только двумя пальцами»).

Что было в коде:
  1. .main-content объявлял вложенную область прокрутки
     (overflow-y: auto + -webkit-overflow-scrolling: touch). Такой слой
     перехватывает касание, хотя прокручивать ему нечего — высота блока равна
     высоте содержимого (измерено на боевом сервере: clientHeight == scrollHeight
     == 3672px). Документ при этом прокручивается нормально, поэтому вложенный
     скроллер только мешал.
  2. viewport запрещал масштабирование (maximum-scale=1.0, user-scalable=no) —
     пользователь не мог увеличить текст жестом (WCAG 1.4.4).
  3. mobile.css использует env(safe-area-inset-bottom), но без viewport-fit=cover
     это значение ВСЕГДА 0, и нижняя навигация не учитывала вырез экрана.
"""
from pathlib import Path

from django.conf import settings
from django.test import TestCase

BASE_CSS = Path(settings.STATICFILES_DIRS[0]) / 'css' / 'base.css'


class ViewportMetaTests(TestCase):
    def _viewport(self):
        html = self.client.get('/accounts/login/').content.decode()
        start = html.index('name="viewport"')
        chunk = html[start:start + 260]
        content_at = chunk.index('content="') + len('content="')
        return chunk[content_at:chunk.index('"', content_at)]

    def test_zoom_is_not_disabled(self):
        viewport = self._viewport()
        self.assertNotIn('user-scalable=no', viewport)
        self.assertNotIn('maximum-scale', viewport)

    def test_viewport_fit_cover_present(self):
        # Без него env(safe-area-inset-*) в CSS всегда 0.
        self.assertIn('viewport-fit=cover', self._viewport())

    def test_width_device_width_present(self):
        self.assertIn('width=device-width', self._viewport())


class MainContentScrollTests(TestCase):
    """Прокручиваться должен документ, а не вложенный блок."""

    def _main_content_block(self):
        css = BASE_CSS.read_text(encoding='utf-8')
        start = css.index('.main-content {')
        return css[start:css.index('}', start)]

    def test_main_content_is_not_a_nested_scroller(self):
        block = self._main_content_block()
        self.assertNotIn('overflow-y: auto', block)
        self.assertNotIn('-webkit-overflow-scrolling', block)

    def test_bottom_padding_respects_safe_area(self):
        # Отступ под фиксированной нижней навигацией + вырез экрана.
        block = self._main_content_block()
        self.assertIn('--bottom-nav-height', block)
        self.assertIn('safe-area-inset-bottom', block)
