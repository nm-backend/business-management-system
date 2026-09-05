"""
Live-аудит прав и безопасности через работающий API (dev-сервер).

Проверяет, что:
- worker не видит финансовые поля и не имеет доступа к финансам/клиентам;
- admin не может повысить себя до owner и не видит суммы;
- запрещённые поля (role/company/is_active) нельзя менять напрямую;
- критические записи нельзя удалить напрямую (DELETE запрещён);
- server-side проверки реально работают (не только фронтенд).
"""
import json
import uuid
import requests

BASE = 'http://127.0.0.1:8000/api/v1'
PASSWORD = 'DemoPass123!'


def login(username):
    r = requests.post(f'{BASE}/accounts/login/', json={
        'username': username, 'password': PASSWORD, 'fingerprint': uuid.uuid4().hex,
    }, timeout=20)
    assert r.status_code == 200, f'login {username} -> {r.status_code}: {r.text[:300]}'
    data = r.json()
    return data['tokens']['access'], data['user']


def get(access, path, **kw):
    r = requests.get(f'{BASE}{path}', headers={'Authorization': f'Bearer {access}'}, **kw, timeout=20)
    return r.status_code, (r.json() if r.text else {})


def patch(access, path, payload):
    r = requests.patch(f'{BASE}{path}', json=payload,
                       headers={'Authorization': f'Bearer {access}'}, timeout=20)
    return r.status_code, (r.json() if r.text else {})


def post(access, path, payload=None):
    r = requests.post(f'{BASE}{path}', json=payload or {},
                      headers={'Authorization': f'Bearer {access}'}, timeout=20)
    return r.status_code, (r.json() if r.text else {})


def delete(access, path):
    r = requests.delete(f'{BASE}{path}', headers={'Authorization': f'Bearer {access}'}, timeout=20)
    return r.status_code, (r.json() if r.text else {})


def main():
    owner, owner_user = login('demo_owner')
    admin, admin_user = login('demo_admin')
    worker, worker_user = login('demo_worker')
    print('== roles ==')
    print('owner.role =', owner_user['role'])
    print('admin.role =', admin_user['role'])
    print('worker.role =', worker_user['role'])
    print('admin id =', admin_user['id'], 'owner id =', owner_user['id'])
    print()

    # 1) Worker: материалы без финансовых полей
    st, body = get(worker, '/warehouse/raw-materials/')
    rows = body.get('results', body) if isinstance(body, dict) else body
    print(f'[worker] /warehouse/raw-materials/ -> {st}, items={len(rows) if isinstance(rows, list) else "?"}')
    if isinstance(rows, list) and rows:
        keys = set(rows[0].keys())
        print('  keys include financial?', {'purchase_price', 'avg_cost_price'} & keys)
        print('  purchase_price in first item =', rows[0].get('purchase_price', 'ABSENT'))

    # 2) Worker: финансы и клиенты закрыты
    st, _ = get(worker, '/finance/expenses/')
    print(f'[worker] /finance/expenses/ -> {st} (expect 403)')
    st, _ = get(worker, '/clients/clients/')
    print(f'[worker] /clients/clients/ -> {st} (expect 403)')
    st, _ = get(worker, '/reports/analytics/owner/')
    print(f'[worker] /reports/analytics/owner/ -> {st} (expect 403)')

    # 3) Admin: клиенты видны, но без сумм
    st, body = get(admin, '/clients/clients/')
    rows = body.get('results', body) if isinstance(body, dict) else body
    print(f'[admin] /clients/clients/ -> {st}, items={len(rows) if isinstance(rows, list) else "?"}')
    if isinstance(rows, list) and rows:
        keys = set(rows[0].keys())
        print('  has debt/total_paid?', {'debt', 'total_paid', 'total_orders_amount'} & keys)
        print('  has has_debt?', 'has_debt' in keys)

    # 4) Admin: не может повысить себя до owner
    st, body = patch(admin, f'/accounts/users/{admin_user["id"]}/', {'role': 'owner'})
    print(f'[admin] PATCH self role->owner -> {st} (expect 403) {str(body)[:160]}')

    # 5) Owner: финансы доступны
    st, _ = get(owner, '/finance/expenses/')
    print(f'[owner] /finance/expenses/ -> {st} (expect 200)')

    # 6) Запрещённые поля: менеджмент полей нельзя перезаписать через материал
    st, body = get(admin, '/warehouse/raw-materials/')
    rows = body.get('results', body) if isinstance(body, dict) else body
    if isinstance(rows, list) and rows:
        mid = rows[0]['id']
        st2, b2 = patch(admin, f'/warehouse/raw-materials/{mid}/', {'company': 99999})
        print(f'[admin] PATCH material company=99999 -> {st2} (expect 400) {str(b2)[:160]}')

    # 7) Критические записи нельзя удалить напрямую (DELETE)
    st, body = delete(owner, '/warehouse/raw-materials/1/')
    print(f'[owner] DELETE /warehouse/raw-materials/1/ -> {st} (expect 405) {str(body)[:120]}')
    st, body = delete(owner, '/clients/clients/1/')
    print(f'[owner] DELETE /clients/clients/1/ -> {st} (expect 405/403) {str(body)[:120]}')

    # 8) Owner не должен иметь возможности трогать чужие компании (суперадмин-эндпоинт)
    st, body = get(owner, '/companies/')
    print(f'[owner] /companies/ (superadmin endpoint) -> {st} (expect 403)')


if __name__ == '__main__':
    main()
