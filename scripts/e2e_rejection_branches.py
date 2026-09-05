"""
«Отказные» ветки производственного цикла заказа через живой API.

Проверяет:
  1) refuse  — работник отказывается от НЕпринятой задачи -> task REFUSED, order WORKER_REFUSED, резерв сохраняется;
  2) повторное назначение + принятие + сдача;
  3) reject  — владелец отклоняет работу -> work REJECTED, task обратно ACCEPTED, order IN_PROGRESS, склад НЕ менялся;
  4) повторная сдача + подтверждение + выдача + оплата;
  5) cancel после оплаты — должно быть ЗАБЛОКИРОВАНО (400, «есть оплата»);
  6) cancel невыданного неоплаченного заказа — должно вернуть резерв и перевести в CANCELLED.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.settings')
django.setup()

import uuid
import datetime
import requests
from decimal import Decimal


def dec(v):
    """API отдаёт Decimal как строку; приводим к числу для сравнений."""
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal('0')

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


def get_order(owner, oid):
    st, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    return o


def get_task(owner, tid):
    st, t = call(owner, 'GET', f'/production/tasks/{tid}/')
    return t


def get_work(owner, wid):
    st, w = call(owner, 'GET', f'/production/works/{wid}/')
    return w


def main():
    owner = login('demo_owner')
    worker = login('demo_worker')

    # --- Замер исходного резерва товара ---
    st, prod = call(owner, 'GET', f'/warehouse/finished-products/{PRODUCT_ID}/')
    print(f'исходный товар #{PRODUCT_ID}: quantity={prod.get("quantity")} required={prod.get("required_for_orders")}')

    # ===================== 1. refuse =====================
    print('\n=== 1. REFUSE (работник отказывается) ===')
    st, order = call(owner, 'POST', '/orders/orders/', {
        'client': CLIENT_ID, 'product': PRODUCT_ID, 'quantity': 3,
        'unit': 'm2', 'total_amount': 2700000, 'comment': 'E2E отказной ветки',
    })
    step(f'создать заказ -> {st}', st in (200, 201))
    oid = order.get('id')
    st, task = call(owner, 'POST', '/production/tasks/', {'order': oid, 'worker': WORKER_ID})
    step(f'назначить задачу -> {st}', st in (200, 201))
    tid = task.get('id')
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ sent_to_worker (={o.get("status")})', o.get('status') == 'sent_to_worker')

    # Резерв должен появиться
    st, prod2 = call(owner, 'GET', f'/warehouse/finished-products/{PRODUCT_ID}/')
    step(f'резерв вырос (required={prod2.get("required_for_orders")})',
         dec(prod2.get('required_for_orders')) >= dec(prod.get('required_for_orders')) + 3)

    st, t2 = call(worker, 'POST', f'/production/tasks/{tid}/refuse/', {'reason': 'no_time', 'comment': 'нет времени'})
    step(f'worker refuse -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ WORKER_REFUSED (={o.get("status")})', o.get('status') == 'worker_refused')
    t3 = get_task(owner, tid)
    step(f'задача REFUSED (={t3.get("status")})', t3.get('status') == 'refused')
    # Резерв НЕ должен сняться (заказ не отменён)
    st, prod3 = call(owner, 'GET', f'/warehouse/finished-products/{PRODUCT_ID}/')
    step(f'резерв сохранился (required={prod3.get("required_for_orders")})',
         dec(prod3.get('required_for_orders')) >= dec(prod.get('required_for_orders')) + 3)

    # Повторный refuse на уже отказанной задаче должен быть заблокирован
    st, t4 = call(worker, 'POST', f'/production/tasks/{tid}/refuse/', {'reason': 'no_time'})
    step(f'повторный refuse заблокирован -> {st}', st in (400, 403))

    # ===================== 2. новое назначение + принятие + сдача =====================
    print('\n=== 2. Повторное назначение -> принятие -> сдача ===')
    st, task2 = call(owner, 'POST', '/production/tasks/', {'order': oid, 'worker': WORKER_ID})
    step(f'назначить заново -> {st}', st in (200, 201))
    tid2 = task2.get('id')
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ снова sent_to_worker (={o.get("status")})', o.get('status') == 'sent_to_worker')
    st, _ = call(worker, 'POST', f'/production/tasks/{tid2}/accept/')
    step(f'worker accept -> {st}', st in (200, 201))
    st, work = call(worker, 'POST', '/production/works/', {
        'task': tid2, 'product': PRODUCT_ID, 'quantity': 3,
        'unit': 'm2', 'operation': 'other', 'defect_quantity': 0,
        'comment': 'Сделал 3 м2',
    })
    step(f'сдать работу -> {st}', st in (200, 201))
    wid = work.get('id')
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ awaiting_confirmation (={o.get("status")})', o.get('status') == 'awaiting_confirmation')

    # ===================== 3. reject =====================
    print('\n=== 3. REJECT (владелец отклоняет работу) ===')
    # Склад до отклонения (товар ещё не приходован — подтверждение не было)
    st, prod_before = call(owner, 'GET', f'/warehouse/finished-products/{PRODUCT_ID}/')
    st, w2 = call(owner, 'POST', f'/production/works/{wid}/reject/', {'reason': 'брак'})
    step(f'owner reject -> {st}', st in (200, 201))
    w3 = get_work(owner, wid)
    step(f'работа REJECTED (={w3.get("status")})', w3.get('status') == 'rejected')
    t5 = get_task(owner, tid2)
    step(f'задача обратно ACCEPTED (={t5.get("status")})', t5.get('status') == 'accepted')
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ IN_PROGRESS (={o.get("status")})', o.get('status') == 'in_progress')
    st, prod_after = call(owner, 'GET', f'/warehouse/finished-products/{PRODUCT_ID}/')
    step(f'склад НЕ изменился (qty {prod_before.get("quantity")} -> {prod_after.get("quantity")})',
         dec(prod_before.get('quantity')) == dec(prod_after.get('quantity')))

    # ===================== 4. повторная сдача -> подтверждение -> выдача -> оплата =====================
    print('\n=== 4. Повторная сдача -> подтверждение -> выдача -> оплата ===')
    st, work2 = call(worker, 'POST', '/production/works/', {
        'task': tid2, 'product': PRODUCT_ID, 'quantity': 3,
        'unit': 'm2', 'operation': 'other', 'defect_quantity': 0,
        'comment': 'Переделал 3 м2',
    })
    step(f'повторно сдать -> {st}', st in (200, 201))
    wid2 = work2.get('id')
    st, w4 = call(owner, 'POST', f'/production/works/{wid2}/confirm/', {})
    step(f'confirm -> {st}', st in (200, 201))
    if st not in (200, 201):
        print('   detail:', str({k: v for k, v in w4.items() if k in ('detail', 'labor_cost')})[:400])
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ ready (={o.get("status")})', o.get('status') == 'ready')
    st, o2 = call(owner, 'POST', f'/orders/orders/{oid}/deliver/')
    step(f'deliver -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ delivered (={o.get("status")})', o.get('status') == 'delivered')
    st, pm = call(owner, 'POST', '/clients/payments/', {
        'client': CLIENT_ID, 'order': oid, 'amount': 2700000,
        'payment_method': 'cash', 'comment': 'Оплата по заказу',
        'payment_date': datetime.datetime.utcnow().isoformat(),
    })
    step(f'оплата -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ paid (payment={o.get("payment_status")})', o.get('payment_status') == 'paid')

    # ===================== 5. cancel после оплаты =====================
    print('\n=== 5. CANCEL после оплаты (должно быть заблокировано) ===')
    st, oc = call(owner, 'POST', f'/orders/orders/{oid}/cancel/')
    detail = str(oc.get('detail', ''))[:120]
    step(f'cancel оплаченного -> {st} ({detail})', st == 400 and 'оплата' in detail)
    _, o = call(owner, 'GET', f'/orders/orders/{oid}/')
    step(f'заказ остался delivered (={o.get("status")})', o.get('status') == 'delivered')

    # ===================== 6. cancel невыданного неоплаченного =====================
    print('\n=== 6. CANCEL невыданного неоплаченного (резерв возвращается) ===')
    st, order2 = call(owner, 'POST', '/orders/orders/', {
        'client': CLIENT_ID, 'product': PRODUCT_ID, 'quantity': 2,
        'unit': 'm2', 'total_amount': 1800000, 'comment': 'E2E отмена неоплаченного',
    })
    oid2 = order2.get('id')
    st, prod_c1 = call(owner, 'GET', f'/warehouse/finished-products/{PRODUCT_ID}/')
    st, oc2 = call(owner, 'POST', f'/orders/orders/{oid2}/cancel/')
    step(f'cancel неоплаченного -> {st}', st in (200, 201))
    _, o = call(owner, 'GET', f'/orders/orders/{oid2}/')
    step(f'заказ CANCELLED (={o.get("status")})', o.get('status') == 'cancelled')
    st, prod_c2 = call(owner, 'GET', f'/warehouse/finished-products/{PRODUCT_ID}/')
    step(f'резерв вернулся (required {prod_c1.get("required_for_orders")} -> {prod_c2.get("required_for_orders")})',
         dec(prod_c2.get('required_for_orders')) == dec(prod_c1.get('required_for_orders')) - 2)
    st, _ = call(owner, 'DELETE', f'/orders/orders/{oid2}/')
    step(f'DELETE отменённого заказа -> {st} (архив/405, без потери)', st in (204, 400, 405))

    print('\n--- ИТОГ ---')
    print(f'отказной заказ #{oid}: status={o.get("status")} payment={o.get("payment_status")}')
    print(f'отменённый заказ #{oid2}: status=cancelled')


if __name__ == '__main__':
    main()
