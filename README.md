# Parviz Store — backend автоматизации закупок

Дипломный проект курса «Python-разработчик: расширенный курс» Нетологии.
Сервис позволяет покупателю оформить один заказ с товарами нескольких
поставщиков. Взаимодействие с приложением выполняется через REST API.

## Возможности

- Регистрация с подтверждением email, вход и восстановление пароля.
- Каталог с характеристиками, поиском, фильтрами и пагинацией.
- Корзина, адреса доставки, оформление и история заказов.
- Импорт YAML-прайсов через API поставщика и команду Django.
- Управление приёмом заказов и просмотр своих позиций заказов поставщиком.
- Изменение статусов администратором и возврат остатков при отмене заказа.
- Подтверждение заказа покупателю и текстовая накладная администратору.
- 40 автоматических тестов импорта, аккаунтов и заказов.

Инструкция рассчитана на локальный запуск. Сейчас письма выводятся в терминал
с сервером. Для доставки на реальные адреса требуется настройка SMTP
в `orders/settings.py`.

## Технологии

Проект проверен с Python 3.12, Django 5.2.18, Django REST Framework 3.18.3
и PostgreSQL 17. Используются PyYAML, Psycopg 3, python-dotenv
и django-rest-passwordreset. Зависимости находятся в `requirements.txt`.

## Установка и запуск

### 1. Код и окружение

```bash
git clone https://github.com/apatientzero/python-final-diplom.git
cd python-final-diplom
```

На macOS с Homebrew:

```bash
brew install python@3.12 postgresql@17
brew services start postgresql@17
"$(brew --prefix python@3.12)/bin/python3.12" -m venv .venv
```

На Linux с установленными Python 3.12 и PostgreSQL:

```bash
python3.12 -m venv .venv
```

Далее на обеих системах:

```bash
source .venv/bin/activate
python --version
command -v python
python -m pip install -r requirements.txt
python -m pip check
```

`python` должен указывать на `.venv` внутри `python-final-diplom`.
В каждом новом терминале переходите в папку проекта и активируйте это окружение.

### 2. PostgreSQL

Подключитесь под ролью с правами создания ролей и баз.
На macOS с Homebrew обычно используется:

```bash
"$(brew --prefix postgresql@17)/bin/psql" -d postgres
```

На Linux с системным пользователем `postgres`:

```bash
sudo -u postgres psql
```

В консоли `psql` выполните:

```sql
CREATE ROLE procurement_user WITH LOGIN;
\password procurement_user
CREATE DATABASE procurement_db OWNER procurement_user;
ALTER ROLE procurement_user CREATEDB;
\q
```

`\password` запросит пароль роли. Право `CREATEDB` нужно для тестовой базы.
Для уже существующей базы используйте её параметры в следующем шаге.

### 3. Переменные окружения

```bash
cp .env.example .env
```

Откройте `.env` в редакторе и заполните:

```dotenv
DB_NAME=procurement_db
DB_USER=procurement_user
DB_PASSWORD='your-local-database-password'
DB_HOST=127.0.0.1
DB_PORT=5432
ORDER_ADMIN_EMAIL=admin@example.test
```

Замените `DB_PASSWORD` паролем, заданным через `\password`.
`ORDER_ADMIN_EMAIL` определяет получателя накладной. `.env` исключён из Git;
в репозиторий добавляется `.env.example` с учебными значениями.

### 4. Миграции и каталог

```bash
python manage.py check
python manage.py migrate
python manage.py import_catalog data/Catalog.yaml --dry-run
python manage.py import_catalog data/Catalog.yaml --supplier-email supplier@parviz-store.test --create-supplier
python manage.py changepassword supplier@parviz-store.test
```

Импорт создаёт активного поставщика с ролью `shop`. `changepassword` задаёт
ему пароль для входа через API. Публичная регистрация создаёт покупателей.

Учебный каталог содержит 21 предложение, 3 категории и цены в USD.
При отсутствии точного остатка `in_stock: true` даёт условный остаток 1,
`false` — 0. Параметр `--demo-quantity 10` задаёт другой учебный остаток.
Повторный импорт обновляет предложения по паре магазин/SKU.
`--replace` обнуляет остатки предложений, отсутствующих в новом прайсе.
Подробности: [импорт каталога](docs/catalog-import.md).

### 5. Администратор и сервер

```bash
python manage.py createsuperuser
python manage.py runserver
```

Каталог: <http://127.0.0.1:8000/api/v1/products>.
Администратор входит через API с email и паролем, заданными при создании.

## Тесты

```bash
python manage.py test backend --settings=orders.test_settings -v 2
```

Ожидаемый результат: `Ran 40 tests` и `OK`.
При `DB_NAME=procurement_db` Django создаёт и удаляет `test_procurement_db`.
Тесты используют почту в памяти и отдельный тестовый кэш.

Только тесты импорта можно запустить на SQLite в памяти:

```bash
python manage.py test backend.test_catalog_import --settings=orders.catalog_test_settings
```

## API

Базовый адрес: `http://127.0.0.1:8000/api/v1`.
Пути используются без завершающего `/`. Защищённые запросы требуют заголовок
`Authorization: Token <токен_из_ответа_на_вход>`.

| Метод | Путь после `/api/v1` | Доступ | Назначение |
| --- | --- | --- | --- |
| POST | `/user/register` | Публичный | Регистрация покупателя |
| POST | `/user/register/confirm` | Публичный | Подтверждение email |
| POST | `/user/login` | Публичный | Получение API-токена |
| POST | `/user/password_reset` | Публичный | Запрос письма восстановления |
| POST | `/user/password_reset/confirm` | Публичный | Установка нового пароля |
| GET | `/products` | Публичный | Каталог |
| GET | `/products/{id}` | Публичный | Детали предложения поставщика |
| GET, POST | `/basket` | Покупатель | Просмотр корзины, добавление товара |
| PATCH, DELETE | `/basket/items/{id}` | Покупатель | Изменение количества, удаление позиции |
| GET, POST | `/user/contact` | Покупатель | Список адресов, создание адреса |
| GET, PATCH, DELETE | `/user/contact/{id}` | Покупатель | Просмотр, изменение, удаление адреса |
| GET, POST | `/order` | Покупатель | История, оформление заказа |
| GET | `/order/{id}` | Покупатель | Детали своего оформленного заказа |
| GET, POST | `/partner/state` | Поставщик | Состояние приёма заказов |
| POST | `/partner/update` | Поставщик | Загрузка YAML-прайса |
| GET | `/partner/orders` | Поставщик | Заказы с собственными позициями и суммами |
| PATCH | `/admin/orders/{id}/state` | Активный `is_staff` | Изменение статуса заказа |

Каталог, история покупателя и заказы поставщика возвращают страницы по 20 записей
с ключами `count`, `next`, `previous`, `results`. Следующая страница — `?page=2`.
Фильтры каталога: `shop`, `category`, `search`. Они применяются совместно;
поиск по названию не учитывает регистр. Предложения с нулевым остатком видны.
Отключение магазина или аккаунта поставщика скрывает его предложения из каталога.

## Пример работы покупателя

Откройте второй терминал. Примеры используют учебный email `buyer@example.test`.
Токены подтверждения и восстановления берутся из писем в терминале с сервером.
Значения переменных с токенами и ID заменяйте в терминале данными из ответов API.

### Регистрация, подтверждение и вход

```bash
API_BASE="http://127.0.0.1:8000/api/v1"
curl -i -X POST "$API_BASE/user/register" \
  -H 'Content-Type: application/json' \
  -d '{"email":"buyer@example.test","password":"Study!Procure_2026","first_name":"Иван","last_name":"Петров","company":"Учебный магазин","position":"Закупщик"}'

CONFIRM_TOKEN="токен_из_письма"
curl -i -X POST "$API_BASE/user/register/confirm" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"buyer@example.test\",\"token\":\"$CONFIRM_TOKEN\"}"

curl -i -X POST "$API_BASE/user/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"buyer@example.test","password":"Study!Procure_2026"}'
```

Регистрация возвращает `201` и `{"Status":true}`. Пользователь неактивен
до подтверждения email. Подтверждение возвращает `200` и `{"Status":true}`.
Токен подтверждения действует 24 часа и используется один раз.
Вход возвращает `200` и `{"Status":true,"Token":"..."}`.
При повторном входе возвращается тот же API-токен.

### Каталог, корзина и адрес

```bash
API_TOKEN="значение_Token_из_ответа_на_вход"
curl -i "$API_BASE/products"
curl -i "$API_BASE/products?search=Apple"

OFFER_ID=1
curl -i -X POST "$API_BASE/basket" \
  -H "Authorization: Token $API_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"product_info\":$OFFER_ID,\"quantity\":1}"
curl -i "$API_BASE/basket" -H "Authorization: Token $API_TOKEN"

curl -i -X POST "$API_BASE/user/contact" \
  -H "Authorization: Token $API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"city":"Москва","street":"Учебная","house":"10","apartment":"25","phone":"+79991234567"}'
```

В `OFFER_ID` укажите доступный `results[].id` из каталога: это ID предложения,
а не поле `product` и не SKU. Для товара другого поставщика повторите POST
с ID его предложения. Первое добавление возвращает `201`, повторное — `200`
и увеличивает количество. При обновлении прайса цена, валюта и название,
записанные в позицию, остаются прежними.

GET корзины возвращает `Basket`, `Items`, `Totals`. Для нового аккаунта
`Basket` равен `null`; при просмотре корзина не создаётся.
PATCH позиции принимает `{"quantity":1}` и устанавливает новое количество.
DELETE удаляет позицию и возвращает `204`.

При создании адреса обязательны `city`, `street`, `house`, `phone`.
Дополнительно принимаются `structure`, `building`, `apartment`.
Телефон — 7–15 цифр и необязательный `+` в начале.
Ответ создания — `201` и адрес с полем `id`.

### Оформление и история

В `BASKET_ID` подставьте `Basket` из GET корзины, в `CONTACT_ID` — `id` адреса:

```bash
BASKET_ID=1
CONTACT_ID=1
curl -i -X POST "$API_BASE/order" \
  -H "Authorization: Token $API_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"order\":$BASKET_ID,\"contact\":$CONTACT_ID}"
curl -i "$API_BASE/order" -H "Authorization: Token $API_TOKEN"
curl -i "$API_BASE/order/$BASKET_ID" -H "Authorization: Token $API_TOKEN"
```

Ответ оформления — `200` и `{"Status":true,"Order":1,"State":"new"}`,
где `Order` содержит фактический ID. Корзина становится заказом с тем же ID.
Все остатки проверяются и списываются в одной транзакции.
Добавление в корзину само по себе товары не резервирует.
Повторное оформление того же заказа отклоняется.
Итоги подсчитываются отдельно по валютам.

При оформлении сохраняется копия адреса в `delivery_address`.
Изменение или удаление адреса сохраняет эту копию.
После фиксации заказа формируются подтверждение покупателю и накладная
на `ORDER_ADMIN_EMAIL`. Накладная — текст письма с позициями, поставщиками,
артикулами и суммами. Отправка синхронная; ошибки уведомлений логируются,
оформленный заказ сохраняется.

## Восстановление пароля

POST `/user/password_reset` принимает `{"email":"buyer@example.test"}`.
POST `/user/password_reset/confirm` принимает
`{"token":"токен_из_письма","password":"New!Procure_2026"}`.
Успешные ответы — `200` и `{"status":"OK"}`. Токен действует 1 час.
После смены пароля прежний API-токен отзывается; войдите с новым паролем.
Для неизвестного или неактивного аккаунта запрос письма возвращает тот же ответ.
Лимиты по IP: запрос письма — 3 в день, подтверждение — 10 в час.

## Поставщик и администратор

Поставщик входит через `/user/login` с email, использованным при импорте,
и паролем, заданным через `changepassword`. Сохраните его `Token`
в переменную `SUPPLIER_TOKEN` в терминале. Запрос загрузки выполняется
из папки проекта, чтобы был доступен `data/Catalog.yaml`:

```bash
SUPPLIER_TOKEN="API-токен_поставщика"
curl -i -X POST "$API_BASE/partner/update" \
  -H "Authorization: Token $SUPPLIER_TOKEN" \
  -F 'file=@data/Catalog.yaml' -F 'replace=false' -F 'demo_quantity=1'
```

Импорт принимает multipart-файл до 2 МиБ и параметры `replace`, `demo_quantity`,
необязательный `shop_name`. Обновление сохраняет флаг приёма заказов.
POST `/partner/state` принимает `{"state":false}` или `{"state":true}`.
Для поставщика без магазина GET состояния и списка заказов возвращает `404`.

Поставщик получает только собственные позиции общего заказа и суммы по ним.
Покупатели получают только свои корзины, адреса и заказы.
История доступна и после отключения приёма заказов магазином.

Администратор получает API-токен через тот же вход. PATCH
`/admin/orders/{id}/state` принимает, например, `{"state":"confirmed"}`.

| Текущий статус | Допустимый следующий статус |
| --- | --- |
| `new` | `confirmed`, `canceled` |
| `confirmed` | `assembled`, `canceled` |
| `assembled` | `sent`, `canceled` |
| `sent` | `delivered` |
| `delivered`, `canceled` | Конечные статусы |

Повтор того же статуса возвращает `200` с `Changed: false`.
При отмене остатки возвращаются один раз; при ошибке откатываются и статус,
и возврат товаров. Покупатель видит новый статус в истории.

Основные ошибки: `400` — некорректные данные или недопустимое действие,
`401` — отсутствует действующий API-токен, `403` — недостаточно прав,
`404` — объект отсутствует или недоступен пользователю, `429` — превышен лимит.
Неверный или просроченный токен восстановления возвращает `404`.
Сбой отправки письма регистрации или восстановления возвращает `503`
и откатывает создание пользователя или нового токена соответственно.

## Материалы и использование AI

- `orders/` — настройки проекта; `backend/` — модели, API, сервисы и тесты.
- `data/Catalog.yaml` — учебный каталог Parviz Store.
- [Импорт каталога](docs/catalog-import.md) — форматы и параметры загрузки.
- [Исходное задание](DIPLOMA_TASK.md) и `reference/` — материалы Нетологии.

ChatGPT применялся для разбора требований, объяснения Django ORM,
подготовки и проверки кода, разработки тестов и документации.
Работа велась поэтапно с разбором изменений, локальными проверками
и регулярными коммитами в Git.