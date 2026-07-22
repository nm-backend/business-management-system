"""
N+1 в CompanyViewSet list (аудит K, находка #6).

CompanySerializer считал users_count (source='users.count') и дважды искал
владельца (get_owner_username + get_owner_full_name, каждый через свежий
_owner()) — 3 доп. запроса на КАЖДУЮ компанию. Правим аннотацией + префетчем.
"""
from django.test import TestCase

from apps.accounts.models import User
from apps.companies.models import Company
from apps.companies.serializers import CompanySerializer
from apps.companies.views import CompanyViewSet


class CompanyListNPlusOneTests(TestCase):
    def setUp(self):
        for i in range(5):
            comp = Company.objects.create(name=f'NP{i}')
            User.objects.create_user(username=f'np_o{i}', password='p',
                                     role=User.Role.OWNER, company=comp)
            User.objects.create_user(username=f'np_w{i}', password='p',
                                     role=User.Role.WORKER, company=comp)

    def test_list_serialization_bounded_queries(self):
        qs = CompanyViewSet().get_queryset()
        # 1 запрос на компании (+ annotate Count) + 1 на префетч владельцев = 2,
        # независимо от числа компаний.
        with self.assertNumQueries(2):
            data = CompanySerializer(qs, many=True).data
            self.assertEqual(len(data), 5)
            self.assertTrue(all(row['owner_username'] for row in data))
            self.assertTrue(all(row['users_count'] == 2 for row in data))
