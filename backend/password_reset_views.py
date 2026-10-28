from smtplib import SMTPException

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django_rest_passwordreset.models import ResetPasswordToken
from django_rest_passwordreset.views import (
    ResetPasswordConfirm,
    ResetPasswordRequestToken,
)
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .serializers import PasswordResetConfirmSerializer

User = get_user_model()


class PasswordResetConfirmThrottle(AnonRateThrottle):
    """Ограничивает подтверждение восстановления по IP-адресу."""

    scope = "password-reset-confirm"
    rate = "10/hour"


class PasswordResetRequestView(ResetPasswordRequestToken):
    """Запрос письма восстановления с откатом при сбое отправки."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)

                # Запросы восстановления одного пользователя выполняем по очереди.
                list(
                    User.objects.select_for_update()
                    .filter(email__iexact=serializer.validated_data["email"])
                    .order_by("id")
                )

                return super().post(request, *args, **kwargs)

        except (SMTPException, OSError):
            return Response(
                {
                    "Status": False,
                    "Errors": {
                        "email": ["Не удалось отправить письмо. Попробуйте позже."],
                    },
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class PasswordResetConfirmView(ResetPasswordConfirm):
    """Атомарная смена пароля по токену восстановления."""

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = PasswordResetConfirmSerializer
    throttle_classes = [PasswordResetConfirmThrottle]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = get_object_or_404(
            ResetPasswordToken,
            key=serializer.validated_data["token"],
        )
        get_object_or_404(
            User.objects.select_for_update(),
            pk=token.user_id,
        )

        # Библиотека повторно проверит токен после получения блокировки.
        return super().post(request, *args, **kwargs)