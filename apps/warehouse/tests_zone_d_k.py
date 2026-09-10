"""
«Г зона» (макет «Омбордаги жойлашув»: сетка А/Б/В/Г).

Зона 'd' существовала в макете, но не в choices: при фильтре по «Г зона»
сервер отвечал пустым списком, а в форме материала зону было не выбрать.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.warehouse.models import RawMaterial, StorageZoneChoices, Warehouse

MATERIALS = '/api/v1/warehouse/raw-materials/'


class ZoneDTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='ZoneCo')
        cls.admin = User.objects.create_user(
            username='z_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.warehouse = Warehouse.objects.create(
            company=cls.company, name='Асосий омбор', is_default=True,
        )
        cls.zone_d_material = RawMaterial.objects.create(
            company=cls.company, name='Оқ мрамор плита', unit='m2',
            quantity=Decimal('25'), stone_type='Табиий мрамор', storage_zone='d',
            warehouse=cls.warehouse,
        )
        RawMaterial.objects.create(
            company=cls.company, name='Қора гранит', unit='m2',
            quantity=Decimal('10'), stone_type='Гранит', storage_zone='a',
            warehouse=cls.warehouse,
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def test_zone_d_choice_exists(self):
        self.assertIn('d', StorageZoneChoices.values)

    def test_filter_by_zone_d(self):
        response = self.api_as(self.admin).get(MATERIALS, {'storage_zone': 'd'})
        self.assertEqual(response.status_code, 200)
        names = [row['name'] for row in response.data['results']]
        self.assertEqual(names, ['Оқ мрамор плита'])

    def test_material_can_be_created_in_zone_d(self):
        response = self.api_as(self.admin).post(MATERIALS, {
            'name': 'Травертин', 'unit': 'm2', 'quantity': '5',
            'storage_zone': 'd', 'warehouse': self.warehouse.id,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['storage_zone'], 'd')

    def test_display_name_is_zone_g(self):
        """Метка зоны — «Г зона», как в макете (А/Б/В/Г)."""
        material = RawMaterial.objects.get(pk=self.zone_d_material.pk)
        self.assertEqual(material.get_storage_zone_display(), 'Г зона')
