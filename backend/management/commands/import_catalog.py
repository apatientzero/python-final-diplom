"""Запуск импорта локального YAML через manage.py."""

from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from backend.models import User
from backend.services.importer import PriceImportError, import_price, parse_price


class Command(BaseCommand):
    help = "Импортировать прайс поставщика или технологический Catalog.yaml."
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path, help="Путь к YAML-файлу.")
        parser.add_argument("--supplier-email", help="Email владельца магазина.")
        parser.add_argument("--shop-name", help="Название магазина, например Parviz Store.")
        parser.add_argument("--demo-quantity", type=int, default=1,
                            help="Учебный остаток при in_stock=true, если quantity отсутствует.")
        parser.add_argument("--create-supplier", action="store_true",
                            help="Создать отсутствующего поставщика с неустановленным паролем.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Проверить файл и показать результат без записи в базу.")
        parser.add_argument("--replace", action="store_true",
                            help="Обнулить остатки предложений, отсутствующих в этом файле.")

    def handle(self, *args, **options):
        try:
            content = options["path"].read_bytes()
        except OSError as exc:
            raise CommandError(f"Не удалось прочитать файл: {exc}") from exc
        kwargs = {"shop_name": options["shop_name"], "demo_quantity": options["demo_quantity"]}
        try:
            data = parse_price(content, **kwargs)
        except PriceImportError as exc:
            raise CommandError(str(exc)) from exc

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Прайс прошёл проверку. Запись в базу не выполнялась."))
            self.stdout.write(f"Магазин: {data['shop']}; валюта: {data['currency']}")
            self.stdout.write(f"Категорий: {len(data['categories'])}; товаров: {len(data['goods'])}")
            self.stdout.write(f"Есть в наличии: {sum(item['quantity'] > 0 for item in data['goods'])}")
            if data.get("demo_stock"):
                self.stdout.write(f"Используются условные учебные остатки: true → {options['demo_quantity']}, false → 0.")
            return

        email = options["supplier_email"]
        if not email:
            raise CommandError("Укажите --supplier-email или используйте --dry-run.")
        email = User.objects.normalize_email(email.strip())
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError("Некорректный --supplier-email.") from exc

        try:
            with transaction.atomic():
                supplier = User.objects.filter(email=email).first()
                created_supplier = supplier is None
                if created_supplier:
                    if not options["create_supplier"]:
                        raise CommandError("Поставщик не найден. Для создания добавьте --create-supplier.")
                    supplier = User.objects.create_user(email=email, type=User.Type.SHOP, is_active=True)
                result = import_price(content, supplier, replace=options["replace"], **kwargs)
        except (PriceImportError, IntegrityError, User.DoesNotExist) as exc:
            raise CommandError(f"Импорт отменён: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Каталог импортирован."))
        self.stdout.write(f"Магазин: {result['shop']}; валюта: {result['currency']}")
        self.stdout.write(f"Категорий: {result['categories']}; товаров обработано: {result['products']}")
        self.stdout.write(f"Создано предложений: {result['created']}; обновлено: {result['updated']}")
        self.stdout.write(f"Обнулено отсутствующих предложений: {result['disabled']}")
        if result["demo_stock"]:
            self.stdout.write(f"Остатки учебные: true → {options['demo_quantity']}, false → 0.")
        if created_supplier:
            self.stdout.write(f"Создан поставщик {email} с type=shop; пароль для входа можно задать командой:")
            self.stdout.write(f"python manage.py changepassword {email}")
