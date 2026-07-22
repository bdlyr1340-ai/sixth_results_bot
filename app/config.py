from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _int_env(name: str, default: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    owner_id: int
    donation_number: str
    database_path: Path
    storage_dir: Path
    public_base_url: str
    web_admin_username: str
    web_admin_password: str
    web_session_secret: str
    port: int
    telegram_upload_limit_mb: int
    log_level: str
    remote_request_timeout: int
    remote_delay_ms: int
    remote_max_pdfs: int
    remote_max_depth: int

    @classmethod
    def from_env(cls) -> "Settings":
        database_path = Path(os.getenv("DATABASE_PATH", "/data/results.sqlite3"))
        storage_dir = Path(os.getenv("STORAGE_DIR", "/data/storage"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
        storage_dir.mkdir(parents=True, exist_ok=True)
        (storage_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (storage_dir / "work").mkdir(parents=True, exist_ok=True)

        public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").strip().rstrip("/")
        secret = os.getenv("WEB_SESSION_SECRET", "").strip() or secrets.token_urlsafe(32)

        return cls(
            bot_token=_require("BOT_TOKEN"),
            owner_id=_int_env("OWNER_ID"),
            donation_number=os.getenv("DONATION_NUMBER", "917392710336").strip(),
            database_path=database_path,
            storage_dir=storage_dir,
            public_base_url=public_base_url,
            web_admin_username=os.getenv("WEB_ADMIN_USERNAME", "owner").strip(),
            web_admin_password=_require("WEB_ADMIN_PASSWORD"),
            web_session_secret=secret,
            port=_int_env("PORT", 8000),
            telegram_upload_limit_mb=_int_env("TELEGRAM_UPLOAD_LIMIT_MB", 19),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            remote_request_timeout=max(10, _int_env("REMOTE_REQUEST_TIMEOUT", 60)),
            remote_delay_ms=max(0, _int_env("REMOTE_DELAY_MS", 150)),
            remote_max_pdfs=max(1, _int_env("REMOTE_MAX_PDFS", 5000)),
            remote_max_depth=max(0, _int_env("REMOTE_MAX_DEPTH", 3)),
        )
