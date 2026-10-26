from django.urls import path

from .views import ConfirmEmail, RegisterAccount

app_name = "backend"

urlpatterns = [
    path(
        "user/register",
        RegisterAccount.as_view(),
        name="user-register",
    ),
    path(
        "user/register/confirm",
        ConfirmEmail.as_view(),
        name="user-register-confirm",
    ),
]