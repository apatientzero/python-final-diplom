from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings

from .managers import UserManager


class User(AbstractUser):
    """Покупатель или поставщик с авторизацией по email."""

    class Type(models.TextChoices):
        BUYER = "buyer", "Покупатель"
        SHOP = "shop", "Поставщик"

    username = None
    email = models.EmailField(unique=True)

    type = models.CharField(
        max_length=5,
        choices=Type.choices,
        default=Type.BUYER,
    )

    company = models.CharField(max_length=100, blank=True)
    position = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email


class Shop(models.Model):
    """Поставщик товаров и состояние приёма заказов."""

    name = models.CharField(max_length=100)
    url = models.URLField(blank=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="shop",
    )

    state = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Category(models.Model):
    """Категория товаров, представленная у поставщиков."""

    name = models.CharField(max_length=100)
    shops = models.ManyToManyField(
        Shop,
        related_name="categories",
        blank=True,
    )

    def __str__(self):
        return self.name


class Product(models.Model):
    """Товар общего каталога."""

    name = models.CharField(max_length=255)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )

    def __str__(self):
        return self.name


class ProductInfo(models.Model):
    """Предложение поставщика: товар, цена и остаток."""

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="product_infos",
    )
    shop = models.ForeignKey(
        Shop,
        on_delete=models.PROTECT,
        related_name="product_infos",
    )
    external_id = models.PositiveBigIntegerField()
    model = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    price_rrc = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "external_id"],
                name="unique_shop_external_id",
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0, price_rrc__gte=0),
                name="product_info_prices_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.product} — {self.shop}"


class Parameter(models.Model):
    """Название характеристики, общее для разных товаров."""

    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class ProductParameter(models.Model):
    """Значение характеристики из прайса поставщика."""

    product_info = models.ForeignKey(
        ProductInfo,
        on_delete=models.CASCADE,
        related_name="product_parameters",
    )
    parameter = models.ForeignKey(
        Parameter,
        on_delete=models.PROTECT,
        related_name="product_parameters",
    )
    value = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product_info", "parameter"],
                name="unique_product_info_parameter",
            ),
        ]

    def __str__(self):
        return f"{self.parameter}: {self.value}"


class Contact(models.Model):
    """Адрес доставки и контактный телефон пользователя."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    city = models.CharField(max_length=75)
    street = models.CharField(max_length=100)
    house = models.CharField(max_length=15)
    structure = models.CharField(max_length=15, blank=True)
    building = models.CharField(max_length=15, blank=True)
    apartment = models.CharField(max_length=15, blank=True)
    phone = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.city}, {self.street}, д. {self.house}"


class Order(models.Model):
    """Корзина или оформленный заказ покупателя."""

    class State(models.TextChoices):
        BASKET = "basket", "Корзина"
        NEW = "new", "Новый"
        CONFIRMED = "confirmed", "Подтверждён"
        ASSEMBLED = "assembled", "Собран"
        SENT = "sent", "Отправлен"
        DELIVERED = "delivered", "Доставлен"
        CANCELED = "canceled", "Отменён"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    dt = models.DateTimeField(auto_now_add=True)
    state = models.CharField(
        max_length=15,
        choices=State.choices,
        default=State.BASKET,
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.SET_NULL,
        related_name="orders",
        null=True,
        blank=True,
    )
    delivery_address = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-dt", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(state="basket"),
                name="unique_user_basket",
            ),
        ]

    def __str__(self):
        return f"Заказ №{self.pk}: {self.get_state_display()}"


class OrderItem(models.Model):
    """Позиция заказа с сохранёнными названием и ценой."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product_info = models.ForeignKey(
        ProductInfo,
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    quantity = models.PositiveIntegerField(default=1)
    product_name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order", "product_info"],
                name="unique_order_product_info",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="order_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="order_item_price_nonnegative",
            ),
        ]

    @property
    def total_price(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"