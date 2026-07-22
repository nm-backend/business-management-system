"""
N+1 в ExchangeRateViewSet (аудит K, находка #7).

Сериализатор отдаёт from_currency_code/to_currency_code (source='..currency.code'),
но queryset был ExchangeRate.objects.all() без select_related — каждая строка
дёргала 2 доп. SELECT к core_currency.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.core.models import Currency, ExchangeRate
from apps.core.serializers import ExchangeRateSerializer
from apps.core.views import ExchangeRateViewSet


class ExchangeRateNPlusOneTests(TestCase):
    def setUp(self):
        self.base = Currency.objects.create(code='US0', name='base', symbol='$')
        for i in range(5):
            cur = Currency.objects.create(code=f'C{i:02d}', name=f'c{i}', symbol='x')
            ExchangeRate.objects.create(
                from_currency=cur, to_currency=self.base,
                rate=Decimal('1.5'), effective_date=datetime.date(2026, 1, 1 + i))

    def test_list_serialization_is_single_query(self):
        # queryset вьюсета (класс-атрибут) со select_related -> 1 запрос на все строки.
        qs = ExchangeRateViewSet.queryset.all()
        with self.assertNumQueries(1):
            data = ExchangeRateSerializer(qs, many=True).data
            self.assertEqual(len(data), 5)
