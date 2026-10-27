from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

User = get_user_model()


class IsBuyer(BasePermission):
    """Разрешает доступ только активному покупателю."""

    message = "Это действие доступно только покупателям."

    def has_permission(self, request, view):
        user = request.user

        return (
            user.is_authenticated
            and user.is_active
            and user.type == User.Type.BUYER
        )