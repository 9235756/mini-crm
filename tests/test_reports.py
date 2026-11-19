"""Юнит-тесты аналитики отчётов и эмулятора Google."""

from datetime import date

import pytest

from gui.reports import analytics_rows, analyze_clients, analyze_deals, analyze_tasks, data_rows

TODAY = date(2026, 11, 19)


def deal(amount, status="new", client_id=None, client_name=None):
    return {"id": 1, "title": "x", "amount": amount, "status": status,
            "client_id": client_id, "client_name": client_name, "created_at": "2026-01-01T00:00:00"}


# ---------- сделки ----------
def test_average_is_total_divided_by_count():
    deals = [deal(100_000), deal(200_000), deal(600_000)]
    a = analyze_deals(deals)
    assert a["total_amount"] == 900_000
    assert a["average_amount"] == 300_000
    assert a["average_amount"] != a["total_amount"]  # ошибка из урока: среднее = общая сумма


def test_average_rounding_and_median():
    a = analyze_deals([deal(10), deal(20), deal(25)])
    assert a["average_amount"] == pytest.approx(18.33, abs=0.01)
    assert a["median_amount"] == 20


def test_empty_deals_do_not_divide_by_zero():
    a = analyze_deals([])
    assert a["count"] == 0 and a["average_amount"] == 0 and a["conversion_pct"] == 0


def test_conversion_and_statuses():
    deals = [deal(100, "won"), deal(100, "won"), deal(100, "won"), deal(50, "lost"), deal(70, "new")]
    a = analyze_deals(deals)
    assert a["conversion_pct"] == 75.0
    assert a["by_status"]["won"] == {"count": 3, "sum": 300}
    assert a["by_status"]["in_progress"] == {"count": 0, "sum": 0}


def test_without_client_and_top_clients():
    deals = [deal(100, client_id=1, client_name="Иванов"), deal(500, client_id=2, client_name="Петров"),
             deal(300, client_id=1, client_name="Иванов"), deal(999)]
    a = analyze_deals(deals)
    assert a["without_client"] == 1
    assert a["top_clients"][0] == ("Петров (#2)", 500)
    assert a["top_clients"][1] == ("Иванов (#1)", 400)


# ---------- клиенты ----------
def test_clients_analysis():
    clients = [
        {"status": "active", "company": "ООО «А»", "created_at": "2026-11-10T10:00:00"},
        {"status": "active", "company": "ООО «А»", "created_at": "2026-01-10T10:00:00"},
        {"status": "lead", "company": "", "created_at": "2026-10-25T10:00:00"},
        {"status": "archived", "company": None, "created_at": "2025-10-25T10:00:00"},
    ]
    a = analyze_clients(clients, today=TODAY)
    assert a["total"] == 4
    assert a["by_status"] == {"active": 2, "lead": 1, "archived": 1}
    assert a["with_company"] == 2 and a["without_company"] == 2
    assert a["top_companies"] == [("ООО «А»", 2)]
    assert a["new_last_30_days"] == 2


# ---------- задачи ----------
def test_tasks_analysis():
    tasks = [
        {"is_done": 1, "due_date": "2026-11-01", "client_id": 1, "deal_id": None},
        {"is_done": 0, "due_date": "2026-11-01", "client_id": None, "deal_id": 5},   # просрочена
        {"is_done": 0, "due_date": "2026-12-01", "client_id": None, "deal_id": None},
        {"is_done": 0, "due_date": None, "client_id": 2, "deal_id": 3},
    ]
    a = analyze_tasks(tasks, today=TODAY)
    assert a["total"] == 4 and a["done"] == 1 and a["not_done"] == 3
    assert a["done_pct"] == 25.0
    assert a["overdue"] == 1
    assert a["linked_to_client"] == 2 and a["linked_to_deal"] == 2 and a["unlinked"] == 1


# ---------- табличное представление ----------
def test_rows_have_header_and_money_column():
    rows, money = data_rows("deals", [deal(1500.5, client_id=1, client_name="Иванов")])
    assert rows[0][4] == "Сумма" and money == [4]
    assert rows[1][4] == 1500.5
    analytics = analytics_rows("deals", analyze_deals([deal(100), deal(300)]))
    labels = {r[0]: r[1] for r in analytics}
    assert labels["Средняя сумма сделки"] == "200,00\u00a0₽"
    assert labels["Общая сумма"] == "400,00\u00a0₽"


# ---------- эмулятор ----------
def test_mock_google_formats(tmp_path):
    from google_integration.config import load_config
    from google_integration.mock_google import MockGoogleDrive, MockGoogleSheets

    cfg = load_config()
    drive, sheets = MockGoogleDrive(cfg, root=tmp_path), MockGoogleSheets(cfg, root=tmp_path)
    meta = drive.create_spreadsheet("Тест", "folder123")
    assert len(meta["id"]) == 44
    assert meta["mimeType"] == "application/vnd.google-apps.spreadsheet"
    assert meta["webViewLink"] == f"https://docs.google.com/spreadsheets/d/{meta['id']}/edit"
    assert meta["parents"] == ["folder123"]

    sheets.ensure_sheets(meta["id"], ["Данные", "Аналитика"])
    resp = sheets.write_values(meta["id"], "Данные!A1", [["a", "b", "c"], [1, 2, 3]])
    assert resp == {"spreadsheetId": meta["id"], "updatedRange": "Данные!A1:C2",
                    "updatedRows": 2, "updatedColumns": 3, "updatedCells": 6}
    assert sheets.read_values(meta["id"], "'Данные'!A1") == [["a", "b", "c"], [1, 2, 3]]
    sheets.format_header(meta["id"], "Данные", money_columns=[1])

    link = drive.get_file_link(meta["id"])
    assert link.startswith("file://") and link.endswith(".html")
    assert any(p.suffix == ".xlsx" for p in tmp_path.iterdir())
    assert [f["id"] for f in drive.list_files("folder123")] == [meta["id"]]
