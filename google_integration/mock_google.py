"""Эмуляция Google Drive и Google Sheets с тем же интерфейсом, что у реальных классов.

Ответы имеют тот же формат, что у Drive API v3 и Sheets API v4. Фактически
каждая «таблица» хранится в ./mock_drive:
  * <title>_<дата>.xlsx — отформатированная копия (openpyxl);
  * <title>_<дата>.html — HTML-страница с аналитикой и данными (её открывает «Открыть»);
  * _data/<id>.json     — содержимое листов и оформление (для read_values);
  * _drive_index.json   — журнал «папки на Диске»: id → имя, пути, ссылки, дата.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from google_integration.config import MOCK_DRIVE_DIR, GoogleConfig, load_config

SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
MOCK_ROOT_FOLDER = "mock-root-folder"
DEFAULT_SHEET = "Лист1"
MONEY_FORMAT = '#,##0.00 "₽"'

_LOCK = threading.RLock()


# ---------- служебное ----------
def _google_like_id() -> str:
    """44 символа base64url — как у ID файлов Google Drive."""
    return base64.urlsafe_b64encode(os.urandom(33)).decode("ascii")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _safe_name(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", title).strip(" .")
    return re.sub(r"\s+", "_", name) or "untitled"


def _col_letter(n: int) -> str:
    return get_column_letter(max(n, 1))


class _Store:
    """Файловое хранилище эмулятора (общее для MockDrive и MockSheets)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.data_dir = root / "_data"
        self.index_file = root / "_drive_index.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_index(self) -> dict:
        if not self.index_file.exists():
            return {}
        return json.loads(self.index_file.read_text(encoding="utf-8"))

    def save_index(self, index: dict) -> None:
        tmp = self.index_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_file)

    def entry(self, file_id: str) -> dict:
        index = self.load_index()
        if file_id not in index:
            raise KeyError(f"Файл {file_id} не найден в эмулированном Google Drive")
        return index[file_id]

    def load_doc(self, file_id: str) -> dict:
        path = self.data_dir / f"{file_id}.json"
        if not path.exists():
            raise KeyError(f"Таблица {file_id} не найдена в эмулированном Google Drive")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_doc(self, file_id: str, doc: dict) -> None:
        path = self.data_dir / f"{file_id}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


# ---------- Drive ----------
class MockGoogleDrive:
    """Тот же интерфейс, что у google_drive.GoogleDrive."""

    def __init__(self, config: GoogleConfig | None = None, root: Path | None = None) -> None:
        self.config = config or load_config()
        self.store = _Store(root or MOCK_DRIVE_DIR)

    def _parent(self, folder_id: str | None) -> str:
        return folder_id or self.config.folder_id or MOCK_ROOT_FOLDER

    def create_spreadsheet(self, title: str, folder_id: str | None = None) -> dict:
        with _LOCK:
            file_id = _google_like_id()
            base = _safe_name(title)
            if not re.search(r"\d{4}-\d{2}-\d{2}", title):  # дата в имени — как <title>_<дата>
                base += datetime.now().strftime("_%Y-%m-%d_%H-%M-%S")
            candidate, n = base, 2
            while (self.store.root / f"{candidate}.html").exists():
                candidate, n = f"{base}_{n}", n + 1
            xlsx_path = self.store.root / f"{candidate}.xlsx"
            html_path = self.store.root / f"{candidate}.html"
            meta = {
                "id": file_id,
                "name": title,
                "mimeType": SPREADSHEET_MIME,
                "parents": [self._parent(folder_id)],
                "webViewLink": f"https://docs.google.com/spreadsheets/d/{file_id}/edit",
                "createdTime": _iso_now(),
            }
            doc = {"title": title, "sheets": {DEFAULT_SHEET: []}, "formats": {}}
            self.store.save_doc(file_id, doc)
            index = self.store.load_index()
            index[file_id] = {
                **meta,
                "xlsx_path": str(xlsx_path),
                "html_path": str(html_path),
                "local_link": html_path.resolve().as_uri(),
            }
            self.store.save_index(index)
            _render(self.store, file_id)
            return meta

    def create_folder(self, name: str, parent_id: str | None = None) -> dict:
        with _LOCK:
            file_id = _google_like_id()
            folder_path = self.store.root / _safe_name(name)
            folder_path.mkdir(parents=True, exist_ok=True)
            meta = {
                "id": file_id,
                "name": name,
                "mimeType": FOLDER_MIME,
                "parents": [self._parent(parent_id)],
                "webViewLink": f"https://drive.google.com/drive/folders/{file_id}",
                "createdTime": _iso_now(),
            }
            index = self.store.load_index()
            index[file_id] = {**meta, "local_link": folder_path.resolve().as_uri()}
            self.store.save_index(index)
            return meta

    def list_files(self, folder_id: str | None = None, page_size: int = 100) -> list[dict]:
        parent = self._parent(folder_id)
        keys = ("id", "name", "mimeType", "parents", "webViewLink", "createdTime")
        files = [
            {k: e[k] for k in keys}
            for e in self.store.load_index().values()
            if parent in e.get("parents", [])
        ]
        return sorted(files, key=lambda f: f["createdTime"], reverse=True)

    def get_file_link(self, file_id: str) -> str:
        """В эмуляции — file:///…html, его открывает кнопка «Открыть»."""
        return self.store.entry(file_id)["local_link"]


# ---------- Sheets ----------
_A1 = re.compile(r"^([A-Z]+)(\d+)$")
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _parse_range(range_: str) -> tuple[str, int, int]:
    """'Данные!B3' -> ('Данные', row0=2, col0=1). Кавычки вокруг имени листа допускаются."""
    sheet, _, cell = range_.partition("!")
    sheet = sheet.strip()
    if len(sheet) >= 2 and sheet[0] == sheet[-1] == "'":
        sheet = sheet[1:-1].replace("''", "'")
    cell = (cell or "A1").split(":")[0].upper()
    m = _A1.match(cell)
    if not m:
        raise ValueError(f"Неподдерживаемый диапазон: {range_!r}")
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - 64)
    return sheet, int(m.group(2)) - 1, col - 1


class MockGoogleSheets:
    """Тот же интерфейс, что у google_sheets.GoogleSheets."""

    def __init__(self, config: GoogleConfig | None = None, root: Path | None = None) -> None:
        self.config = config or load_config()
        self.store = _Store(root or MOCK_DRIVE_DIR)

    def _props(self, doc: dict) -> list[dict]:
        return [{"sheetId": i, "title": t} for i, t in enumerate(doc["sheets"])]

    def add_sheet(self, spreadsheet_id: str, title: str) -> dict:
        with _LOCK:
            doc = self.store.load_doc(spreadsheet_id)
            if title in doc["sheets"]:
                raise ValueError(f"Лист «{title}» уже существует")
            doc["sheets"][title] = []
            self.store.save_doc(spreadsheet_id, doc)
            _render(self.store, spreadsheet_id)
            props = self._props(doc)[-1]
            return {**props, "index": props["sheetId"], "sheetType": "GRID"}

    def ensure_sheets(self, spreadsheet_id: str, titles: list[str]) -> list[dict]:
        with _LOCK:
            doc = self.store.load_doc(spreadsheet_id)
            sheets = doc["sheets"]
            if titles and titles[0] not in sheets:
                first = next(iter(sheets))
                sheets = {(titles[0] if k == first else k): v for k, v in sheets.items()}
            for title in titles[1:]:
                sheets.setdefault(title, [])
            doc["sheets"] = sheets
            self.store.save_doc(spreadsheet_id, doc)
            _render(self.store, spreadsheet_id)
            return self._props(doc)

    def write_values(self, spreadsheet_id: str, range_: str, values: list[list]) -> dict:
        with _LOCK:
            doc = self.store.load_doc(spreadsheet_id)
            sheet, row0, col0 = _parse_range(range_)
            if sheet not in doc["sheets"]:
                raise KeyError(f"Лист «{sheet}» не найден")
            grid: list[list] = doc["sheets"][sheet]
            for r, row in enumerate(values):
                while len(grid) <= row0 + r:
                    grid.append([])
                target = grid[row0 + r]
                while len(target) < col0 + len(row):
                    target.append(None)
                for c, value in enumerate(row):
                    target[col0 + c] = value
            self.store.save_doc(spreadsheet_id, doc)
            _render(self.store, spreadsheet_id)

            rows = len(values)
            cols = max((len(r) for r in values), default=0)
            end = f"{_col_letter(col0 + cols)}{row0 + rows}"
            return {
                "spreadsheetId": spreadsheet_id,
                "updatedRange": f"{sheet}!{_col_letter(col0 + 1)}{row0 + 1}:{end}",
                "updatedRows": rows,
                "updatedColumns": cols,
                "updatedCells": sum(len(r) for r in values),
            }

    def read_values(self, spreadsheet_id: str, range_: str) -> list[list]:
        doc = self.store.load_doc(spreadsheet_id)
        sheet, row0, col0 = _parse_range(range_)
        grid = doc["sheets"].get(sheet)
        if grid is None:
            raise KeyError(f"Лист «{sheet}» не найден")
        # Как и Sheets API: хвостовые пустые ячейки отбрасываются
        result = []
        for row in grid[row0:]:
            part = list(row[col0:])
            while part and part[-1] in (None, ""):
                part.pop()
            result.append(part)
        while result and not result[-1]:
            result.pop()
        return result

    def format_header(
        self,
        spreadsheet_id: str,
        sheet_title: str,
        money_columns: list[int] | None = None,
    ) -> dict:
        with _LOCK:
            doc = self.store.load_doc(spreadsheet_id)
            if sheet_title not in doc["sheets"]:
                raise KeyError(f"Лист «{sheet_title}» не найден")
            fmt = doc["formats"].setdefault(sheet_title, {})
            fmt["header"] = True
            fmt["money_columns"] = sorted(set(money_columns or []))
            self.store.save_doc(spreadsheet_id, doc)
            _render(self.store, spreadsheet_id)
            replies = 2 + len(fmt["money_columns"])
            return {"spreadsheetId": spreadsheet_id, "replies": [{} for _ in range(replies)]}

    def auto_resize(self, spreadsheet_id: str, sheet_title: str, columns: int) -> dict:
        with _LOCK:
            doc = self.store.load_doc(spreadsheet_id)
            doc["formats"].setdefault(sheet_title, {})["auto_resize"] = columns
            self.store.save_doc(spreadsheet_id, doc)
            _render(self.store, spreadsheet_id)
            return {"spreadsheetId": spreadsheet_id, "replies": [{}]}


# ---------- рендер .xlsx и .html ----------
HEADER_FILL = PatternFill("solid", fgColor="29548C")
HEADER_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="D5DCE6")


def _render(store: _Store, file_id: str) -> None:
    entry = store.entry(file_id)
    doc = store.load_doc(file_id)
    _render_xlsx(Path(entry["xlsx_path"]), doc)
    _render_html(Path(entry["html_path"]), doc, entry)


def _render_xlsx(path: Path, doc: dict) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    for title, grid in doc["sheets"].items():
        ws = wb.create_sheet(title=title[:31])
        fmt = doc["formats"].get(title, {})
        money = {c + 1 for c in fmt.get("money_columns", [])}
        for row in grid:
            ws.append(row)
        if fmt.get("header") and grid:
            for cell in ws[1]:
                cell.fill = HEADER_FILL
                cell.font = HEADER_FONT
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = Border(bottom=THIN)
            ws.freeze_panes = "A2"
        for col in money:
            for (cell,) in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                if isinstance(cell.value, (int, float)):
                    cell.number_format = MONEY_FORMAT
        # автоширина
        widths: dict[int, int] = {}
        for row in grid:
            for i, value in enumerate(row, start=1):
                text = f"{value:,.2f} ₽" if i in money and isinstance(value, (int, float)) else str(value or "")
                widths[i] = max(widths.get(i, 0), len(text))
        for i, w in widths.items():
            ws.column_dimensions[get_column_letter(i)].width = min(max(w + 2, 8), 60)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _fmt_cell(value, is_money: bool) -> str:
    if value is None:
        return ""
    if is_money and isinstance(value, (int, float)):
        return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return html.escape(str(value))


_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--muted:#5b6675;--line:#e3e7ed;--accent:#29548c;--zebra:#fafbfc}
@media (prefers-color-scheme:dark){:root{--bg:#12161c;--card:#1a2029;--ink:#e6eaf0;--muted:#9aa6b5;--line:#2a323d;--accent:#6d9bd6;--zebra:#1d242e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:32px 16px 64px}
header{display:flex;flex-wrap:wrap;gap:8px 24px;align-items:baseline;justify-content:space-between;border-bottom:2px solid var(--accent);padding-bottom:12px;margin-bottom:24px}
h1{font-size:26px;margin:0;letter-spacing:-.01em}
.meta{color:var(--muted);font-size:13px}
.meta code{font-size:12px}
h2{font-size:18px;margin:32px 0 12px}
.metrics{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:0;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.metrics .sec{grid-column:1/-1;padding:10px 16px;font-weight:600;color:var(--accent);background:var(--zebra);border-top:1px solid var(--line)}
.metrics .sec:first-child{border-top:0}
.metrics .m{display:flex;justify-content:space-between;gap:12px;padding:8px 16px;border-top:1px solid var(--line)}
.metrics .m span:last-child{font-variant-numeric:tabular-nums;font-weight:600;text-align:right;white-space:nowrap}
.tbl{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:auto;max-height:75vh}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{position:sticky;top:0;background:var(--accent);color:#fff;text-align:left;padding:8px 10px;white-space:nowrap}
td{padding:6px 10px;border-top:1px solid var(--line);vertical-align:top}
td.nw{white-space:nowrap}
tr:nth-child(even) td{background:var(--zebra)}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.note{color:var(--muted);font-size:12px;margin-top:24px}
"""


def _render_metrics(grid: list[list]) -> str:
    out = ['<div class="metrics">']
    for row in grid[1:] if grid and grid[0][:1] == ["Показатель"] else grid:
        cells = list(row) + [None, None]
        label, value = cells[0], cells[1]
        if label in (None, ""):
            continue
        if value in (None, ""):
            out.append(f'<div class="sec">{html.escape(str(label))}</div>')
        else:
            out.append(
                f'<div class="m"><span>{html.escape(str(label))}</span>'
                f"<span>{_fmt_cell(value, False)}</span></div>"
            )
    out.append("</div>")
    return "".join(out)


def _render_table(grid: list[list], money: set[int]) -> str:
    if not grid:
        return '<p class="meta">Лист пуст.</p>'
    head = "".join(f"<th>{html.escape(str(h or ''))}</th>" for h in grid[0])
    body = []
    for row in grid[1:]:
        tds = []
        for i, value in enumerate(row):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cls = ' class="num"'
            elif isinstance(value, str) and _DATE_LIKE.match(value):
                cls = ' class="nw"'
            else:
                cls = ""
            tds.append(f"<td{cls}>{_fmt_cell(value, i in money)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _render_html(path: Path, doc: dict, entry: dict) -> None:
    sections = []
    # Аналитика — первой, затем остальные листы
    order = sorted(doc["sheets"], key=lambda t: 0 if t == "Аналитика" else 1)
    for title in order:
        grid = doc["sheets"][title]
        fmt = doc["formats"].get(title, {})
        if title == "Аналитика":
            body = _render_metrics(grid)
        else:
            body = _render_table(grid, set(fmt.get("money_columns", [])))
        rows = max(len(grid) - 1, 0)
        caption = f" · строк: {rows}" if title != "Аналитика" and grid else ""
        sections.append(f"<h2>{html.escape(title)}{caption}</h2>{body}")

    title = html.escape(doc["title"])
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header><h1>{title}</h1>
<div class="meta">Создан {html.escape(entry["createdTime"])} · ID <code>{html.escape(entry["id"])}</code></div></header>
{"".join(sections)}
<p class="note">Эмуляция Google Sheets (GOOGLE_MODE=mock). Копия в Excel: {html.escape(Path(entry["xlsx_path"]).name)}.
В режиме real отчёт открывается по ссылке {html.escape(entry["webViewLink"])}.</p>
</div></body></html>"""
    path.write_text(page, encoding="utf-8")
