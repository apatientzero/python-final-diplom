from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Prefetch

from backend.models import Order, OrderItem


def send_order_email(order_id, *, to_admin=False):
    """Отправляет подтверждение покупателю или накладную администратору."""
    order = (
        Order.objects
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=(
                    OrderItem.objects
                    .select_related("product_info__shop")
                    .order_by("id")
                ),
            ),
        )
        .get(pk=order_id)
    )

    if order.state == Order.State.BASKET:
        raise ValueError("Нельзя отправить подтверждение для корзины.")

    lines = [
        f"Заказ №{order.pk}",
        f"Покупатель: {order.user.get_full_name() or order.user.email}",
        f"Email: {order.user.email}",
        "",
        "Состав заказа:",
    ]
    totals = {}

    for number, item in enumerate(order.items.all(), start=1):
        lines.extend([
            f"{number}. {item.product_name}",
            f"   Поставщик: {item.product_info.shop.name}",
            f"   Артикул: {item.product_info.external_id}",
            f"   Количество: {item.quantity}",
            f"   Цена: {item.price:.2f} {item.currency}",
            f"   Сумма: {item.total_price:.2f} {item.currency}",
            "",
        ])
        totals[item.currency] = (
            totals.get(item.currency, Decimal("0.00"))
            + item.total_price
        )

    lines.append("Итого:")
    for currency, amount in sorted(totals.items()):
        lines.append(f"{amount:.2f} {currency}")

    lines.extend(["", "Адрес доставки:"])
    address_fields = [
        ("city", "Город"),
        ("street", "Улица"),
        ("house", "Дом"),
        ("structure", "Строение"),
        ("building", "Корпус"),
        ("apartment", "Квартира"),
        ("phone", "Телефон"),
    ]
    for field, label in address_fields:
        value = order.delivery_address.get(field)
        if value:
            lines.append(f"{label}: {value}")

    if to_admin:
        subject = f"Накладная по заказу №{order.pk}"
        recipient = settings.ORDER_ADMIN_EMAIL
    else:
        subject = f"Ваш заказ №{order.pk} принят"
        recipient = order.user.email

    sent = send_mail(
        subject=subject,
        message="\n".join(lines),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )

    if sent != 1:
        raise OSError("Не удалось отправить письмо о заказе.")

    return sent