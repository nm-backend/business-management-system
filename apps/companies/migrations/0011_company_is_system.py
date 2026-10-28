"""
Флаг «системная компания» для компании, созданной миграцией 0002.

Миграция 0002 создаёт компанию SkladPro только при переносе легаси-данных
(на чистой установке её нет). Такая компания — не тестовый тенант: её удаление
уничтожило бы данные, ещё не разложенные по компаниям. Помечаем её флагом,
чтобы защита не зависела от имени (имя можно изменить в админке).
"""
from django.db import migrations, models


def mark_legacy_company(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Company.objects.filter(name='SkladPro').update(is_system=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0010_company_min_work_photos'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='is_system',
            field=models.BooleanField(
                default=False, db_index=True, verbose_name='Системная компания',
            ),
        ),
        migrations.RunPython(mark_legacy_company, noop),
    ]
