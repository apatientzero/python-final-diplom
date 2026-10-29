"""SMTP backend с пошаговой авторизацией LOGIN."""

import smtplib

from django.core.mail.backends.smtp import EmailBackend as DjangoEmailBackend


class LoginAuthMixin:
    """Передаёт логин и пароль в ответ на отдельные запросы сервера."""

    def login(self, user, password, *, initial_response_ok=False):
        self.ehlo_or_helo_if_needed()
        methods = self.esmtp_features.get("auth", "").upper().split()

        if "LOGIN" not in methods:
            raise smtplib.SMTPNotSupportedError(
                "SMTP-сервер не поддерживает AUTH LOGIN."
            )

        self.user = user
        self.password = password
        return self.auth(
            "LOGIN",
            self.auth_login,
            initial_response_ok=initial_response_ok,
        )


class LoginSMTP(LoginAuthMixin, smtplib.SMTP):
    pass


class LoginSMTPSSL(LoginAuthMixin, smtplib.SMTP_SSL):
    pass


class EmailBackend(DjangoEmailBackend):
    """Использует настройки соединения и отправку сообщений Django."""

    @property
    def connection_class(self):
        return LoginSMTPSSL if self.use_ssl else LoginSMTP