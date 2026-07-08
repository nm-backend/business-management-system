from django.contrib import admin
from .models import Currency, ExchangeRate

@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'symbol', 'is_default', 'is_active']
    list_filter = ['is_default', 'is_active']
    search_fields = ['code', 'name']

@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['from_currency', 'to_currency', 'rate', 'effective_date']
    list_filter = ['from_currency', 'to_currency']
    date_hierarchy = 'effective_date'
