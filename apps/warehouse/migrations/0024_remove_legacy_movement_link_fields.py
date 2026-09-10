"""Удаление legacy-ссылок движений склада.

- legacy_related_order_id: данные перенесены в related_order (см. 0023);
- related_production_id: write-only поле, ни одно чтение в коде и API
  его не использовало (связь работы и движений восстанавливается через
  reason 'Work #<id> confirmed' при необходимости археологии).
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('warehouse', '0023_stockmovement_related_order_fk'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='stockmovement',
            name='legacy_related_order_id',
        ),
        migrations.RemoveField(
            model_name='stockmovement',
            name='related_production_id',
        ),
    ]
