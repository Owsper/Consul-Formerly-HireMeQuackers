"""Central configuration for consul.

All settings come from environment variables (optionally loaded from a local
``.env`` file). API keys are deliberately *not* persisted anywhere else: the
database only ever stores non-secret preferences.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv(override=False)
except Exception:  # pragma: no cover - dotenv missing is fine
    pass

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR_DEFAULT = PROJECT_ROOT / "data"


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    raw = _env(name)
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = "consul"
    data_dir: Path = DATA_DIR_DEFAULT
    database_url: str = ""
    max_upload_mb: int = 10

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    llm_enabled: bool = True
    llm_temperature: float = 0.2
    llm_max_retries: int = 2

    http_timeout_seconds: int = 20
    max_concurrency: int = 8
    per_source_concurrency: int = 3
    user_agent: str = "consul/1.0 (personal job search assistant)"

    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "de"
    jooble_api_key: str = ""

    search_provider: str = "none"
    search_api_key: str = ""

    seed_boards: dict[str, list[str]] = field(default_factory=dict)

    @property
    def llm_available(self) -> bool:
        return bool(self.llm_enabled and self.gemini_api_key)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def templates_dir(self) -> Path:
        return PROJECT_ROOT / "templates"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.uploads_dir, self.exports_dir, self.backups_dir):
            path.mkdir(parents=True, exist_ok=True)

    def missing_configuration(self) -> dict[str, list[str]]:
        """Human readable list of optional integrations lacking credentials."""
        missing: dict[str, list[str]] = {}
        if not self.llm_available:
            missing["Gemini LLM"] = ["GEMINI_API_KEY"]
        if not (self.adzuna_app_id and self.adzuna_app_key):
            missing["Adzuna"] = ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"]
        if not self.jooble_api_key:
            missing["Jooble"] = ["JOOBLE_API_KEY"]
        if self.search_provider == "none" or not self.search_api_key:
            missing["Search engine"] = ["SEARCH_PROVIDER", "SEARCH_API_KEY"]
        return missing


def _build_settings() -> Settings:
    database_url = _env("DATABASE_URL")
    if not database_url:
        database_url = f"sqlite:///{(DATA_DIR_DEFAULT / 'consul.db').as_posix()}"
    return Settings(
        data_dir=Path(_env("DATA_DIR") or DATA_DIR_DEFAULT),
        database_url=database_url,
        max_upload_mb=_env_int("MAX_UPLOAD_MB", 10),
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_model=_env("GEMINI_MODEL") or "gemini-2.5-flash",
        llm_enabled=_env_bool("LLM_ENABLED", True),
        http_timeout_seconds=_env_int("HTTP_TIMEOUT_SECONDS", 20),
        max_concurrency=_env_int("MAX_CONCURRENCY", 8),
        per_source_concurrency=_env_int("PER_SOURCE_CONCURRENCY", 3),
        user_agent=_env("USER_AGENT") or "consul/1.0 (personal job search assistant)",
        adzuna_app_id=_env("ADZUNA_APP_ID"),
        adzuna_app_key=_env("ADZUNA_APP_KEY"),
        adzuna_country=_env("ADZUNA_COUNTRY") or "de",
        jooble_api_key=_env("JOOBLE_API_KEY"),
        search_provider=(_env("SEARCH_PROVIDER") or "none").lower(),
        search_api_key=_env("SEARCH_API_KEY"),
        seed_boards={
            "greenhouse": _env_list("GREENHOUSE_BOARDS"),
            "lever": _env_list("LEVER_COMPANIES"),
            "ashby": _env_list("ASHBY_BOARDS"),
            "smartrecruiters": _env_list("SMARTRECRUITERS_COMPANIES"),
            "workable": _env_list("WORKABLE_ACCOUNTS"),
            "recruitee": _env_list("RECRUITEE_COMPANIES"),
            "personio": _env_list("PERSONIO_COMPANIES"),
            "workday": _env_list("WORKDAY_TENANTS"),
            "teamtailor": _env_list("TEAMTAILOR_SITES"),
        },
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _build_settings()


def reload_settings() -> Settings:
    """Used by the settings page after environment changes (best effort)."""
    get_settings.cache_clear()
    return get_settings()
