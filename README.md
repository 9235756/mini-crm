# Мини-CRM: клиенты, сделки, задачи + отчёты в Google Drive

Бэкенд на FastAPI + SQLite (запуск через Docker Compose), интерфейс на Tkinter, выгрузка отчётов в Google Sheets / Google Drive с OAuth2-авторизацией пользователя.

Проект работает **без Google-ключей**: по умолчанию включена эмуляция (`GOOGLE_MODE=mock`). Эмулятор отвечает в том же формате, что Drive API и Sheets API, а отчёты сохраняет в папку `mock_drive/` как отформатированный `.xlsx` и HTML-страницу. Для настоящего Google достаточно поставить `GOOGLE_MODE=real` — остальной код не меняется.

## Структура

```
mini_crm/
├── backend/               FastAPI: main.py, database.py (CRUD на sqlite3), models.py, schemas.py
│   └── routers/           clients.py, deals.py, tasks.py, stats.py
├── google_integration/    config.py, auth.py (OAuth2), google_drive.py, google_sheets.py,
│                          mock_google.py (эмуляция), __init__.py (фабрики get_drive/get_sheets)
├── gui/                   app.py (Tkinter), api_client.py (requests), reports.py (аналитика + выгрузка)
├── tests/                 test_reports.py (аналитика, эмулятор), test_api.py (эндпоинты)
├── config/settings.txt    создаётся из окна «Настройки Google»
├── data/crm.db            база (монтируется в контейнер)
├── mock_drive/            «эмулированный Google Drive»: отчёты .xlsx + .html, журнал _drive_index.json
├── docker/Dockerfile, docker-compose.yml
├── fill_test_data.py      заполнение базы тестовыми данными
├── run_demo.py            весь сценарий одной командой
└── start_gui.py           запуск интерфейса
```

## Запуск (Windows PowerShell)

```powershell
cd mini_crm
copy example.env .env
python -m venv venv
.\venv\Scripts\Activate.ps1          # если запрещено: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt

docker compose up -d --build         # бэкенд на http://localhost:8000
curl.exe http://localhost:8000/health
```

Откройте Swagger: **http://localhost:8000/docs** — там можно вызвать все эндпоинты.

```powershell
python fill_test_data.py             # по 1000 клиентов, сделок и задач (--count 50 — быстрее)
python start_gui.py                  # интерфейс
python run_demo.py                   # весь сценарий одной командой
pytest                               # 15 тестов
```

На macOS / Linux те же команды, только `cp example.env .env` и `source venv/bin/activate`.

Код бэкенда примонтирован в контейнер: правки в `backend/` подхватываются автоматически (`uvicorn --reload`), пересобирать образ не нужно. База лежит в `data/crm.db` и переживает перезапуск контейнера. Начать с чистой базы: `docker compose down`, удалить `data/crm.db`, снова `docker compose up -d`.

## API

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/health` | проверка живости |
| GET | `/stats` | сводка по всем сущностям |
| GET / POST | `/clients` | список (`search`, `status`, `limit`, `offset`) / создание |
| GET / PUT / DELETE | `/clients/{id}` | чтение / изменение / удаление |
| POST | `/clients/{id}/archive` | архивировать клиента |
| GET / POST | `/deals` | список (`search`, `status`, `client_id`, `limit`, `offset`) / создание |
| GET / PUT / DELETE | `/deals/{id}` | чтение / изменение / удаление |
| PUT | `/deals/{id}/client` | привязать (`{"client_id": 5}`) или отвязать (`{"client_id": null}`) клиента |
| PUT | `/deals/{id}/status` | сменить статус: `new`, `in_progress`, `won`, `lost` |
| GET / POST | `/tasks` | список (`search`, `is_done`, `client_id`, `deal_id`, `limit`, `offset`) / создание |
| GET / PUT / DELETE | `/tasks/{id}` | чтение / изменение / удаление |
| PUT | `/tasks/{id}/done` | отметить выполненной (`{"is_done": true}`) или нет |

Поиск не зависит от регистра и корректно работает с кириллицей: встроенный `lower()` в SQLite понимает только латиницу, поэтому в базе зарегистрирована Python-функция `py_lower`. Запросы `ИВАНОВ` и `иванов` находят одно и то же.

## Интерфейс

- Вкладки «Клиенты», «Сделки», «Задачи»: таблица, поиск (Enter), фильтр статуса, постраничный просмотр по 200 записей.
- Кнопки «Добавить», «Изменить» (или двойной щелчок по строке), «Архивировать» / «Удалить», «Обновить», **«Выгрузить отчёт»**.
- В форме сделки клиент выбирается из списка «ID — Имя», дата проверяется по формату ГГГГ-ММ-ДД.
- **«Настройки Google»**: выбор `client_secret.json` и JSON сервисного аккаунта, поле ID папки с кнопкой **«Вставить»** (берёт текст из буфера обмена; если вставить всю ссылку на папку, ID извлечётся сам). Настройки сохраняются в `config/settings.txt`.
- Выгрузка идёт в фоне, окно не зависает. По окончании появляется окно со ссылкой и кнопками **«Открыть»** и «Копировать ссылку».

## Отчёты и аналитика

Каждый отчёт — таблица с двумя листами: «Данные» (все записи, жирная цветная шапка, закреплённая первая строка, денежный формат) и «Аналитика». Аналитика считается в Python (`gui/reports.py`), без формул:

- **Клиенты:** всего, по статусам, с компанией и без, топ-5 компаний, новые за 30 дней.
- **Сделки:** общая сумма, **средняя = общая сумма / количество сделок**, медиана, количество и сумма по статусам, конверсия won / (won + lost), сделки без клиента, топ-5 клиентов по сумме.
- **Задачи:** всего, выполнено и нет, % выполнения, просроченные, привязанные к клиенту, к сделке, без привязки.

В уроке средняя сумма сделки совпадала с общей. Здесь расчёт исправлен и закрыт тестом `test_average_is_total_divided_by_count`, а `run_demo.py` дополнительно проверяет это на реальных данных.

**Где лежат отчёты в режиме mock:** `mock_drive/Отчёт_по_сделкам_2026-11-19_10-01.html` и `.xlsx` рядом. Журнал «папки на Диске» — `mock_drive/_drive_index.json`.

## Переключение на настоящий Google (`GOOGLE_MODE=real`)

1. https://console.cloud.google.com/ → создать проект.
2. APIs & Services → Library → включить **Google Drive API** и **Google Sheets API**.
3. OAuth consent screen → External → в разделе **Test users** добавить свой Gmail. Без этого вход завершится ошибкой `403 access_denied`.
4. Credentials → Create Credentials → **OAuth client ID** → Desktop app → скачать JSON и положить как `google_integration/client_secret.json` (или выбрать файл в «Настройках Google»).
5. Создать папку на Google Drive и скопировать её ID — часть адреса после `/folders/`. Вставить в «Настройках Google» кнопкой «Вставить» или прописать в `.env` (`GOOGLE_DRIVE_FOLDER_ID`).
6. В `.env` поставить `GOOGLE_MODE=real` и выгрузить отчёт. При первой выгрузке откроется браузер для входа в Google, после этого появится `google_integration/token.json`, и дальше вход не потребуется.

Авторизация выполняется в GUI на компьютере пользователя, от его имени и в его браузере, а не на сервере. Файлы `.env`, `token.json`, `client_secret*.json` и ключи сервисного аккаунта исключены из git.

## Скриншоты для сдачи

1. **Swagger** — `http://localhost:8000/docs` со списком эндпоинтов и, например, выполненным `GET /clients?search=...`.
2. **Docker** — `docker compose ps` со статусом `healthy` (или Docker Desktop с запущенным контейнером).
3. **Заполнение базы** — вывод `python fill_test_data.py` с прогресс-барами.
4. **GUI с данными** — главное окно с заполненной таблицей (по одному снимку на каждую вкладку или хотя бы «Сделки»).
5. **Окно «Настройки Google»** с режимом и кнопкой «Вставить».
6. **Окно успеха выгрузки** — со ссылкой и кнопками «Открыть» / «Копировать ссылку».
7. **Открытый отчёт** — HTML-страница из `mock_drive` (блок «Аналитика» и таблица) или таблица в Google Sheets в режиме real.
8. **Папка с отчётами** — `mock_drive/` в проводнике или папка на Google Drive.
9. **Итог `python run_demo.py`** — финальная таблица со ссылками и метриками.
10. **`pytest`** — все тесты зелёные.
