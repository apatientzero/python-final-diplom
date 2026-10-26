from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    ConfirmEmailSerializer,
    LoginSerializer,
    RegisterSerializer,
)

from smtplib import SMTPException

from .services.email_confirmation import (
    EmailConfirmationError,
    confirm_email,
    create_confirmation_token,
    send_confirmation_email,
)

from rest_framework.authtoken.models import Token

User = get_user_model()


class RegisterAccount(APIView):
    """Регистрация неактивного покупателя через POST-запрос."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"Status": False, "Errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                user = serializer.save()
                token = create_confirmation_token(user)
                send_confirmation_email(user, token)

        except (SMTPException, OSError):
            return Response(
                {
                    "Status": False,
                    "Errors": {
                        "email": [
                            "Не удалось отправить письмо. "
                            "Попробуйте зарегистрироваться позже."
                        ],
                    },
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except IntegrityError:
            # Другой запрос мог зарегистрировать email после проверки.
            if User.objects.filter(
                email__iexact=serializer.validated_data["email"]
            ).exists():
                return Response(
                    {
                        "Status": False,
                        "Errors": {"email": ["Этот email уже зарегистрирован."]},
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            raise

        return Response(
            {"Status": True},
            status=status.HTTP_201_CREATED,
        )


class ConfirmEmail(APIView):
    """Подтверждение email и активация пользователя."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ConfirmEmailSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"Status": False, "Errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            confirm_email(**serializer.validated_data)
        except EmailConfirmationError as exc:
            return Response(
                {"Status": False, "Errors": {"token": [str(exc)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"Status": True},
            status=status.HTTP_200_OK,
        )


class LoginAccount(APIView):
    """Выдаёт API-токен после проверки email и пароля."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(
            data=request.data,
            context={"request": request},
        )

        if not serializer.is_valid():
            return Response(
                {"Status": False, "Errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.validated_data["user"]
        token, created = Token.objects.get_or_create(user=user)

        return Response(
            {"Status": True, "Token": token.key},
            status=status.HTTP_200_OK,
        )