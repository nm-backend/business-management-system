from decouple import config

environment = config('DJANGO_ENV', default='development')

if environment == 'production':
    from .production import *
else:
    from .development import *
