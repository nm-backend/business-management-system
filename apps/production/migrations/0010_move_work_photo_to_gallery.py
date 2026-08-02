"""
Переносит уже загруженные одиночные фото работ в галерею.

WorkRecord.photo остаётся на месте, но интерфейс с этого момента показывает
WorkPhoto. Без переноса все снимки, приложенные рабочими до появления
галереи, пропали бы из карточки подтверждения.
"""
from django.db import migrations


def photo_to_gallery(apps, schema_editor):
    WorkRecord = apps.get_model('production', 'WorkRecord')
    WorkPhoto = apps.get_model('production', 'WorkPhoto')

    existing = set(WorkPhoto.objects.values_list('work_id', flat=True))
    WorkPhoto.objects.bulk_create([
        WorkPhoto(work_id=work.id, image=work.photo)
        for work in WorkRecord.objects.exclude(photo='').exclude(photo=None)
        if work.id not in existing
    ])


def gallery_to_photo(apps, schema_editor):
    """
    Откат: возвращаем первый снимок галереи в одиночное поле, если оно пустое.
    Сами записи галереи удалит откат предыдущей миграции.
    """
    WorkRecord = apps.get_model('production', 'WorkRecord')
    WorkPhoto = apps.get_model('production', 'WorkPhoto')

    for work in WorkRecord.objects.filter(photo=''):
        first = WorkPhoto.objects.filter(work_id=work.id).order_by('id').first()
        if first:
            work.photo = first.image
            work.save(update_fields=['photo'])


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0009_workphoto'),
    ]

    operations = [
        migrations.RunPython(photo_to_gallery, gallery_to_photo),
    ]
