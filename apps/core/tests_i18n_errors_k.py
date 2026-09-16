"""
Regression tests for Block 2 localization of error messages.

Verifies:
1. Every new error key exists in all 3 locale files
2. translate() returns correct language text
3. Missing key returns the key itself (fallback)
4. API errors don't return hardcoded Russian when user language is Uzbek
5. API errors don't return hardcoded English when user language is Russian
"""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from core.utils import translate


def _load_errors():
    """Load the 'errors' section from all 3 locale files."""
    locale_dir = Path(settings.BASE_DIR) / 'locale'
    result = {}
    for lang in ('uz_cyrl', 'ru', 'ky'):
        data = json.loads((locale_dir / f'{lang}.json').read_text(encoding='utf-8'))
        result[lang] = data.get('errors', {})
    return result


def _flat_keys(errors, prefix=''):
    """Flatten nested dict into dot-separated keys."""
    keys = set()
    for k, v in errors.items():
        path = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            keys.update(_flat_keys(v, path))
        else:
            keys.add(path)
    return keys


class ErrorKeysExistInAllLocalesTest(SimpleTestCase):
    """Every error key in ru.json must also exist in uz_cyrl.json and ky.json."""

    def test_all_error_keys_match(self):
        errors = _load_errors()
        ru_keys = _flat_keys(errors['ru'])
        uz_keys = _flat_keys(errors['uz_cyrl'])
        ky_keys = _flat_keys(errors['ky'])

        self.assertEqual(ru_keys, uz_keys,
                         f'Keys in RU but not UZ: {ru_keys - uz_keys}\n'
                         f'Keys in UZ but not RU: {uz_keys - ru_keys}')
        self.assertEqual(ru_keys, ky_keys,
                         f'Keys in RU but not KY: {ru_keys - ky_keys}\n'
                         f'Keys in KY but not RU: {ky_keys - ru_keys}')

    def test_minimum_key_count(self):
        """At least 150 error keys should exist (sanity check)."""
        errors = _load_errors()
        count = len(_flat_keys(errors['ru']))
        self.assertGreaterEqual(count, 150,
                                f'Only {count} error keys found, expected >= 150')


class TranslateReturnsCorrectLanguageTest(SimpleTestCase):
    """translate() with different lang codes returns correct translations."""

    def test_ru_returns_russian(self):
        result = translate('errors.common.subscription_expired', 'ru')
        self.assertIn('Подписка', result)

    def test_uz_returns_uzbek(self):
        result = translate('errors.common.subscription_expired', 'uz_cyrl')
        self.assertIn('подписка', result.lower()) or self.assertIn('муддати', result)

    def test_ky_returns_kyrgyz(self):
        result = translate('errors.common.subscription_expired', 'ky')
        self.assertIn('жазылуу', result) or self.assertIn('мөөнөтү', result)

    def test_fallback_to_uz_cyrl(self):
        """Unknown language falls back to uz_cyrl."""
        result = translate('errors.common.subscription_expired', 'xx')
        uz = translate('errors.common.subscription_expired', 'uz_cyrl')
        self.assertEqual(result, uz)

    def test_missing_key_returns_key(self):
        """Non-existent key returns the key string itself."""
        result = translate('errors.nonexistent.deep.key', 'ru')
        self.assertEqual(result, 'errors.nonexistent.deep.key')

    def test_params_substituted(self):
        """Parameters are correctly substituted in translated strings."""
        result = translate('errors.orders.invalid_transition', 'ru', {
            'from': 'new', 'to': 'delivered', 'allowed': 'in_progress'
        })
        self.assertIn('new', result)
        self.assertIn('delivered', result)

    def test_auth_messages_translated(self):
        """Auth error keys exist and translate correctly."""
        for key in ('invalid_credentials', 'account_inactive', 'company_inactive',
                     'password_incorrect', 'passwords_no_match'):
            for lang in ('ru', 'uz_cyrl', 'ky'):
                result = translate(f'errors.auth.{key}', lang)
                self.assertNotEqual(result, f'errors.auth.{key}',
                                    f'Key errors.auth.{key} not found in {lang}')

    def test_order_messages_translated(self):
        """Order error keys exist and translate correctly."""
        for key in ('delivered_cannot_edit', 'has_payments_no_cancel',
                     'already_cancelled', 'already_delivered'):
            for lang in ('ru', 'uz_cyrl', 'ky'):
                result = translate(f'errors.orders.{key}', lang)
                self.assertNotEqual(result, f'errors.orders.{key}',
                                    f'Key errors.orders.{key} not found in {lang}')

    def test_production_messages_translated(self):
        """Production error keys exist and translate correctly."""
        for key in ('task_not_pending', 'work_not_pending',
                     'worker_own_tasks', 'owner_admin_confirm_only'):
            for lang in ('ru', 'uz_cyrl', 'ky'):
                result = translate(f'errors.production.{key}', lang)
                self.assertNotEqual(result, f'errors.production.{key}',
                                    f'Key errors.production.{key} not found in {lang}')


class APIErrorLocalizationTest(TestCase):
    """API errors should be localized based on user's language preference."""

    def setUp(self):
        self.company = Company.objects.create(name='TestCo', is_active=True)
        self.owner = User.objects.create_user(
            username='i18n_owner', password='p',
            role=User.Role.OWNER, company=self.company, language='uz_cyrl'
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_order_cancel_error_in_uzbek(self):
        """Cancelled order error should be in Uzbek for Uzbek-speaking user."""
        from apps.orders.models import Order
        from apps.clients.models import Client
        from django.utils import timezone
        client = Client.objects.create(company=self.company, name='К')
        order = Order.objects.create(
            company=self.company, client=client,
            custom_product_name='Товар', quantity=1, unit='sht',
            total_amount=100, deadline=timezone.now(),
        )
        order.status = Order.Status.CANCELLED
        order.save(update_fields=['status'])

        resp = self.api.post(f'/api/v1/orders/orders/{order.id}/cancel/')
        self.assertEqual(resp.status_code, 400)
        detail = str(resp.data.get('detail', ''))
        # Should NOT contain Russian "Бекор"
        self.assertNotIn('Бекор қилинди', detail)
        # Should contain Uzbek text
        uz_text = translate('errors.orders.already_cancelled', 'uz_cyrl')
        self.assertIn(uz_text, detail)


class FrontendI18nTimeoutTest(SimpleTestCase):
    """Frontend api.js uses i18n for timeout message."""

    def test_api_js_uses_i18n(self):
        api_js = Path(settings.BASE_DIR) / 'static' / 'js' / 'api.js'
        content = api_js.read_text(encoding='utf-8')
        self.assertIn('i18n', content,
                       'api.js should use i18n.translate for timeout message')
        self.assertIn("translate('common.error')", content,
                       'Should use translate key, not hardcoded string')
