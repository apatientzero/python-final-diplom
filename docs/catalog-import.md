# Импорт каталога Parviz Store

Команда поддерживает `data/Catalog.yaml` с разделами `catalog.laptops`,
`catalog.all_in_ones`, `catalog.monitors` и прежний формат `shop/categories/goods`.
Исходный файл содержит 21 позицию: 8 ноутбуков, 5 моноблоков и 8 мониторов.
Имена, комплектации, цены и годы выпуска загружаются из учебного файла;
импорт не подтверждает их соответствие реальным предложениям производителей.

## Подготовка

Работать из папки проекта, где находится `manage.py`, с активированной `.venv`.
PostgreSQL должен быть запущен, а `.env` — содержать параметры подключения.

```bash
python manage.py check
python manage.py migrate
python manage.py import_catalog data/Catalog.yaml --dry-run
```

В данном файле цены выражены в **USD**. Они сохраняются без пересчёта.
`ProductInfo.currency` хранит валюту предложения, а `OrderItem.currency` — валюту
сохранённой цены заказа. У существующих записей после миграции остаётся `RUB`.
При создании позиции заказа необходимо копировать `price`, `product_name`
и `currency` из предложения; складывать в один итог можно суммы одной валюты.

В исходнике нет точных остатков и рекомендованной цены. Для учебной загрузки:

- `in_stock: true` даёт условный остаток **1**, `false` — **0**;
- при наличии явного `quantity` используется он;
- `--demo-quantity 10` позволяет выбрать другой условный остаток;
- `price_rrc` при отсутствии копируется из `price`;
- `catalog.demo_stock` в характеристиках отмечает условный остаток.

Исходные буквенные SKU сохраняются в строковом `external_id`. Старые числовые
коды переводятся в строки. Списки портов и тегов сохраняются как JSON-строки,
`null` — как строка `null`. Технические характеристики остаются отдельными
записями `Parameter` / `ProductParameter`.

## Первая загрузка

```bash
python manage.py import_catalog data/Catalog.yaml --supplier-email supplier@parviz-store.test --create-supplier
```

Команда создаёт отсутствующего поставщика с `type=shop`, `is_active=True`
и неустановленным паролем, затем связывает с ним магазин `Parviz Store`.
Для последующей авторизации пароль задаётся через терминал:

```bash
python manage.py changepassword supplier@parviz-store.test
```

При повторной загрузке того же файла ожидается **0 созданных и 21 обновлённое
предложение**. По умолчанию предложения, которых нет в файле, сохраняют остатки.
Для полной синхронизации прайса применяется `--replace`: отсутствующим позициям
проставляется остаток 0, а ссылки из заказов сохраняются.

```bash
python manage.py import_catalog data/Catalog.yaml --supplier-email supplier@parviz-store.test --replace
```

## Как устроен код

1. `parse_price()` читает YAML, при необходимости преобразует новый формат
   в общий и проверяет все записи до начала импорта.
2. `import_price()` проверяет роль поставщика и открывает `transaction.atomic()`.
3. Категория определяется по названию, товар — по паре название/категория,
   предложение — по паре поставщик/SKU. Ограничения базы обеспечивают уникальность.
4. `update_or_create()` обновляет цену, валюту, остаток и характеристики.
5. При ошибке все записи текущего импорта откатываются. Цены в `OrderItem`
   не меняются при обновлении прайса.

Миграция `0009_catalog_skus_and_currency` добавляет валюту к предложениям
и позициям заказов, меняет тип `external_id` на строковый и обеспечивает
уникальность названий категорий и пар название/категория для товаров.
Она рассчитана на состояние проекта после миграции `0008_orderitem`.

## Тесты

```bash
python manage.py test backend.test_catalog_import --settings=orders.catalog_test_settings
```

Эти настройки используют отдельную SQLite в памяти. Рабочая PostgreSQL
не участвует в тестах, дополнительные права на создание тестовой БД не нужны.
Проверяются повторная загрузка, два поставщика, обновление характеристик,
валюта и цены заказов, откат при ошибках, dry-run и старый формат прайса.

## Сохранение в Git

После успешного импорта:

```bash
git add backend/models.py backend/services backend/management backend/migrations/0009_catalog_skus_and_currency.py backend/test_catalog_import.py orders/catalog_test_settings.py data/Catalog.yaml docs/catalog-import.md
git diff --cached --stat
git commit -m "Add technology catalog import with SKU and currency support"
git push origin master
```
