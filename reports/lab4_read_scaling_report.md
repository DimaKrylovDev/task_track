# Отчёт по лабораторной работе №4

## Масштабирование чтения PostgreSQL: Primary + Replica

Дата выполнения: 17 сентября 2026 года  
Проект: `krasova`, Task Tracker API  
СУБД: PostgreSQL 17  
Схема: один Primary и одна асинхронная physical streaming Replica

## 1. Цель работы

Настроить для собственного backend-сервиса два экземпляра PostgreSQL, проверить
передачу изменений через WAL и направить реальный read-сценарий приложения на
Replica. Операции записи должны остаться на Primary.

В качестве read-сценария выбраны:

- `GET /api/tasks`;
- `GET /api/projects/{project_id}/tasks`.

Авторизация, получение отдельной задачи и все операции `POST`, `PUT`, `DELETE`
остались на Primary.

## 2. Архитектура стенда

```text
                         WAL stream
                       (asynchronous)
┌─────────────┐ write ┌──────────────────┐       ┌──────────────────┐
│ FastAPI API │──────▶│ postgres-primary │──────▶│ postgres-replica │
│             │       │ read/write       │       │ hot standby      │
│             │ read ───────────────────────────▶│ read-only        │
└─────────────┘       └──────────────────┘       └──────────────────┘
       │                       ▲
       └─ auth и прочие reads ─┘
```

Primary принимает изменения, записывает их в WAL и передаёт WAL-поток Replica.
Replica находится в recovery, воспроизводит WAL и разрешает SELECT в режиме hot
standby.

## 3. Часть 1. Запуск Primary и Replica

Существенная часть `compose.yaml`:

```yaml
services:
  postgres-primary:
    image: postgres:17-alpine
    command:
      - postgres
      - -c
      - wal_level=replica
      - -c
      - max_wal_senders=10
      - -c
      - wal_keep_size=256MB
    volumes:
      - postgres_primary_data:/var/lib/postgresql/data
      - ./docker/postgres/primary/init-replication.sh:/docker-entrypoint-initdb.d/10-init-replication.sh:ro
    ports:
      - "56432:5432"

  postgres-replica:
    image: postgres:17-alpine
    entrypoint: ["/usr/local/bin/replica-entrypoint.sh"]
    volumes:
      - postgres_replica_data:/var/lib/postgresql/data
      - ./docker/postgres/replica/entrypoint.sh:/usr/local/bin/replica-entrypoint.sh:ro
    ports:
      - "56433:5432"
    depends_on:
      postgres-primary:
        condition: service_healthy
```

Роли контейнеров:

| Контейнер | Роль | Адрес внутри Compose | Порт хоста |
|---|---|---|---|
| `krasova-postgres-primary-1` | Primary, read/write | `postgres-primary:5432` | `56432` |
| `krasova-postgres-replica-1` | Replica, read-only | `postgres-replica:5432` | `56433` |

Подключение с хоста:

```bash
psql postgresql://tracker:tracker@localhost:56432/tracker
psql postgresql://tracker:tracker@localhost:56433/tracker
```

Подключение через Docker:

```bash
docker compose exec postgres-primary psql -U tracker -d tracker
docker compose exec postgres-replica psql -U tracker -d tracker
```

Фактический результат `docker compose ps`:

```text
krasova-backend-1            Up             0.0.0.0:8000->8000/tcp
krasova-postgres-primary-1   Up (healthy)   0.0.0.0:56432->5432/tcp
krasova-postgres-replica-1   Up (healthy)   0.0.0.0:56433->5432/tcp
```

## 4. Часть 2. Настройка streaming replication

При первой инициализации Primary создаётся роль `replicator` с атрибутами
`REPLICATION LOGIN`, а в `pg_hba.conf` добавляется доступ к replication protocol.

Replica при пустом volume выполняет `pg_basebackup` с Primary, создаёт
`standby.signal` и записывает `primary_conninfo`. При последующих стартах готовый
volume используется повторно.

Путь изменения:

1. Транзакция изменяет страницы данных на Primary.
2. Описание изменения фиксируется в WAL.
3. WAL sender на Primary передаёт записи WAL по replication connection.
4. WAL receiver на Replica записывает полученный поток.
5. Startup/recovery process воспроизводит WAL.
6. После replay изменение становится видимо SELECT на Replica.

Проверка Primary:

```sql
SELECT application_name, client_addr, state, sync_state,
       sent_lsn, write_lsn, flush_lsn, replay_lsn
FROM pg_stat_replication;
```

Полученный результат:

```text
application_name | krasova-replica
client_addr      | 192.168.96.4
state            | streaming
sync_state       | async
sent_lsn         | 0/31A8030
write_lsn        | 0/31A8030
flush_lsn        | 0/31A8030
replay_lsn       | 0/31A8030
```

Проверка ролей узлов:

```text
Primary: pg_is_in_recovery() = false, transaction_read_only = off
Replica: pg_is_in_recovery() = true,  transaction_read_only = on
```

Значение `sync_state = async` означает, что commit на Primary не ждёт
подтверждения replay от Replica.

## 5. Часть 3. Доказательство репликации

Запись выполнена на Primary:

```sql
INSERT INTO users (id, email, display_name, password_hash)
VALUES (
  '00000000-0000-4000-8000-000000000004',
  'lab4.replication@example.com',
  'Lab 4 replicated user',
  'not-used-in-lab'
);
```

Результат записи:

```text
id                                   | email                        | display_name
00000000-0000-4000-8000-000000000004 | lab4.replication@example.com | Lab 4 replicated user
INSERT 0 1
```

SELECT выполнен на Replica:

```sql
SELECT id, email, display_name
FROM users
WHERE id = '00000000-0000-4000-8000-000000000004';
```

Результат:

```text
id                                   | email                        | display_name
00000000-0000-4000-8000-000000000004 | lab4.replication@example.com | Lab 4 replicated user
(1 row)
```

Строка, созданная на Primary, появилась на Replica без отдельного копирования со
стороны приложения.

## 6. Часть 4. Read-only поведение Replica

На Replica была выполнена попытка `INSERT INTO users ...`. PostgreSQL вернул:

```text
ERROR: cannot execute INSERT in a read-only transaction
```

Replica не является независимой базой для записи. Её состояние формируется
replay WAL с Primary. Произвольная локальная запись нарушила бы единую историю
изменений и привела бы к расхождению узлов. Записи приложения поэтому всегда
направляются на Primary.

## 7. Часть 5. Чтение backend через Replica

В настройки добавлен второй URL:

```dotenv
DATABASE_URL=postgresql+asyncpg://tracker:tracker@postgres-primary:5432/tracker
REPLICA_DATABASE_URL=postgresql+asyncpg://tracker:tracker@postgres-replica:5432/tracker
```

В `app/db/session.py` созданы два engine и две session factory:

```python
engine = create_async_engine(
    settings.database_url,
    connect_args={"server_settings": {"application_name": "krasova-primary"}},
)
replica_engine = create_async_engine(
    settings.replica_database_url,
    connect_args={"server_settings": {"application_name": "krasova-read-replica"}},
)
```

FastAPI использует две явные зависимости:

```python
def get_uow() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory)

def get_read_uow() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(replica_session_factory)
```

Только два endpoint списка задач получают `ReadUowDep`:

```python
@router.get("/api/tasks")
async def list_tasks(current_user: CurrentUser, uow: ReadUowDep, ...): ...

@router.get("/api/projects/{project_id}/tasks")
async def list_project_tasks(current_user: CurrentUser, uow: ReadUowDep, ...): ...
```

`POST /api/tasks`, `PUT`, `DELETE` и `GET /api/tasks/{task_id}` используют обычный
`UowDep`, связанный с Primary. Это намеренное разделение, а не автоматическая
маршрутизация по типу SQL.

Проверенный сквозной сценарий:

```text
GET  /health       -> 200
POST /api/auth/register -> 201
POST /api/projects -> 201
POST /api/tasks    -> 201, запись на Primary
GET  /api/tasks    -> 200, total=1, чтение с Replica
```

Задача стала видна с первой попытки GET примерно через 53 мс от начала запроса.
Это наблюдение конкретного запуска, а не гарантия максимального lag.

Подтверждение фактических соединений через `pg_stat_activity`:

```text
Replica: application_name=krasova-read-replica, state=idle, backend_type=client backend
Primary: application_name=krasova-primary,      state=idle, backend_type=client backend
```

## 8. Часть 6. Replication lag

В обычном локальном запуске Replica успевала применить изменение до первого GET.
Чтобы воспроизводимо показать окно рассогласования, replay был кратковременно
приостановлен штатной функцией PostgreSQL:

```sql
-- Replica
SELECT pg_wal_replay_pause();

-- Primary
INSERT INTO users (...) VALUES (...);

-- Primary: строка уже есть
SELECT count(*) ...; -- 1

-- Replica: WAL получен, но ещё не применён
SELECT count(*) ...; -- 0
SELECT pg_size_pretty(
  pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn())::bigint
); -- 384 bytes

-- Replica
SELECT pg_wal_replay_resume();
```

После возобновления replay:

```text
replica_rows_after_resume = 1
replay_lag_bytes          = 0 bytes
```

Это демонстрирует eventual consistency: Primary может подтвердить commit раньше,
чем Replica применит соответствующий WAL.

## 9. Изменения проекта

| Файл | Изменение |
|---|---|
| `compose.yaml` | Добавлены Primary, Replica, volumes, healthchecks и отдельные DB URL |
| `docker/postgres/primary/init-replication.sh` | Создание replication-role и правила `pg_hba.conf` |
| `docker/postgres/replica/entrypoint.sh` | `pg_basebackup`, standby mode и подключение к Primary |
| `app/core/config.py` | Добавлен `replica_database_url` |
| `app/db/session.py` | Добавлены replica engine/factory и имена подключений |
| `app/api/deps.py` | Добавлен отдельный read-only Unit of Work |
| `app/api/routers/tasks.py` | Два GET списка переведены на Replica |
| `tests/test_api_integration.py` | Интеграционные тесты переопределяют обе фабрики |
| `tests/test_read_replica.py` | Проверяется точный набор endpoint, использующих Replica |
| `.env.example`, `README.md` | Добавлены конфигурация и команды эксплуатации |

Миграции структуры данных не менялись: physical replication переносит DDL через
WAL после выполнения Alembic на Primary.

## 10. Что улучшилось и что ухудшилось

Улучшения:

- SELECT списка задач можно вынести с Primary и увеличить суммарную пропускную
  способность чтения;
- чтения и записи имеют явные подключения, поэтому случайная запись на Replica
  не маскируется;
- Replica может использоваться для тяжёлых отчётных SELECT;
- `application_name` упрощает наблюдение за маршрутизацией;
- тест фиксирует, какие именно endpoint читают с Replica.

Компромиссы и ухудшения:

- после записи список задач может временно вернуть старые данные;
- появились второй сервер, второй connection pool, дополнительная память, диск и
  операционная сложность;
- если Replica недоступна, два endpoint списка задач сейчас завершаются ошибкой —
  автоматического fallback на Primary нет;
- чтение списка использует Primary для проверки access token и Replica для самого
  списка, то есть один HTTP-запрос обращается к двум БД;
- это не ускоряет отдельный SQL-запрос и не исправляет плохие планы запросов;
- Replica не является резервной копией: ошибочный DELETE также попадёт в WAL;
- автоматический failover не реализован, поэтому решение даёт read scaling, но не
  полноценную high availability;
- стенд использует `wal_keep_size`, но не replication slot/WAL archive. После
  долгого отключения Replica может потребоваться новый base backup;
- лабораторные replication credentials записаны в Compose открытым текстом и для
  production должны быть перенесены в secret manager.

Новый Primary использует отдельный volume. Старый контейнер/volume проекта не
удалялся, чтобы не потерять существующие данные.

## 11. Контрольные вопросы

### 1. Чем Primary отличается от Replica?

Primary принимает обычные транзакции чтения и записи и формирует WAL. Replica
получает WAL, находится в recovery/hot standby и обслуживает SELECT, но не
принимает независимые пользовательские INSERT/UPDATE/DELETE.

### 2. Почему запись выполняем на Primary?

Primary является единственным владельцем упорядоченной истории изменений.
Запись в один узел исключает конфликтующие независимые истории. Physical standby
воспроизводит эту историю и технически работает read-only.

### 3. Как изменение из Primary попадает на Replica?

Primary фиксирует изменение в WAL. WAL sender передаёт поток по replication
protocol, WAL receiver на Replica принимает и сохраняет его, затем recovery
process воспроизводит записи WAL над локальной копией данных.

### 4. Что такое WAL в контексте репликации?

WAL (Write-Ahead Log) — последовательный журнал описаний изменений. Запись WAL
должна быть надёжно сохранена до записи изменённых страниц таблиц. Для physical
replication WAL одновременно служит потоком инструкций, по которому Replica
воспроизводит состояние Primary.

### 5. Что такое replication lag?

Это отставание Replica от Primary. Его можно выражать временем, байтами WAL или
разницей LSN. Lag включает передачу, запись, flush и replay WAL и растёт при
медленной сети, диске, высокой нагрузке, блокирующих запросах или остановке replay.

### 6. Почему следующий SELECT после INSERT может увидеть старые данные?

При асинхронной репликации commit завершается после фиксации на Primary и не ждёт
replay на Replica. SELECT может попасть в интервал между commit на Primary и replay
соответствующей WAL-записи на Replica. Это нарушение read-after-write consistency,
но ожидаемое поведение eventual consistency.

### 7. Что масштабируется при Read Scaling?

Масштабируется суммарная способность системы обслуживать больше независимых
чтений: запросы распределяются между узлами. Один конкретный SQL-запрос сам по
себе обычно не становится быстрее и выполняется целиком на одном выбранном узле.

### 8. Почему Replica не отменяет индексы и оптимизацию SQL?

Replica выполняет тот же план запроса над почти теми же данными. Запрос без
подходящего индекса продолжит читать лишние страницы, расходовать CPU и I/O, а
долгий SELECT на hot standby может конфликтовать с применением WAL. Реплики
добавляют вычислительную ёмкость, но не исправляют неэффективность каждого запроса.

### 9. CAP-теорема

CAP относится к распределённым системам при сетевом разделении и утверждает, что
одновременно гарантировать Consistency, Availability и Partition tolerance нельзя.
Если произошёл partition, система должна выбрать между:

- **C (Consistency)** — каждый успешный read видит последнее согласованное
  значение, но часть запросов может быть отклонена;
- **A (Availability)** — каждый исправный узел отвечает, но ответ может содержать
  устаревшие или расходящиеся данные;
- **P (Partition tolerance)** — система продолжает определённым образом работать
  при потере связи между узлами; для реально распределённой системы это не
  опциональная характеристика, а условие, с которым приходится считаться.

Текущая асинхронная Primary/Replica схема допускает устаревшие чтения с Replica,
то есть для read scaling ослабляет немедленную согласованность. При потере связи
Primary продолжит принимать записи, а Replica может отвечать старыми данными.
Однако автоматического promotion/failover здесь нет, поэтому сам стенд нельзя
называть полноценной AP- или HA-системой только по факту наличия Replica.

## 12. Итог

Primary и Replica запущены, physical streaming replication работает в режиме
`streaming/async`, запись с Primary появляется на Replica, а запись на Replica
запрещена. Два реальных GET endpoint проекта используют отдельное replica-
подключение. Replication lag воспроизведён и измерен: до replay Replica не видела
строку при отставании 384 байта, после replay строка появилась и lag стал нулевым.
