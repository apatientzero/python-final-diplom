"""Изолированные настройки SQLite для тестов импорта, без доступа к рабочей БД."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "catalog-tests-only"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "backend.apps.BackendConfig",
]
AUTH_USER_MODEL = "backend.User"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
USE_I18N = False
TIME_ZONE = "UTC"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
