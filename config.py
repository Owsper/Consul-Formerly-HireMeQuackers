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

# (base URL, example model) for providers that speak the OpenAI chat shape.
# ``LLM_BASE_URL`` and ``LLM_MODEL`` always override these.
LLM_PROVIDER_PRESETS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-20b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai",
               "gemini-3.8-flash"),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest"),
    "cerebras": ("https://api.cerebras.ai/v1", "llama-3.3-70b"),
    "zai": ("https://api.z.ai/api/paas/v4", "glm-4-flash"),
    "ollama": ("http://localhost:11434/v1", "llama3.1"),
    "custom": ("", ""),
}


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
class LLMRoute:
    """One automatic provider choice for a class of LLM work."""

    provider: str
    model: str
    max_output_tokens: int = 4096
    reasoning_effort: str = ""
    max_prompt_chars: int = 0


# The app, not the user, chooses the model. These routes put the strongest
# long-context model on extraction and high-stakes CV reasoning, while Groq
# handles the higher-volume drafting work. Each task has a fallback chain so a
# free-tier 429 or an outage degrades instead of breaking the workflow.
DEFAULT_TASK_ROUTES: dict[str, tuple[LLMRoute, ...]] = {
    "extraction": (
        LLMRoute("gemini", "gemini-3.8-flash", 8192),
        LLMRoute("gemini", "gemini-3.5-flash-lite", 8192),
        # Groq's free 8K tokens/minute budget cannot take a long CV prompt;
        # skip it rather than sending a request that is guaranteed to fail.
        LLMRoute("groq", "openai/gpt-oss-120b", 4096, "low", 16000),
    ),
    "reasoning": (
        LLMRoute("gemini", "gemini-3.8-flash", 8192),
        LLMRoute("groq", "openai/gpt-oss-120b", 4096, "medium", 16000),
        LLMRoute("gemini", "gemini-3.5-flash-lite", 8192),
    ),
    "writing": (
        LLMRoute("groq", "openai/gpt-oss-120b", 4096, "low", 16000),
        LLMRoute("gemini", "gemini-3.8-flash", 8192),
        LLMRoute("gemini", "gemini-3.5-flash-lite", 8192),
    ),
    "planning": (
        LLMRoute("groq", "openai/gpt-oss-120b", 4096, "medium", 16000),
        LLMRoute("gemini", "gemini-3.8-flash", 8192),
        LLMRoute("gemini", "gemini-3.5-flash-lite", 8192),
    ),
    "utility": (
        LLMRoute("groq", "openai/gpt-oss-20b", 2048, "low", 16000),
        LLMRoute("gemini", "gemini-3.5-flash-lite", 4096),
    ),
}


def _route_list(name: str, fallback: tuple[LLMRoute, ...]) -> tuple[LLMRoute, ...]:
    """Allow operators to override a route with ``provider:model,...`` specs."""
    raw = _env(name)
    if not raw:
        return fallback
    routes: list[LLMRoute] = []
    for part in raw.split(","):
        provider, separator, model = part.strip().partition(":")
        provider, model = provider.strip().lower(), model.strip()
        if not separator or not provider or not model:
            continue
        routes.append(LLMRoute(
            provider, model,
            max_output_tokens=8192 if provider == "gemini" else 4096,
            reasoning_effort="low" if provider == "groq" else "",
            max_prompt_chars=0 if provider == "gemini" else 16000,
        ))
    return tuple(routes) or fallback


@dataclass(frozen=True)
class Settings:
    app_name: str = "consul"
    data_dir: Path = DATA_DIR_DEFAULT
    database_url: str = ""
    max_upload_mb: int = 10

    llm_enabled: bool = True
    llm_temperature: float = 0.2
    llm_max_retries: int = 2

    # Legacy single-provider selection. Automatic task routes use the Groq and
    # Gemini keys below; every preset still talks to an OpenAI-compatible
    # /chat/completions endpoint, so a custom provider remains a final fallback.
    llm_provider: str = "groq"
    llm_api_key: str = ""
    groq_api_key: str = ""
    gemini_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = 45
    llm_max_output_tokens: int = 8192
    llm_reasoning_effort: str = ""
    llm_cooldown_seconds: int = 180
    llm_routes: dict[str, tuple[LLMRoute, ...]] = field(
        default_factory=lambda: dict(DEFAULT_TASK_ROUTES))

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

    def api_key_for(self, provider: str) -> str:
        """The key for a route, without mixing one provider's key into another."""
        provider = (provider or "").lower()
        if provider == "groq":
            return self.groq_api_key or (
                self.llm_api_key if self.llm_provider == "groq" else "")
        if provider == "gemini":
            return self.gemini_api_key or (
                self.llm_api_key if self.llm_provider == "gemini" else "")
        if provider == "ollama":
            return ""
        return self.llm_api_key if provider == self.llm_provider else ""

    def endpoint_for(self, provider: str) -> str:
        provider = (provider or "").lower()
        if provider == self.llm_provider and self.llm_base_url:
            return self.llm_base_url.rstrip("/")
        return LLM_PROVIDER_PRESETS.get(provider, ("", ""))[0]

    def provider_available(self, provider: str) -> bool:
        if not self.llm_enabled:
            return False
        provider = (provider or "").lower()
        if provider == "ollama":
            return True
        if provider in {"groq", "gemini"}:
            return bool(self.api_key_for(provider))
        return provider == self.llm_provider and bool(self.llm_api_key)

    @property
    def llm_available(self) -> bool:
        return any(self.provider_available(provider) for provider in
                   {"groq", "gemini", self.llm_provider})

    @property
    def active_model(self) -> str:
        if self.llm_model:
            return self.llm_model
        return LLM_PROVIDER_PRESETS.get(self.llm_provider, ("", ""))[1]

    @property
    def llm_endpoint(self) -> str:
        return self.endpoint_for(self.llm_provider)

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
            missing["LLM"] = [
                "GROQ_API_KEY and/or GEMINI_API_KEY (or LLM_PROVIDER + LLM_API_KEY)",
            ]
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
    provider = (_env("LLM_PROVIDER") or "groq").lower()
    return Settings(
        data_dir=Path(_env("DATA_DIR") or DATA_DIR_DEFAULT),
        database_url=database_url,
        max_upload_mb=_env_int("MAX_UPLOAD_MB", 10),
        llm_enabled=_env_bool("LLM_ENABLED", True),
        llm_provider=provider,
        llm_api_key=_env("LLM_API_KEY") or _env("ZAI_API_KEY"),
        groq_api_key=_env("GROQ_API_KEY"),
        gemini_api_key=_env("GEMINI_API_KEY"),
        llm_base_url=_env("LLM_BASE_URL") or _env("ZAI_API_BASE"),
        llm_model=_env("LLM_MODEL"),
        llm_timeout_seconds=_env_int("LLM_TIMEOUT_SECONDS", 45),
        llm_max_output_tokens=_env_int("LLM_MAX_OUTPUT_TOKENS", 8192),
        llm_reasoning_effort=_env("LLM_REASONING_EFFORT").lower(),
        llm_cooldown_seconds=_env_int("LLM_COOLDOWN_SECONDS", 180),
        llm_routes={
            task: _route_list(f"LLM_ROUTE_{task.upper()}", routes)
            for task, routes in DEFAULT_TASK_ROUTES.items()
        },
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
