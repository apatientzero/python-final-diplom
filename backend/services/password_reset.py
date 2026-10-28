from django.conf import settings
from django.core.mail import send_mail
from django_rest_passwordreset.models import get_password_reset_token_expiry_time


def send_password_reset_email(reset_password_token):
    """Отправляет пользователю токен для восстановления пароля."""

    hours = get_password_reset_token_expiry_time()
    message = (
        "Вы запросили восстановление пароля в Parviz Store.\n\n"
        "Ваш токен восстановления:\n"
        f"{reset_password_token.key}\n\n"
        "Отправьте POST-запрос с полями token и password:\n"
        "/api/v1/user/password_reset/confirm\n\n"
        f"Срок действия токена: {hours} ч. с момента создания.\n"
        "Если вы не запрашивали восстановление, проигнорируйте это письмо.\n"
    )

    sent = send_mail(
        subject="Восстановление пароля в Parviz Store",
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[reset_password_token.user.email],
        fail_silently=False,
    )

    if sent != 1:
        raise OSError("Письмо для восстановления пароля не отправлено.")

    return sent