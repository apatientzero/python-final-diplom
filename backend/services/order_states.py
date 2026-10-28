from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from backend.models import Order, OrderItem, ProductInfo

User = get_user_model()

ORDER_STATE_TRANSITIONS = {
    Order.State.NEW: {Order.State.CONFIRMED, Order.State.CANCELED},
    Order.State.CONFIRMED: {Order.State.ASSEMBLED, Order.State.CANCELED},
    Order.State.ASSEMBLED: {Order.State.SENT, Order.State.CANCELED},
    Order.State.SENT: {Order.State.DELIVERED},
    Order.State.DELIVERED: set(),
    Order.State.CANCELED: set(),
}


def _restore_stock(order):
    """Возвращает товары в рамках транзакции изменения статуса."""

    items = list(
        OrderItem.objects.select_for_update()
        .filter(order=order)
        .order_by("product_info_id")
    )
    offer_ids = [item.product_info_id for item in items]

    # Соблюдаем порядок блокировок оформления заказа и импорта прайса.
    supplier_ids = (
        ProductInfo.objects.filter(pk__in=offer_ids)
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
            ProductInfo.objects.select_for_update()
            .filter(pk__in=offer_ids)
            .order_by("pk")
        )
    }

    # Проверяем все остатки перед записью в базу.
    for item in items:
        offer = offers[item.product_info_id]
        quantity = offer.quantity + item.quantity
        if quantity > 2**31 - 1:
            raise ValidationError({
                "state": [
                    f"Возврат товара «{item.product_name}» превысит допустимый остаток."
                ],
            })
        offer.quantity = quantity

    for offer in offers.values():
        offer.save(update_fields=["quantity"])


@transaction.atomic
def change_order_state(*, user, order_id, state):
    """Меняет статус заказа и возвращает товары при отмене."""

    if not User.objects.filter(
        pk=user.pk, is_active=True, is_staff=True,
    ).exists():
        raise PermissionDenied("Изменять статус может только администратор.")

    order = get_object_or_404(
        Order.objects.exclude(state=Order.State.BASKET),
        pk=order_id,
    )

    # Сначала блокируем покупателя, затем заказ — как при оформлении.
    get_object_or_404(
        User.objects.select_for_update(),
        pk=order.user_id,
    )
    order = get_object_or_404(
        Order.objects.select_for_update().exclude(state=Order.State.BASKET),
        pk=order.pk,
        user_id=order.user_id,
    )

    if state == order.state:
        return order, False

    allowed = ORDER_STATE_TRANSITIONS.get(order.state, set())
    if state not in allowed:
        raise ValidationError({
            "state": [f"Переход из «{order.state}» в «{state}» недоступен."],
        })

    if state == Order.State.CANCELED:
        _restore_stock(order)

    order.state = state
    order.save(update_fields=["state"])
    return order, True