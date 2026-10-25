from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RegisterSerializer

User = get_user_model()


class RegisterAccount(APIView):
    """Регистрация неактивного покупателя через POST-запрос."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"Status": False, "Errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            # Другой запрос мог зарегистрировать email после проверки.
            if User.objects.filter(
                email__iexact=serializer.validated_data["email"]
            ).exists():
                return Response(
                    {
                        "Status": False,
                        "Errors": {"email": ["Этот email уже зарегистрирован."]},
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            raise

        return Response(
            {"Status": True},
            status=status.HTTP_201_CREATED,
        )
