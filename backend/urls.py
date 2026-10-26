from django.urls import path

from .views import (
    ConfirmEmail,
    LoginAccount,
    ProductList,
    RegisterAccount,
)

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
    path(
        "user/login",
        LoginAccount.as_view(),
        name="user-login",
    ),
    path(
        "products",
        ProductList.as_view(),
        name="product-list",
    ),
]