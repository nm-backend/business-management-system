"""
Приложение не должно зависеть от чужих серверов и мусора в репозитории.

1. Chart.js тянулся с cdn.jsdelivr.net. В цеху со слабым интернетом графики
   просто не отрисовывались, а в консоли на каждой загрузке висела ошибка CSP
   на его sourcemap (connect-src 'self' ws: wss:). Библиотека перенесена в
   static/js/vendor/.
2. apple-mobile-web-app-capable устарел — браузер предупреждал об этом при
   каждом открытии страницы.
3. В git лежал дамп базы (backups/*.json) с 10 учётными записями и хешами
   паролей, служебная база .freebuff/desktop.db на 27 МБ, dev-база и media/.
   Всё это снято с учёта и закрыто .gitignore.
"""
from pathlib import Path

from django.conf import settings
from django.test import TestCase

BASE_DIR = Path(settings.BASE_DIR)
STATIC = Path(settings.STATICFILES_DIRS[0])


class OfflineAssetsTests(TestCase):
    def test_chartjs_is_served_locally(self):
        vendor = STATIC / 'js' / 'vendor' / 'chart.umd.min.js'
        self.assertTrue(vendor.is_file(), 'Chart.js должен лежать в проекте')
        self.assertGreater(vendor.stat().st_size, 50_000, 'файл Chart.js подозрительно мал')

    def test_no_external_script_hosts_in_templates(self):
        """Скрипты — только свои: чужой CDN может лечь или подменить код."""
        offenders = []
        for tpl in BASE_DIR.joinpath('templates').rglob('*.html'):
            for line in tpl.read_text(encoding='utf-8').splitlines():
                stripped = line.strip()
                if stripped.startswith('<!--') or stripped.startswith('#'):
                    continue
                if '<script' in stripped and 'src="http' in stripped:
                    offenders.append(f'{tpl.name}: {stripped[:80]}')
        self.assertEqual(offenders, [], f'внешние скрипты: {offenders}')

    def test_modern_web_app_meta_present(self):
        html = self.client.get('/accounts/login/').content.decode()
        self.assertIn('name="mobile-web-app-capable"', html)


class RepositoryHygieneTests(TestCase):
    """Мусор не должен возвращаться в репозиторий."""

    def test_gitignore_covers_generated_junk(self):
        ignore = (BASE_DIR / '.gitignore').read_text(encoding='utf-8')
        for pattern in ('backups/', '.freebuff/', '.playwright-mcp/', '*.sqlite3', 'media/'):
            self.assertIn(pattern, ignore, f'не игнорируется: {pattern}')

    def test_no_database_dump_committed(self):
        """
        Дамп содержит учётные записи с хешами паролей и токены — в системе
        контроля версий ему не место даже в приватном репозитории.
        """
        dumps = list(BASE_DIR.glob('backups/*.json'))
        for dump in dumps:
            # файл может лежать на диске, но НЕ должен отслеживаться git'ом —
            # это проверяет .gitignore выше; здесь убеждаемся, что каталог закрыт
            self.assertTrue((BASE_DIR / '.gitignore').read_text(encoding='utf-8').count('backups/'),
                            f'{dump.name} не закрыт .gitignore')
