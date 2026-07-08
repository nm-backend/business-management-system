from rest_framework import serializers
from .models import Currency, ExchangeRate

class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ['id', 'code', 'name', 'symbol', 'is_default', 'is_active', 'decimal_places']

class ExchangeRateSerializer(serializers.ModelSerializer):
    from_currency_code = serializers.CharField(source='from_currency.code', read_only=True)
    to_currency_code = serializers.CharField(source='to_currency.code', read_only=True)

    class Meta:
        model = ExchangeRate
        fields = ['id', 'from_currency', 'to_currency', 'from_currency_code', 'to_currency_code', 'rate', 'effective_date']
