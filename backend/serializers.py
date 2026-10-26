from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

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