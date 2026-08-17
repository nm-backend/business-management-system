"""Минимальная репродукция гонки: два потока продлевают подписку."""
import os
import threading
import traceback
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.settings')
import django
django.setup()

from django.test.utils import setup_test_environment, teardown_test_environment
from django.test.runner import DiscoverRunner

runner = DiscoverRunner(verbosity=0)
old_config = runner.setup_databases()

setup_test_environment()

from datetime import timedelta
from django.utils import timezone
from apps.accounts.models import User
from apps.companies.models import Company, SubscriptionPlan
from apps.companies.subscriptions import extend_subscription

try:
    User.objects.create_superuser(username='probe_root', password='pw')
    company = Company.objects.create(name='ProbeCo', plan=SubscriptionPlan.get_default_plan())
    now = timezone.now()
    company.subscription_start = now
    company.subscription_end = now + timedelta(days=10)
    company.save(update_fields=['subscription_start', 'subscription_end'])

    barrier = threading.Barrier(2)
    results = []

    def extend():
        try:
            barrier.wait(timeout=10)
            extend_subscription(company, days=30, actor=None)
            results.append('ok')
        except Exception as exc:
            results.append(f'err: {type(exc).__name__}: {exc}')
            traceback.print_exc()

    threads = [threading.Thread(target=extend) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    alive = [t.is_alive() for t in threads]
    print('alive after join:', alive)
    print('results:', results)
    company.refresh_from_db()
    print('end:', company.subscription_end, 'history:', company.subscription_changes.count())
finally:
    teardown_test_environment()
    runner.teardown_databases(old_config)
