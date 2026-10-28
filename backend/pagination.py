from rest_framework.pagination import PageNumberPagination


class CatalogPagination(PageNumberPagination):
    """Выдаёт каталог страницами по 20 предложений."""

    page_size = 20


class OrderPagination(PageNumberPagination):
    """Выдаёт историю заказов страницами по 20 записей."""

    page_size = 20