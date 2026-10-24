"""Чтение двух форматов прайса и атомарное обновление каталога поставщика."""

import json
from decimal import Decimal, InvalidOperation

import yaml
from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator
from django.db import transaction

from backend.models import (
    Category,
    Currency,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
    User,
)


class PriceImportError(ValueError):
    """Ошибка структуры прайса или попытка импорта от имени покупателя."""


def parse_price(content, *, shop_name=None, demo_quantity=1):
    """Разбирает обычный прайс или Catalog.yaml и возвращает проверенные данные."""
    if not isinstance(content, (str, bytes)):
        raise PriceImportError("Передайте содержимое YAML-файла строкой или байтами.")
    try:
        data = yaml.safe_load(content)
    except (yaml.YAMLError, UnicodeError, RecursionError) as exc:
        raise PriceImportError("Не удалось разобрать YAML-файл.") from exc

    if not isinstance(data, dict):
        raise PriceImportError("Прайс должен содержать словарь.")
    if "catalog" in data:
        data = _adapt_tech_catalog(data["catalog"], shop_name, demo_quantity)
    elif shop_name is not None:
        data["shop"] = shop_name

    name = data.get("shop")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise PriceImportError("Поле 'shop' должно содержать название от 1 до 100 символов.")
    data["shop"] = name.strip()

    currency = data.get("currency", Currency.RUB)
    if not isinstance(currency, str) or currency.upper() not in Currency.values:
        raise PriceImportError("Поддерживаемые валюты: RUB, USD.")
    data["currency"] = currency.upper()

    for field in ("categories", "goods"):
        if not isinstance(data.get(field), list):
            raise PriceImportError(f"Раздел '{field}' должен быть списком.")
    _validate_categories(data["categories"])
    _validate_goods(data["goods"], data["categories"])
    return data


def _validate_categories(categories):
    """Проверяет внешние идентификаторы и названия категорий."""
    category_ids = set()
    for number, category in enumerate(categories, start=1):
        if not isinstance(category, dict):
            raise PriceImportError(f"Категория №{number} должна быть словарём.")
        category_id = category.get("id")
        if type(category_id) is not int or category_id < 0:
            raise PriceImportError(
                f"Категория №{number}: id должен быть целым неотрицательным числом."
            )
        if category_id in category_ids:
            raise PriceImportError(f"Категория №{number}: повторяется id={category_id}.")
        category_ids.add(category_id)
        name = category.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise PriceImportError(
                f"Категория №{number}: название должно содержать от 1 до 100 символов."
            )
        category["name"] = name.strip()


def _validate_goods(goods, categories):
    """Проверяет товары, приводит артикулы к строкам, а цены — к Decimal."""
    category_ids = {category["id"] for category in categories}
    external_ids = set()
    money_validator = DecimalValidator(max_digits=12, decimal_places=2)
    for number, item in enumerate(goods, start=1):
        label = f"Товар №{number}"
        if not isinstance(item, dict):
            raise PriceImportError(f"{label} должен быть словарём.")

        external_id = item.get("id")
        if type(external_id) is int and external_id >= 0:
            external_id = str(external_id)
        if not isinstance(external_id, str) or not external_id.strip():
            raise PriceImportError(f"{label}: id должен быть непустым артикулом.")
        external_id = external_id.strip()
        if len(external_id) > 100:
            raise PriceImportError(f"{label}: id длиннее 100 символов.")
        if external_id in external_ids:
            raise PriceImportError(f"{label}: повторяется id={external_id}.")
        external_ids.add(external_id)
        item["id"] = external_id

        quantity = item.get("quantity")
        if type(quantity) is not int or not 0 <= quantity <= 2**31 - 1:
            raise PriceImportError(f"{label}: quantity должно быть целым числом от 0 до 2147483647.")
        category_id = item.get("category")
        if type(category_id) is not int or category_id not in category_ids:
            raise PriceImportError(f"{label}: category должна ссылаться на категорию из прайса.")

        for field, maximum, required in (("name", 255, True), ("model", 100, False)):
            value = item.get(field, "")
            if not isinstance(value, str) or len(value.strip()) > maximum:
                raise PriceImportError(f"{label}: {field} должно быть строкой до {maximum} символов.")
            value = value.strip()
            if required and not value:
                raise PriceImportError(f"{label}: {field} не должно быть пустым.")
            item[field] = value

        for field in ("price", "price_rrc"):
            try:
                amount = Decimal(str(item.get(field)))
                if not amount.is_finite() or amount < 0:
                    raise ValidationError("Недопустимая цена.")
                money_validator(amount)
            except (InvalidOperation, ValidationError) as exc:
                raise PriceImportError(
                    f"{label}: неверное значение '{field}'. "
                    "Нужна неотрицательная цена: до 12 цифр всего и до 2 после запятой."
                ) from exc
            item[field] = amount

        parameters = item.get("parameters", {})
        if not isinstance(parameters, dict):
            raise PriceImportError(f"{label}: parameters должно быть словарём.")
        normalized = {}
        for key, value in parameters.items():
            if not isinstance(key, str) or not key.strip() or len(key.strip()) > 100:
                raise PriceImportError(f"{label}: название характеристики должно содержать от 1 до 100 символов.")
            key = key.strip()
            if key in normalized:
                raise PriceImportError(f"{label}: повторяется характеристика '{key}'.")
            if not isinstance(value, (str, int, float, bool)):
                raise PriceImportError(f"{label}: характеристика '{key}' должна содержать строку, число или bool.")
            normalized[key] = str(value)
        item["parameters"] = normalized


def _parameter_text(value):
    """Сохраняет списки портов, теги и null как читаемый JSON в TextField."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PriceImportError("Недопустимое значение характеристики в Catalog.yaml.") from exc


def _adapt_tech_catalog(catalog, shop_name, demo_quantity):
    """Преобразует приложенный каталог, сохраняя исходные SKU и валюту."""
    if not isinstance(catalog, dict):
        raise PriceImportError("Раздел catalog должен быть словарём.")
    if type(demo_quantity) is not int or not 0 <= demo_quantity <= 2**31 - 1:
        raise PriceImportError("Учебный остаток должен быть целым числом от 0 до 2147483647.")
    metadata = catalog.get("metadata", {})
    if not isinstance(metadata, dict):
        raise PriceImportError("Раздел metadata должен быть словарём.")
    groups = (("laptops", "Ноутбуки"), ("all_in_ones", "Моноблоки"), ("monitors", "Мониторы"))
    unknown = set(catalog) - {"metadata", *(key for key, _ in groups)}
    if unknown:
        raise PriceImportError("Неизвестные разделы каталога: " + ", ".join(map(str, unknown)))
    result = {
        "shop": shop_name if shop_name is not None else "Parviz Store",
        "currency": metadata.get("default_currency", "USD"),
        "categories": [],
        "goods": [],
        "demo_stock": False,
    }
    for category_id, (group, category_name) in enumerate(groups, start=1):
        rows = catalog.get(group)
        if not isinstance(rows, list):
            raise PriceImportError(f"Раздел '{group}' должен быть списком.")
        result["categories"].append({"id": category_id, "name": category_name})
        for row in rows:
            if not isinstance(row, dict):
                raise PriceImportError(f"Товар в разделе '{group}' должен быть словарём.")
            brand, model = row.get("brand"), row.get("model")
            if not isinstance(brand, str) or not brand.strip() or not isinstance(model, str) or not model.strip():
                raise PriceImportError(f"Для товара в '{group}' обязательны brand и model.")
            brand, model = brand.strip(), model.strip()
            name = model if model.casefold().startswith(brand.casefold() + " ") else f"{brand} {model}"
            in_stock = row.get("in_stock")
            if type(in_stock) is not bool:
                raise PriceImportError(f"{name}: in_stock должно быть true или false.")
            is_demo = "quantity" not in row
            quantity = row.get("quantity", demo_quantity if in_stock else 0)
            if not in_stock and quantity != 0:
                raise PriceImportError(f"{name}: при in_stock=false quantity должно быть равно 0.")
            result["demo_stock"] = result["demo_stock"] or is_demo
            specs = row.get("specs", {})
            if not isinstance(specs, dict):
                raise PriceImportError(f"{name}: specs должно быть словарём.")
            parameters = {key: _parameter_text(value) for key, value in specs.items()}
            # Префикс отделяет сведения о товаре от одноимённых технических specs.
            for field in ("brand", "category", "os", "release_year", "tags", "in_stock"):
                if field in row:
                    parameters[f"catalog.{field}"] = _parameter_text(row[field])
            parameters["catalog.demo_stock"] = "true" if is_demo else "false"
            result["goods"].append({
                "id": row.get("id"),
                "category": category_id,
                "name": name,
                "model": model,
                "price": row.get("price"),
                "price_rrc": row.get("price_rrc", row.get("price")),
                "quantity": quantity,
                "parameters": parameters,
            })
    expected = metadata.get("total_items")
    if expected is not None and (type(expected) is not int or expected != len(result["goods"])):
        raise PriceImportError("metadata.total_items не совпадает с фактическим числом товаров.")
    return result


def import_price(content, supplier, *, shop_name=None, demo_quantity=1, replace=False):
    """Обновляет прайс целиком в одной транзакции. Цены заказов остаются снимками."""
    data = parse_price(content, shop_name=shop_name, demo_quantity=demo_quantity)
    if getattr(supplier, "pk", None) is None:
        raise PriceImportError("Сначала сохраните учётную запись поставщика.")
    with transaction.atomic():
        # Сериализуем импорты одного поставщика, в том числе до создания Shop.
        owner = User.objects.select_for_update().get(pk=supplier.pk)
        if owner.type != User.Type.SHOP:
            raise PriceImportError("Импорт разрешён только поставщикам с type='shop'.")
        shop, _ = Shop.objects.update_or_create(user=owner, defaults={"name": data["shop"]})
        categories = {}
        for category in data["categories"]:
            obj, _ = Category.objects.get_or_create(name=category["name"])
            categories[category["id"]] = obj
        if replace:
            shop.categories.set(categories.values())
        else:
            shop.categories.add(*categories.values())

        created_count, updated_count = 0, 0
        external_ids = []
        for item in data["goods"]:
            product, _ = Product.objects.get_or_create(
                name=item["name"], category=categories[item["category"]]
            )
            offer, created = ProductInfo.objects.update_or_create(
                shop=shop,
                external_id=item["id"],
                defaults={
                    "product": product,
                    "model": item["model"],
                    "quantity": item["quantity"],
                    "price": item["price"],
                    "price_rrc": item["price_rrc"],
                    "currency": data["currency"],
                },
            )
            external_ids.append(item["id"])
            created_count += int(created)
            updated_count += int(not created)
            parameter_ids = []
            for name, value in item["parameters"].items():
                parameter, _ = Parameter.objects.get_or_create(name=name)
                parameter_ids.append(parameter.pk)
                ProductParameter.objects.update_or_create(
                    product_info=offer, parameter=parameter, defaults={"value": value}
                )
            offer.product_parameters.exclude(parameter_id__in=parameter_ids).delete()

        disabled = 0
        if replace:
            # Отсутствующий товар получает нулевой остаток; исторические ссылки сохраняются.
            disabled = shop.product_infos.exclude(external_id__in=external_ids).exclude(quantity=0).update(quantity=0)
        return {
            "shop_id": shop.pk,
            "shop": shop.name,
            "currency": data["currency"],
            "categories": len(categories),
            "products": len(data["goods"]),
            "created": created_count,
            "updated": updated_count,
            "disabled": disabled,
            "demo_stock": data.get("demo_stock", False),
        }
