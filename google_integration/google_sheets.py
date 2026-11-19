"""Работа с Google Sheets API v4."""

from __future__ import annotations

from googleapiclient.discovery import build

from google_integration.auth import get_credentials
from google_integration.config import GoogleConfig, load_config

HEADER_BG = {"red": 0.16, "green": 0.33, "blue": 0.55}
HEADER_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}
MONEY_PATTERN = '#,##0.00 "₽"'


def quote_sheet(title: str) -> str:
    """Имя листа в A1-нотации: кириллицу и пробелы нужно брать в кавычки."""
    return "'" + title.replace("'", "''") + "'"


class GoogleSheets:
    def __init__(self, config: GoogleConfig | None = None, credentials=None) -> None:
        self.config = config or load_config()
        creds = credentials or get_credentials(self.config)
        self.service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._api = self.service.spreadsheets()

    # ---------- листы ----------
    def _sheets(self, spreadsheet_id: str) -> list[dict]:
        meta = self._api.get(
            spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))"
        ).execute()
        return [s["properties"] for s in meta.get("sheets", [])]

    def _sheet_id(self, spreadsheet_id: str, title: str) -> int:
        for props in self._sheets(spreadsheet_id):
            if props["title"] == title:
                return props["sheetId"]
        raise KeyError(f"Лист «{title}» не найден в таблице {spreadsheet_id}")

    def _batch(self, spreadsheet_id: str, requests: list[dict]) -> dict:
        return self._api.batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    def add_sheet(self, spreadsheet_id: str, title: str) -> dict:
        resp = self._batch(spreadsheet_id, [{"addSheet": {"properties": {"title": title}}}])
        return resp["replies"][0]["addSheet"]["properties"]

    def ensure_sheets(self, spreadsheet_id: str, titles: list[str]) -> list[dict]:
        """Первый (стандартный) лист переименовывает в titles[0], остальные добавляет."""
        existing = self._sheets(spreadsheet_id)
        names = {s["title"] for s in existing}
        requests: list[dict] = []
        if titles and titles[0] not in names:
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": existing[0]["sheetId"], "title": titles[0]},
                        "fields": "title",
                    }
                }
            )
        for title in titles[1:]:
            if title not in names:
                requests.append({"addSheet": {"properties": {"title": title}}})
        if requests:
            self._batch(spreadsheet_id, requests)
        return self._sheets(spreadsheet_id)

    # ---------- данные ----------
    def write_values(self, spreadsheet_id: str, range_: str, values: list[list]) -> dict:
        """Записывает значения. range_ — 'Лист!A1' или просто имя листа."""
        sheet, _, cell = range_.partition("!")
        a1 = f"{quote_sheet(sheet)}!{cell or 'A1'}"
        return (
            self._api.values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=a1,
                valueInputOption="RAW",  # без интерпретации: «+7 900…» не станет формулой
                body={"values": values},
            )
            .execute()
        )

    def read_values(self, spreadsheet_id: str, range_: str) -> list[list]:
        sheet, _, cell = range_.partition("!")
        a1 = quote_sheet(sheet) + (f"!{cell}" if cell else "")
        resp = self._api.values().get(spreadsheetId=spreadsheet_id, range=a1).execute()
        return resp.get("values", [])

    # ---------- оформление ----------
    def format_header(
        self,
        spreadsheet_id: str,
        sheet_title: str,
        money_columns: list[int] | None = None,
    ) -> dict:
        """Жирная цветная шапка, закреплённая первая строка, денежный формат колонок."""
        sheet_id = self._sheet_id(spreadsheet_id, sheet_title)
        requests: list[dict] = [
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": HEADER_BG,
                            "horizontalAlignment": "CENTER",
                            "textFormat": {"bold": True, "foregroundColor": HEADER_FG},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }
            },
        ]
        for col in money_columns or []:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "startColumnIndex": col,
                            "endColumnIndex": col + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {"type": "CURRENCY", "pattern": MONEY_PATTERN}
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }
            )
        return self._batch(spreadsheet_id, requests)

    def auto_resize(self, spreadsheet_id: str, sheet_title: str, columns: int) -> dict:
        sheet_id = self._sheet_id(spreadsheet_id, sheet_title)
        return self._batch(
            spreadsheet_id,
            [
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": columns,
                        }
                    }
                }
            ],
        )
