"""
Кнопка «Назад» при открытом модальном окне и версия статики.

БАГ (воспроизведён в браузере на живом приложении): при открытой карточке заказа
аппаратная кнопка «Назад» меняла хеш — страница под окном перерисовывалась
(#/orders -> #/settings, заголовок «Настройки»), а само окно оставалось висеть
поверх чужого экрана.

РЕШЕНИЕ: ui.modal() кладёт в историю СВОЮ запись с тем же адресом, поэтому
«Назад» приходит как popstate без смены адреса — роутер просто закрывает окно.
Закрытие крестиком/Escape освобождает эту запись через history.back(), иначе в
истории копился мусор и «Назад» приходилось жать дважды.

ВТОРОЙ БАГ: ASSET_VERSION была захардкоженной строкой. После деплоя браузеры
продолжали брать СТАРЫЕ js/css из кэша, пока константу не поменяют руками
(воспроизведено: правка ui.js не доезжала до страницы). Теперь версия считается
по времени изменения файлов в static/.
"""
from pathlib import Path

from django.conf import settings
from django.test import TestCase

JS = Path(settings.STATICFILES_DIRS[0]) / 'js'


class ModalHistoryContractTests(TestCase):
    def test_modal_takes_own_history_entry(self):
        ui = (JS / 'ui.js').read_text(encoding='utf-8')
        self.assertIn('skpModal', ui)
        self.assertIn('history.pushState', ui)
        # закрытие освобождает занятую запись
        self.assertIn('history.back()', ui)
        self.assertIn('closeModal(', ui)
        self.assertIn('closeTopModal(', ui)

    def test_router_closes_modal_on_back(self):
        router = (JS / 'router.js').read_text(encoding='utf-8')
        self.assertIn("addEventListener('popstate'", router)
        self.assertIn('closeTopModal', router)
        # Escape тоже закрывает окно
        self.assertIn("'Escape'", router)

    def test_components_close_modals_through_api(self):
        """
        Прямой modal.remove() в компонентах оставлял бы занятую запись истории —
        после сохранения формы «Назад» срабатывал бы вхолостую.
        """
        offenders = []
        for path in sorted(JS.rglob('*.js')):
            if path.name == 'ui.js':
                continue
            if 'modal.remove()' in path.read_text(encoding='utf-8'):
                offenders.append(path.name)
        self.assertEqual(offenders, [], f'закрывают окно в обход ui.closeModal: {offenders}')


class AssetVersionTests(TestCase):
    def test_asset_version_is_derived_not_hardcoded(self):
        base = (Path(settings.BASE_DIR) / 'skladpro' / 'settings' / 'base.py').read_text(encoding='utf-8')
        self.assertIn('_compute_asset_version', base)
        self.assertNotIn("ASSET_VERSION = '20260714enhance'", base)

    def test_asset_version_changes_when_static_file_changes(self):
        import os
        import time

        from skladpro.settings.base import _compute_asset_version

        target = Path(settings.STATICFILES_DIRS[0]) / 'js' / 'ui.js'
        original = _compute_asset_version()
        stat = target.stat()
        try:
            os.utime(target, (stat.st_atime, time.time() + 120))
            self.assertNotEqual(_compute_asset_version(), original)
        finally:
            os.utime(target, (stat.st_atime, stat.st_mtime))

    def test_version_reaches_the_page(self):
        html = self.client.get('/accounts/login/').content.decode()
        self.assertIn(f'?v={settings.ASSET_VERSION}', html)
