import hashlib
import secrets

from django.utils import timezone

from backend.models import ConfirmEmailToken

from django.conf import settings
from django.core.mail import send_mail

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction


def hash_token(token):
    """Возвращает SHA-256 хеш токена."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_confirmation_token(user):
    """Создаёт токен и сохраняет его хеш для подтверждения email."""
    if user.is_active:
        raise ValueError("Email активного пользователя подтверждать не требуется.")

    token = secrets.token_urlsafe(32)

    ConfirmEmailToken.objects.update_or_create(
        user=user,
        defaults={
            "email": user.email,
            "token_hash": hash_token(token),
            "created_at": timezone.now(),
        },
    )

    return token


def send_confirmation_email(user, token):
    """Отправляет пользователю токен подтверждения email."""
    sent = send_mail(
        subject="Подтверждение регистрации в Parviz Store",
        message=(
            "Вы зарегистрировались в Parviz Store.\n\n"
            f"Ваш токен подтверждения:\n{token}\n\n"
            "Токен действует 24 часа.\n\n"
            "Для подтверждения отправьте POST-запрос на "
            "/api/v1/user/register/confirm "
            "с полями email и token.\n\n"
            "Если вы не регистрировались, проигнорируйте письмо."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

    if sent != 1:
        raise OSError("Не удалось отправить письмо подтверждения.")


class EmailConfirmationError(ValueError):
    """Ошибка подтверждения email."""


@transaction.atomic
def confirm_email(email, token):
    """Активирует пользователя по действующему одноразовому токену."""
    User = get_user_model()
    error_message = "Токен недействителен или срок его действия истёк."

    user = (
        User.objects.select_for_update()
        .filter(email=email, is_active=False)
        .first()
    )
    if user is None:
        raise EmailConfirmationError(error_message)

    record = (
        ConfirmEmailToken.objects.select_for_update()
        .filter(user=user)
        .first()
    )
    if record is None:
        raise EmailConfirmationError(error_message)

    if record.email != user.email:
        raise EmailConfirmationError(error_message)

    if timezone.now() >= record.created_at + timedelta(hours=24):
        raise EmailConfirmationError(error_message)

    if not secrets.compare_digest(record.token_hash, hash_token(token)):
        raise EmailConfirmationError(error_message)

    user.is_active = True
    user.save(update_fields=["is_active"])
    record.delete()