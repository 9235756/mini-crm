"""Демонстрация всего сценария мини-CRM одной командой (без GUI).

    python run_demo.py              # при пустой базе заполнит по 1000 записей
    python run_demo.py --count 50
"""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from google_integration import get_drive, load_config
from gui.api_client import APIError, CRMClient
from gui.reports import REPORT_TITLES, export_report, local_path

console = Console()


def show(title: str, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) if data is not None else "(пустой ответ, 204)"
    console.print(f"[bold cyan]→ {title}[/]")
    console.print(text, highlight=True, soft_wrap=True)


def step(n: int, title: str) -> None:
    console.rule(f"[bold]Шаг {n}. {title}")


def demo_crud(api: CRMClient) -> None:
    client = api.create_client({
        "full_name": "Демонстрационный Клиент Петрович",
        "company": "ООО «Демо»",
        "email": "demo.client@example.ru",
        "phone": "+7 900 000-00-00",
        "status": "lead",
    })
    show("POST /clients — создан клиент", client)

    client = api.update_client(client["id"], {"status": "active", "notes": "Стал активным после звонка"})
    show("PUT /clients/{id} — обновлён статус и заметка", client)

    deal = api.create_deal({"title": "Демо: внедрение CRM", "client_id": client["id"],
                            "amount": 250000, "status": "new", "close_date": "2026-12-31"})
    show("POST /deals — создана сделка, привязанная к клиенту", deal)

    deal = api.set_deal_status(deal["id"], "in_progress")
    show("PUT /deals/{id}/status — статус «в работе»", {k: deal[k] for k in ("id", "title", "status")})

    deal = api.set_deal_client(deal["id"], None)
    show("PUT /deals/{id}/client — клиент отвязан", {k: deal[k] for k in ("id", "client_id", "client_name")})
    deal = api.set_deal_client(deal["id"], client["id"])
    show("PUT /deals/{id}/client — клиент привязан обратно",
         {k: deal[k] for k in ("id", "client_id", "client_name")})

    task = api.create_task({"title": "Демо: подготовить договор", "due_date": "2026-12-01",
                            "client_id": client["id"], "deal_id": deal["id"]})
    show("POST /tasks — создана задача", task)
    task = api.set_task_done(task["id"], True)
    show("PUT /tasks/{id}/done — задача выполнена", {k: task[k] for k in ("id", "title", "is_done")})

    found = api.list("clients", search="ДЕМОНСТРАЦИОННЫЙ")
    show("GET /clients?search=ДЕМОНСТРАЦИОННЫЙ — поиск без учёта регистра (кириллица)",
         {"total": found["total"], "first": [c["full_name"] for c in found["items"][:3]]})
    found = api.list("deals", search="демо: внедрение")
    show("GET /deals?search=демо: внедрение", {"total": found["total"]})

    client = api.archive_client(client["id"])
    show("POST /clients/{id}/archive — клиент в архиве", {k: client[k] for k in ("id", "full_name", "status")})


def main() -> None:
    parser = argparse.ArgumentParser(description="Демонстрация мини-CRM")
    parser.add_argument("--count", type=int, default=1000, help="сколько записей создать, если база пуста")
    parser.add_argument("--skip-crud", action="store_true", help="не показывать CRUD-операции")
    args = parser.parse_args()

    config = load_config()
    api = CRMClient(config.api_url)
    console.print(Panel.fit(
        f"[bold]Мини-CRM — демонстрация[/]\nAPI: {config.api_url}\nGoogle: [bold]{config.mode}[/]",
        border_style="cyan",
    ))

    step(1, "Проверка бэкенда")
    if not api.health():
        console.print(f"[red]Бэкенд недоступен по адресу {config.api_url}.[/]\n"
                      "Запустите его командой: [bold]docker compose up -d --build[/]")
        sys.exit(1)
    stats = api.stats()
    was_empty = stats["clients"]["total"] == 0
    console.print(f"[green]GET /health → ok[/]. В базе: клиентов {stats['clients']['total']}, "
                  f"сделок {stats['deals']['total']}, задач {stats['tasks']['total']}")

    if not args.skip_crud:
        step(2, "CRUD: создание, изменение, поиск, архивирование")
        demo_crud(api)

    step(3, "Тестовые данные")
    if was_empty:
        from fill_test_data import fill

        console.print(f"База была пуста — создаю по {args.count} клиентов, сделок и задач…")
        fill(config.api_url, args.count)
    else:
        console.print("База уже заполнена — пропускаю (заполнить заново: удалите data/crm.db и перезапустите контейнер).")
    show("GET /stats", api.stats())

    step(4, "Выгрузка отчётов в Google Drive" + (" (эмуляция)" if config.is_mock else ""))
    results = []
    for kind in ("clients", "deals", "tasks"):
        with console.status(f"{REPORT_TITLES[kind]}…") as status:
            result = export_report(kind, api, progress=lambda m: status.update(f"{REPORT_TITLES[kind]}: {m}"))
        console.print(f"[green]✓[/] {result.title}: строк — {result.rows}")
        results.append(result)

    deals = next(r for r in results if r.kind == "deals").analysis
    assert deals["count"] < 2 or deals["average_amount"] != deals["total_amount"], \
        "Средняя сумма сделки совпала с общей — ошибка расчёта!"

    step(5, "Итог")
    table = Table(title="Выгруженные отчёты", show_lines=True, expand=True)
    table.add_column("Отчёт", style="bold", no_wrap=True)
    table.add_column("ID таблицы", overflow="fold", max_width=24)
    table.caption = "В режиме mock: путь к локальной HTML-копии (её открывает «Открыть» в GUI) и ссылка в формате Google Sheets"
    table.add_column("Ссылка", overflow="fold")
    table.add_column("Ключевые метрики", overflow="fold")
    for r in results:
        link = r.link if r.link == r.web_view_link else f"{local_path(r.link)}\n[dim]{r.web_view_link}[/]"
        table.add_row(REPORT_TITLES[r.kind], r.spreadsheet_id, link, r.summary)
    console.print(table)

    files = get_drive(config).list_files()
    where = "папка ./mock_drive (журнал _drive_index.json)" if config.is_mock else "папка на Google Drive"
    console.print(f"Файлов в «папке на Диске»: {len(files)} — {where}")
    console.print(Panel.fit(
        f"Google работал в режиме [bold]{config.mode}[/] "
        + ("(эмуляция: отчёты — .xlsx и .html в ./mock_drive)." if config.is_mock
           else "(настоящие Google Drive API и Google Sheets API)."),
        border_style="green",
    ))


if __name__ == "__main__":
    try:
        main()
    except APIError as exc:
        console.print(f"[red]Ошибка API:[/] {exc}")
        sys.exit(1)
