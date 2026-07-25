"""
Management command: python manage.py generate_vapid_keys

Генерирует VAPID ключи для Web Push и выводит их в формате для .env
"""
import base64
from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from py_vapid import Vapid


class Command(BaseCommand):
    help = 'Generate VAPID keys for Web Push notifications'

    def handle(self, *args, **options):
        v = Vapid()
        v.generate_keys()

        pub_bytes = v.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()

        priv_bytes = v.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        priv_b64 = base64.urlsafe_b64encode(priv_bytes).rstrip(b'=').decode()

        self.stdout.write(self.style.SUCCESS('VAPID keys generated! Add to .env or settings:'))
        self.stdout.write('')
        self.stdout.write(f'VAPID_PUBLIC_KEY={pub_b64}')
        self.stdout.write(f'VAPID_PRIVATE_KEY={priv_b64}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            'Also add VAPID_PUBLIC_KEY to your frontend for push subscription.'
        ))
