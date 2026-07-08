from .base import *
from decouple import config

DEBUG = True

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

CORS_ALLOW_ALL_ORIGINS = True
