"""Оформление заказов, остатки, уведомления и права доступа."""

from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from .models import Category, Contact, Order, Product, ProductInfo, Shop
from .services.order_states import change_order_state
from .services.orders import checkout_order

User = get_user_model()


class OrderApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.buyer = User.objects.create_user(
            email="buyer@example.test", is_active=True,
        )
        cls.other = User.objects.create_user(
            email="other@example.test", is_active=True,
        )
        cls.admin = User.objects.create_user(
            email="admin@example.test", is_active=True, is_staff=True,
        )

        category = Category.objects.create(name="Учебная техника")
        cls.offers = []

        for number, price, currency, quantity in (
            (1, "10.00", "USD", 5),
            (2, "100.00", "RUB", 7),
        ):
            supplier = User.objects.create_user(
                email=f"supplier-{number}@example.test",
                type=User.Type.SHOP,
                is_active=True,
            )
            shop = Shop.objects.create(
                user=supplier, name=f"Магазин {number}",
            )
            product = Product.objects.create(
                name=f"Учебный товар {number}", category=category,
            )
            cls.offers.append(ProductInfo.objects.create(
                product=product,
                shop=shop,
                external_id="SKU-001",
                price=Decimal(price),
                price_rrc=Decimal(price),
                currency=currency,
                quantity=quantity,
            ))

        cls.contact = Contact.objects.create(
            user=cls.buyer,
            city="Москва",
            street="Учебная",
            house="10",
            apartment="25",
            phone="+79991234567",
        )
        cls.other_contact = Contact.objects.create(
            user=cls.other,
            city="Казань",
            street="Школьная",
            house="20",
            phone="+79997654321",
        )

    def setUp(self):
        cache.clear()
        self.buyer_client = self.client_for(self.buyer)
        self.other_client = self.client_for(self.other)
        self.admin_client = self.client_for(self.admin)
        self.supplier_client = self.client_for(self.offers[0].shop.user)

    def client_for(self, user):
        client = APIClient()
        token, _ = Token.objects.get_or_create(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client

    def make_basket(self):
        for offer, quantity in zip(self.offers, (2, 3)):
            response = self.buyer_client.post(
                reverse("backend:basket"),
                {"product_info": offer.pk, "quantity": quantity},
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)

        return Order.objects.get(
            user=self.buyer, state=Order.State.BASKET,
        )

    def checkout(self, basket, *, client=None, contact=None):
        return (client or self.buyer_client).post(
            reverse("backend:order-list"),
            {
                "order": basket.pk,
                "contact": (contact or self.contact).pk,
            },
            format="json",
        )

    def make_order(self):
        basket = self.make_basket()
        response = self.checkout(basket)
        self.assertEqual(response.status_code, 200, response.data)
        return Order.objects.get(pk=basket.pk)

    def stocks(self):
        return tuple(
            ProductInfo.objects
            .filter(pk__in=[offer.pk for offer in self.offers])
            .order_by("pk")
            .values_list("quantity", flat=True)
        )

    def change_state(self, order, state, *, client=None):
        return (client or self.admin_client).patch(
            reverse(
                "backend:admin-order-state",
                kwargs={"pk": order.pk},
            ),
            {"state": state},
            format="json",
        )

    def test_checkout_preserves_snapshots_and_deducts_both_suppliers_stock(self):
        basket = self.make_basket()
        self.assertEqual(self.stocks(), (5, 7))

        ProductInfo.objects.filter(pk=self.offers[0].pk).update(
            price="999.00", currency="RUB",
        )
        Product.objects.filter(pk=self.offers[0].product_id).update(
            name="Новое название товара",
        )

        response = self.checkout(basket)
        self.assertEqual(response.status_code, 200)

        basket.refresh_from_db()
        self.assertEqual(basket.state, Order.State.NEW)
        self.assertEqual(basket.contact_id, self.contact.pk)
        self.assertEqual(self.stocks(), (3, 4))

        item = basket.items.get(product_info=self.offers[0])
        self.assertEqual(item.price, Decimal("10.00"))
        self.assertEqual(item.currency, "USD")
        self.assertEqual(item.product_name, "Учебный товар 1")
        self.assertEqual(item.total_price, Decimal("20.00"))

        details = self.buyer_client.get(
            reverse("backend:order-detail", kwargs={"pk": basket.pk}),
        )
        self.assertEqual(details.status_code, 200)
        self.assertEqual(
            details.data["totals"],
            {"USD": "20.00", "RUB": "300.00"},
        )
        self.assertEqual(len(details.data["items"]), 2)

    def test_address_snapshot_survives_contact_update_and_deletion(self):
        order = self.make_order()
        address = dict(order.delivery_address)
        contact_url = reverse(
            "backend:contact-detail", kwargs={"pk": self.contact.pk},
        )

        response = self.buyer_client.patch(
            contact_url,
            {"city": "Казань", "apartment": "99"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.delivery_address, address)

        self.assertEqual(
            self.buyer_client.delete(contact_url).status_code, 204,
        )
        order.refresh_from_db()
        self.assertIsNone(order.contact_id)
        self.assertEqual(order.delivery_address, address)
        self.assertEqual(address["city"], "Москва")
        self.assertEqual(address["apartment"], "25")

    def test_repeated_checkout_does_not_touch_stock_or_new_basket(self):
        order = self.make_order()
        response = self.buyer_client.post(
            reverse("backend:basket"),
            {"product_info": self.offers[0].pk, "quantity": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        new_basket_id = response.data["Item"]["order"]
        self.assertNotEqual(new_basket_id, order.pk)

        response = self.checkout(order)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stocks(), (3, 4))

        new_basket = Order.objects.get(pk=new_basket_id)
        self.assertEqual(new_basket.state, Order.State.BASKET)
        self.assertEqual(new_basket.items.get().quantity, 1)

    def test_empty_basket_and_foreign_objects_cannot_be_checked_out(self):
        basket = Order.objects.create(user=self.buyer)
        self.assertEqual(self.checkout(basket).status_code, 400)

        basket = self.make_basket()
        self.assertEqual(
            self.checkout(
                basket, contact=self.other_contact,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.checkout(
                basket,
                client=self.other_client,
                contact=self.other_contact,
            ).status_code,
            404,
        )

        basket.refresh_from_db()
        self.assertEqual(basket.state, Order.State.BASKET)
        self.assertEqual(basket.delivery_address, {})
        self.assertIsNone(basket.contact_id)
        self.assertEqual(self.stocks(), (5, 7))

    def test_unavailable_second_offer_does_not_partially_deduct_stock(self):
        basket = self.make_basket()
        offer = self.offers[1]
        scenarios = (
            (
                Shop.objects.filter(pk=offer.shop_id),
                {"state": False},
                {"state": True},
            ),
            (
                User.objects.filter(pk=offer.shop.user_id),
                {"is_active": False},
                {"is_active": True},
            ),
            (
                ProductInfo.objects.filter(pk=offer.pk),
                {"quantity": 0},
                {"quantity": 7},
            ),
        )

        for queryset, invalid, restored in scenarios:
            with self.subTest(invalid=invalid):
                queryset.update(**invalid)
                stock_before = self.stocks()

                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    response = self.checkout(basket)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.stocks(), stock_before)
                self.assertEqual(callbacks, [])

                basket.refresh_from_db()
                self.assertEqual(basket.state, Order.State.BASKET)
                self.assertIsNone(basket.contact_id)
                self.assertEqual(basket.delivery_address, {})
                queryset.update(**restored)

        self.assertEqual(len(mail.outbox), 0)

    def test_checkout_failure_rolls_back_all_stock_and_order_changes(self):
        basket = self.make_basket()

        # Ошибка возникает после списания остатков, при сохранении заказа.
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with patch.object(
                Order,
                "save",
                side_effect=IntegrityError("Сбой сохранения"),
            ):
                with self.assertRaises(IntegrityError):
                    checkout_order(
                        user=self.buyer,
                        order_id=basket.pk,
                        contact_id=self.contact.pk,
                    )

        basket.refresh_from_db()
        self.assertEqual(basket.state, Order.State.BASKET)
        self.assertIsNone(basket.contact_id)
        self.assertEqual(basket.delivery_address, {})
        self.assertEqual(self.stocks(), (5, 7))
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_order_emails_wait_for_commit_and_are_not_repeated(self):
        basket = self.make_basket()

        # TestCase сам не делает commit: запускаем сохранённые callbacks.
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.assertEqual(self.checkout(basket).status_code, 200)
            self.assertEqual(len(mail.outbox), 0)

        self.assertEqual(len(callbacks), 2)
        self.assertEqual(len(mail.outbox), 2)

        letters = {letter.to[0]: letter for letter in mail.outbox}
        self.assertEqual(
            set(letters),
            {self.buyer.email, settings.ORDER_ADMIN_EMAIL},
        )
        self.assertEqual(
            letters[self.buyer.email].subject,
            f"Ваш заказ №{basket.pk} принят",
        )
        self.assertEqual(
            letters[settings.ORDER_ADMIN_EMAIL].subject,
            f"Накладная по заказу №{basket.pk}",
        )

        for letter in letters.values():
            for text in (
                "20.00 USD", "300.00 RUB",
                "Магазин 1", "Магазин 2", "Учебная",
            ):
                self.assertIn(text, letter.body)

        with self.captureOnCommitCallbacks(execute=True) as repeated:
            self.assertEqual(self.checkout(basket).status_code, 400)

        self.assertEqual(repeated, [])
        self.assertEqual(len(mail.outbox), 2)

    def test_order_history_is_private_and_survives_shop_shutdown(self):
        order = self.make_order()
        own_basket = Order.objects.create(user=self.buyer)
        other_order = Order.objects.create(
            user=self.other, state=Order.State.NEW,
        )
        detail_url = reverse(
            "backend:order-detail", kwargs={"pk": order.pk},
        )

        self.assertEqual(
            self.other_client.get(detail_url).status_code, 404,
        )
        for hidden in (own_basket, other_order):
            response = self.buyer_client.get(
                reverse(
                    "backend:order-detail",
                    kwargs={"pk": hidden.pk},
                ),
            )
            self.assertEqual(response.status_code, 404)

        history = self.buyer_client.get(reverse("backend:order-list"))
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data["count"], 1)
        self.assertEqual(
            [row["id"] for row in history.data["results"]],
            [order.pk],
        )

        Shop.objects.filter(pk=self.offers[0].shop_id).update(
            state=False,
        )
        response = self.buyer_client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["totals"],
            {"USD": "20.00", "RUB": "300.00"},
        )

        item_url = reverse(
            "backend:basket-item-detail",
            kwargs={"pk": order.items.first().pk},
        )
        response = self.buyer_client.patch(
            item_url, {"quantity": 1}, format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            self.buyer_client.delete(item_url).status_code, 404,
        )

    def test_cancellation_restores_stock_once_from_each_allowed_stage(self):
        for stage in (
            Order.State.NEW,
            Order.State.CONFIRMED,
            Order.State.ASSEMBLED,
        ):
            with self.subTest(stage=stage):
                order = self.make_order()

                # Подготавливаем заказ на нужном этапе обработки.
                Order.objects.filter(pk=order.pk).update(state=stage)
                items_before = list(order.items.order_by("pk").values())

                Shop.objects.filter(pk=self.offers[0].shop_id).update(
                    state=False,
                )
                User.objects.filter(
                    pk=self.offers[1].shop.user_id,
                ).update(is_active=False)

                response = self.change_state(
                    order, Order.State.CANCELED,
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data["Changed"])
                self.assertEqual(self.stocks(), (5, 7))

                order.refresh_from_db()
                self.assertEqual(order.state, Order.State.CANCELED)
                self.assertEqual(
                    list(order.items.order_by("pk").values()),
                    items_before,
                )

                response = self.change_state(
                    order, Order.State.CANCELED,
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.data["Changed"])
                self.assertEqual(self.stocks(), (5, 7))

                Shop.objects.filter(pk=self.offers[0].shop_id).update(
                    state=True,
                )
                User.objects.filter(
                    pk=self.offers[1].shop.user_id,
                ).update(is_active=True)

    def test_cancellation_failure_rolls_back_all_refunds(self):
        order = self.make_order()

        with patch.object(
            Order,
            "save",
            side_effect=IntegrityError("Сбой сохранения"),
        ):
            with self.assertRaises(IntegrityError):
                change_order_state(
                    user=self.admin,
                    order_id=order.pk,
                    state=Order.State.CANCELED,
                )

        order.refresh_from_db()
        self.assertEqual(order.state, Order.State.NEW)
        self.assertEqual(self.stocks(), (3, 4))
        self.assertEqual(order.items.count(), 2)

    def test_admin_status_permissions_are_checked_for_every_request(self):
        order = self.make_order()

        for client, expected in (
            (self.client, 401),
            (self.buyer_client, 403),
            (self.supplier_client, 403),
        ):
            with self.subTest(expected=expected):
                response = self.change_state(
                    order, Order.State.CONFIRMED, client=client,
                )
                self.assertEqual(response.status_code, expected)

        User.objects.filter(pk=self.admin.pk).update(is_staff=False)
        self.assertEqual(
            self.change_state(
                order, Order.State.CONFIRMED,
            ).status_code,
            403,
        )

        User.objects.filter(pk=self.admin.pk).update(
            is_staff=True, is_active=False,
        )
        self.assertEqual(
            self.change_state(
                order, Order.State.CONFIRMED,
            ).status_code,
            401,
        )

        order.refresh_from_db()
        self.assertEqual(order.state, Order.State.NEW)
        self.assertEqual(self.stocks(), (3, 4))

    def test_lifecycle_rejects_skips_reverse_and_late_cancellation(self):
        order = self.make_order()
        self.assertEqual(
            self.change_state(
                order, Order.State.DELIVERED,
            ).status_code,
            400,
        )

        for state in (
            Order.State.CONFIRMED,
            Order.State.ASSEMBLED,
            Order.State.SENT,
            Order.State.DELIVERED,
        ):
            response = self.change_state(order, state)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["State"], state)
            self.assertTrue(response.data["Changed"])

            if state == Order.State.SENT:
                self.assertEqual(
                    self.change_state(
                        order, Order.State.CANCELED,
                    ).status_code,
                    400,
                )

        self.assertEqual(
            self.change_state(order, Order.State.NEW).status_code, 400,
        )
        self.assertEqual(
            self.change_state(
                order, Order.State.CANCELED,
            ).status_code,
            400,
        )

        order.refresh_from_db()
        self.assertEqual(order.state, Order.State.DELIVERED)
        self.assertEqual(self.stocks(), (3, 4))