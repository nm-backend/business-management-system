"""Seed dev database with test data for preview."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.dev_sqlite_settings')

import django
django.setup()

from django.contrib.auth import get_user_model
from apps.companies.models import Company
from apps.warehouse.models import RawMaterial, FinishedProduct
from apps.clients.models import Client
from apps.orders.models import Order
from django.utils import timezone
from decimal import Decimal

User = get_user_model()
pw = 'Test1234!'

company, _ = Company.objects.get_or_create(name='SkladPro Test', defaults={'is_active': True})

for username, first, last, comp, role in [
    ('superadmin', 'Super', 'Admin', None, 'superadmin'),
    ('owner', 'Ivan', 'Owner', company, 'owner'),
    ('admin', 'Alex', 'Admin', company, 'admin'),
    ('manager', 'Anna', 'Manager', company, 'manager'),
    ('worker', 'Petr', 'Worker', company, 'worker'),
]:
    user, created = User.objects.get_or_create(
        username=username,
        defaults={'first_name': first, 'last_name': last, 'role': role, 'company': comp, 'email': f'{username}@example.com'}
    )
    user.set_password(pw)
    user.save()
    print(f'  {"+" if created else "="} {username} ({role})')

sa = User.objects.get(username='superadmin')
sa.company = None; sa.role = 'superadmin'; sa.is_staff = True; sa.is_superuser = True
sa.set_password(pw); sa.save()
print('  ~ superadmin updated')

RawMaterial.objects.get_or_create(name='Пиломатериал', company=company, defaults={'quantity': 100, 'unit': 'm3', 'purchase_price': Decimal('5000'), 'avg_cost_price': Decimal('5000'), 'min_stock': 10})
RawMaterial.objects.get_or_create(name='Гвозди', company=company, defaults={'quantity': 50, 'unit': 'kg', 'purchase_price': Decimal('200'), 'avg_cost_price': Decimal('200'), 'min_stock': 5})
print('Materials OK')

prod1, _ = FinishedProduct.objects.get_or_create(name='Стул деревянный', company=company, defaults={'quantity': 10, 'unit': 'шт', 'cost_price': Decimal('12000'), 'sale_price': Decimal('25000'), 'min_stock': 2})
print('Products OK')

client1, _ = Client.objects.get_or_create(name='IP Bobur', company=company, defaults={'phone': '+998901234567', 'debt': Decimal('1500000'), 'address': 'Ташкент, Чиланзар'})
client2, _ = Client.objects.get_or_create(name='OOO Alisher', company=company, defaults={'phone': '+998907654321', 'debt': Decimal('0'), 'address': 'Ташкент, Юнусабад'})
print('Clients OK')

# Orders — DB is fresh, just create directly
Order.objects.create(client=client1, product=prod1, quantity=2, total_amount=Decimal('50000'), status='pending', deadline=timezone.now()+timezone.timedelta(days=7), company=company, paid_amount=Decimal('0'))
Order.objects.create(client=client2, product=prod1, quantity=1, total_amount=Decimal('25000'), paid_amount=Decimal('10000'), status='in_progress', deadline=timezone.now()+timezone.timedelta(days=14), company=company)
print('Orders OK')
print('DONE')
