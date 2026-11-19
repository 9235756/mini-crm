"""Отчёты: сбор данных из API, аналитика в Python и выгрузка в Google Drive/Sheets.

Модуль не знает, работает он с настоящим Google или с эмуляцией: всё идёт
через фабрики google_integration.get_drive() / get_sheets().
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from google_integration import get_drive, get_sheets, load_config
from gui.api_client import CRMClient

CLIENT_STATUS_RU = {"active": "Активный", "lead": "Лид", "archived": "В архиве"}
DEAL_STATUS_RU = {"new": "Новая", "in_progress": "В работе", "won": "Выиграна", "lost": "Проиграна"}

REPORT_TITLES = {"clients": "Отчёт по клиентам", "deals": "Отчёт по сделкам", "tasks": "Отчёт по задачам"}
DATA_SHEET = "Данные"
ANALYTICS_SHEET = "Аналитика"

Progress = Callable[[str], None]


# ======================= аналитика =======================
def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def analyze_clients(clients: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    border = today - timedelta(days=30)
    companies = Counter(c["company"].strip() for c in clients if (c.get("company") or "").strip())
    with_company = sum(1 for c in clients if (c.get("company") or "").strip())
    by_status = Counter(c.get("status") for c in clients)
    new_30 = sum(
        1 for c in clients if (d := _parse_date(c.get("created_at"))) and border <= d <= today
    )
    return {
        "total": len(clients),
        "by_status": {s: by_status.get(s, 0) for s in CLIENT_STATUS_RU},
        "with_company": with_company,
        "without_company": len(clients) - with_company,
        "top_companies": companies.most_common(5),
        "new_last_30_days": new_30,
    }


def analyze_deals(deals: list[dict]) -> dict:
    amounts = [float(d.get("amount") or 0) for d in deals]
    count = len(amounts)
    total = sum(amounts)
    # Средняя = общая сумма / количество сделок (в уроке среднее ошибочно совпадало с общей)
    average = total / count if count else 0.0
    median = statistics.median(amounts) if amounts else 0.0

    by_status: dict[str, dict] = {s: {"count": 0, "sum": 0.0} for s in DEAL_STATUS_RU}
    for d in deals:
        bucket = by_status.setdefault(d.get("status"), {"count": 0, "sum": 0.0})
        bucket["count"] += 1
        bucket["sum"] += float(d.get("amount") or 0)

    won, lost = by_status["won"]["count"], by_status["lost"]["count"]
    per_client: dict[str, float] = defaultdict(float)
    for d in deals:
        if d.get("client_id") is not None:
            name = d.get("client_name") or f"Клиент #{d['client_id']}"
            per_client[f"{name} (#{d['client_id']})"] += float(d.get("amount") or 0)
    top = sorted(per_client.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "count": count,
        "total_amount": round(total, 2),
        "average_amount": round(average, 2),
        "median_amount": round(median, 2),
        "by_status": {k: {"count": v["count"], "sum": round(v["sum"], 2)} for k, v in by_status.items()},
        "conversion_pct": _pct(won, won + lost),
        "without_client": sum(1 for d in deals if d.get("client_id") is None),
        "top_clients": [(name, round(s, 2)) for name, s in top],
    }


def analyze_tasks(tasks: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    total = len(tasks)
    done = sum(1 for t in tasks if t.get("is_done"))
    overdue = sum(
        1
        for t in tasks
        if not t.get("is_done") and (d := _parse_date(t.get("due_date"))) and d < today
    )
    return {
        "total": total,
        "done": done,
        "not_done": total - done,
        "done_pct": _pct(done, total),
        "overdue": overdue,
        "linked_to_client": sum(1 for t in tasks if t.get("client_id") is not None),
        "linked_to_deal": sum(1 for t in tasks if t.get("deal_id") is not None),
        "unlinked": sum(1 for t in tasks if t.get("client_id") is None and t.get("deal_id") is None),
    }


# ======================= табличное представление =======================
def _num(x: float) -> str:
    """42.1 -> «42,1» (десятичная запятая)."""
    return f"{x:g}".replace(".", ",")


def local_path(link: str) -> str:
    """file:///…/%D0%9E… -> читаемый путь; прочие ссылки — без изменений."""
    if not link.startswith("file://"):
        return link
    from urllib.parse import unquote, urlparse

    path = unquote(urlparse(link).path)
    return path[1:] if len(path) > 2 and path[2] == ":" else path  # /C:/… -> C:/… на Windows


def _money(x: float) -> str:
    """1234567.5 -> «1 234 567,50 ₽» (неразрывные пробелы)."""
    return f"{x:,.2f}".replace(",", "\u00a0").replace(".", ",") + "\u00a0₽"


def analytics_rows(kind: str, a: dict) -> list[list]:
    """Лист «Аналитика»: строки [Показатель, Значение]; строка без значения — заголовок раздела."""
    rows: list[list] = [["Показатель", "Значение"]]
    if kind == "clients":
        rows += [
            ["Общее", ""],
            ["Всего клиентов", a["total"]],
            ["Новые за последние 30 дней", a["new_last_30_days"]],
            ["С компанией", a["with_company"]],
            ["Без компании", a["without_company"]],
            ["По статусам", ""],
            *[[CLIENT_STATUS_RU[s], n] for s, n in a["by_status"].items()],
            ["Топ-5 компаний (по числу клиентов)", ""],
            *[[name, n] for name, n in a["top_companies"]],
        ]
    elif kind == "deals":
        rows += [
            ["Общее", ""],
            ["Количество сделок", a["count"]],
            ["Общая сумма", _money(a["total_amount"])],
            ["Средняя сумма сделки", _money(a["average_amount"])],
            ["Медиана суммы", _money(a["median_amount"])],
            ["Конверсия won / (won + lost)", f"{_num(a['conversion_pct'])}\u00a0%"],
            ["Сделок без клиента", a["without_client"]],
            ["По статусам: количество / сумма", ""],
            *[
                [DEAL_STATUS_RU.get(s, s), f"{v['count']} шт. / {_money(v['sum'])}"]
                for s, v in a["by_status"].items()
            ],
            ["Топ-5 клиентов по сумме сделок", ""],
            *[[name, _money(s)] for name, s in a["top_clients"]],
        ]
    elif kind == "tasks":
        rows += [
            ["Общее", ""],
            ["Всего задач", a["total"]],
            ["Выполнено", a["done"]],
            ["Не выполнено", a["not_done"]],
            ["Процент выполнения", f"{_num(a['done_pct'])}\u00a0%"],
            ["Просрочено (срок прошёл, не выполнены)", a["overdue"]],
            ["Привязка", ""],
            ["Привязаны к клиенту", a["linked_to_client"]],
            ["Привязаны к сделке", a["linked_to_deal"]],
            ["Без привязки", a["unlinked"]],
        ]
    else:
        raise ValueError(f"Неизвестный тип отчёта: {kind}")
    return rows


def data_rows(kind: str, items: list[dict]) -> tuple[list[list], list[int]]:
    """Лист «Данные»: шапка + строки и индексы денежных колонок."""
    if kind == "clients":
        header = ["ID", "ФИО", "Компания", "Email", "Телефон", "Статус", "Заметки", "Создан"]
        rows = [
            [c["id"], c["full_name"], c.get("company") or "", c.get("email") or "",
             c.get("phone") or "", CLIENT_STATUS_RU.get(c["status"], c["status"]),
             c.get("notes") or "", c["created_at"].replace("T", " ")]
            for c in items
        ]
        return [header, *rows], []
    if kind == "deals":
        header = ["ID", "Название", "ID клиента", "Клиент", "Сумма", "Валюта", "Статус",
                  "Дата закрытия", "Создана"]
        rows = [
            [d["id"], d["title"], d.get("client_id") or "", d.get("client_name") or "",
             float(d.get("amount") or 0), d.get("currency") or "RUB",
             DEAL_STATUS_RU.get(d["status"], d["status"]), d.get("close_date") or "", d["created_at"].replace("T", " ")]
            for d in items
        ]
        return [header, *rows], [4]
    if kind == "tasks":
        header = ["ID", "Задача", "Описание", "Срок", "Выполнена", "ID клиента", "ID сделки", "Создана"]
        rows = [
            [t["id"], t["title"], t.get("description") or "", t.get("due_date") or "",
             "Да" if t.get("is_done") else "Нет", t.get("client_id") or "",
             t.get("deal_id") or "", t["created_at"].replace("T", " ")]
            for t in items
        ]
        return [header, *rows], []
    raise ValueError(f"Неизвестный тип отчёта: {kind}")


ANALYZERS = {"clients": analyze_clients, "deals": analyze_deals, "tasks": analyze_tasks}


def key_metrics(kind: str, a: dict) -> str:
    if kind == "clients":
        return f"всего {a['total']}, активных {a['by_status']['active']}, новых за 30 дн. {a['new_last_30_days']}"
    if kind == "deals":
        return (f"сделок: {a['count']}, сумма {_money(a['total_amount'])}, "
                f"средняя {_money(a['average_amount'])}, конверсия {_num(a['conversion_pct'])} %")
    return f"всего {a['total']}, выполнено {_num(a['done_pct'])} %, просрочено {a['overdue']}"


# ======================= выгрузка =======================
@dataclass
class ReportResult:
    kind: str
    title: str
    spreadsheet_id: str
    link: str            # то, что открывает кнопка «Открыть» (в mock — file:///…html)
    web_view_link: str   # ссылка в формате Google Sheets
    rows: int
    mode: str
    analysis: dict = field(default_factory=dict)

    @property
    def summary(self) -> str:
        return key_metrics(self.kind, self.analysis)


def export_report(
    kind: str,
    client: CRMClient | None = None,
    progress: Progress | None = None,
) -> ReportResult:
    """Собирает все записи сущности, считает аналитику и создаёт Google-таблицу."""
    if kind not in REPORT_TITLES:
        raise ValueError(f"Неизвестный тип отчёта: {kind}")
    say = progress or (lambda _msg: None)
    config = load_config()
    client = client or CRMClient(config.api_url)

    say("Загрузка записей из API…")
    items = client.fetch_all(kind, progress=lambda got, total: say(f"Загружено {got} из {total}"))

    say("Расчёт аналитики…")
    analysis = ANALYZERS[kind](items)
    data, money_cols = data_rows(kind, items)
    analytics = analytics_rows(kind, analysis)

    say("Создание таблицы в Google Drive…")
    drive, sheets = get_drive(config), get_sheets(config)
    title = f"{REPORT_TITLES[kind]} {datetime.now():%Y-%m-%d %H:%M}"
    meta = drive.create_spreadsheet(title, config.folder_id)
    sid = meta["id"]

    say("Запись данных…")
    sheets.ensure_sheets(sid, [DATA_SHEET, ANALYTICS_SHEET])
    sheets.write_values(sid, f"{DATA_SHEET}!A1", data)
    sheets.write_values(sid, f"{ANALYTICS_SHEET}!A1", analytics)

    say("Оформление…")
    sheets.format_header(sid, DATA_SHEET, money_columns=money_cols)
    sheets.format_header(sid, ANALYTICS_SHEET)
    sheets.auto_resize(sid, DATA_SHEET, len(data[0]))
    sheets.auto_resize(sid, ANALYTICS_SHEET, 2)

    link = drive.get_file_link(sid)
    say("Готово")
    return ReportResult(
        kind=kind,
        title=title,
        spreadsheet_id=sid,
        link=link,
        web_view_link=meta.get("webViewLink", link),
        rows=len(items),
        mode=config.mode,
        analysis=analysis,
    )
