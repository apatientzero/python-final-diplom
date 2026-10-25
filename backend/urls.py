from django.urls import path

from .views import RegisterAccount

app_name = "backend"

urlpatterns = [
    path("user/register", RegisterAccount.as_view(), name="user-register"),
]