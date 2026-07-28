"""
Каждый ключ, который фронтенд просит у i18n, должен существовать во всех локалях.

Воспроизведено: `common.delete_confirm` не был заведён ни в одной локали, а три
обработчика удаления в finance.js его запрашивали. i18n.translate() при
отсутствии ключа возвращает САМ КЛЮЧ (static/js/i18n.js), поэтому в диалоге
удаления пользователю показывалась строка «common.delete_confirm».

Молчаливая деградация — худший вид: интерфейс выглядит работающим, а текст
подменён служебной строкой. Тест ловит это на любом ключе и в любом файле.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

LOCALES = ('ru', 'uz_cyrl', 'ky')

# ui.t('a.b') и window.ui.t("a.b") — только строковые литералы: ключи,
# собранные из переменных, статически проверить нельзя.
T_CALL = re.compile(r"""\bui\.t\(\s*['"]([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)['"]\s*\)""")

# data-i18n="a.b" в шаблонных строках; интерполяцию ${...} пропускаем.
DATA_I18N = re.compile(r"""data-i18n=["']([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)["']""")


def _load(name):
    path = Path(settings.BASE_DIR) / 'locale' / f'{name}.json'
    with path.open(encoding='utf-8') as fh:
        return json.load(fh)


def _has(dictionary, dotted):
    current = dictionary
    for part in dotted.split('.'):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return isinstance(current, str)


class FrontendI18nKeysTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.locales = {name: _load(name) for name in LOCALES}
        cls.sources = sorted((Path(settings.BASE_DIR) / 'static' / 'js').rglob('*.js'))

    def _keys(self, pattern):
        found = {}
        for path in self.sources:
            if 'vendor' in path.parts:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            for key in pattern.findall(text):
                found.setdefault(key, path.name)
        return found

    def test_sources_are_found(self):
        """Страховка: если файлы перестанут находиться, тест не должен молча зеленеть."""
        self.assertGreater(len(self.sources), 5)

    def test_every_ui_t_key_exists_in_every_locale(self):
        missing = []
        for key, source in self._keys(T_CALL).items():
            absent = [name for name, data in self.locales.items() if not _has(data, key)]
            if absent:
                missing.append(f'{key} ({source}) — нет в {", ".join(absent)}')
        self.assertFalse(missing, 'Ключи без перевода:\n  ' + '\n  '.join(missing))

    def test_every_data_i18n_key_exists_in_every_locale(self):
        missing = []
        for key, source in self._keys(DATA_I18N).items():
            absent = [name for name, data in self.locales.items() if not _has(data, key)]
            if absent:
                missing.append(f'{key} ({source}) — нет в {", ".join(absent)}')
        self.assertFalse(missing, 'Ключи без перевода:\n  ' + '\n  '.join(missing))

    def test_locales_have_the_same_key_set(self):
        """Разъезд локалей приводит к тому же результату: ключ вместо текста."""
        def flat(node, prefix=''):
            keys = set()
            for key, value in node.items():
                path = f'{prefix}{key}'
                if isinstance(value, dict):
                    keys |= flat(value, f'{path}.')
                else:
                    keys.add(path)
            return keys

        reference = flat(self.locales['ru'])
        for name in LOCALES[1:]:
            other = flat(self.locales[name])
            self.assertFalse(reference - other, f'нет в {name}: {sorted(reference - other)[:20]}')
            self.assertFalse(other - reference, f'нет в ru: {sorted(other - reference)[:20]}')
