"""Настройки Google: .env + config/settings.txt (сохраняется из GUI).

Приоритет: значения из config/settings.txt (заданы пользователем в окне
«Настройки Google») перекрывают значения из .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = PROJECT_ROOT / "config" / "settings.txt"
MOCK_DRIVE_DIR = PROJECT_ROOT / "mock_drive"

DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
)

# Ключи settings.txt -> переменные окружения
_SETTINGS_KEYS = {
    "client_secret_file": "GOOGLE_CLIENT_SECRET_FILE",
    "service_account_file": "GOOGLE_SERVICE_ACCOUNT_FILE",
    "folder_id": "GOOGLE_DRIVE_FOLDER_ID",
}

_PLACEHOLDERS = {"", "your_folder_id_here"}


def _resolve(path: str | None) -> Path | None:
    if not path:
        return None
    p = Path(path).expanduser()
    return p if p.is_absolute() else PROJECT_ROOT / p


def read_gui_settings() -> dict[str, str]:
    """Читает config/settings.txt (формат key=value, # — комментарий)."""
    result: dict[str, str] = {}
    if not SETTINGS_FILE.exists():
        return result
    for line in SETTINGS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in _SETTINGS_KEYS:
            result[key.strip()] = value.strip()
    return result


def save_gui_settings(values: dict[str, str]) -> Path:
    """Сохраняет настройки из GUI в config/settings.txt."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Настройки Google, сохранённые из окна «Настройки Google» (gui/app.py)"]
    for key in _SETTINGS_KEYS:
        lines.append(f"{key}={values.get(key, '').strip()}")
    SETTINGS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return SETTINGS_FILE


@dataclass(frozen=True)
class GoogleConfig:
    mode: str
    client_secret_file: Path | None
    token_file: Path
    service_account_file: Path | None
    folder_id: str | None
    scopes: tuple[str, ...]
    api_url: str

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"


def load_config() -> GoogleConfig:
    """Собирает актуальную конфигурацию (вызывается при каждом обращении к фабрике)."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    gui = read_gui_settings()

    def pick(gui_key: str) -> str | None:
        value = gui.get(gui_key) or os.getenv(_SETTINGS_KEYS[gui_key], "")
        return value.strip() or None

    mode = os.getenv("GOOGLE_MODE", "mock").strip().lower()
    if mode not in ("mock", "real"):
        raise ValueError(f"GOOGLE_MODE должен быть 'mock' или 'real', получено: {mode!r}")

    folder_id = pick("folder_id")
    if folder_id in _PLACEHOLDERS:
        folder_id = None

    scopes_env = os.getenv("GOOGLE_SCOPES", "")
    scopes = tuple(s.strip() for s in scopes_env.split(",") if s.strip()) or DEFAULT_SCOPES

    return GoogleConfig(
        mode=mode,
        client_secret_file=_resolve(pick("client_secret_file")),
        token_file=_resolve(os.getenv("GOOGLE_TOKEN_FILE", "google_integration/token.json")),
        service_account_file=_resolve(pick("service_account_file")),
        folder_id=folder_id,
        scopes=scopes,
        api_url=os.getenv("API_URL", "http://localhost:8000").rstrip("/"),
    )
