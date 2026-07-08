from django.contrib.auth.models import BaseUserManager

class UserManager(BaseUserManager):
    """Custom user manager for SkladPro."""

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('Username is required')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'owner')
        return self.create_user(username, password, **extra_fields)

    def owners(self):
        return self.filter(role='owner', is_active=True)

    def admins(self):
        return self.filter(role='admin', is_active=True)

    def workers(self):
        return self.filter(role='worker', is_active=True)
