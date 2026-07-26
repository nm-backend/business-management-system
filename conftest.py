# =============================================================================
# SkladPro — Root pytest conftest
#
# Shared fixtures available to all test modules.
# =============================================================================

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.warehouse.models import RawMaterial, FinishedProduct


# ==================== User Fixtures ====================

@pytest.fixture
def api_client():
    """Returns an unauthenticated DRF API client."""
    return APIClient()


@pytest.fixture
def auth_client(api_client):
    """Returns an API client that auto-authenticates.
    Sub-fixtures should set api_client.force_authenticate(user=...)."""
    return api_client


@pytest.fixture
def owner(db):
    user = User.objects.create(
        username='owner', role=User.Role.OWNER,
        full_name='Owner User',
    )
    user.set_password('owner123')
    user.save()
    return user


@pytest.fixture
def admin(db):
    user = User.objects.create(
        username='admin', role=User.Role.ADMIN,
        full_name='Admin User', can_write_to_owner=True,
    )
    user.set_password('admin123')
    user.save()
    return user


@pytest.fixture
def worker(db):
    user = User.objects.create(
        username='worker', role=User.Role.WORKER,
        full_name='Worker User',
    )
    user.set_password('worker123')
    user.save()
    return user


@pytest.fixture
def owner_client(api_client, owner):
    """Authenticated API client as owner."""
    api_client.force_authenticate(user=owner)
    return api_client


@pytest.fixture
def admin_client(api_client, admin):
    """Authenticated API client as admin."""
    api_client.force_authenticate(user=admin)
    return api_client


@pytest.fixture
def worker_client(api_client, worker):
    """Authenticated API client as worker."""
    api_client.force_authenticate(user=worker)
    return api_client


# ==================== Model Fixtures ====================

@pytest.fixture
def client_obj(db):
    return Client.objects.create(name='Test Client', phone='998901234567')


@pytest.fixture
def raw_material(db):
    return RawMaterial.objects.create(
        name='Test Marble', unit='m2', quantity=100,
        purchase_price=100000,
    )


@pytest.fixture
def finished_product(db):
    return FinishedProduct.objects.create(
        name='Test Countertop', unit='шт', quantity=10,
        sale_price=1000000, cost_price=500000,
    )
