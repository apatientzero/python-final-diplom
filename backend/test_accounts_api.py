"""Регрессии регистрации, входа и восстановления пароля через API."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from django_rest_passwordreset.models import ResetPasswordToken
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import ConfirmEmailToken
from .services.email_confirmation import create_confirmation_token, hash_token

User = get_user_model()


class AccountApiTests(APITestCase):
    def setUp(self):
        # Django очищает БД и письма между тестами, но кэш требует очистки.
        cache.clear()
        self.password = "River!8Mango^29Cloud"
        self.payload = {
            "email": "Buyer@Example.test",
            "password": self.password,
            "first_name": "Mike",
            "last_name": "Tyson",
            "company": "Учебный магазин",
            "position": "Закупщик",
        }

    def post(self, name, data):
        return self.client.post(
            reverse(f"backend:{name}"), data, format="json",
        )

    def create_user(self, email="buyer@example.test", *, is_active=True):
        return User.objects.create_user(
            email=email,
            password=self.password,
            is_active=is_active,
        )

    def token_from_email(self, marker):
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(marker, mail.outbox[0].body)
        return mail.outbox[0].body.split(marker, 1)[1].splitlines()[0]

    def test_registration_confirmation_and_login(self):
        response = self.post("user-register", {
            **self.payload,
            "type": "shop",
            "is_staff": True,
            "is_active": True,
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, {"Status": True})

        user = User.objects.get(email="buyer@example.test")
        self.assertEqual(user.type, User.Type.BUYER)
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password(self.password))
        self.assertNotEqual(user.password, self.password)

        token = self.token_from_email("Ваш токен подтверждения:\n")
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertEqual(
            ConfirmEmailToken.objects.get(user=user).token_hash,
            hash_token(token),
        )

        credentials = {
            "email": self.payload["email"],
            "password": self.password,
        }
        self.assertEqual(self.post("user-login", credentials).status_code, 400)
        self.assertFalse(Token.objects.filter(user=user).exists())

        confirmation = {"email": self.payload["email"], "token": token}
        self.assertEqual(
            self.post("user-register-confirm", confirmation).status_code, 200,
        )
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(ConfirmEmailToken.objects.filter(user=user).exists())

        self.assertEqual(
            self.post("user-register-confirm", confirmation).status_code, 400,
        )

        login = self.post("user-login", credentials)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.data["Token"], Token.objects.get(user=user).key)
        self.assertEqual(self.post("user-login", credentials).data, login.data)

    def test_duplicate_registration_does_not_send_second_email(self):
        self.assertEqual(self.post("user-register", self.payload).status_code, 201)

        response = self.post("user-register", {
            **self.payload,
            "email": self.payload["email"].lower(),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data["Errors"])
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_registration_rolls_back_if_email_fails(self):
        with patch(
            "backend.services.email_confirmation.send_mail",
            side_effect=OSError("Почта недоступна"),
        ):
            response = self.post("user-register", self.payload)

        self.assertEqual(response.status_code, 503)
        self.assertFalse(User.objects.exists())
        self.assertFalse(ConfirmEmailToken.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_and_expired_confirmation_do_not_activate_user(self):
        user = self.create_user(is_active=False)
        token = create_confirmation_token(user)
        data = {"email": user.email, "token": "wrong-token"}

        self.assertEqual(self.post("user-register-confirm", data).status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

        ConfirmEmailToken.objects.filter(user=user).update(
            created_at=timezone.now() - timedelta(hours=25),
        )
        data["token"] = token

        self.assertEqual(self.post("user-register-confirm", data).status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_login_rejects_wrong_password_and_inactive_user(self):
        user = self.create_user()
        response = self.post("user-login", {
            "email": user.email,
            "password": "Wrong!Password42",
        })
        self.assertEqual(response.status_code, 400)

        user.is_active = False
        user.save(update_fields=["is_active"])
        response = self.post("user-login", {
            "email": user.email,
            "password": self.password,
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Token.objects.filter(user=user).exists())

        response = self.post("user-login", {"email": user.email})
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data["Errors"])

    def test_password_reset_changes_password_and_revokes_tokens(self):
        user = self.create_user()
        old_api_token = Token.objects.create(user=user).key

        response = self.post("password-reset-request", {
            "email": user.email.upper(),
        })
        self.assertEqual(response.status_code, 200)

        token = self.token_from_email("Ваш токен восстановления:\n")
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertEqual(ResetPasswordToken.objects.get(user=user).key, token)
        self.assertNotIn(token, str(response.data))

        user.refresh_from_db()
        self.assertTrue(user.check_password(self.password))
        self.assertTrue(Token.objects.filter(key=old_api_token).exists())

        response = self.post("password-reset-confirm", {
            "token": token,
            "password": "123",
        })
        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.check_password(self.password))
        self.assertTrue(ResetPasswordToken.objects.filter(key=token).exists())
        self.assertTrue(Token.objects.filter(key=old_api_token).exists())

        # Пробелы в начале и конце входят в пароль и должны сохраниться.
        new_password = "  Orbit!7Falcon#53River  "
        response = self.post("password-reset-confirm", {
            "token": token,
            "password": new_password,
        })
        self.assertEqual(response.status_code, 200)

        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))
        self.assertFalse(user.check_password(self.password))
        self.assertFalse(Token.objects.filter(user=user).exists())
        self.assertFalse(ResetPasswordToken.objects.filter(user=user).exists())

        response = self.client.get(
            reverse("backend:basket"),
            HTTP_AUTHORIZATION=f"Token {old_api_token}",
        )
        self.assertEqual(response.status_code, 401)

        response = self.post("password-reset-confirm", {
            "token": token,
            "password": self.password,
        })
        self.assertEqual(response.status_code, 404)
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))

        response = self.post("user-login", {
            "email": user.email,
            "password": new_password,
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["Token"], old_api_token)

    def test_password_reset_does_not_disclose_accounts(self):
        active = self.create_user()
        inactive = self.create_user("inactive@example.test", is_active=False)

        responses = [
            self.post("password-reset-request", {"email": email})
            for email in (active.email, inactive.email, "unknown@example.test")
        ]
        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, responses[0].data)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [active.email])
        self.assertFalse(ResetPasswordToken.objects.filter(user=inactive).exists())

    def test_password_reset_rolls_back_if_email_fails(self):
        user = self.create_user()
        api_token = Token.objects.create(user=user)

        with patch(
            "backend.services.password_reset.send_mail",
            side_effect=OSError("Почта недоступна"),
        ):
            response = self.post("password-reset-request", {"email": user.email})

        self.assertEqual(response.status_code, 503)
        self.assertFalse(ResetPasswordToken.objects.filter(user=user).exists())
        self.assertTrue(Token.objects.filter(pk=api_token.pk).exists())
        user.refresh_from_db()
        self.assertTrue(user.check_password(self.password))
        self.assertEqual(len(mail.outbox), 0)

    def test_expired_reset_token_cannot_change_password(self):
        user = self.create_user()
        token = ResetPasswordToken.objects.create(user=user)

        ResetPasswordToken.objects.filter(pk=token.pk).update(
            created_at=timezone.now() - timedelta(hours=2),
        )
        response = self.post("password-reset-confirm", {
            "token": token.key,
            "password": "Orbit!7Falcon#53River",
        })
        self.assertEqual(response.status_code, 404)
        user.refresh_from_db()
        self.assertTrue(user.check_password(self.password))

    def test_password_reset_request_is_throttled(self):
        for expected in (200, 200, 200, 429):
            response = self.post("password-reset-request", {
                "email": "unknown@example.test",
            })
            self.assertEqual(response.status_code, expected)

        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_confirmation_is_throttled(self):
        for expected in [404] * 10 + [429]:
            response = self.post("password-reset-confirm", {
                "token": "unknown-token",
                "password": self.password,
            })
            self.assertEqual(response.status_code, expected)