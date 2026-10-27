from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from backend.models import Order, OrderItem, ProductInfo

User = get_user_model()


@transaction.atomic
def add_to_basket(*, user, product_info, quantity):
    """Добавляет указанное количество товара в корзину покупателя."""

    buyer = (
        User.objects.select_for_update()
        .filter(pk=user.pk, is_active=True, type=User.Type.BUYER)
        .first()
    )
    if buyer is None:
        raise PermissionDenied("Корзина доступна только покупателям.")

    offer = get_object_or_404(
        ProductInfo.objects
        .select_for_update(of=("self",))
        .select_related("product", "shop")
        .filter(
            shop__state=True,
            shop__user__is_active=True,
        ),
        pk=product_info,
    )

    basket, _ = Order.objects.get_or_create(
        user=buyer,
        state=Order.State.BASKET,
    )

    item = OrderItem.objects.filter(
        order=basket,
        product_info=offer,
    ).first()

    new_quantity = quantity
    if item is not None:
        new_quantity += item.quantity

    if new_quantity > offer.quantity:
        raise ValidationError({
            "quantity": [
                f"Недостаточно товара. Доступно: {offer.quantity}."
            ],
        })

    if item is None:
        item = OrderItem.objects.create(
            order=basket,
            product_info=offer,
            quantity=new_quantity,
            product_name=offer.product.name,
            price=offer.price,
            currency=offer.currency,
        )
        created = True
    else:
        item.quantity = new_quantity
        item.save(update_fields=["quantity"])
        created = False

    return item, created