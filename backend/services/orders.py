from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from backend.models import Contact, Order, OrderItem, ProductInfo

User = get_user_model()


@transaction.atomic
def checkout_order(*, user, order_id, contact_id):
    """Оформляет корзину, списывает остатки и сохраняет адрес."""

    buyer = (
        User.objects.select_for_update()
        .filter(pk=user.pk, is_active=True, type=User.Type.BUYER)
        .first()
    )
    if buyer is None:
        raise PermissionDenied("Оформление доступно только покупателям.")

    order = get_object_or_404(
        Order.objects.select_for_update(),
        pk=order_id,
        user=buyer,
    )

    if order.state != Order.State.BASKET:
        raise ValidationError({
            "order": ["Этот заказ уже не является корзиной."],
        })

    contact = get_object_or_404(
        Contact.objects.select_for_update(),
        pk=contact_id,
        user=buyer,
    )

    items = list(
        OrderItem.objects
        .select_for_update()
        .filter(order=order)
        .order_by("product_info_id")
    )

    if not items:
        raise ValidationError({
            "order": ["Нельзя оформить пустую корзину."],
        })

    offer_ids = [item.product_info_id for item in items]

    # Импорт прайса тоже блокирует пользователя-поставщика.
    # Получаем эти блокировки перед блокировками предложений.
    supplier_ids = (
        ProductInfo.objects
        .filter(pk__in=offer_ids)
        .values_list("shop__user_id", flat=True)
    )
    list(
        User.objects.select_for_update()
        .filter(pk__in=supplier_ids)
        .order_by("pk")
    )

    offers = {
        offer.pk: offer
        for offer in (
            ProductInfo.objects
            .select_for_update(of=("self", "shop"))
            .select_related("shop__user")
            .filter(pk__in=offer_ids)
            .order_by("pk")
        )
    }

    # Сначала проверяем все позиции.
    for item in items:
        offer = offers.get(item.product_info_id)

        if (
            offer is None
            or not offer.shop.state
            or not offer.shop.user.is_active
        ):
            raise ValidationError({
                "order": [
                    f"Предложение «{item.product_name}» недоступно."
                ],
            })

        if item.quantity > offer.quantity:
            raise ValidationError({
                "order": [
                    f"Недостаточно товара «{item.product_name}». "
                    f"Доступно: {offer.quantity}, "
                    f"в корзине: {item.quantity}."
                ],
            })

    # После успешной проверки списываем остатки.
    for item in items:
        offer = offers[item.product_info_id]
        offer.quantity -= item.quantity
        offer.save(update_fields=["quantity"])

    order.contact = contact
    order.delivery_address = {
        "city": contact.city,
        "street": contact.street,
        "house": contact.house,
        "structure": contact.structure,
        "building": contact.building,
        "apartment": contact.apartment,
        "phone": contact.phone,
    }
    order.state = Order.State.NEW
    order.save(
        update_fields=["contact", "delivery_address", "state"],
    )

    return order