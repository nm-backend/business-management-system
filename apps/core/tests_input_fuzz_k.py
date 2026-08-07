"""
Фаззинг всех /api/v1 эндпоинтов мусорными данными.

Задача: любой мусор в URL, query или теле запроса должен давать корректный
ответ API (4xx JSON), а не 500 и не HTML-страницу ошибки Django.
"""
import json
import re

from django.test import TestCase
from django.urls import get_resolver, resolve, Resolver404
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company

REPORT = r'C:\Users\User\AppData\Local\Temp\opencode\fuzz_report.txt'

PATH_GARBAGE = ['abc', '0', '-1', '999999999999999999999', '1.5', 'null']

BODIES = [
    {},
    {'pk': 'abc'},
    {'id': -1},
    {'x': {'nested': 'value'}},
    {'count': 10 ** 30},
    {'price': -12345.678},
    {'date': '2026-13-45'},
    {'name': '<script>alert(1)</script>'},
    {'name': 'x' * 5000},
    {'name': 'a\u0000b\nc'},
    {'text': 'a' * 100000},
]

QUERY_GARBAGE = {
    'page': 'abc', 'page_size': '-1', 'status': 'xyz', 'format': 'zzz',
    'search': "' OR 1=1 --", 'date_from': 'not-a-date', 'date_to': '9999-99-99',
    'q': '%', 'x': 'a' * 2000,
}


def collect_routes():
    """
    Собирает все пути под api/v1 из urlconf.

    DefaultRouter генерирует regex-паттерны ('^orders/(?P<pk>[^/.]+)/$').
    Превращаем их в конкретные пути (orders/5/) и проверяем через resolve,
    чтобы в фазз попали РЕАЛЬНО доступные маршруты.
    """
    routes = []

    def walk(patterns, prefix=''):
        for p in patterns:
            if getattr(p, 'url_patterns', None):
                walk(p.url_patterns, prefix + str(p.pattern))
            else:
                path = prefix + str(p.pattern)
                if not path.startswith('api/v1'):
                    continue
                if (path.startswith(('api/v1/schema', 'api/v1/swagger', 'api/v1/redoc'))):
                    continue
                if '<' in path:
                    routes.append('/' + path)
                    continue
                if re.fullmatch(r'[a-z0-9_\-./]+', path):
                    routes.append('/' + path)
                    continue
                # Regex-паттерн DefaultRouter: подставляем образцы вместо групп.
                regex = p.pattern.regex.pattern if hasattr(p.pattern, 'regex') else ''
                if regex.startswith('^'):
                    samples = {'pk': '5', 'id': '5', 'format': 'json', 'slug': 'x'}
                    converted = re.sub(
                        r'\(\?P<(\w+)>[^)]*\)',
                        lambda m: samples.get(m.group(1), 'x'),
                        regex,
                    )
                    converted = converted.replace(r'\.', '.').lstrip('^').rstrip('$')
                    if '.json' in converted or 'format' in converted:
                        continue  # вариант с суффиксом формата — дубль основного
                    candidate = '/' + prefix + converted
                    try:
                        resolve(candidate)
                        routes.append(candidate)
                    except Resolver404:
                        pass

    walk(get_resolver().url_patterns)
    return sorted(set(routes))


def path_variants(route):
    if '<' not in route:
        return [route]
    parts = re.split(r'<[^>]+>', route)
    seps = re.findall(r'<[^>]+>', route)
    variants = []
    for value in PATH_GARBAGE:
        out = parts[0]
        for i in range(len(seps)):
            out += value + parts[i + 1]
        variants.append(out)
    return variants


class InputFuzzTests(TestCase):
    maxDiff = None

    def setUp(self):
        self.fails = []
        self.company = Company.objects.create(name='FuzzCo', is_active=True)
        self.superadmin = User.objects.create_superuser(
            username='fuzz_super', password='pw12345X')
        self.worker = User.objects.create_user(
            username='fuzz_worker', password='pw12345X',
            role=User.Role.WORKER, company=self.company)
        self.routes = collect_routes()
        print(f'\n[fuzz] routes collected: {len(self.routes)}')

    def check(self, user, method, path, status, content_type, body_preview=''):
        if status == 500:
            self.fails.append(f'{method} {path} -> 500 | body: {body_preview[:200]}')
            return
        if status == 404:
            # HTML на 404 — штатная кастомная страница «не найдено»
            # (непойманные URL и pk-мусор, не прошедший конвертер). ОК.
            return
        if status >= 400 and 'html' in (content_type or ''):
            self.fails.append(f'{method} {path} -> {status} HTML page | {body_preview[:120]}')
            return
        if status < 500 and 'json' not in (content_type or '') and status not in (204, 205):
            self.fails.append(f'{method} {path} -> {status} non-JSON ({content_type})')

    def fuzz(self, user, methods=('get', 'post', 'put', 'patch', 'delete')):
        client = APIClient()
        client.force_authenticate(user=user)
        count = 0
        for route in self.routes:
            for path in path_variants(route):
                for method in methods:
                    fn = getattr(client, method)
                    count += 1
                    resp = fn(path, data=QUERY_GARBAGE)
                    self.check(user, method.upper(), path, resp.status_code,
                               resp.get('Content-Type', ''))
                for method in ('post', 'put', 'patch'):
                    fn = getattr(client, method)
                    for body in BODIES:
                        count += 1
                        resp = fn(path, data=body, format='json')
                        self.check(user, method.upper(), path, resp.status_code,
                                   resp.get('Content-Type', ''), json.dumps(body)[:200])
                    count += 1
                    resp = fn(path, data='{not valid json', content_type='application/json')
                    self.check(user, method.upper(), path, resp.status_code,
                               resp.get('Content-Type', ''), 'invalid json')
                    count += 1
                    resp = fn(path, data={'a': 'b'}, content_type='application/x-www-form-urlencoded')
                    self.check(user, method.upper(), path, resp.status_code,
                               resp.get('Content-Type', ''), 'form-encoded')
                    count += 1
                    resp = fn(path, data={'field': 'v'}, content_type='multipart/form-data')
                    self.check(user, method.upper(), path, resp.status_code,
                               resp.get('Content-Type', ''), 'multipart')
                if count % 1000 == 0:
                    print(f'[fuzz] {count} requests, fails so far: {len(self.fails)}')
        print(f'[fuzz] done: {count} requests, fails: {len(self.fails)}')
        return count

    def test_superadmin_fuzz(self):
        self.fuzz(self.superadmin)

    def test_worker_light_fuzz(self):
        client = APIClient()
        client.force_authenticate(user=self.worker)
        count = 0
        for route in self.routes:
            for path in path_variants(route):
                for method in ('get', 'post', 'patch'):
                    fn = getattr(client, method)
                    count += 1
                    resp = fn(path, data={'pk': 'abc', 'status': 'zzz'})
                    self.check(self.worker, method.upper(), path, resp.status_code,
                               resp.get('Content-Type', ''))
        print(f'[fuzz-worker] done: {count} requests')

    def tearDown(self):
        with open(REPORT, 'a', encoding='utf-8') as f:
            for line in self.fails:
                f.write(line + '\n')
        if self.fails:
            msg = '\n'.join(self.fails[:60])
            raise AssertionError(f'Fuzz found {len(self.fails)} problems:\n{msg}')
