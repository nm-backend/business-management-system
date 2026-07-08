from django.contrib.auth.models import AbstractUser
from django.db import models
from .managers import UserManager

class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Egasi'
        ADMIN = 'admin', 'Administrator'
        WORKER = 'worker', 'Ishchi'

    class Language(models.TextChoices):
        UZBEK = 'uz_cyrl', 'Ўзбекча'
        RUSSIAN = 'ru', 'Русский'

    email = models.EmailField(blank=True, default='')
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.WORKER, db_index=True)
    phone = models.CharField(max_length=20, blank=True, default='')
    full_name = models.CharField(max_length=255, blank=True, default='')
    avatar = models.ImageField(upload_to='avatars/', blank=True, default='')
    language = models.CharField(max_length=10, choices=Language.choices, default=Language.UZBEK)

    can_write_to_owner = models.BooleanField(default=False)
    can_create_workers = models.BooleanField(default=False)
    can_see_other_workers = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']

    def __str__(self):
        return self.full_name or self.username

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_worker(self):
        return self.role == self.Role.WORKER

    @property
    def display_role(self):
        return dict(self.Role.choices).get(self.role, self.role)
