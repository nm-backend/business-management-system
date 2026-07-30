# Generated manually: merge migration — adds arrival_date to FinishedProduct
# after 0007_alter_finishedproduct_cost_price_and_more.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('warehouse', '0007_alter_finishedproduct_cost_price_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='finishedproduct',
            name='arrival_date',
            field=models.DateField(blank=True, null=True, verbose_name='Дата поступления'),
        ),
    ]
