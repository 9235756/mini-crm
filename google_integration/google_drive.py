"""Работа с Google Drive API v3."""

from __future__ import annotations

from googleapiclient.discovery import build

from google_integration.auth import get_credentials
from google_integration.config import GoogleConfig, load_config

SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_FIELDS = "id, name, mimeType, parents, webViewLink, createdTime"


class GoogleDrive:
    def __init__(self, config: GoogleConfig | None = None, credentials=None) -> None:
        self.config = config or load_config()
        creds = credentials or get_credentials(self.config)
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def create_spreadsheet(self, title: str, folder_id: str | None = None) -> dict:
        """Создаёт Google-таблицу в папке. Возвращает метаданные файла Drive."""
        body: dict = {"name": title, "mimeType": SPREADSHEET_MIME}
        parent = folder_id or self.config.folder_id
        if parent:
            body["parents"] = [parent]
        return (
            self.service.files()
            .create(body=body, fields=FILE_FIELDS, supportsAllDrives=True)
            .execute()
        )

    def create_folder(self, name: str, parent_id: str | None = None) -> dict:
        body: dict = {"name": name, "mimeType": FOLDER_MIME}
        parent = parent_id or self.config.folder_id
        if parent:
            body["parents"] = [parent]
        return (
            self.service.files()
            .create(body=body, fields=FILE_FIELDS, supportsAllDrives=True)
            .execute()
        )

    def list_files(self, folder_id: str | None = None, page_size: int = 100) -> list[dict]:
        """Файлы в папке (без удалённых), новые сверху."""
        parent = folder_id or self.config.folder_id
        query = "trashed = false"
        if parent:
            query += f" and '{parent}' in parents"
        files: list[dict] = []
        token = None
        while True:
            resp = (
                self.service.files()
                .list(
                    q=query,
                    pageSize=page_size,
                    pageToken=token,
                    orderBy="createdTime desc",
                    fields=f"nextPageToken, files({FILE_FIELDS})",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            files.extend(resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                return files

    def get_file_link(self, file_id: str) -> str:
        meta = (
            self.service.files()
            .get(fileId=file_id, fields="webViewLink", supportsAllDrives=True)
            .execute()
        )
        return meta["webViewLink"]
