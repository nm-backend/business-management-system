import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='companies.Company')
def provision_subscription(sender, instance, created, **kwargs):
    if not created:
        return
    from .services import create_subscription
    create_subscription(instance)
