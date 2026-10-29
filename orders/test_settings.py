"""Настройки автотестов на отдельной тестовой базе PostgreSQL."""

from .settings import *  # noqa: F403

DEBUG = False
SECRET_KEY = "procurement-tests-only"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "Parviz Store <noreply@parviz-store.test>"
ORDER_ADMIN_EMAIL = "admin@parviz-store.test"

# Быстрый хешер используется только в тестовом окружении.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "procurement-tests",
    },
}