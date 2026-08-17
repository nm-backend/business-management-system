"""
Сервис управления подписками компаний (SaaS).

Единственное место, где меняется состояние подписки. Используется:
- API супер-администратора (apps/companies/views.py);
- задачей Celery (apps/companies/tasks.py);
- при создании компании (сериализатор/админка).

ЖИЗНЕННЫЙ ЦИКЛ:
    active --(end прошёл)--> grace --(grace_period_days прошли)--> expired
    active/grace --(ручная заморозка)--> frozen --(разморозка)--> active
    expired --(продление/активация)--> active
    любой статус --(смена тарифа)--> тот же статус, другой план

КОНКУРЕНТНОСТЬ: каждая мутирующая операция перечитывает строку компании в
SELECT ... FOR UPDATE внутри transaction.atomic. Два параллельных продления
НЕ теряют дни (второй ждёт коммит первого и сдвигает end от уже обновлённого
значения), два параллельных freeze не дублируют историю (второй видит FROZEN
и выходит). История/аудит пишутся в той же транзакции, что и изменение, —
отсутствие записи истории при изменённом статусе исключено. Уведомления
(колокольчик/push) отправляются ПОСЛЕ коммита — внешние вызовы не держат
блокировку строки.

Гарантии:
- Все изменения пишут историю (SubscriptionChange) и audit log;
- Продление активной подписки НЕ обнуляет остаток (end сдвигается от текущего end);
- Продление/активация истёкшей, замороженной или льготной подписки
  размораживает компанию и снимает флаг триала (is_trial=False);
- Некорректные сроки (прошедшая дата, дни <= 0) отклоняются;
- Все даты — timezone-aware.

ЛЬГОТНЫЙ ПЕРИОД (grace): после истечения срока бизнес продолжает работать
до end + grace_period_days, владелец предупреждён. Обоснование: платёж
подтверждается супер-администратором вручную, поэтому жёсткий обрыв в момент
истечения срока был бы враждебен бизнесу — льготный период даёт время на
договорённость о продлении без потери доступа. По его окончании компания
переводится в expired (бизнес-доступ блокируется).

ТРИАЛ: компания создаётся с is_trial=True (план Free Trial). Любое ручное
продление/активация/установка срока/разморозка/смена тарифа супер-
администратором снимает флаг — компания становится «платной» (оплата пока
подтверждается вручную).
"""
from contextlib import contextmanager
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.services import write_audit_log
from .models import DEFAULT_SUBSCRIPTION_DAYS, Company, SubscriptionChange, SubscriptionPlan

# Верхняя граница продления: защита от опечаток (напр. 99999 дней).
MAX_EXTENSION_DAYS = 3650

# Поля подписки, которые синхронизируются обратно в переданный объект company
# после работы под блокировкой (view читает их в ответе).
_SYNC_FIELDS = (
    'subscription_status', 'subscription_start', 'subscription_end',
    'is_trial', 'grace_period_days', 'plan', 'plan_id',
)


class SubscriptionError(ValueError):
    """Некорректный запрос на изменение подписки (превращается в 400)."""


@contextmanager
def _locked_company(company):
    """
    Открывает транзакцию и берёт строку компании в SELECT ... FOR UPDATE.

    Возвращает свежий инстанс (locked) с актуальным состоянием; при выходе
    из контекста состояние locked копируется обратно в переданный company.
    """
    with transaction.atomic():
        locked = Company.objects.select_for_update().get(pk=company.pk)
        try:
            yield locked
        finally:
            for field in _SYNC_FIELDS:
                setattr(company, field, getattr(locked, field))


def _iso(dt):
    return dt.isoformat() if dt else None


def _mark_expiry_alerts_read(company):
    """
    Помечает прочитанными предупреждения об истечении подписки.

    Вызывается для действий, сдвигающих срок вперёд (активация, продление,
    установка даты, разморозка): старые алерты «подписка истекает», «льготный
    период» и «подписка истекла» неактуальны и не должны висеть в колокольчике.
    Дедупликация задачи notify_subscription_expiry учитывает дату создания,
    поэтому следующий цикл предупреждений создаст свежие уведомления.
    """
    from apps.messaging.models import Notification

    Notification.objects.filter(
        company_id=company.id,
        type__in=(
            Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON,
            Notification.NotificationType.SUBSCRIPTION_EXPIRING,
            Notification.NotificationType.SUBSCRIPTION_GRACE_STARTED,
            Notification.NotificationType.SUBSCRIPTION_EXPIRED,
        ),
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())


def _mark_renewal_requests_read(company):
    """
    Помечает прочитанными запросы на продление по компании.

    Когда супер-админ продлевает/активирует подписку, запрос владельца
    обработан: колокольчик супер-админа очищается от «висящих» запросов,
    а дедупликация сбрасывается — владелец сможет запросить продление снова,
    когда срок снова станет близок.
    """
    from apps.messaging.models import Notification

    Notification.objects.filter(
        company_id=company.id,
        type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())


def _notify_subscription_renewed(company):
    """
    Уведомляет владельца/админов компании, что подписка продлена
    (колокольчик + VAPID push с переходом на страницу «Подписка»).

    Вызывается действиями, сдвигающими срок вперёд: активация, продление,
    установка даты, разморозка. При создании компании (триал) НЕ вызывается —
    там уведомление было бы спамом. Замкнутый цикл: владелец запросил
    продление -> супер-админ продлил -> владелец получает подтверждение.
    """
    from apps.accounts.models import User
    from apps.accounts.push_service import send_push_to_user
    from apps.messaging.models import Notification
    from apps.messaging.services import notify_staff

    end_text = (
        company.subscription_end.strftime('%d.%m.%Y')
        if company.subscription_end else '—'
    )
    recipients = list(User.objects.filter(
        company_id=company.id,
        is_active=True,
        role__in=(User.Role.OWNER, User.Role.ADMIN),
    ))
    notify_staff(
        company,
        Notification.NotificationType.SUBSCRIPTION_EXTENDED,
        company.name,
        f'{company.name} — до {end_text}',
    )
    for user in recipients:
        send_push_to_user(
            user,
            company.name,
            f'Подписка продлена до {end_text}',
            data={'url': '/#/subscription'},
        )
    return recipients


def _notify_grace_started(company):
    """
    Уведомляет владельца/админов и супер-админов о начале льготного периода.

    Сообщает конкретную дату блокировки (end + grace_period_days). Вызывается
    ТОЛЬКО при переходе active -> grace (однократно за цикл — статусная
    проверка + FOR UPDATE в задаче Celery исключают повторные срабатывания).
    """
    from apps.accounts.models import User
    from apps.accounts.push_service import send_push_to_user
    from apps.messaging.models import Notification
    from apps.messaging.services import notify

    grace_end = company.grace_end
    deadline_text = grace_end.strftime('%d.%m.%Y') if grace_end else '—'
    staff = list(User.objects.filter(
        company_id=company.id,
        is_active=True,
        role__in=(User.Role.OWNER, User.Role.ADMIN),
    ))
    superadmins = list(User.objects.filter(
        role=User.Role.SUPERADMIN, is_active=True,
    ))
    notify(
        staff + superadmins,
        Notification.NotificationType.SUBSCRIPTION_GRACE_STARTED,
        company.name,
        f'{company.name} — льготный период до {deadline_text}',
        company=company,
    )
    for user in staff + superadmins:
        send_push_to_user(
            user,
            company.name,
            f'Льготный период до {deadline_text}. Продлите подписку.',
            data={'url': '/#/subscription' if user.company_id else '/#/companies'},
        )


def _notify_subscription_expired(company):
    """
    Уведомляет владельца/админов, что подписка истекла и доступ ограничен.

    Вызывается только при фактическом переходе в expired (статусная проверка
    в expire_company под блокировкой), поэтому повторные запуски Celery
    не спамят.
    """
    from apps.accounts.models import User
    from apps.accounts.push_service import send_push_to_user
    from apps.messaging.models import Notification
    from apps.messaging.services import notify

    staff = list(User.objects.filter(
        company_id=company.id,
        is_active=True,
        role__in=(User.Role.OWNER, User.Role.ADMIN),
    ))
    notify(
        staff,
        Notification.NotificationType.SUBSCRIPTION_EXPIRED,
        company.name,
        f'{company.name} — подписка истекла, доступ ограничен',
        company=company,
    )
    for user in staff:
        send_push_to_user(
            user,
            company.name,
            'Подписка истекла. Обратитесь к администратору платформы.',
            data={'url': '/#/subscription'},
        )


def _notify_plan_changed(company, plan):
    """Уведомляет владельца/админов о смене тарифа."""
    from apps.accounts.models import User
    from apps.accounts.push_service import send_push_to_user
    from apps.messaging.models import Notification
    from apps.messaging.services import notify_staff

    recipients = list(User.objects.filter(
        company_id=company.id,
        is_active=True,
        role__in=(User.Role.OWNER, User.Role.ADMIN),
    ))
    notify_staff(
        company,
        Notification.NotificationType.SUBSCRIPTION_PLAN_CHANGED,
        company.name,
        f'{company.name} — тариф «{plan.name}»',
    )
    for user in recipients:
        send_push_to_user(
            user,
            company.name,
            f'Тариф изменён: «{plan.name}»',
            data={'url': '/#/subscription'},
        )


def _record_change(*, company, action, old_status, new_status, old_end, new_end,
                   days_added=None, old_plan='', new_plan='', actor=None, note=''):
    """Пишет строку истории и audit log одной операцией."""
    SubscriptionChange.objects.create(
        company=company,
        action=action,
        old_status=old_status,
        new_status=new_status,
        old_end=old_end,
        new_end=new_end,
        days_added=days_added,
        old_plan=old_plan,
        new_plan=new_plan,
        actor=actor,
        note=note,
    )
    audit_action = {
        SubscriptionChange.Action.ACTIVATED: AuditLog.Action.SUBSCRIPTION_ACTIVATED,
        SubscriptionChange.Action.EXTENDED: AuditLog.Action.SUBSCRIPTION_EXTENDED,
        SubscriptionChange.Action.END_SET: AuditLog.Action.SUBSCRIPTION_END_SET,
        SubscriptionChange.Action.GRACE_STARTED: AuditLog.Action.SUBSCRIPTION_GRACE_STARTED,
        SubscriptionChange.Action.FROZEN: AuditLog.Action.SUBSCRIPTION_FROZEN,
        SubscriptionChange.Action.UNFROZEN: AuditLog.Action.SUBSCRIPTION_UNFROZEN,
        SubscriptionChange.Action.EXPIRED: AuditLog.Action.SUBSCRIPTION_EXPIRED,
        SubscriptionChange.Action.PLAN_CHANGED: AuditLog.Action.SUBSCRIPTION_PLAN_CHANGED,
        SubscriptionChange.Action.CANCELLED: AuditLog.Action.SUBSCRIPTION_EXPIRED,
    }[action]
    changes = {
        'subscription_status': {'old': old_status, 'new': new_status},
        'subscription_end': {'old': _iso(old_end), 'new': _iso(new_end)},
    }
    if action == SubscriptionChange.Action.PLAN_CHANGED:
        changes['plan'] = {'old': old_plan, 'new': new_plan}
    write_audit_log(
        action=audit_action,
        actor=actor,
        target=company,
        company=company,
        changes=changes,
        metadata={'note': note, 'days_added': days_added,
                  'old_plan': old_plan, 'new_plan': new_plan},
    )
    # Действия, сдвигающие срок вперёд, делают старые предупреждения
    # об истечении неактуальными — помечаем прочитанными.
    if action in {
        SubscriptionChange.Action.ACTIVATED,
        SubscriptionChange.Action.EXTENDED,
        SubscriptionChange.Action.END_SET,
        SubscriptionChange.Action.UNFROZEN,
    }:
        _mark_expiry_alerts_read(company)
        # Продление обрабатывает и запрос владельца: дедупликация сбрасывается,
        # колокольчик супер-админа не висит с устаревшим запросом.
        _mark_renewal_requests_read(company)


def activate_for_new_company(company, *, actor=None):
    """
    Первичная активация при создании компании: триал на 30 дней.

    Компания получает план по умолчанию (Free Trial), is_trial=True и срок
    30 дней от текущего момента. Вызывается из CompanyCreateSerializer.create
    и admin.save_model — компания не может существовать без подписки.
    """
    now = timezone.now()
    company.plan = SubscriptionPlan.get_default_plan()
    company.is_trial = True
    company.subscription_status = Company.SubscriptionStatus.ACTIVE
    company.subscription_start = now
    company.subscription_end = now + timedelta(days=DEFAULT_SUBSCRIPTION_DAYS)
    company.save(update_fields=[
        'plan', 'is_trial',
        'subscription_status', 'subscription_start', 'subscription_end', 'updated_at',
    ])
    plan_name = company.plan.name if company.plan else ''
    _record_change(
        company=company,
        action=SubscriptionChange.Action.ACTIVATED,
        old_status='', new_status=company.subscription_status,
        old_end=None, new_end=company.subscription_end,
        days_added=DEFAULT_SUBSCRIPTION_DAYS,
        new_plan=plan_name,
        actor=actor,
        note='Триал при создании компании',
    )


def activate_subscription(company, *, actor=None, note=''):
    """
    Активировать подписку (вручную супер-администратором).

    Если срок в прошлом или не задан — выдаётся стандартные 30 дней от текущего
    момента. Если срок ещё в будущем — остаётся прежним (компания просто
    размораживается). Снимает флаг триала.
    """
    with _locked_company(company) as locked:
        now = timezone.now()
        old_status = locked.subscription_status
        old_end = locked.subscription_end

        if locked.subscription_end is None or locked.subscription_end <= now:
            locked.subscription_end = now + timedelta(days=DEFAULT_SUBSCRIPTION_DAYS)
        if locked.subscription_start is None:
            locked.subscription_start = now
        locked.subscription_status = Company.SubscriptionStatus.ACTIVE
        if locked.is_trial:
            locked.is_trial = False
        locked.save(update_fields=[
            'subscription_status', 'subscription_start', 'subscription_end',
            'is_trial', 'updated_at',
        ])
        _record_change(
            company=locked,
            action=SubscriptionChange.Action.ACTIVATED,
            old_status=old_status, new_status=locked.subscription_status,
            old_end=old_end, new_end=locked.subscription_end,
            actor=actor, note=note,
        )
    _notify_subscription_renewed(company)
    return company


def extend_subscription(company, *, days, actor=None, note=''):
    """
    Продлить подписку на `days` дней.

    Активная подписка: новый end = текущий end + days (остаток НЕ обнуляется).
    Истёкшая/замороженная/льготная: end = now + days, компания снова активна.
    Снимает флаг триала. Параллельные продления сериализуются блокировкой
    строки — дни не теряются.
    """
    if not isinstance(days, int) or isinstance(days, bool):
        raise SubscriptionError('Количество дней должно быть целым числом.')
    if days <= 0:
        raise SubscriptionError('Количество дней должно быть больше нуля.')
    if days > MAX_EXTENSION_DAYS:
        raise SubscriptionError(f'Максимальное продление — {MAX_EXTENSION_DAYS} дней.')

    with _locked_company(company) as locked:
        now = timezone.now()
        old_status = locked.subscription_status
        old_end = locked.subscription_end

        if locked.subscription_end is not None and locked.subscription_end > now:
            # Остаток сохраняется: продлеваем от текущей даты окончания.
            new_end = locked.subscription_end + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)

        if locked.subscription_start is None:
            locked.subscription_start = now
        locked.subscription_end = new_end
        locked.subscription_status = Company.SubscriptionStatus.ACTIVE
        if locked.is_trial:
            locked.is_trial = False
        locked.save(update_fields=[
            'subscription_status', 'subscription_start', 'subscription_end',
            'is_trial', 'updated_at',
        ])
        _record_change(
            company=locked,
            action=SubscriptionChange.Action.EXTENDED,
            old_status=old_status, new_status=locked.subscription_status,
            old_end=old_end, new_end=locked.subscription_end,
            days_added=days,
            actor=actor, note=note,
        )
    _notify_subscription_renewed(company)
    return company


def set_subscription_end(company, *, end, actor=None, note=''):
    """
    Установить точную дату окончания подписки.

    end обязан быть в будущем (прошедшие/отрицательные сроки запрещены).
    Установка будущей даты автоматически активирует компанию.
    Снимает флаг триала.
    """
    if end is None:
        raise SubscriptionError('Укажите дату окончания подписки.')
    now = timezone.now()
    if end <= now:
        raise SubscriptionError('Дата окончания должна быть в будущем.')

    with _locked_company(company) as locked:
        old_status = locked.subscription_status
        old_end = locked.subscription_end

        if locked.subscription_start is None:
            locked.subscription_start = now
        locked.subscription_end = end
        locked.subscription_status = Company.SubscriptionStatus.ACTIVE
        if locked.is_trial:
            locked.is_trial = False
        locked.save(update_fields=[
            'subscription_status', 'subscription_start', 'subscription_end',
            'is_trial', 'updated_at',
        ])
        _record_change(
            company=locked,
            action=SubscriptionChange.Action.END_SET,
            old_status=old_status, new_status=locked.subscription_status,
            old_end=old_end, new_end=locked.subscription_end,
            actor=actor, note=note,
        )
    _notify_subscription_renewed(company)
    return company


def change_plan(company, *, plan, actor=None, note=''):
    """
    Сменить тариф (план) компании без изменения сроков подписки.

    Допустим в любом статусе (кроме cancelled). Новый план обязан быть активным.
    Срок и остаток дней не трогаются — смена тарифа меняет «тарифную корзину»,
    а продление выполняется отдельным действием. Снимает флаг триала: активный
    выбор тарифа супер-администратором означает конец бесплатного периода.
    """
    if plan is None:
        raise SubscriptionError('Укажите тариф.')
    if not plan.is_active:
        raise SubscriptionError('Выбранный тариф недоступен.')

    with _locked_company(company) as locked:
        if locked.subscription_status == Company.SubscriptionStatus.CANCELLED:
            raise SubscriptionError('Отменённой компании нельзя сменить тариф.')
        if locked.plan_id == plan.id:
            raise SubscriptionError('Компания уже на этом тарифе.')

        old_plan = locked.plan
        old_plan_name = old_plan.name if old_plan else ''
        locked.plan = plan
        if locked.is_trial:
            locked.is_trial = False
        locked.save(update_fields=['plan', 'is_trial', 'updated_at'])
        _record_change(
            company=locked,
            action=SubscriptionChange.Action.PLAN_CHANGED,
            old_status=locked.subscription_status, new_status=locked.subscription_status,
            old_end=locked.subscription_end, new_end=locked.subscription_end,
            old_plan=old_plan_name, new_plan=plan.name,
            actor=actor, note=note,
        )
    _notify_plan_changed(company, plan)
    return company


def freeze_company(company, *, actor=None, note=''):
    """
    Ручная заморозка компании супер-администратором.

    Статус становится FROZEN (независимо от срока и льготного периода).
    Срок сохраняется — при продлении компания корректно разморозится.
    Бизнес-доступ блокируется permission'ом SubscriptionAccessPermission.
    Идемпотентно: повторная заморозка уже замороженной компании ничего
    не меняет (параллельные freeze не дублируют историю).
    """
    with _locked_company(company) as locked:
        if locked.subscription_status == Company.SubscriptionStatus.CANCELLED:
            raise SubscriptionError('Отменённую компанию нельзя заморозить.')
        if locked.subscription_status == Company.SubscriptionStatus.FROZEN:
            return company

        old_status = locked.subscription_status
        old_end = locked.subscription_end

        locked.subscription_status = Company.SubscriptionStatus.FROZEN
        locked.save(update_fields=['subscription_status', 'updated_at'])
        _record_change(
            company=locked,
            action=SubscriptionChange.Action.FROZEN,
            old_status=old_status, new_status=locked.subscription_status,
            old_end=old_end, new_end=locked.subscription_end,
            actor=actor, note=note,
        )
    return company


def unfreeze_company(company, *, actor=None, note=''):
    """
    Разморозка компании.

    Если срок ещё в будущем — просто возврат в active. Если срок прошёл
    (заморозка после истечения) — выдаётся стандартный срок от текущего
    момента, иначе компания мгновенно снова окажется истёкшей.
    Снимает флаг триала.
    """
    with _locked_company(company) as locked:
        if locked.subscription_status != Company.SubscriptionStatus.FROZEN:
            raise SubscriptionError('Компания не заморожена.')

        now = timezone.now()
        old_status = locked.subscription_status
        old_end = locked.subscription_end

        if locked.subscription_end is None or locked.subscription_end <= now:
            locked.subscription_end = now + timedelta(days=DEFAULT_SUBSCRIPTION_DAYS)
        if locked.subscription_start is None:
            locked.subscription_start = now
        locked.subscription_status = Company.SubscriptionStatus.ACTIVE
        if locked.is_trial:
            locked.is_trial = False
        locked.save(update_fields=[
            'subscription_status', 'subscription_start', 'subscription_end',
            'is_trial', 'updated_at',
        ])
        _record_change(
            company=locked,
            action=SubscriptionChange.Action.UNFROZEN,
            old_status=old_status, new_status=locked.subscription_status,
            old_end=old_end, new_end=locked.subscription_end,
            actor=actor, note=note,
        )
    _notify_subscription_renewed(company)
    return company


def start_grace(company, *, note='Автоматически: срок подписки истёк, начался льготный период'):
    """
    Переход active -> grace (вызывается задачей Celery).

    Льготный период: бизнес продолжает работать до end + grace_period_days,
    владелец предупреждён уведомлением с датой блокировки. Идемпотентно:
    повторный вызов для не-active компании ничего не меняет и историю
    не дублирует.
    """
    with _locked_company(company) as locked:
        if locked.subscription_status != Company.SubscriptionStatus.ACTIVE:
            return company

        old_status = locked.subscription_status
        old_end = locked.subscription_end

        locked.subscription_status = Company.SubscriptionStatus.GRACE
        locked.save(update_fields=['subscription_status', 'updated_at'])
        _record_change(
            company=locked,
            action=SubscriptionChange.Action.GRACE_STARTED,
            old_status=old_status, new_status=locked.subscription_status,
            old_end=old_end, new_end=locked.subscription_end,
            note=note,
        )
    _notify_grace_started(company)
    return company


def expire_company(company, *, note='Автоматически: срок подписки истёк'):
    """
    Перевод компании в статус expired (вызывается задачей Celery).

    Допустим из active (если льготный период уже прошёл или равен нулю) и из
    grace (если льготный период вышел). Системное действие: actor отсутствует,
    привязка к компании идёт через параметр company в write_audit_log.
    Идемпотентно: повторный вызов для уже expired компании ничего не меняет
    и историю не дублирует. Уведомляет владельца при фактическом переходе.
    """
    with _locked_company(company) as locked:
        if locked.subscription_status not in (
            Company.SubscriptionStatus.ACTIVE,
            Company.SubscriptionStatus.GRACE,
        ):
            return company

        old_status = locked.subscription_status
        old_end = locked.subscription_end

        locked.subscription_status = Company.SubscriptionStatus.EXPIRED
        locked.save(update_fields=['subscription_status', 'updated_at'])
        _record_change(
            company=locked,
            action=SubscriptionChange.Action.EXPIRED,
            old_status=old_status, new_status=locked.subscription_status,
            old_end=old_end, new_end=locked.subscription_end,
            note=note,
        )
    _notify_subscription_expired(company)
    return company
