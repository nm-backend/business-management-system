"""
Полный производственный цикл заказа через живой API (те же эндпоинты, что
вызывает UI): создание -> назначение работнику -> принятие -> сдача работы ->
подтверждение -> выдача -> оплата. Выполняется реальными ролями (owner/worker).
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.settings')
django.setup()

import uuid
import requests

BASE = 'http://127.0.0.1:8000/api/v1'
PASSWORD = 'DemoPass123!'
CLIENT_ID = 22   # Акбаров Азизбек
PRODUCT_ID = 46  # Ошхона столешница
WORKER_ID = 93   # demo_worker


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


def main():
    owner = login('demo_owner')
    worker = login('demo_worker')

    print('1. Owner: СОЗДАНИЕ ЗАКАЗА')
    st, order = call(owner, 'POST', '/orders/orders/', {
        'client': CLIENT_ID, 'product': PRODUCT_ID, 'quantity': 5,
        'unit': 'm2', 'total_amount': 4500000, 'comment': 'E2E тест цикла',
    })
    step(f'POST /orders/orders/ -> {st}', st in (200, 201))
    oid = order.get('id')
    print(f'   order #{oid} status={order.get("status")} payment={order.get("payment_status")}')

    print('2. Owner: НАЗНАЧЕНИЕ РАБОТНИКУ')
    st, task = call(owner, 'POST', '/production/tasks/', {'order': oid, 'worker': WORKER_ID})
    step(f'POST /production/tasks/ -> {st}', st in (200, 201))
    tid = task.get('id')
    print(f'   task #{tid} status={task.get("status")}')
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ стал sent_to_worker (={o.get("status")})', o.get('status') == 'sent_to_worker')

    print('3. Worker: ПРИНЯТИЕ ЗАДАЧИ')
    st, t2 = call(worker, 'POST', f'/production/tasks/{tid}/accept/')
    step(f'POST accept -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ стал accepted (={o.get("status")})', o.get('status') == 'accepted')

    print('4. Worker: СДАЧА РАБОТЫ')
    st, work = call(worker, 'POST', '/production/works/', {
        'task': tid, 'product': PRODUCT_ID, 'quantity': 5,
        'unit': 'm2', 'operation': 'other', 'defect_quantity': 0,
        'comment': 'Сделал 5 м2 столешницы',
    })
    step(f'POST /production/works/ -> {st}', st in (200, 201))
    wid = work.get('id')
    print(f'   work #{wid} status={work.get("status")}')
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ стал awaiting_confirmation (={o.get("status")})', o.get('status') == 'awaiting_confirmation')

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

    print('6. Owner: ВЫДАЧА КЛИЕНТУ')
    st, o2 = call(owner, 'POST', f'/orders/orders/{oid}/deliver/')
    step(f'POST deliver -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ стал delivered (={o.get("status")}), cost_price={o.get("cost_price")}',
         o.get('status') == 'delivered')

    print('7. Owner: ПРИЁМ ОПЛАТЫ')
    import datetime
    st, pm = call(owner, 'POST', '/clients/payments/', {
        'client': CLIENT_ID, 'order': oid, 'amount': 4500000,
        'payment_method': 'cash', 'comment': 'Оплата по заказу',
        'payment_date': datetime.datetime.utcnow().isoformat(),
    })
    step(f'POST /clients/payments/ -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ оплачен (payment_status={o.get("payment_status")}, paid={o.get("paid_amount")})',
         o.get('payment_status') == 'paid')

    print('--- ИТОГ ---')
    print(f'order #{oid}: status={o.get("status")} payment={o.get("payment_status")} '
          f'total={o.get("total_amount")} paid={o.get("paid_amount")} cost={o.get("cost_price")}')
    st, earn = call(worker, 'GET', '/production/works/my-earnings/')
    print(f'worker earnings endpoint -> {st}: {str(earn)[:200]}')


if __name__ == '__main__':
    main()
