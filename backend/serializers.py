from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from django.contrib.auth import authenticate
from .models import Contact, Order, OrderItem, ProductInfo, ProductParameter
from decimal import Decimal
from django_rest_passwordreset.serializers import PasswordTokenSerializer

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    """Проверяет данные регистрации и создаёт неактивного покупателя."""

    email = serializers.EmailField(
        max_length=254,
        validators=[UniqueValidator(queryset=User.objects.all(), lookup="iexact")],
    )
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=128,
    )

    class Meta:
        model = User
        fields = [
            "id", "email", "password",
            "first_name", "last_name", "company", "position",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "first_name": {"required": True, "allow_blank": False},
            "last_name": {"required": True, "allow_blank": False},
            "company": {"required": True, "allow_blank": False},
            "position": {"required": True, "allow_blank": False},
        }

    def validate_email(self, value):
        return value.lower()

    def validate(self, attrs):
        user = User(
            email=attrs["email"],
            first_name=attrs["first_name"],
            last_name=attrs["last_name"],
        )
        try:
            validate_password(attrs["password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            **validated_data,
            type=User.Type.BUYER,
            is_active=False,
        )


class ConfirmEmailSerializer(serializers.Serializer):
    """Проверяет формат данных для подтверждения email."""

    email = serializers.EmailField(max_length=254)
    token = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
    )

    def validate_email(self, value):
        return value.lower()


class LoginSerializer(serializers.Serializer):
    """Проверяет email и пароль для входа."""

    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=128,
    )

    def validate_email(self, value):
        return value.lower()

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            email=attrs["email"],
            password=attrs["password"],
        )

        if user is None or not user.is_active:
            raise serializers.ValidationError(
                "Неверный email или пароль, либо аккаунт не активирован."
            )

        attrs["user"] = user
        return attrs


class ProductParameterSerializer(serializers.ModelSerializer):
    """Название и значение характеристики товара."""

    parameter = serializers.CharField(
        source="parameter.name",
        read_only=True,
    )

    class Meta:
        model = ProductParameter
        fields = ["parameter", "value"]
        read_only_fields = fields


class ProductInfoSerializer(serializers.ModelSerializer):
    """Предложение поставщика с ценой, остатком и характеристиками."""

    name = serializers.CharField(
        source="product.name",
        read_only=True,
    )
    category = serializers.IntegerField(
        source="product.category_id",
        read_only=True,
    )
    category_name = serializers.CharField(
        source="product.category.name",
        read_only=True,
    )
    shop_name = serializers.CharField(
        source="shop.name",
        read_only=True,
    )
    parameters = ProductParameterSerializer(
        source="product_parameters",
        many=True,
        read_only=True,
    )

    class Meta:
        model = ProductInfo
        fields = [
            "id",
            "product",
            "name",
            "category",
            "category_name",
            "shop",
            "shop_name",
            "external_id",
            "model",
            "quantity",
            "price",
            "price_rrc",
            "currency",
            "parameters",
        ]
        read_only_fields = fields


class CatalogFilterSerializer(serializers.Serializer):
    """Проверяет параметры фильтрации каталога."""

    shop = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=2**63 - 1,
    )
    category = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=2**63 - 1,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
    )


class BasketItemInputSerializer(serializers.Serializer):
    """Проверяет данные для добавления предложения в корзину."""

    product_info = serializers.IntegerField(
        min_value=1,
        max_value=2**63 - 1,
    )
    quantity = serializers.IntegerField(
        min_value=1,
        max_value=2**31 - 1,
    )


class BasketItemSerializer(serializers.ModelSerializer):
    """Позиция корзины с сохранённой ценой и стоимостью."""

    total_price = serializers.DecimalField(
        max_digits=22,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "order",
            "product_info",
            "product_name",
            "quantity",
            "price",
            "currency",
            "total_price",
        ]
        read_only_fields = fields


class BasketItemQuantitySerializer(serializers.Serializer):
    """Проверяет новое количество позиции корзины."""

    quantity = serializers.IntegerField(
        min_value=1,
        max_value=2**31 - 1,
    )


class ContactSerializer(serializers.ModelSerializer):
    """Адрес доставки и контактный телефон покупателя."""

    phone = serializers.RegexField(
        regex=r"\A\+?[0-9]{7,15}\Z",
        max_length=16,
        error_messages={
            "invalid": (
                "Укажите от 7 до 15 цифр. "
                "В начале допускается знак +. "
                "Пробелы, скобки и дефисы не используются."
            ),
        },
    )

    class Meta:
        model = Contact
        fields = [
            "id",
            "city",
            "street",
            "house",
            "structure",
            "building",
            "apartment",
            "phone",
        ]
        read_only_fields = ["id"]


class OrderCheckoutSerializer(serializers.Serializer):
    """Проверяет ID корзины и адреса для оформления заказа."""

    order = serializers.IntegerField(
        min_value=1,
        max_value=2**63 - 1,
    )
    contact = serializers.IntegerField(
        min_value=1,
        max_value=2**63 - 1,
    )


class OrderSerializer(serializers.ModelSerializer):
    """Заказ с позициями, копией адреса и итогами по валютам."""

    items = BasketItemSerializer(many=True, read_only=True)
    totals = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "dt",
            "state",
            "contact",
            "delivery_address",
            "items",
            "totals",
        ]
        read_only_fields = fields

    def get_totals(self, obj):
        totals = {}

        for item in obj.items.all():
            totals[item.currency] = (
                totals.get(item.currency, Decimal("0.00"))
                + item.total_price
            )

        return {
            currency: f"{amount:.2f}"
            for currency, amount in sorted(totals.items())
        }


class SupplierStateSerializer(serializers.Serializer):
    """Проверяет флаг приёма заказов поставщиком."""

    state = serializers.BooleanField()


class SupplierImportSerializer(serializers.Serializer):
    """Проверяет файл прайса и параметры импорта."""

    file = serializers.FileField(
        max_length=255,
        allow_empty_file=False,
    )
    shop_name = serializers.CharField(
        required=False,
        max_length=100,
    )
    demo_quantity = serializers.IntegerField(
        default=1,
        min_value=0,
        max_value=2**31 - 1,
    )
    replace = serializers.BooleanField(default=False)

    def validate_file(self, value):
        if value.size > 2 * 1024 * 1024:
            raise serializers.ValidationError(
                "Размер файла не должен превышать 2 МиБ."
            )
        return value


class SupplierOrderSerializer(serializers.ModelSerializer):
    """Заказ с позициями и суммами только текущего поставщика."""

    items = BasketItemSerializer(
        source="supplier_items",
        many=True,
        read_only=True,
    )
    totals = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "dt", "state", "delivery_address", "items", "totals",
        ]
        read_only_fields = fields

    def get_totals(self, obj):
        totals = {}

        for item in obj.supplier_items:
            totals[item.currency] = (
                totals.get(item.currency, Decimal("0.00"))
                + item.total_price
            )

        return {
            currency: f"{amount:.2f}"
            for currency, amount in sorted(totals.items())
        }


class PasswordResetConfirmSerializer(PasswordTokenSerializer):
    """Сохраняет пробелы в пароле и ограничивает размеры полей."""

    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=128,
    )
    token = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=64,
    )