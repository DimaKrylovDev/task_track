# Task Tracker API

Командный трекер задач на FastAPI и PostgreSQL. Проект подготовлен как исходная
система для экспериментов с индексами, планами запросов, партиционированием,
репликацией и шардированием. Фронтенд не входит в проект.

## Запуск

Требуется Docker с Compose. Запуск приложения и PostgreSQL:

```bash
docker compose up --build
```

Миграции применяются сервисом `db-migrate` автоматически. После запуска доступны:

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/health`

Для локального запуска без Docker скопируйте `.env.example` в `.env`, замените
хост БД на `localhost`, укажите адрес собственной PostgreSQL, установите зависимости
и выполните:

```bash
python -m pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

## Архитектура

```text
HTTP / FastAPI router
        ↓
Application service (бизнес-правила)
        ↓
Repository + Unit of Work (SQL и транзакция)
        ↓
PostgreSQL
```

- `app/api` — HTTP-маршруты, зависимости и Pydantic-схемы.
- `app/services` — сценарии приложения и проверки прав.
- `app/repositories` — запросы SQLAlchemy и Unit of Work.
- `app/db` — ORM-модели и подключение к PostgreSQL.
- `app/domain` — статусы, приоритеты и роли предметной области.
- `alembic` — единственный способ изменения схемы БД.

Роутеры не получают SQLAlchemy session и не обращаются к БД напрямую. Один вызов
сервиса открывает один Unit of Work и завершается одной транзакцией.

## Схема БД

```mermaid
erDiagram
    USERS ||--o{ AUTH_SESSIONS : owns
    USERS ||--o{ PROJECTS : owns
    USERS ||--o{ PROJECT_MEMBERS : participates
    PROJECTS ||--o{ PROJECT_MEMBERS : contains
    PROJECTS ||--o{ TASKS : contains
    USERS ||--o{ TASKS : creates
    USERS ||--o{ TASKS : assigned
    PROJECTS ||--o{ TAGS : defines
    TASKS ||--o{ TASK_TAGS : classified
    TAGS ||--o{ TASK_TAGS : applies
    TASKS ||--o{ COMMENTS : receives
    USERS ||--o{ COMMENTS : writes
```

Владелец проекта всегда присутствует в `project_members` с ролью `OWNER`.
Остальные участники имеют роль `MEMBER`. Задачу нельзя назначить пользователю, не
входящему в проект, и к задаче нельзя прикрепить тег другого проекта. При удалении
участника из проекта назначенные ему задачи автоматически становятся неназначенными.

## Авторизация

1. `POST /api/auth/register` или `POST /api/auth/login` возвращает access и refresh JWT.
2. Access JWT передаётся как `Authorization: Bearer <token>`.
3. `POST /api/auth/refresh` ротирует refresh-токен: использованный токен отзывается.
4. `POST /api/auth/logout` отзывает текущую refresh-сессию.

В production обязательно задайте длинный случайный `JWT_SECRET`.

## Основные endpoint'ы

| Метод | URL | Назначение |
|---|---|---|
| POST | `/api/auth/register` | Регистрация и выдача токенов |
| POST | `/api/auth/login` | Вход |
| POST | `/api/auth/refresh` | Ротация refresh JWT |
| GET, PUT | `/api/users/me` | Профиль |
| GET, POST | `/api/projects` | Список и создание проектов |
| GET, PUT, DELETE | `/api/projects/{id}` | CRUD проекта |
| GET, POST | `/api/projects/{id}/members` | Участники проекта |
| GET, POST | `/api/tasks` | Список и создание задач |
| GET, PUT, DELETE | `/api/tasks/{id}` | CRUD задачи |
| GET | `/api/projects/{id}/tasks` | Задачи конкретного проекта |
| GET | `/api/projects/{id}/stats` | Агрегированная статистика |
| GET, POST | `/api/tags` | Список и создание тегов |
| GET, PUT, DELETE | `/api/tags/{id}` | CRUD тега |
| GET, POST | `/api/tasks/{id}/comments` | Комментарии задачи |
| GET, PUT, DELETE | `/api/comments/{id}` | CRUD комментария |

`GET /api/tasks` и связанный endpoint проекта принимают `page`, `page_size`,
`project_id`, `status`, `priority`, `assignee_id`, `tag_id`, `created_from`,
`created_to`, `search` и `sort`. Разрешённая сортировка: `created_at`,
`-created_at`, `due_at`, `-due_at`.

## Основная сущность для масштабирования

Основная сущность: **`tasks`**.

Задачи естественно накапливаются, имеют поле `created_at`, внешние ключи на проект,
автора и исполнителя, many-to-many связь с тегами. Список задач использует поиск,
диапазон дат, фильтры и сортировку — это делает таблицу подходящей для последующего
анализа индексов, партиционирования по времени и шардирования по проекту.

В лабораторной работе №3 таблица `tasks` разделена на четыре `HASH`-партиции по
UUID `id`. Такой ключ сохраняет простой первичный ключ и внешние ключи из
`comments` и `task_tags`; точечные операции API по `task_id` используют
partition pruning. Диапазонные списки задач по датам при этой стратегии читают
все четыре партиции — это осознанный компромисс текущей схемы.

Проверить и при необходимости восстановить набор партиций можно командами:

```bash
docker compose run --rm partition-maintenance python -m app.cli.partitions check
docker compose run --rm partition-maintenance python -m app.cli.partitions create
```

Проверка сохраняет состояние `OK`/`CRITICAL`, поэтому одинаковый alert не
отправляется повторно, а переход обратно в `OK` создаёт recovery-уведомление.
Сообщение всегда попадает в лог. Для отправки JSON `{"text": "..."}` во внешний
канал задайте `PARTITION_ALERT_WEBHOOK_URL`. В production обе команды удобно
запускать по расписанию оркестратора; готовый one-shot профиль запускается так:

```bash
docker compose --profile maintenance run --rm partition-maintenance
```

### Telegram alerts

1. Создайте бота через `@BotFather`, получите токен и отправьте своему боту `/start`.
2. Узнайте `chat_id` через метод Telegram `getUpdates`: после сообщения боту
   нужный ID находится в `result[].message.chat.id`. Для группы добавьте туда
   бота и отправьте ему команду. Токен не публикуйте и не сохраняйте в репозитории.
3. Добавьте в локальный `.env` проекта:

```dotenv
TELEGRAM_BOT_TOKEN=токен_от_BotFather
TELEGRAM_CHAT_ID=ID_чата
```

Отправка выполняется официальным методом
[`sendMessage`](https://core.telegram.org/bots/api#sendmessage), без webhook-посредника.
Проверить доставку без подключения к БД:

```bash
docker compose run --build --rm partition-maintenance python -m app.cli.partitions test-alert
```

Проверить партиции (миграции должны быть применены):

```bash
docker compose run --rm partition-maintenance python -m app.cli.partitions check
```

`check` отправляет первый статус, изменение проблемы и recovery, но не повторяет
неизменившийся статус. При ошибке доставки процесс завершается с ошибкой и не
записывает новое состояние: следующий запуск повторяет отправку. Без Telegram-
настроек остаётся прежний режим логирования; если задан только один параметр,
команда сообщает об ошибке конфигурации.

Для учебной таблицы `events` реализован отправитель outbox. Запускайте его из
каталога `krasova` с `DATABASE_URL`, указывающим на БД учебной лабораторной:

```bash
DATABASE_URL=postgresql+asyncpg://krasova:krasova_lab1@localhost:55432/krasova_lab1 \
  .venv/bin/python -m app.cli.partitions deliver-events
```

Он доставляет до 100 сообщений за запуск и отмечает их `delivered_at` только
после подтверждения Telegram. Для `check` используется Celery-расписание ниже;
`deliver-events` запускайте отдельно через cron или планировщик.
Доставка outbox — at-least-once: при аварии между
отправкой и фиксацией транзакции возможен повтор сообщения.

### Автоматическая проверка через Celery

При обычном `docker compose up --build -d` теперь запускаются Redis, Celery
worker и один Celery Beat. Миграции выполняет отдельный `db-migrate` до старта
API и фоновых сервисов.

- Beat ставит `partitions.check` в очередь каждые 5 минут (00, 05, 10, …).
- `partitions.create` запускается независимо, ежедневно в 01:00 по Москве.
- Worker обращается к PostgreSQL и использует существующую Telegram-отправку
  и подавление дубликатов. Ошибки БД и доставки повторяются до трёх раз с backoff.

При работающих Beat, Redis, worker и Telegram уведомление обычно приходит в
течение 0–5 минут после сбоя плюс время очереди и доставки. Это не гарантия:
при остановленном планировщике или сетевом сбое задержка будет больше.

```bash
docker compose up --build -d
docker compose logs -f celery-worker celery-beat
```

Немедленно поставить проверку в очередь, не дожидаясь расписания:

```bash
docker compose exec celery-worker celery -A app.celery_app:celery_app call partitions.check
```

Не масштабируйте `celery-beat`: для одного расписания должен работать один
экземпляр. Расписание хранится в отдельном volume. Настройки используют механизм
[Celery periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html).
Учебный outbox `events` не включён в это расписание: он находится в другой БД
и доставляется отдельной командой `deliver-events`.

## Read Scaling: Primary + Replica

Docker Compose поднимает `postgres-primary` и read-only hot standby
`postgres-replica`. Миграции и все операции записи используют Primary. Запросы
`GET /api/tasks` и `GET /api/projects/{project_id}/tasks` используют отдельное
подключение `REPLICA_DATABASE_URL`; остальные endpoint по-прежнему работают с
Primary, чтобы сохранить ожидаемое read-after-write поведение.

Создать или дозапустить Replica можно отдельным скриптом:

```bash
./scripts/create_replica.sh
```

Скрипт запускает Primary, создаёт недостающую replication-роль,
добавляет правила `pg_hba.conf`, запускает Replica и проверяет состояние
`streaming`. Повторный запуск не удаляет данные Primary.

```bash
docker compose up -d --build

# Primary с хоста
psql postgresql://tracker:tracker@localhost:56432/tracker

# Replica с хоста
psql postgresql://tracker:tracker@localhost:56433/tracker

# Состояние streaming replication
docker compose exec postgres-primary psql -U tracker -d tracker \
  -c "SELECT application_name, state, sync_state, sent_lsn, replay_lsn FROM pg_stat_replication"
```

Replica использует асинхронную physical streaming replication. Поэтому списки
задач масштабируются по чтению, но сразу после записи могут кратковременно вернуть
устаревшие данные. Автоматического fallback на Primary сейчас нет. Пароли
репликации в `compose.yaml` предназначены только для локальной лабораторной среды;
в production их следует хранить в secrets.

## Сложные запросы

Оба JOIN-запроса реально выполняются репозиториями при обращении к API.

Подробная выдача задач объединяет проект, автора, исполнителя и проверку членства:

```sql
SELECT tasks.*, projects.*, creator.*, assignee.*
FROM tasks
JOIN projects ON projects.id = tasks.project_id
JOIN users AS creator ON creator.id = tasks.creator_id
LEFT JOIN users AS assignee ON assignee.id = tasks.assignee_id
JOIN project_members
  ON project_members.project_id = tasks.project_id
 AND project_members.user_id = :current_user_id
WHERE tasks.created_at BETWEEN :created_from AND :created_to
ORDER BY tasks.created_at DESC
LIMIT :page_size OFFSET :offset;
```

Список комментариев связывает комментарий, задачу и автора:

```sql
SELECT comments.*, tasks.*, users.*
FROM comments
JOIN tasks ON tasks.id = comments.task_id
JOIN users ON users.id = comments.author_id
WHERE comments.task_id = :task_id
ORDER BY comments.created_at;
```

Статистика проекта использует несколько `GROUP BY`, включая нагрузку исполнителей:

```sql
SELECT users.id, users.display_name, COUNT(tasks.id) AS task_count
FROM users
JOIN tasks ON tasks.assignee_id = users.id
WHERE tasks.project_id = :project_id
GROUP BY users.id, users.display_name
ORDER BY task_count DESC;
```

## Генерация данных

Генератор добавляет данные пакетами и не очищает существующую БД. Небольшой набор:

```bash
docker compose exec backend python -m app.cli.seed
```

Пример большого набора:

```bash
docker compose exec backend python -m app.cli.seed \
  --users 1000 \
  --projects 100 \
  --tasks 1000000 \
  --comments 2000000 \
  --batch-size 10000 \
  --seed 42
```

Параметры `--tags-per-project` и `--members-per-project` управляют связанными
данными. Все seed-пользователи одного запуска имеют пароль, указанный через
`--password` (по умолчанию `SeedPassword123!`). Email сгенерированного пользователя
выводится в таблице `users` и уникален для каждого запуска.

## Тесты

```bash
pytest
ruff check .
```

Интеграционные тесты по умолчанию пропускаются, чтобы случайно не удалить обычную
БД. Создайте отдельную БД с `test` в названии и запустите:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test pytest
```

## Шардирование пользователей (лабораторная работа №5)

Четыре независимых PostgreSQL-узла `postgres-shard-0` … `postgres-shard-3`
предназначены для эксперимента с сущностью `User`. Router выбирает узел по UUID
пользователя. Реализованы стратегии `SHA-256(user_id) % N` и consistent hash
ring со 128 virtual nodes на физический shard.

```bash
# Запуск независимых узлов
docker compose up -d postgres-shard-0 postgres-shard-1 \
  postgres-shard-2 postgres-shard-3

# Расчёт распределения и переноса без обращения к БД
python -m app.cli.sharding simulate --records 100000

# Создание users и фактическая загрузка 100 000 строк в первые три PostgreSQL
python -m app.cli.sharding seed --records 100000 --shards 3 \
  --strategy modulo --reset

# Проверка физического количества строк
python -m app.cli.sharding count --shards 3
```

При запуске CLI внутри контейнера `backend` адреса передаются через
`SHARD_DATABASE_URLS`; при запуске с хоста используются порты `56540`–`56543`.
Встроенный `hash()` Python намеренно не применяется: его строковые значения
меняются между процессами. Для воспроизводимой маршрутизации используется
SHA-256.

### Распределённые запросы (лабораторная работа №6)

После загрузки данных можно воспроизвести single-shard lookup, параллельный
`COUNT(*)` по всем shard и глобальный merge для `ORDER BY ... LIMIT`:

```bash
python -m app.cli.shard_queries --shards 3 \
  --search "Lab 5 User 99" --limit 10
```

Точный distributed-запрос завершается ошибкой `shard_unavailable`, если хотя бы
один узел недоступен: молча возвращать неполный `COUNT` или неверный top-N
нельзя. Для пользовательского endpoint такую ошибку следует преобразовывать в
HTTP 503; частичный ответ допустим только как явно описанный режим API.

Тестовая fixture пересоздаёт таблицы только в указанной test-БД.
