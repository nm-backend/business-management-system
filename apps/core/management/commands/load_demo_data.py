# =============================================================================
# SkladPro — Demo Data Loader
#
# Usage:  python manage.py load_demo_data
#         python manage.py load_demo_data --force   (reset first)
# =============================================================================

from decimal import Decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.warehouse.models import RawMaterial, FinishedProduct, Recipe, RecipeItem
from apps.orders.models import Order, OrderStatus, PaymentStatus
from apps.finance.models import LaborRate, Expense


class Command(BaseCommand):
    help = 'Loads demo data for development and testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='Delete existing data before loading (except superusers)',
        )

    def handle(self, *args, **options):
        # Guard: refuse to load twice without --force
        if Client.objects.exists() and not options['force']:
            self.stdout.write(self.style.WARNING(
                'Data already loaded. Use --force to reload.'
            ))
            return

        if options['force']:
            self._clear_data()

        self._create_users()
        self._create_clients()
        self._create_warehouse()
        self._create_orders()
        self._create_production()
        self._create_finance()

        self.stdout.write(self.style.SUCCESS('[OK] Demo data loaded successfully!'))

    def _clear_data(self):
        self.stdout.write('Clearing existing data...')
        User.objects.filter(is_superuser=False).delete()
        Client.objects.all().delete()
        RawMaterial.objects.all().delete()
        FinishedProduct.objects.all().delete()
        Order.objects.all().delete()
        LaborRate.objects.all().delete()
        Expense.objects.all().delete()
        self.stdout.write('  OK - Data cleared')

    def _create_users(self):
        self.stdout.write('Creating users...')

        owner, _ = User.objects.get_or_create(
            username='owner',
            defaults={
                'role': User.Role.OWNER,
                'full_name': 'Akbar Xo\'jayev',
                'phone': '+998901234567',
                'language': User.Language.UZBEK,
                'can_create_workers': True,
                'is_staff': True,
            },
        )
        owner.set_password('owner123')
        owner.save()

        admin, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'role': User.Role.ADMIN,
                'full_name': 'Bobur Karimov',
                'phone': '+998901234568',
                'language': User.Language.RUSSIAN,
                'can_create_workers': False,
                'can_write_to_owner': True,
                'is_staff': True,
            },
        )
        admin.set_password('admin123')
        admin.save()

        worker1, _ = User.objects.get_or_create(
            username='worker',
            defaults={
                'role': User.Role.WORKER,
                'full_name': 'Jamshid Toshmatov',
                'phone': '+998901234569',
                'language': User.Language.UZBEK,
            },
        )
        worker1.set_password('worker123')
        worker1.save()

        worker2, _ = User.objects.get_or_create(
            username='dilmurod',
            defaults={
                'role': User.Role.WORKER,
                'full_name': 'Dilmurod Rahimov',
                'phone': '+998901234570',
                'language': User.Language.UZBEK,
            },
        )
        worker2.set_password('worker123')
        worker2.save()

        self.stdout.write(f'  [OK] {User.objects.filter(is_superuser=False).count()} users created')
        self.stdout.write('    owner / owner123  (Egasi)')
        self.stdout.write('    admin / admin123  (Administrator)')
        self.stdout.write('    worker / worker123  (Ishchi)')
        self.stdout.write('    dilmurod / worker123  (Ishchi)')

    def _create_clients(self):
        self.stdout.write('Creating clients...')

        clients_data = [
            ('Kamoliddin Anvarov', '+998901111111', 'Toshkent, Chilonzor'),
            ('Madina Yusupova', '+998902222222', 'Toshkent, Yunusobod'),
            ('Shavkat Rasulov', '+998903333333', 'Samarqand, Registon'),
            ('Gulnora Azimova', '+998904444444', 'Buxoro, Labihovuz'),
            ('Rustam Bekmurodov', '+998905555555', 'Farg\'ona, Markaz'),
            ('Nigora Sodiqova', '+998906666666', 'Andijon, Chorsu'),
            ('Oybek Sultonov', '+998907777777', 'Namangan, Markaziy bozor'),
            ('Zulfiya Karimova', '+998908888888', 'Nukus, Oltinko\'l'),
        ]

        for name, phone, address in clients_data:
            Client.objects.create(
                name=name,
                phone=phone,
                address=address,
            )

        self.stdout.write(f'  [OK] {Client.objects.count()} clients created')

    def _create_warehouse(self):
        self.stdout.write('Creating warehouse...')

        # Raw materials
        marble = RawMaterial.objects.create(
            name='Marmar oq (White Marble)', unit='m2', quantity=150,
            purchase_price=Decimal('200000'),
            min_stock=20, supplier='Italiya Stone LTD',
        )
        granite = RawMaterial.objects.create(
            name='Granit qora (Black Granite)', unit='m2', quantity=100,
            purchase_price=Decimal('350000'),
            min_stock=15, supplier='Hindiston Granite Co',
        )
        travertine = RawMaterial.objects.create(
            name='Travertin (Travertine)', unit='m2', quantity=80,
            purchase_price=Decimal('180000'),
            min_stock=10, supplier='Turkiya Mermer AS',
        )
        glue = RawMaterial.objects.create(
            name='Yelim (Adhesive)', unit='kg', quantity=200,
            purchase_price=Decimal('15000'),
            min_stock=50, supplier='Soudal Oziq-ovqat',
        )
        polish = RawMaterial.objects.create(
            name='Polishing paste', unit='kg', quantity=50,
            purchase_price=Decimal('45000'),
            min_stock=10, supplier='Klindex Italy',
        )

        self.stdout.write('  [OK] Raw materials created')

        # Finished products
        countertop = FinishedProduct.objects.create(
            name='Oshxona stol ustki (Countertop 2.4m)', unit='шт',
            quantity=5, sale_price=Decimal('1500000'),
            cost_price=Decimal('800000'), min_stock=2,
        )
        windowsill = FinishedProduct.objects.create(
            name='Deraza osti (Windowsill 1.2m)', unit='шт',
            quantity=8, sale_price=Decimal('450000'),
            cost_price=Decimal('250000'), min_stock=3,
        )
        stairs = FinishedProduct.objects.create(
            name='Zina pog\'onasi (Stair step)', unit='шт',
            quantity=3, sale_price=Decimal('600000'),
            cost_price=Decimal('350000'), min_stock=1,
        )
        monument = FinishedProduct.objects.create(
            name='Yodgorlik (Monument standard)', unit='шт',
            quantity=2, sale_price=Decimal('2500000'),
            cost_price=Decimal('1200000'), min_stock=1,
        )

        self.stdout.write('  [OK] Finished products created')

        # Recipes (Bill of Materials)
        r1 = Recipe.objects.create(product=countertop, name='Countertop 2.4m recipe')
        RecipeItem.objects.create(recipe=r1, material=marble, quantity_required=3, unit='m2')
        RecipeItem.objects.create(recipe=r1, material=glue, quantity_required=0.5, unit='kg')
        RecipeItem.objects.create(recipe=r1, material=polish, quantity_required=0.2, unit='kg')

        r2 = Recipe.objects.create(product=windowsill, name='Windowsill 1.2m recipe')
        RecipeItem.objects.create(recipe=r2, material=travertine, quantity_required=0.8, unit='m2')
        RecipeItem.objects.create(recipe=r2, material=glue, quantity_required=0.3, unit='kg')

        r3 = Recipe.objects.create(product=stairs, name='Stair step recipe')
        RecipeItem.objects.create(recipe=r3, material=granite, quantity_required=1.2, unit='m2')
        RecipeItem.objects.create(recipe=r3, material=polish, quantity_required=0.15, unit='kg')

        self.stdout.write('  [OK] Recipes created')

    def _create_orders(self):
        self.stdout.write('Creating orders...')

        clients = list(Client.objects.all())
        products = list(FinishedProduct.objects.all())
        owner = User.objects.get(username='owner')
        worker = User.objects.get(username='worker')

        orders_data = [
            (0, 0, 2, 'm2', '2026-08-15', OrderStatus.READY, PaymentStatus.PAID, Decimal('3000000'), Decimal('3000000')),
            (1, 1, 3, 'шт', '2026-08-20', OrderStatus.IN_PROGRESS, PaymentStatus.PARTIAL, Decimal('1350000'), Decimal('500000')),
            (2, 2, 5, 'шт', '2026-09-01', OrderStatus.NEW, PaymentStatus.UNPAID, Decimal('3000000'), Decimal('0')),
            (3, 0, 1, 'm2', '2026-07-25', OrderStatus.DELIVERED, PaymentStatus.PAID, Decimal('1500000'), Decimal('1500000')),
            (4, 3, 1, 'шт', '2026-09-10', OrderStatus.NEW, PaymentStatus.UNPAID, Decimal('2500000'), Decimal('0')),
            (5, 1, 2, 'шт', '2026-08-05', OrderStatus.SENT_TO_WORKER, PaymentStatus.UNPAID, Decimal('900000'), Decimal('0')),
        ]

        for client_idx, product_idx, qty, unit, deadline, status, payment, total, paid in orders_data:
            Order.objects.create(
                client=clients[client_idx],
                product=products[product_idx] if product_idx < len(products) else None,
                quantity=qty,
                unit=unit,
                deadline=date.fromisoformat(deadline),
                status=status,
                payment_status=payment,
                total_amount=total,
                paid_amount=paid,
                worker=worker if status in (OrderStatus.SENT_TO_WORKER, OrderStatus.IN_PROGRESS) else None,
            )

        # An overdue order
        overdue_client = Client.objects.create(
            name='Murod Aliqulov (Qarzdor)',
            phone='+998909999999',
            address='Sirdaryo, Guliston',
        )
        Order.objects.create(
            client=overdue_client,
            quantity=2, unit='m2',
            deadline=date.today() - timedelta(days=15),
            status=OrderStatus.NEW,
            payment_status=PaymentStatus.UNPAID,
            total_amount=Decimal('1600000'),
        )

        self.stdout.write(f'  [OK] {Order.objects.count()} orders created')

    def _create_production(self):
        self.stdout.write('Creating production data...')

        worker = User.objects.get(username='worker')

        # Labor rates
        LaborRate.objects.create(
            operation=LaborRate.OperationType.CUTTING,
            unit='m2',
            rate_per_unit=Decimal('50000'),
            description='Kesish (Cutting)',
        )
        LaborRate.objects.create(
            operation=LaborRate.OperationType.POLISHING,
            unit='m2',
            rate_per_unit=Decimal('75000'),
            description='Silvirlash (Polishing)',
        )

        self.stdout.write('  [OK] Production data created')

    def _create_finance(self):
        self.stdout.write('Creating finance data...')

        owner = User.objects.get(username='owner')

        Expense.objects.create(
            category=Expense.Category.RENT,
            amount=Decimal('5000000'),
            comment='Ishlab chiqarish sexi ijarasi (iyul)',
            added_by=owner,
            payment_date=date.today() - timedelta(days=5),
        )
        Expense.objects.create(
            category=Expense.Category.ELECTRICITY,
            amount=Decimal('850000'),
            comment='Elektr energiyasi (iyun)',
            added_by=owner,
            payment_date=date.today() - timedelta(days=10),
        )
        Expense.objects.create(
            category=Expense.Category.TRANSPORT,
            amount=Decimal('350000'),
            comment='Material yetkazib berish (Toshkent-Samarqand)',
            added_by=owner,
            payment_date=date.today() - timedelta(days=3),
        )
        Expense.objects.create(
            category=Expense.Category.TOOLS,
            amount=Decimal('1200000'),
            comment='Almaz disk (kesish uchun) x2',
            added_by=owner,
            payment_date=date.today() - timedelta(days=2),
        )

        self.stdout.write(f'  [OK] {Expense.objects.count()} expenses created')
