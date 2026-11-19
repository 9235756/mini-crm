"""OAuth2-авторизация пользователя Google (InstalledAppFlow + token.json).

Первый запуск открывает браузер: пользователь входит в свой аккаунт и даёт доступ.
Токен сохраняется в token.json и дальше обновляется автоматически (refresh_token).
Запасной вариант — сервисный аккаунт (JSON-ключ), если OAuth-клиента нет.
"""

from __future__ import annotations

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from google_integration.config import GoogleConfig, load_config


class GoogleAuthError(RuntimeError):
    pass


def _oauth_credentials(client_secret: Path, token_file: Path, scopes: list[str]) -> Credentials:
    creds: Credentials | None = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None  # токен отозван — авторизуемся заново
    else:
        creds = None

    if creds is None:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), scopes)
        creds = flow.run_local_server(
            port=0,
            authorization_prompt_message="Откройте ссылку для входа в Google: {url}",
            success_message="Авторизация прошла успешно. Окно можно закрыть.",
            open_browser=True,
        )

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_credentials(config: GoogleConfig | None = None):
    """Учётные данные для Drive/Sheets API: OAuth пользователя или сервисный аккаунт."""
    config = config or load_config()
    scopes = list(config.scopes)

    if config.client_secret_file and config.client_secret_file.exists():
        return _oauth_credentials(config.client_secret_file, config.token_file, scopes)

    if config.service_account_file and config.service_account_file.exists():
        return service_account.Credentials.from_service_account_file(
            str(config.service_account_file), scopes=scopes
        )

    raise GoogleAuthError(
        "Не найден ни client_secret.json (OAuth), ни JSON сервисного аккаунта. "
        "Укажите файлы в окне «Настройки Google» или в .env (см. example.env), "
        "либо включите эмуляцию: GOOGLE_MODE=mock."
    )
