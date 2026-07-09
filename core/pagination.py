"""
Custom pagination classes for API responses.

Этот модуль содержит классы пагинации для Django REST Framework,
позволяющие контролировать количество элементов на странице
для различных типов данных.

Использование:
- В ViewSet указывается pagination_class
- Клиент может управлять размером страницы через query параметр page_size
- Есть ограничения на максимальный размер страницы для защиты от перегрузки
"""
from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """
    Стандартная пагинация для большинства API endpoints.

    Настройки:
        page_size: 20 - элементов на странице по умолчанию
        page_size_query_param: 'page_size' - параметр для изменения размера
        max_page_size: 100 - максимальный размер страницы

    Используется для:
    - Списков материалов на складе
    - Списков готовой продукции
    - Списков пользователей
    - Общих списков сущностей
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class SmallPagination(PageNumberPagination):
    """
    Маленькая пагинация для списков с небольшим количеством элементов.

    Настройки:
        page_size: 10 - элементов на странице по умолчанию
        page_size_query_param: 'page_size' - параметр для изменения размера
        max_page_size: 50 - максимальный размер страницы

    Используется для:
    - Списков с детальной информацией
    - Списков, где каждый элемент занимает много места
    - Списков с высокой нагрузкой на рендеринг
    """
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class LargePagination(PageNumberPagination):
    """
    Большая пагинация для списков, где нужно много элементов на странице.

    Настройки:
        page_size: 50 - элементов на странице по умолчанию
        page_size_query_param: 'page_size' - параметр для изменения размера
        max_page_size: 200 - максимальный размер страницы

    Используется для:
    - Историй и логов (audit logs)
    - Статистических данных
    - Списков, где важен обзор большого количества данных
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200
