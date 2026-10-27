from django.urls import path

from .views import (
    BasketItemDetailView,
    BasketView,
    ConfirmEmail,
    LoginAccount,
    ProductDetail,
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
    path(
        "products/<int:pk>",
        ProductDetail.as_view(),
        name="product-detail",
    ),
    path(
        "basket",
        BasketView.as_view(),
        name="basket",
    ),
    path(
        "basket/items/<int:pk>",
        BasketItemDetailView.as_view(),
        name="basket-item-detail",
    ),
]