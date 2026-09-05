"""
Демо-контент для ручной проверки списков/фильтров (разработка).

Дополняет компанию «Granit Demo MChJ» справочными данными:
готовые товары, клиенты, расходы. Идемпотентен.
"""
import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.settings')
django.setup()

from apps.companies.models import Company
from apps.warehouse.models import RawMaterial, FinishedProduct, Recipe, RecipeItem, StockMovement, UnitChoices
from apps.clients.models import Client
from apps.finance.models import Expense, ExpenseCategory, PaymentMethod as ExpensePaymentMethod
from apps.accounts.models import User

company = Company.objects.get(name='Granit Demo MChJ')
owner = User.objects.get(username='demo_owner', company=company)
print('company', company.id)

# ── Сырьё ──
MATERIALS = [
    # name, stone_type, color, size, thickness, unit, qty, zone, purchase_price
    ('Мармар крем', 'Мармар', 'Крем', '2.2 × 1.1 × 1.5 м', '20 мм', 'sht', 16, 'a', '1250000'),
    ('Мармар қора', 'Мармар', 'Қора', '2.3 × 1.3 × 1.7 м', '20 мм', 'sht', 12, 'a', '1500000'),
    ('Гранит серый', 'Гранит', 'Серый', '2.0 × 3.0 м', '20 мм', 'm2', 150, 'b', '380000'),
    ('Гранит қора', 'Гранит', 'Қора', '2.0 × 3.0 м', '20 мм', 'm2', 98, 'b', '420000'),
    ('Травертин бежевый', 'Травертин', 'Бежевый', '2.0 × 3.0 м', '20 мм', 'm2', 72, 'c', '300000'),
    ('Елим (AB)', 'Бошқа', '', '', '', 'kg', 30, 'other', '45000'),
    ('Полиэстер қўшилма', 'Бошқа', '', '', '', 'kg', 12, 'other', '70000'),
]
for name, st, color, size, thick, unit, qty, zone, price in MATERIALS:
    if not RawMaterial.objects.filter(company=company, name=name).exists():
        RawMaterial.objects.create(
            company=company, name=name, stone_type=st, color=color, size=size,
            thickness=thick, unit=unit, quantity=qty, storage_zone=zone,
            purchase_price=Decimal(price), avg_cost_price=Decimal(price),
            min_stock=Decimal('5') if unit in ('sht',) else Decimal('10'),
        )
print('materials ok')

# ── Готовая продукция ──
PRODUCTS = [
    ('Ошхона столешница', 'Столешница', 'm2', 40, '450000', '900000'),
    ('Подоконник', 'Подоконник', 'dona', 18, '180000', '450000'),
    ('Лестница ступени', 'Лестница', 'dona', 22, '250000', '600000'),
]
for name, cat, unit, qty, cost, sale in PRODUCTS:
    if not FinishedProduct.objects.filter(company=company, name=name).exists():
        FinishedProduct.objects.create(
            company=company, name=name, category=cat, unit=unit, quantity=qty,
            cost_price=Decimal(cost), sale_price=Decimal(sale), min_stock=Decimal('3'),
        )
print('products ok')

# ── Клиенты ──
CLIENTS = [
    ('Акбаров Азизбек', '+998 90 123-45-67', 'Тошкент ш., Юнусобод тумани', 'Тўловларни бўлиб-бўлиб амалга оширади'),
    ('Раҳмонов Бобур', '+998 91 222-33-44', 'Тошкент ш., Миробод тумани', ''),
    ('Исломов Икром', '+998 93 555-11-22', 'Тошкент ш., Яккасарой тумани', ''),
    ('Норматов Нодир', '+998 90 777-88-99', 'Тошкент ш., Чилонзор тумани', 'Ишончли мижоз'),
]
for name, phone, addr, comment in CLIENTS:
    if not Client.objects.filter(company=company, name=name).exists():
        Client.objects.create(company=company, name=name, phone=phone, address=addr, comment=comment)
print('clients ok')

# ── Расходы (только owner видит) ──
from datetime import date
EXPENSES = [
    (ExpenseCategory.RENT, '2500000', date(2026, 8, 3), 'Ойлик ижара'),
    (ExpenseCategory.ELECTRICITY, '850000', date(2026, 8, 10), 'Электр энергия'),
    (ExpenseCategory.TRANSPORT, '400000', date(2026, 8, 15), 'Транспорт'),
    (ExpenseCategory.SALARY, '3200000', date(2026, 8, 25), 'Иш ҳақи'),
    (ExpenseCategory.TOOLS, '250000', date(2026, 8, 28), 'Асбоб'),
]
for cat, amount, day, comment in EXPENSES:
    if not Expense.objects.filter(company=company, category=cat, date=day).exists():
        Expense.objects.create(
            company=company, category=cat, amount=Decimal(amount),
            date=day, comment=comment,            created_by=owner,
            payment_method=ExpensePaymentMethod.CASH,
        )
print('expenses ok')
print('DONE')
