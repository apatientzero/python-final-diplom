from django.dispatch import receiver
from django_rest_passwordreset.signals import (
    post_password_reset,
    reset_password_token_created,
)
from rest_framework.authtoken.models import Token

from .services.password_reset import send_password_reset_email


@receiver(
    reset_password_token_created,
    dispatch_uid="backend.password_reset_email",
)
def password_reset_token_created(sender, instance, reset_password_token, **kwargs):
    """Отправляет письмо по сигналу библиотеки восстановления пароля."""

    send_password_reset_email(reset_password_token)


@receiver(
    post_password_reset,
    dispatch_uid="backend.password_reset_revoke_api_token",
)
def revoke_api_token_after_password_reset(sender, user, **kwargs):
    """Отзывает прежний API-токен после успешной смены пароля."""

    Token.objects.filter(user=user).delete()