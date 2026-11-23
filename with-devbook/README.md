# GitLab Project Registry

Сервис хранит проекты в SQLite и обновляет их метаданные через GitLab REST API. Для запуска нужны Python 3.11+ с SQLite 3.35+ и менеджер зависимостей uv.

## Запуск

Выполните команды из каталога `with-devbook/`:

```sh
uv sync --locked
cp .env.example .env
uv run --locked alembic upgrade head
uv run --locked uvicorn registry.main:app
```

API доступен по адресу `http://localhost:8000`, контракт OpenAPI — по `/openapi.json`. Приложение читает настройки из окружения и локального `.env`. Переменные окружения имеют приоритет. Для синхронизации задайте `GITLAB_TOKEN` с правом чтения проекта. API реестра работает без пользовательской авторизации.

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `DATABASE_PATH` | `projects.sqlite3` | Путь к файлу SQLite |
| `GITLAB_URL` | `https://gitlab.com` | Базовый URL GitLab. Поддерживается размещение в подкаталоге |
| `GITLAB_TOKEN` | Пусто | Токен GitLab с доступом на чтение проекта |
| `GITLAB_TIMEOUT_SECONDS` | `5.0` | Общий бюджет HTTP-запроса и таймауты HTTP-клиента в секундах |

## API

| Метод и путь | Успешный ответ |
| --- | --- |
| `POST /projects` | `201`, проект и заголовок `Location` |
| `GET /projects/{id}` | `200`, проект |
| `GET /projects` | `200`, массив проектов по возрастанию `id` |
| `PATCH /projects/{id}` | `200`, проект с обновлёнными полями |
| `DELETE /projects/{id}` | `204`, пустое тело |
| `POST /projects/{id}/sync` | `200`, проект с обновлёнными метаданными |

Создание принимает положительный целочисленный `gitlab_project_id`, непустые `name` и `path_with_namespace`, HTTP(S) URL в `web_url` и необязательный `default_branch`. Сервер назначает локальный `id` и записывает даты в UTC. PATCH принимает любое подмножество полей создания. Передайте `"default_branch": null`, чтобы очистить ветку.

```sh
curl -i http://localhost:8000/projects \
  -H 'Content-Type: application/json' \
  -d '{"gitlab_project_id":123,"name":"Registry","path_with_namespace":"team/registry","web_url":"https://gitlab.example/team/registry","default_branch":"main"}'

curl -i -X POST http://localhost:8000/projects/1/sync
```

Синхронизация запрашивает `GET /api/v4/projects/{gitlab_project_id}` с заголовком `PRIVATE-TOKEN` и сохраняет четыре поля одной записью. При конкурентном PATCH или sync вернётся `409`. При конкурентном удалении вернётся `404`. Запрос в GitLab выполняется один раз, без перенаправлений.

Ошибки имеют поля `code`, `message` и `details`. Отсутствующий локальный проект даёт `404`, повторный GitLab ID — `409`, ошибки валидации — `422`. Для sync ошибки GitLab и некорректные ответы дают `502`, отсутствующий токен — `503`, таймаут — `504`.

```json
{"code":"project_not_found","message":"Project does not exist","details":{}}
```

## Проверки

После `uv sync` запустите проверки из этой директории:

```sh
uv run --no-sync pytest
uv run --no-sync ruff check .
uv run --no-sync black --check .
uv run --no-sync mypy registry alembic
uv run --no-sync alembic check
```

`alembic check` использует БД, подготовленную командой `alembic upgrade head`. Тесты применяют миграции к временной SQLite БД и подставляют ответы на границе HTTP-клиента.
