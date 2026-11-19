"""Интеграция с Google Drive и Google Sheets.

Фабрики get_drive() и get_sheets() возвращают настоящие клиенты API или эмуляцию
в зависимости от GOOGLE_MODE (.env). Остальной код не знает, какой режим включён.
"""

from __future__ import annotations

from google_integration.config import GoogleConfig, load_config


def get_mode() -> str:
    return load_config().mode


def get_drive(config: GoogleConfig | None = None):
    config = config or load_config()
    if config.is_mock:
        from google_integration.mock_google import MockGoogleDrive

        return MockGoogleDrive(config)
    from google_integration.google_drive import GoogleDrive

    return GoogleDrive(config)


def get_sheets(config: GoogleConfig | None = None):
    config = config or load_config()
    if config.is_mock:
        from google_integration.mock_google import MockGoogleSheets

        return MockGoogleSheets(config)
    from google_integration.google_sheets import GoogleSheets

    return GoogleSheets(config)


__all__ = ["get_drive", "get_sheets", "get_mode", "load_config"]
