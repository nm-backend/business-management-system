"""
Транслит-поиск (замечание тестировщика): «Гулнора» должна находиться
по запросу «Gulnora» и наоборот — клиенты, заказы, сотрудники в чате.
"""
from django.test import TestCase

from apps.core.translit import to_cyrillic, to_latin, translit_variants


class TranslitUnitTests(TestCase):
    def test_latin_to_cyrillic(self):
        self.assertEqual(to_cyrillic('gulnora'), 'гулнора')
        self.assertEqual(to_cyrillic('Shoxrux'), 'шохрух')
        self.assertEqual(to_cyrillic("O'ktam"), 'ўктам')
        self.assertEqual(to_cyrillic("G'ani"), 'ғани')
        self.assertEqual(to_cyrillic('Chinor'), 'чинор')
        self.assertEqual(to_cyrillic('Farruh'), 'фарруҳ')

    def test_cyrillic_to_latin(self):
        self.assertEqual(to_latin('Гулнора'), 'gulnora')
        self.assertEqual(to_latin('Ўктам'), "o'ktam")
        # «х» по-узбекски латиницей — «x» (Шахзод -> Shaxzod), как в «Shox».
        self.assertEqual(to_latin('Шахзод'), 'shaxzod')

    def test_variants_include_both_directions(self):
        variants = translit_variants('Gulnora')
        self.assertIn('gulnora', variants)
        self.assertIn('гулнора', variants)

    def test_empty_query_gives_no_variants(self):
        self.assertEqual(translit_variants('   '), [])


class TranslitSearchAPITests(TestCase):
    def setUp(self):
        from apps.accounts.models import User
        from apps.clients.models import Client
        from apps.companies.models import Company
        self.company = Company.objects.create(name='TransCo', is_active=True)
        self.owner = User.objects.create_user(username='tr_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Гулнора Рахимова',
                                                phone='+998901234567')
        Client.objects.create(company=self.company, name='Иван Мраморов', phone='+998902345678')
        self.client.force_login(self.owner)

    def test_latin_query_finds_cyrillic_client(self):
        resp = self.client.get('/api/v1/clients/clients/?search=Gulnora')
        self.assertEqual(resp.status_code, 200)
        names = [c['name'] for c in resp.json()['results']]
        self.assertIn('Гулнора Рахимова', names)
        self.assertNotIn('Иван Мраморов', names)

    def test_cyrillic_query_finds_latin_typed_client(self):
        resp = self.client.get('/api/v1/clients/clients/?search=Иван')
        names = [c['name'] for c in resp.json()['results']]
        self.assertEqual(names, ['Иван Мраморов'])
