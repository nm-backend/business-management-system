"""
Полный E2E-прогон всех модулей и ролей через живой API.

Проверяет:
  1) матрицу доступа по ролям (owner / admin / worker) для каждого модуля;
  2) видимость финансовых полей (у worker/admin не должно быть цен);
  3) ключевые write-операции владельца в каждом модуле;
  4) отчёты (PDF/Excel), уведомления, локализацию, компанию.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.settings')
django.setup()

import uuid
import requests

BASE = 'http://127.0.0.1:8000/api/v1'
PASSWORD = 'DemoPass123!'


def login(username):
    r = requests.post(f'{BASE}/accounts/login/', json={
        'username': username, 'password': PASSWORD, 'fingerprint': uuid.uuid4().hex,
    }, timeout=20)
    r.raise_for_status()
    return r.json()['tokens']['access']


def call(access, method, path, payload=None):
    r = requests.request(method, f'{BASE}{path}', json=payload,
                         headers={'Authorization': f'Bearer {access}'}, timeout=25)
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def step(label, ok, extra=''):
    print(('  [OK] ' if ok else '  [FAIL] ') + label + (f'  ({extra})' if extra else ''))


# Модули, доступные всем членам компании (GET)
MODULES = [
    ('warehouse/raw-materials', 'Склад: сырьё'),
    ('warehouse/finished-products', 'Склад: товары'),
    ('warehouse/stock-movements', 'Склад: движения'),
    ('warehouse/recipes', 'Склад: рецепты'),
    ('orders/orders', 'Заказы'),
    ('production/tasks', 'Производство: задачи'),
    ('production/works', 'Производство: работы'),
    ('messaging/conversations', 'Мессенджер: диалоги'),
    ('messaging/notifications', 'Мессенджер: уведомления'),
    ('clients/clients', 'Клиенты'),
    ('finance/expenses', 'Финансы: расходы'),
    ('finance/labor-rates', 'Финансы: ставки труда'),
    ('finance/worker-payments', 'Финансы: выплаты работникам'),
]


def access_matrix():
    owner = login('demo_owner')
    admin = login('demo_admin')
    worker = login('demo_worker')
    print('\n=== МАТРИЦА ДОСТУПА ПО РОЛЯМ (GET) ===')
    for path, label in MODULES:
        o = call(owner, 'GET', f'/{path}/')[0]
        a = call(admin, 'GET', f'/{path}/')[0]
        w = call(worker, 'GET', f'/{path}/')[0]
        print(f'{label:38} owner={o} admin={a} worker={w}')
    return owner, admin, worker


def field_visibility(owner, admin, worker):
    print('\n=== ВИДИМОСТЬ ФИНАНСОВЫХ ПОЛЕЙ ===')
    # 1. worker не видит закупочные цены на сырьё
    st, raw = call(worker, 'GET', '/warehouse/raw-materials/')
    item = (raw.get('results') or [{}])[0] if isinstance(raw, dict) else (raw or [{}])[0]
    leaked = [k for k in ('purchase_price', 'avg_cost_price', 'cost_price', 'sale_price') if k in item]
    step(f'worker: сырьё без цен (keys={list(item.keys())})', st == 200 and not leaked, f'leaked={leaked}')

    # 2. worker не видит цены на готовую продукцию
    st, fp = call(worker, 'GET', '/warehouse/finished-products/')
    item = (fp.get('results') or [{}])[0] if isinstance(fp, dict) else (fp or [{}])[0]
    leaked = [k for k in ('cost_price', 'sale_price', 'labor_rate') if k in item]
    step(f'worker: товары без цен (keys={list(item.keys())})', st == 200 and not leaked, f'leaked={leaked}')

    # 3. admin не видит суммы клиентов (только флаг has_debt)
    st, cl = call(admin, 'GET', '/clients/clients/')
    item = (cl.get('results') or [{}])[0] if isinstance(cl, dict) else (cl or [{}])[0]
    leaked = [k for k in ('total_debt', 'balance', 'amount', 'total_amount', 'debt') if k in item]
    step(f'admin: клиенты без сумм (keys={list(item.keys())})', st == 200 and not leaked, f'leaked={leaked}')

    # 4. worker не видит финансовую аналитику owner
    st, _ = call(worker, 'GET', '/finance/expenses/')
    step(f'worker: расходы запрещены', st in (403, 404), f'status={st}')
    st, _ = call(worker, 'GET', '/finance/worker-payments/')
    step(f'worker: выплаты запрещены', st in (403, 404), f'status={st}')

    # 5. worker видит только свой заработок (my_earnings — с подчёркиванием)
    st, earn = call(worker, 'GET', '/production/works/my_earnings/')
    step(f'worker: свой заработок доступен', st == 200, f'status={st} keys={list(earn.keys())}')


def write_ops(owner):
    print('\n=== WRITE-ОПЕРАЦИИ ВЛАДЕЛЬЦА ===')
    # Сырьё
    st, mat = call(owner, 'POST', '/warehouse/raw-materials/', {
        'name': 'E2E сырьё', 'unit': 'kg', 'quantity': 10,
    })
    step(f'создать сырьё -> {st}', st in (200, 201), f'id={mat.get("id")}')
    mat_id = mat.get('id')

    # Приход сырья
    st, _ = call(owner, 'POST', f'/warehouse/raw-materials/{mat_id}/incoming/', {
        'quantity': 5, 'price': 1000, 'reason': 'E2E приход',
    })
    step(f'приход сырья -> {st}', st in (200, 201), f'status={st}')

    # Расход сырья
    st, _ = call(owner, 'POST', f'/warehouse/raw-materials/{mat_id}/outgoing/', {
        'quantity': 1, 'reason': 'E2E расход',
    })
    step(f'расход сырья -> {st}', st in (200, 201), f'status={st}')

    # Товар (готовая продукция) — unit должен быть из допустимых значений (sht/izdelie/m2/kg...)
    st, prod = call(owner, 'POST', '/warehouse/finished-products/', {
        'name': 'E2E товар', 'unit': 'sht', 'quantity': 0, 'category': 'other',
        'cost_price': 5000, 'sale_price': 9000,
    })
    step(f'создать товар -> {st}', st in (200, 201), f'id={prod.get("id")}')

    # Клиент
    st, cl = call(owner, 'POST', '/clients/clients/', {
        'name': 'E2E клиент', 'phone': '+998901234567',
    })
    step(f'создать клиента -> {st}', st in (200, 201), f'id={cl.get("id")}')
    cl_id = cl.get('id')

    # Расход
    st, exp = call(owner, 'POST', '/finance/expenses/', {
        'category': 'other', 'amount': 25000, 'description': 'E2E расход',
        'date': '2026-09-05',
    })
    step(f'создать расход -> {st}', st in (200, 201), f'id={exp.get("id")}')

    # Заказ
    st, order = call(owner, 'POST', '/orders/orders/', {
        'client': cl_id, 'product': prod.get('id'), 'quantity': 1,
        'unit': 'sht', 'total_amount': 9000, 'comment': 'E2E все модули',
    })
    step(f'создать заказ -> {st}', st in (200, 201), f'id={order.get("id")}')

    return cl_id


def reports_and_misc(owner):
    print('\n=== ОТЧЁТЫ / УВЕДОМЛЕНИЯ / КОМПАНИЯ / ЛОКАЛИЗАЦИЯ ===')
    st, body = call(owner, 'GET', '/reports/analytics/owner/')
    step(f'аналитика owner -> {st}', st == 200, f'revenue={body.get("revenue")}') if isinstance(body, dict) else step(f'аналитика owner -> {st}', st == 200)
    st, _ = call(owner, 'GET', '/reports/export/finance/')
    step(f'экспорт финансов (XLSX) -> {st}', st == 200, f'status={st}')
    st, _ = call(owner, 'GET', '/reports/export/stock/')
    step(f'экспорт склада (XLSX) -> {st}', st == 200, f'status={st}')
    st, _ = call(owner, 'GET', '/reports/export/orders/')
    step(f'экспорт заказов (XLSX) -> {st}', st == 200, f'status={st}')
    st, _ = call(owner, 'GET', '/reports/export/work/')
    step(f'экспорт работ (XLSX) -> {st}', st == 200, f'status={st}')
    st, _ = call(owner, 'GET', '/reports/export/?report_type=material_shortage&format_type=xlsx')
    step(f'общий экспорт (material_shortage) -> {st}', st == 200, f'status={st}')
    st, _ = call(owner, 'GET', '/reports/export/?report_type=material_shortage&format_type=pdf')
    step(f'общий экспорт PDF -> {st}', st == 200, f'status={st}')

    st, _ = call(owner, 'GET', '/messaging/notifications/?limit=1')
    step(f'уведомления -> {st}', st == 200, f'status={st}')

    st, me = call(owner, 'GET', '/accounts/me/')
    step(f'текущий пользователь/компания -> {st}', st == 200, f'role={me.get("role")}')

    st, _ = call(owner, 'GET', '/core/currencies/')
    step(f'валюты -> {st}', st == 200, f'status={st}')

    # Локализация: язык в запросе/ответе (проверка, что API отвечает)
    r = requests.get(f'{BASE}/warehouse/raw-materials/', headers={
        'Authorization': f'Bearer {owner}', 'Accept-Language': 'ru',
    }, timeout=25)
    step(f'локализация ru (Accept-Language) -> {r.status_code}', r.status_code == 200, f'status={r.status_code}')


def main():
    owner, admin, worker = access_matrix()
    field_visibility(owner, admin, worker)
    write_ops(owner)
    reports_and_misc(owner)
    print('\n--- E2E ВСЕХ МОДУЛЕЙ ЗАВЕРШЁН ---')


if __name__ == '__main__':
    main()
