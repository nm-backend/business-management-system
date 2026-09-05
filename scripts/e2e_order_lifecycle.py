"""
Полный производственный цикл заказа через живой API (те же эндпоинты, что
вызывает UI): создание -> назначение работнику -> принятие -> сдача работы ->
подтверждение -> выдача -> оплата. Выполняется реальными ролями (owner/worker).

ПОСЛЕ КАЖДОЙ ФАЗЫ проверяется производный ledger — те же формулы, что в
apps/reports/services.py (owner-analytics) и Client.recalculate_financials:
  - client_debt  = Client.debt (агрегат заказов/оплат клиента);
  - cash         = выручка периода − расходы (без зарплат) − выплаты работникам;
  - worker_debts = Σ labor_cost подтверждённых работ − Σ выплат (накопительно);
  - revenue      = Σ оплат за период;
  - cost_of_goods= Σ quantity × order.cost_price (снимок на момент выдачи).

Снимки сравниваются с базовым (delta), поэтому на живой демо-базе с
существующими данными и прошлыми прогонами проверки остаются точными.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.settings')
django.setup()

import uuid
from decimal import Decimal

import requests
from django.utils import timezone

BASE = 'http://127.0.0.1:8000/api/v1'
PASSWORD = 'DemoPass123!'
CLIENT_ID = 22   # Акбаров Азизбек
PRODUCT_ID = 46  # Ошхона столешница
WORKER_ID = 93   # demo_worker
QUANTITY = 5
TOTAL_AMOUNT = 4500000


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


def step(label, ok):
    print(('  [OK] ' if ok else '  [FAIL] ') + label)
    return ok


def dec(value):
    """Decimal из строки/числа/None (JSON отдаёт суммы как str или float)."""
    return Decimal(str(value or 0))


def delta(now, base):
    """Разница двух денежных значений, округлённая до 2 знаков (деньги)."""
    return round(float(dec(now) - dec(base)), 2)


def ledger(access):
    """
    Снимок производного ledger: долг клиента (Client.debt) + owner-аналитика
    за сегодня (cash, worker_debts, revenue, cost_of_goods).
    """
    st, client = call(access, 'GET', f'/clients/clients/{CLIENT_ID}/')
    if st != 200:
        print(f'   client #{CLIENT_ID} -> {st}: {str(client)[:200]}')
        return None
    st, anal = call(access, 'GET', '/reports/analytics/owner/?period=today')
    if st != 200:
        print(f'   analytics owner -> {st}: {str(anal)[:200]}')
        return None
    return {
        'client_debt': client.get('debt'),
        'client_archived': client.get('is_archived'),
        'revenue': anal.get('revenue'),
        'cost_of_goods': anal.get('cost_of_goods'),
        'cash': anal.get('cash'),
        'worker_debts': anal.get('worker_debts'),
    }


def check_ledger(access, label, base, expected):
    """
    Сверяет delta каждой метрики ledger с ожидаемой (delta от базового снимка).

    expected: {metric: delta_от_базы}. Метрики, которых нет в expected,
    не проверяются. Возвращает свежий снимок (или None, если API недоступен).
    """
    now = ledger(access)
    if now is None:
        step(f'{label}: ledger недоступен', False)
        return None
    for key, exp in expected.items():
        got = delta(now[key], base[key])
        ok = got == round(float(exp), 2)
        step(f'{label} · {key}: {got} (ожидалось {round(float(exp), 2)})', ok)
    return now


def main():
    owner = login('demo_owner')
    worker = login('demo_worker')

    base = ledger(owner)
    if base is None:
        step('базовый снимок ledger недоступен', False)
        return
    print(f'   baseline: client_debt={base["client_debt"]} '
          f'cash={base["cash"]} worker_debts={base["worker_debts"]}')

    print('1. Owner: СОЗДАНИЕ ЗАКАЗА')
    st, order = call(owner, 'POST', '/orders/orders/', {
        'client': CLIENT_ID, 'product': PRODUCT_ID, 'quantity': QUANTITY,
        'unit': 'm2', 'total_amount': TOTAL_AMOUNT, 'comment': 'E2E тест цикла',
    })
    step(f'POST /orders/orders/ -> {st}', st in (200, 201))
    oid = order.get('id')
    print(f'   order #{oid} status={order.get("status")} payment={order.get("payment_status")}')
    # Ledger: долг клиента вырос на сумму заказа; касса и долги работникам не тронуты
    # (оплаты ещё не было, труд ещё не начислен).
    check_ledger(owner, 'ledger после создания', base,
                 {'client_debt': TOTAL_AMOUNT, 'cash': 0, 'worker_debts': 0})

    print('2. Owner: НАЗНАЧЕНИЕ РАБОТНИКУ')
    st, task = call(owner, 'POST', '/production/tasks/', {'order': oid, 'worker': WORKER_ID})
    step(f'POST /production/tasks/ -> {st}', st in (200, 201))
    tid = task.get('id')
    print(f'   task #{tid} status={task.get("status")}')
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ стал sent_to_worker (={o.get("status")})', o.get('status') == 'sent_to_worker')
    # Ledger: назначение ничего не меняет.
    check_ledger(owner, 'ledger после назначения', base,
                 {'client_debt': TOTAL_AMOUNT, 'cash': 0, 'worker_debts': 0})

    print('3. Worker: ПРИНЯТИЕ ЗАДАЧИ')
    st, t2 = call(worker, 'POST', f'/production/tasks/{tid}/accept/')
    step(f'POST accept -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ стал accepted (={o.get("status")})', o.get('status') == 'accepted')
    # Ledger: принятие ничего не меняет.
    check_ledger(owner, 'ledger после принятия', base,
                 {'client_debt': TOTAL_AMOUNT, 'cash': 0, 'worker_debts': 0})

    print('4. Worker: СДАЧА РАБОТЫ')
    st, work = call(worker, 'POST', '/production/works/', {
        'task': tid, 'product': PRODUCT_ID, 'quantity': QUANTITY,
        'unit': 'm2', 'operation': 'other', 'defect_quantity': 0,
        'comment': 'Сделал 5 м2 столешницы',
    })
    step(f'POST /production/works/ -> {st}', st in (200, 201))
    wid = work.get('id')
    print(f'   work #{wid} status={work.get("status")}')
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ стал awaiting_confirmation (={o.get("status")})', o.get('status') == 'awaiting_confirmation')
    # Ledger: сдача работы денег не двигает (начисление происходит на подтверждении).
    check_ledger(owner, 'ledger после сдачи работы', base,
                 {'client_debt': TOTAL_AMOUNT, 'cash': 0, 'worker_debts': 0})

    print('5. Owner: ПОДТВЕРЖДЕНИЕ РАБОТЫ')
    st, w2 = call(owner, 'POST', f'/production/works/{wid}/confirm/', {})
    step(f'POST confirm -> {st}', st in (200, 201))
    if st not in (200, 201):
        print('   detail:', str({k: v for k, v in w2.items() if k in ('detail', 'labor_cost')})[:400])
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ стал ready (={o.get("status")})', o.get('status') == 'ready')
    _, w3 = call(owner, 'GET', f'/production/works/{wid}/')
    step(f'работа подтверждена (={w3.get("status")}), labor_cost={w3.get("labor_cost")}',
         w3.get('status') == 'confirmed')
    # Ledger: начислен труд — долг перед работником вырос ровно на labor_cost
    # (касса и долг клиента не меняются: выплаты ещё не было).
    labor_cost = dec(w3.get('labor_cost'))
    check_ledger(owner, 'ledger после подтверждения', base, {
        'client_debt': TOTAL_AMOUNT, 'cash': 0,
        'worker_debts': float(labor_cost),
    })

    print('6. Owner: ВЫДАЧА КЛИЕНТУ')
    st, o2 = call(owner, 'POST', f'/orders/orders/{oid}/deliver/')
    step(f'POST deliver -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ стал delivered (={o.get("status")}), cost_price={o.get("cost_price")}',
         o.get('status') == 'delivered')
    # Ledger: COGS зафиксирован снимком cost_price на момент выдачи
    # (quantity × order.cost_price). Долг клиента и касса пока без изменений.
    cogs_expected = float(dec(QUANTITY) * dec(o.get('cost_price')))
    check_ledger(owner, 'ledger после выдачи', base, {
        'client_debt': TOTAL_AMOUNT, 'cash': 0,
        'worker_debts': float(labor_cost),
        'cost_of_goods': cogs_expected,
    })

    print('7. Owner: ПРИЁМ ОПЛАТЫ')
    st, pm = call(owner, 'POST', '/clients/payments/', {
        'client': CLIENT_ID, 'order': oid, 'amount': TOTAL_AMOUNT,
        'payment_method': 'cash', 'comment': 'Оплата по заказу',
        'payment_date': timezone.now().isoformat(),
    })
    step(f'POST /clients/payments/ -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ оплачен (payment_status={o.get("payment_status")}, paid={o.get("paid_amount")})',
         o.get('payment_status') == 'paid')
    # Ledger: оплата — деньги пришли в кассу (revenue/cash + сумма), долг клиента
    # вернулся к базовому (net delta 0), долг работникам и COGS не меняются.
    check_ledger(owner, 'ledger после оплаты', base, {
        'client_debt': 0,
        'revenue': TOTAL_AMOUNT,
        'cash': TOTAL_AMOUNT,
        'worker_debts': float(labor_cost),
        'cost_of_goods': cogs_expected,
    })

    print('--- ИТОГ ---')
    print(f'order #{oid}: status={o.get("status")} payment={o.get("payment_status")} '
          f'total={o.get("total_amount")} paid={o.get("paid_amount")} cost={o.get("cost_price")}')
    final = ledger(owner)
    if final is not None:
        print('   ledger deltas от baseline:')
        for key in ('client_debt', 'revenue', 'cost_of_goods', 'cash', 'worker_debts'):
            print(f'      {key}: {delta(final[key], base[key])}')
    st, earn = call(worker, 'GET', '/production/works/my-earnings/')
    print(f'worker earnings endpoint -> {st}: {str(earn)[:200]}')


if __name__ == '__main__':
    main()