"""
Валют по умолчанию в системе может быть только одна.

Приложение защищает это переопределённым Currency.save(), но два
параллельных запроса могли проскочить мимо него (сначала обе вставки,
потом сброс). Частичный уникальный индекс ниже закрывает гонку на уровне
БД: вторая вставка с is_default=True падает с IntegrityError, а save()
повторяет сброс и сохраняется заново (apps/core/models.py).
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_exchangerate_rate_validator'),
    ]

    operations = [
        migrations.RunSQL(
            sql='CREATE UNIQUE INDEX core_currency_single_default '
                'ON core_currency (is_default) WHERE is_default;',
            reverse_sql='DROP INDEX core_currency_single_default;',
        ),
    ]
