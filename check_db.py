"""Check what's in dev_preview.sqlite3"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.dev_sqlite_settings')
import django
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()
users = User.objects.all().values('id','username','role','is_active','company_id','status','email')
print('=== USERS ===')
for u in users:
    print(u)

try:
    from apps.companies.models import Company
    companies = Company.objects.all().values('id','name','is_active')
    print('=== COMPANIES ===')
    for c in companies:
        print(c)
except Exception as e:
    print(f'No companies: {e}')

try:
    from apps.accounts.models import AccessKey
    keys = AccessKey.objects.all().values('id','key','user_id','status')
    print('=== ACCESS KEYS ===')
    for k in keys:
        print(k)
except Exception as e:
    print(f'No access keys: {e}')

# Check for any sample data
try:
    from apps.warehouse.models import RawMaterial
    mats = RawMaterial.objects.all().values('id','name','quantity')
    print('=== RAW MATERIALS ===')
    for m in mats:
        print(m)
except Exception as e:
    print(f'No raw materials: {e}')

try:
    from apps.clients.models import Client
    clients = Client.objects.all().values('id','full_name','company_id')
    print('=== CLIENTS ===')
    for c in clients:
        print(c)
except Exception as e:
    print(f'No clients: {e}')

try:
    from apps.orders.models import Order
    orders = Order.objects.all().values('id','status','client_id')
    print('=== ORDERS ===')
    for o in orders:
        print(o)
except Exception as e:
    print(f'No orders: {e}')
