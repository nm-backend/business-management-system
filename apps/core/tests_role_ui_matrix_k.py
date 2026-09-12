"""
Матрица «роль → окна» на стороне UI: шаблон ↔ SPA-роутер ↔ супер-админ.

Три согласования, которые легко разъехать при рефакторинге навигации:
  1. data-role каждого пункта сайдбара/нижней навигации (base.html) совпадает
     с ролевым списком его маршрута (addGuardedRoute в app.js) — UI не может
     показать окно, которое маршрут запретит;
  2. все бизнес-маршруты присутствуют в superadmin-блок-листе (прямой адрес
     #/orders у платформенного админа даёт 403-заглушку, а не пустой экран);
  3. словарь data-role ограничен известными значениями — опечатка вида
     "staff-workes" молча скрыла бы пункт у всех.

Ожидаемая матрица (ТЗ):
  * owner                — всё: дашборд, заказы, продажи, склад, производство,
                           финансы, клиенты, чат, подписка, настройки, аудит;
  * admin                — без финансов и продаж (сервер тоже не отдаёт);
  * worker               — дашборд, свои заказы, склад (чтение), производство, чат;
  * superadmin           — платформа: компании, настройки.
"""
import re

from django.test import SimpleTestCase

BASE_HTML = 'templates/base.html'
APP_JS = 'static/js/app.js'

# data-role → множество ролей, которым пункт виден в навигации.
ROLE_SETS = {
    None: {'owner', 'admin', 'worker'},
    'owner': {'owner'},
    'owner-admin': {'owner', 'admin'},
    'staff': {'owner', 'admin'},
    'staff-worker': {'worker'},
    'superadmin': {'superadmin'},
}

# Ожидаемый data-role пункта навигации по адресу окна.
EXPECTED_NAV = {
    '/': None,
    '/orders': None,
    '/sales': 'owner',
    '/warehouse': None,
    '/production': 'staff-worker',
    '/finance': 'owner',
    '/clients': 'staff',
    '/messages': None,
    '/subscription': 'owner-admin',
    '/companies': 'superadmin',
    '/settings': None,
}

# Ожидаемый список допущенных ролей маршрута (2-й аргумент addGuardedRoute).
EXPECTED_ROUTES = {
    '/': None,
    '/warehouse': None,
    '/finished-products': None,
    '/clients': ['owner', 'admin'],
    '/orders': None,
    '/orders/kanban': ['owner', 'admin'],
    '/production': None,
    '/sales': ['owner'],
    '/finance': ['owner'],
    '/messages': None,
    '/subscription': ['owner', 'admin'],
    '/settings': None,
    '/audit': ['owner'],
    '/backup': ['owner'],
}

# Бизнес-маршруты, заблокированные для супер-админа (403-заглушка).
EXPECTED_SUPERADMIN_BLOCKED = [
    '/orders', '/warehouse', '/finished-products', '/production', '/clients',
    '/sales', '/finance', '/subscription', '/audit', '/backup',
]


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class RoleUiMatrixTests(SimpleTestCase):
    """UI-матрица «роль → окна»: навигация согласована с роутером и ролями."""

    def test_nav_links_match_expected_matrix(self):
        html = _read(BASE_HTML)
        links = re.findall(
            r'<a href="#([^"]+)" class="(?:sidebar-link|nav-item)"[^>]*>', html)
        seen = set()
        problems = []
        for match in re.finditer(
                r'<a href="#([^"]+)" class="(sidebar-link|nav-item)"([^>]*)>', html):
            path, kind, attrs = match.group(1), match.group(2), match.group(3)
            seen.add(path)
            role_match = re.search(r'data-role="([^"]+)"', attrs)
            data_role = role_match.group(1) if role_match else None
            expected = EXPECTED_NAV.get(path)
            if expected != data_role:
                problems.append(
                    f'{kind} {path}: data-role={data_role!r}, ожидалось {expected!r}')
        self.assertFalse(problems, 'Навигация разошлась с матрицей:\n  ' + '\n  '.join(problems))
        missing = set(EXPECTED_NAV) - seen
        self.assertFalse(missing, f'Пунктов навигации нет в шаблоне: {sorted(missing)}')

    def test_data_role_vocabulary(self):
        """data-role только из известного словаря — опечатка скрыла бы пункт."""
        html = _read(BASE_HTML)
        used = set(re.findall(r'data-role="([^"]+)"', html))
        unknown = used - set(ROLE_SETS)
        self.assertFalse(unknown, f'Неизвестные data-role: {sorted(unknown)}')

    def test_routes_match_expected_matrix(self):
        js = _read(APP_JS)
        routes = {}
        for match in re.finditer(
                r"addGuardedRoute\('([^']+)',\s*[\w.]+,\s*(null|\[[^\]]*\])\)", js):
            path = match.group(1)
            allowed = match.group(2)
            routes[path] = None if allowed == 'null' else eval(allowed)  # noqa: S307
        problems = []
        for path, expected in EXPECTED_ROUTES.items():
            actual = routes.get(path, '<нет>')
            if actual != expected:
                problems.append(f'маршрут {path}: {actual!r}, ожидалось {expected!r}')
        extra = set(routes) - set(EXPECTED_ROUTES)
        if extra:
            problems.append(f'незадокументированные маршруты: {sorted(extra)}')
        self.assertFalse(problems, 'Роутер разошёлся с матрицей:\n  ' + '\n  '.join(problems))

    def test_ui_never_shows_route_that_role_cannot_open(self):
        """Каждому пункту навигации маршрут разрешает все его роли (или маршрут открыт всем)."""
        html = _read(BASE_HTML)
        js = _read(APP_JS)
        routes = {}
        for match in re.finditer(
                r"addGuardedRoute\('([^']+)',\s*[\w.]+,\s*(null|\[[^\]]*\])\)", js):
            routes[match.group(1)] = (
                None if match.group(2) == 'null' else set(eval(match.group(2))))  # noqa: S307
        problems = []
        for match in re.finditer(
                r'<a href="#([^"]+)" class="(?:sidebar-link|nav-item)"([^>]*)>', html):
            path, attrs = match.group(1), match.group(2)
            role_match = re.search(r'data-role="([^"]+)"', attrs)
            if role_match is None:
                continue
            nav_roles = ROLE_SETS[role_match.group(1)]
            route_roles = routes.get(path)
            if route_roles is None:
                continue  # маршрут открыт всем бизнес-ролям
            denied = nav_roles - route_roles
            if denied:
                problems.append(f'{path}: навигация видна {sorted(nav_roles)}, '
                                f'маршрут пускает только {sorted(route_roles)}')
        self.assertFalse(problems, 'UI показывает запрещённые окна:\n  ' + '\n  '.join(problems))

    def test_superadmin_blocklist_covers_business_routes(self):
        """Прямой адрес бизнес-окна у супер-админа даёт 403-заглушку."""
        js = _read(APP_JS)
        match = re.search(r"\[([^\]]*'/[^\]]*)\]\.forEach", js)
        self.assertIsNotNone(match, 'superadmin-блок-лист не найден в app.js')
        blocked = re.findall(r"'([^']+)'", match.group(1))
        self.assertEqual(blocked, EXPECTED_SUPERADMIN_BLOCKED)
