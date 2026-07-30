import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.dev_sqlite_settings')
import django; django.setup()
from django.utils import timezone
from apps.accounts.models import User
from apps.companies.models import Company
from apps.clients.models import Client
from apps.warehouse.models import RawMaterial, FinishedProduct
from apps.orders.models import Order
from apps.finance.models import Expense, LaborRate

today = timezone.now().date()
uid = User.objects.create_superuser('superadmin', 'SuperAdmin123!', full_name='Super Admin', role='superadmin')
company = Company.objects.create(name='Granit-Kamneobrabotka', is_active=True)
owner = User.objects.create_user('ivan_owner', 'OwnerPass123!', company=company, role='owner', full_name='Ivan Owner')
admin = User.objects.create_user('alex_admin', 'AdminPass123!', company=company, role='admin', full_name='Alex Admin', can_create_workers=True)
User.objects.create_user('petr_worker', 'Worker123!', company=company, role='worker', full_name='Petr Worker')
User.objects.create_user('anna_worker', 'Worker123!', company=company, role='worker', full_name='Anna Worker')
RawMaterial.objects.create(company=company, name='Granit Absolute Black', unit='m2', quantity=100, purchase_price=5000, avg_cost_price=5000)
RawMaterial.objects.create(company=company, name='Mramor White', unit='m2', quantity=50, purchase_price=150000, avg_cost_price=150000)
FinishedProduct.objects.create(company=company, name='Stoleshnitsa 600x400', unit='izdelie', sale_price=45000, cost_price=30000)
FinishedProduct.objects.create(company=company, name='Podokonnik 1200x300', unit='izdelie', sale_price=30000, cost_price=20000)
Client.objects.create(company=company, name='OOO Alisher', phone='+998901234567')
Client.objects.create(company=company, name='IP Bobur', phone='+998907654321')
Order.objects.create(company=company, client_id=1, product_id=1, quantity=2, unit='sht', total_amount=90000, status='ready', worker_id=5)
Order.objects.create(company=company, client_id=2, product_id=2, quantity=1, unit='sht', total_amount=30000, status='new')
Expense.objects.create(company=company, category='rent', amount=500000, comment='Office rent', created_by=owner, date=today)
Expense.objects.create(company=company, category='electricity', amount=100000, comment='Electro', created_by=owner, date=today)
LaborRate.objects.create(company=company, product_id=1, operation='cutting', rate_per_unit=5000)
print(f'OK: {User.objects.count()} users, {Company.objects.count()} companies')
