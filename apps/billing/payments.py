"""
Payment adapter для подписок.

Единый контракт провайдера: create_payment() создаёт платёж и возвращает
клиентские данные (checkout URL / ID платежа), confirm() завершает оплату
и продлевает подписку. Основная бизнес-логика (renew/freeze/audit/история)
живёт в apps.billing.services и НЕ знает о конкретном провайдере — подключить
Payme или Click позже = написать класс с этим же интерфейсом и зарегистрировать
его в REGISTRY, ничего не меняя в моделях, вьюхах и сервисах.

Текущий провайдер по умолчанию — manual: продление создаёт счёт pending,
а подтверждает оплату супер-администратор (в админке или через API).
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class PaymentProvider:
    """Базовый контракт платёжного провайдера."""

    key = 'base'

    def create_payment(self, invoice, request=None):
        """Создаёт платёж для счёта.

        Возвращает dict для клиента: {'invoice_id', 'status', ...}.
        Может заполнить invoice.provider_payment_id и сохранить.
        """
        raise NotImplementedError

    def confirm(self, invoice, actor=None, request=None):
        """Подтверждает оплату счёта (вызывается после верификации).

        Должна пометить счёт оплаченным и продлить подписку. Возвращает invoice.
        """
        raise NotImplementedError


class ManualProvider(PaymentProvider):
    """
    Ручное подтверждение: счёт ждёт, пока супер-администратор подтвердит
    оплату (реальный перевод на счёт/карту вне системы). Никаких внешних
    запросов — работает офлайн и в тестах.
    """

    key = 'manual'

    def create_payment(self, invoice, request=None):
        return {
            'invoice_id': invoice.id,
            'status': invoice.status,
            'provider': self.key,
            'message': 'Ожидает подтверждения оплаты администратором платформы.',
        }

    def confirm(self, invoice, actor=None, request=None):
        from .services import confirm_invoice_paid
        return confirm_invoice_paid(invoice, actor=actor, request=request)


class PaymeProvider(PaymentProvider):
    """
    Заготовка интеграции Payme (Merchant API) — НЕ реализована.

    Контракт:
      - create_payment: создать транзакцию в Payme, сохранить
        invoice.provider_payment_id, вернуть {'checkout_url': ..., 'payment_id': ...}.
      - confirm: вызвать CheckPerformTransaction/PerformTransaction логику
        (или получить подтверждение из вебхука) и затем подтвердить оплату.
      - Вебхук Payme приходит на /api/v1/billing/webhooks/payme/ — view должен
        верифицировать подпись (merchant key из настроек) и вызвать confirm().

    Настройки (добавить в .env):
      SUBSCRIPTION_PAYMENT_PROVIDER=payme
      PAYME_MERCHANT_ID=...
      PAYME_MERCHANT_KEY=...
    """

    key = 'payme'

    def create_payment(self, invoice, request=None):
        raise NotImplementedError(
            'PaymeProvider не подключён: реализуйте create_payment и вебхук '
            '(см. docstring в apps/billing/payments.py).'
        )

    def confirm(self, invoice, actor=None, request=None):
        raise NotImplementedError('PaymeProvider не подключён.')


class ClickProvider(PaymentProvider):
    """Заготовка интеграции Click (Merchant API) — НЕ реализована. Аналогично PaymeProvider."""

    key = 'click'

    def create_payment(self, invoice, request=None):
        raise NotImplementedError(
            'ClickProvider не подключён: реализуйте create_payment и вебхук.'
        )

    def confirm(self, invoice, actor=None, request=None):
        raise NotImplementedError('ClickProvider не подключён.')


REGISTRY = {
    ManualProvider.key: ManualProvider,
    PaymeProvider.key: PaymeProvider,
    ClickProvider.key: ClickProvider,
}

# Заглушки, у которых create_payment/confirm кидают NotImplementedError: на них
# нельзя выдавать счёт — иначе owner получит 500 вместо понятной ошибки.
_NOT_IMPLEMENTED = {PaymeProvider, ClickProvider}


def get_provider(key=None):
    """Возвращает экземпляр провайдера по ключу (или из настроек).

    Если в настройках указан ещё не реализованный провайдер (payme/click),
    тихо откатываемся на manual — продление не должно падать из-за
    неподключённой интеграции.
    """
    provider_key = key or getattr(settings, 'SUBSCRIPTION_PAYMENT_PROVIDER', 'manual')
    provider_cls = REGISTRY.get(provider_key, ManualProvider)
    if provider_cls in _NOT_IMPLEMENTED:
        logger.warning('Payment provider %s is not implemented yet, falling back to manual', provider_key)
        provider_cls = ManualProvider
    return provider_cls()
