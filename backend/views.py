from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    BasketItemInputSerializer,
    BasketItemQuantitySerializer,
    BasketItemSerializer,
    CatalogFilterSerializer,
    ConfirmEmailSerializer,
    ContactSerializer,
    LoginSerializer,
    OrderCheckoutSerializer,
    OrderSerializer,
    ProductInfoSerializer,
    RegisterSerializer,
)

from smtplib import SMTPException

from .services.email_confirmation import (
    EmailConfirmationError,
    confirm_email,
    create_confirmation_token,
    send_confirmation_email,
)

from rest_framework.authtoken.models import Token

from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateDestroyAPIView,
)

from .models import Contact, Order, ProductInfo
from .pagination import CatalogPagination, OrderPagination
from .permissions import IsBuyer

from .services.basket import (
    add_to_basket,
    delete_basket_item,
    set_basket_item_quantity,
)

from decimal import Decimal
from .services.orders import checkout_order

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
                user = serializer.save()
                token = create_confirmation_token(user)
                send_confirmation_email(user, token)

        except (SMTPException, OSError):
            return Response(
                {
                    "Status": False,
                    "Errors": {
                        "email": [
                            "Не удалось отправить письмо. "
                            "Попробуйте зарегистрироваться позже."
                        ],
                    },
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
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


class ConfirmEmail(APIView):
    """Подтверждение email и активация пользователя."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ConfirmEmailSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"Status": False, "Errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            confirm_email(**serializer.validated_data)
        except EmailConfirmationError as exc:
            return Response(
                {"Status": False, "Errors": {"token": [str(exc)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"Status": True},
            status=status.HTTP_200_OK,
        )


class LoginAccount(APIView):
    """Выдаёт API-токен после проверки email и пароля."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(
            data=request.data,
            context={"request": request},
        )

        if not serializer.is_valid():
            return Response(
                {"Status": False, "Errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.validated_data["user"]
        token, created = Token.objects.get_or_create(user=user)

        return Response(
            {"Status": True, "Token": token.key},
            status=status.HTTP_200_OK,
        )


class ProductList(ListAPIView):
    """Каталог с фильтрацией по магазину, категории и названию."""

    permission_classes = [AllowAny]
    serializer_class = ProductInfoSerializer
    pagination_class = CatalogPagination

    def get_queryset(self):
        filters = CatalogFilterSerializer(
            data=self.request.query_params,
        )
        filters.is_valid(raise_exception=True)
        params = filters.validated_data

        queryset = (
            ProductInfo.objects
            .filter(
                shop__state=True,
                shop__user__is_active=True,
            )
            .select_related("product__category", "shop")
            .prefetch_related("product_parameters__parameter")
            .order_by("id")
        )

        if "shop" in params:
            queryset = queryset.filter(shop_id=params["shop"])

        if "category" in params:
            queryset = queryset.filter(
                product__category_id=params["category"],
            )

        search = params.get("search", "")
        if search:
            queryset = queryset.filter(
                product__name__icontains=search,
            )

        return queryset


class ProductDetail(RetrieveAPIView):
    """Подробная информация об одном предложении поставщика."""

    permission_classes = [AllowAny]
    serializer_class = ProductInfoSerializer

    def get_queryset(self):
        return (
            ProductInfo.objects
            .filter(
                shop__state=True,
                shop__user__is_active=True,
            )
            .select_related("product__category", "shop")
            .prefetch_related("product_parameters__parameter")
        )


class BasketView(APIView):
    """Добавление предложений в корзину текущего покупателя."""

    permission_classes = [IsAuthenticated, IsBuyer]

    def get(self, request):
        basket = Order.objects.filter(
            user=request.user,
            state=Order.State.BASKET,
        ).first()

        items = []
        if basket is not None:
            items = list(basket.items.order_by("id"))

        totals = {}
        for item in items:
            totals[item.currency] = (
                totals.get(item.currency, Decimal("0.00"))
                + item.total_price
            )

        return Response(
            {
                "Status": True,
                "Basket": basket.pk if basket is not None else None,
                "Items": BasketItemSerializer(items, many=True).data,
                "Totals": {
                    currency: f"{amount:.2f}"
                    for currency, amount in sorted(totals.items())
                },
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = BasketItemInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        item, created = add_to_basket(
            user=request.user,
            **serializer.validated_data,
        )

        response_status = (
            status.HTTP_201_CREATED
            if created
            else status.HTTP_200_OK
        )

        return Response(
            {
                "Status": True,
                "Created": created,
                "Item": BasketItemSerializer(item).data,
            },
            status=response_status,
        )


class BasketItemDetailView(APIView):
    """Изменение количества и удаление позиции своей корзины."""

    permission_classes = [IsAuthenticated, IsBuyer]

    def patch(self, request, pk):
        serializer = BasketItemQuantitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        item = set_basket_item_quantity(
            user=request.user,
            item_id=pk,
            quantity=serializer.validated_data["quantity"],
        )

        return Response(
            {
                "Status": True,
                "Item": BasketItemSerializer(item).data,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        delete_basket_item(
            user=request.user,
            item_id=pk,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class ContactList(ListCreateAPIView):
    """Просмотр и создание адресов текущего покупателя."""

    permission_classes = [IsAuthenticated, IsBuyer]
    serializer_class = ContactSerializer
    pagination_class = None

    def get_queryset(self):
        return Contact.objects.filter(
            user=self.request.user,
        ).order_by("id")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ContactDetail(RetrieveUpdateDestroyAPIView):
    """Просмотр, редактирование и удаление своего адреса."""

    permission_classes = [IsAuthenticated, IsBuyer]
    serializer_class = ContactSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Contact.objects.filter(user=self.request.user)


class OrderView(APIView):
    """Оформление заказа из корзины текущего покупателя."""

    permission_classes = [IsAuthenticated, IsBuyer]

    def get(self, request):
        orders = (
            Order.objects
            .filter(user=request.user)
            .exclude(state=Order.State.BASKET)
            .prefetch_related("items")
            .order_by("-dt", "-id")
        )

        paginator = OrderPagination()
        page = paginator.paginate_queryset(orders, request, view=self)

        serializer = OrderSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = OrderCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = checkout_order(
            user=request.user,
            order_id=serializer.validated_data["order"],
            contact_id=serializer.validated_data["contact"],
        )

        return Response(
            {
                "Status": True,
                "Order": order.pk,
                "State": order.state,
            },
            status=status.HTTP_200_OK,
        )


class OrderDetail(RetrieveAPIView):
    """Просмотр своего оформленного заказа."""

    permission_classes = [IsAuthenticated, IsBuyer]
    serializer_class = OrderSerializer

    def get_queryset(self):
        return (
            Order.objects
            .filter(user=self.request.user)
            .exclude(state=Order.State.BASKET)
            .prefetch_related("items")
        )