from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from django.contrib.auth import authenticate
from .models import ProductInfo, ProductParameter

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