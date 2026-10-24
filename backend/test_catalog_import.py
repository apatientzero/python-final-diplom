"""Проверки импорта из приложенного Catalog.yaml и совместимости старого прайса."""

import json
from copy import deepcopy
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import yaml
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from backend.models import Category, Currency, Order, OrderItem, Product, ProductInfo, Shop, User
from backend.services.importer import PriceImportError, import_price, parse_price


class CatalogImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.path = Path(settings.BASE_DIR) / "data" / "Catalog.yaml"
        cls.content = cls.path.read_text(encoding="utf-8")
        cls.supplier = User.objects.create_user("supplier@example.test", type=User.Type.SHOP, is_active=True)

    def changed_content(self, change):
        raw = yaml.safe_load(self.content)
        change(raw["catalog"])
        return yaml.safe_dump(raw, allow_unicode=True)

    def test_original_catalog_preserves_skus_prices_availability_and_currency(self):
        data = parse_price(self.content)
        self.assertEqual(data["currency"], Currency.USD)
        self.assertEqual([c["name"] for c in data["categories"]], ["Ноутбуки", "Моноблоки", "Мониторы"])
        self.assertEqual(len(data["goods"]), 21)
        self.assertEqual(data["goods"][0]["id"], "APL-MBA-M4-13")
        self.assertEqual(data["goods"][0]["price"], Decimal("1099"))
        self.assertEqual(data["goods"][0]["price_rrc"], Decimal("1099"))
        self.assertEqual(sum(row["quantity"] > 0 for row in data["goods"]), 20)
        aio = next(row for row in data["goods"] if row["id"] == "APL-IMAC-M4-24")
        self.assertIn("Thunderbolt 4 x2", json.loads(aio["parameters"]["ports"]))
        screen = next(row for row in data["goods"] if row["id"] == "APL-PRO-DISPLAY-XDR2")
        self.assertEqual(screen["parameters"]["camera"], "null")

    def test_repeated_import_updates_same_offers(self):
        first = import_price(self.content, self.supplier)
        ids = dict(ProductInfo.objects.values_list("external_id", "pk"))
        second = import_price(self.content, self.supplier)
        self.assertEqual((first["created"], first["updated"]), (21, 0))
        self.assertEqual((second["created"], second["updated"]), (0, 21))
        self.assertEqual(dict(ProductInfo.objects.values_list("external_id", "pk")), ids)
        self.assertEqual((Shop.objects.count(), Category.objects.count(), Product.objects.count()), (1, 3, 21))

    def test_two_suppliers_share_products_but_have_separate_offers(self):
        other = User.objects.create_user("other@example.test", type=User.Type.SHOP)
        import_price(self.content, self.supplier)
        import_price(self.content, other)
        self.assertEqual(Category.objects.count(), 3)
        self.assertEqual(Product.objects.count(), 21)
        self.assertEqual(ProductInfo.objects.count(), 42)
        content = self.changed_content(lambda catalog: catalog["laptops"][0].update(price=1199))
        import_price(content, self.supplier)
        first = ProductInfo.objects.get(shop__user=self.supplier, external_id="APL-MBA-M4-13")
        second = ProductInfo.objects.get(shop__user=other, external_id="APL-MBA-M4-13")
        self.assertEqual((first.price, second.price), (Decimal("1199"), Decimal("1099")))

    def test_reimport_preserves_order_price_and_currency_snapshots(self):
        import_price(self.content, self.supplier)
        offer = ProductInfo.objects.get(external_id="APL-MBA-M4-13")
        buyer = User.objects.create_user("buyer@example.test")
        order = Order.objects.create(user=buyer)
        item = OrderItem.objects.create(
            order=order, product_info=offer, quantity=2, product_name=offer.product.name,
            price=offer.price, currency=offer.currency,
        )
        content = self.changed_content(lambda catalog: catalog["laptops"][0].update(price=1299))
        import_price(content, self.supplier)
        offer.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(offer.price, Decimal("1299"))
        self.assertEqual((item.price, item.currency, item.total_price), (Decimal("1099"), "USD", Decimal("2198")))

    def test_replace_zeroes_missing_offer_and_preserves_order_reference(self):
        import_price(self.content, self.supplier)
        offer = ProductInfo.objects.get(external_id="APL-MBA-M4-13")
        buyer = User.objects.create_user("buyer@example.test")
        order = Order.objects.create(user=buyer)
        item = OrderItem.objects.create(
            order=order, product_info=offer, quantity=1,
            product_name=offer.product.name, price=offer.price, currency=offer.currency,
        )
        def remove(catalog):
            catalog["laptops"].pop(0)
            catalog["metadata"]["total_items"] = 20
        report = import_price(self.changed_content(remove), self.supplier, replace=True)
        offer.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(report["disabled"], 1)
        self.assertEqual((offer.quantity, item.product_info_id), (0, offer.pk))

    def test_missing_offers_are_kept_when_replace_is_not_requested(self):
        import_price(self.content, self.supplier)
        def remove(catalog):
            catalog["laptops"].pop(0)
            catalog["metadata"]["total_items"] = 20
        report = import_price(self.changed_content(remove), self.supplier)
        self.assertEqual(report["disabled"], 0)
        self.assertEqual(ProductInfo.objects.get(external_id="APL-MBA-M4-13").quantity, 1)

    def test_stale_attributes_removed_only_from_updated_offer(self):
        import_price(self.content, self.supplier)
        content = self.changed_content(lambda catalog: catalog["all_in_ones"][0]["specs"].pop("ports"))
        import_price(content, self.supplier)
        changed = ProductInfo.objects.get(external_id="APL-IMAC-M4-24")
        other = ProductInfo.objects.get(external_id="APL-IMAC-M4PRO-32")
        self.assertFalse(changed.product_parameters.filter(parameter__name="ports").exists())
        self.assertTrue(other.product_parameters.filter(parameter__name="ports").exists())

    def test_supplier_state_is_preserved_on_import(self):
        import_price(self.content, self.supplier)
        Shop.objects.filter(user=self.supplier).update(state=False)
        import_price(self.content, self.supplier)
        self.assertFalse(Shop.objects.get(user=self.supplier).state)

    def test_invalid_catalog_does_not_write_partial_data(self):
        content = self.changed_content(lambda catalog: catalog["monitors"][-1].update(price="-1"))
        with self.assertRaises(PriceImportError):
            import_price(content, self.supplier)
        self.assertEqual((Shop.objects.count(), Category.objects.count(), Product.objects.count()), (0, 0, 0))

    def test_runtime_error_rolls_back_created_rows(self):
        with patch("backend.services.importer.ProductParameter.objects.update_or_create", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                import_price(self.content, self.supplier)
        self.assertEqual((Shop.objects.count(), Category.objects.count(), ProductInfo.objects.count()), (0, 0, 0))

    def test_buyer_cannot_import(self):
        buyer = User.objects.create_user("buyer@example.test")
        with self.assertRaises(PriceImportError):
            import_price(self.content, buyer)
        self.assertEqual(Shop.objects.count(), 0)

    def test_original_diploma_format_and_numeric_skus_still_work(self):
        raw = {"shop": "Старый формат", "categories": [{"id": 224, "name": "Смартфоны"}], "goods": [
            {"id": 42, "category": 224, "name": "Телефон", "price": 100,
             "price_rrc": 120, "quantity": 3, "parameters": {"Память": 256}},
        ]}
        report = import_price(yaml.safe_dump(raw, allow_unicode=True), self.supplier)
        offer = ProductInfo.objects.get()
        self.assertEqual((report["created"], offer.external_id, offer.currency), (1, "42", "RUB"))
        raw["goods"].append(deepcopy(raw["goods"][0]))
        raw["goods"][1]["id"] = "42"
        with self.assertRaises(PriceImportError):
            parse_price(yaml.safe_dump(raw, allow_unicode=True))

    def test_invalid_new_format_fields_are_rejected(self):
        cases = [("price", "12.345"), ("price", "NaN"), ("id", True), ("in_stock", "yes"), ("quantity", -1)]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                content = self.changed_content(lambda catalog: catalog["laptops"][0].update({field: value}))
                with self.assertRaises(PriceImportError):
                    parse_price(content)
        for currency in ("EUR", None, 123):
            with self.subTest(currency=currency):
                content = self.changed_content(lambda catalog: catalog["metadata"].update(default_currency=currency))
                with self.assertRaises(PriceImportError):
                    parse_price(content)

    def test_command_dry_run_does_not_create_owner_or_catalog(self):
        output = StringIO()
        call_command("import_catalog", str(self.path), dry_run=True, stdout=output)
        self.assertIn("товаров: 21", output.getvalue())
        self.assertEqual((User.objects.count(), Shop.objects.count()), (1, 0))

    def test_command_creates_supplier_once_with_unusable_password(self):
        for _ in range(2):
            call_command("import_catalog", str(self.path), supplier_email="store@example.test",
                         create_supplier=True, stdout=StringIO())
        supplier = User.objects.get(email="store@example.test")
        self.assertTrue(supplier.is_active)
        self.assertEqual(supplier.type, User.Type.SHOP)
        self.assertFalse(supplier.has_usable_password())
        self.assertEqual((User.objects.count(), Shop.objects.count(), ProductInfo.objects.count()), (2, 1, 21))

    def test_command_missing_account_fails_without_writes(self):
        with self.assertRaises(CommandError):
            call_command("import_catalog", str(self.path), supplier_email="missing@example.test", stdout=StringIO())
        self.assertEqual((User.objects.count(), Shop.objects.count()), (1, 0))

    def test_count_mismatch_and_unknown_sections_are_rejected(self):
        for change in (
            lambda catalog: catalog["metadata"].update(total_items=22),
            lambda catalog: catalog.update(phones=[]),
        ):
            with self.assertRaises(PriceImportError):
                parse_price(self.changed_content(change))
