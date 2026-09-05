"""
Демо-данные для ручной проверки UI/UX (разработка).

Создаёт компанию «Granit Demo MChJ» с владельцем, администратором и
работником (пароли одинаковые: DemoPass123!), если их ещё нет.
Повторный запуск безопасен (идемпотентен).
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skladpro.settings')
django.setup()

from apps.accounts.models import User
from apps.companies.models import Company
from apps.companies.subscriptions import activate_for_new_company

PASSWORD = 'DemoPass123!'


def get_or_create_company():
    company = Company.objects.filter(name='Granit Demo MChJ').first()
    if company is None:
        company = Company.objects.create(name='Granit Demo MChJ')
        activate_for_new_company(company)
        print('Создана компания id=', company.id)
    return company


def get_or_create_user(company, username, full_name, phone, role, **extra):
    user = User.objects.filter(username=username).first()
    if user is None:
        user = User(
            username=username,
            full_name=full_name,
            phone=phone,
            role=role,
            company=company,
            is_active=True,
            **extra,
        )
        user.set_password(PASSWORD)
        user.save()
        print(f'Создан {role}: {username} (id={user.id})')
    return user


def main():
    company = get_or_create_company()
    get_or_create_user(company, 'demo_owner', 'Акмаль Каримов', '+998 90 123-45-67', User.Role.OWNER)
    get_or_create_user(
        company, 'demo_admin', 'Ботир Алимов', '+998 91 111-22-33', User.Role.ADMIN,
        can_create_workers=True,
        can_write_to_owner=True,
        can_see_other_workers=True,
    )
    get_or_create_user(
        company, 'demo_worker', 'Анварбек Мирзаев', '+998 93 444-55-66', User.Role.WORKER,
        position='Мастер по камню',
    )
    print('Компания id =', company.id)
    print('Статус подписки =', company.effective_subscription_status)
    print('Пользователи:', list(
        User.objects.filter(company=company).values_list('username', 'role')
    ))
    print('Пароль всех: ', PASSWORD)


if __name__ == '__main__':
    main()
