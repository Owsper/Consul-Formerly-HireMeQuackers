"""Shared connector infrastructure: HTTP, result types, relevance, normalisation."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import httpx

from config import Settings
from core.exceptions import RateLimitedError, UnsafeURLError
from core.logging_config import get_logger
from core.schemas import (
    JobRecord, ListingStatus, PlannedQuery, SearchPreferences, SourceHealth, WorkMode,
)
from core.security import validate_url
from core.text import normalize_text, normalize_whitespace, similarity

logger = get_logger("connectors")

WORK_MODE_PATTERNS = [
    (WorkMode.REMOTE, ("remote", "home office", "homeoffice", "home-office", "télétravail",
                       "teletravail", "remoto", "thuiswerken", "fully remote", "work from home")),
    (WorkMode.HYBRID, ("hybrid", "hybride", "hybrides", "híbrido", "hybrid work")),
    (WorkMode.ONSITE, ("on-site", "onsite", "on site", "vor ort", "in person", "presencial")),
]


@dataclass
class CompanySeed:
    name: str = ""
    identifier: str = ""
    provider: str = ""
    country: str = ""
    career_url: str = ""


@dataclass
class ConnectorContext:
    queries: list[PlannedQuery] = field(default_factory=list)
    preferences: SearchPreferences = field(default_factory=SearchPreferences)
    companies: list[CompanySeed] = field(default_factory=list)
    search_terms: set[str] = field(default_factory=set)
    exclude_terms: set[str] = field(default_factory=set)


@dataclass
class RequestStats:
    made: int = 0
    ok: int = 0
    failed: int = 0
    error: str = ""
    rate_limited: bool = False
    restricted: bool = False


@dataclass
class ConnectorResult:
    connector: str
    display_name: str
    status: SourceHealth = SourceHealth.HEALTHY
    jobs: list[JobRecord] = field(default_factory=list)
    queries_executed: int = 0
    requests_made: int = 0
    requests_ok: int = 0
    requests_failed: int = 0
    duration_seconds: float = 0.0
    error: str = ""
    detail: str = ""
    last_success: datetime | None = None


class RateLimiter:
    """Simple per-connector pacing to avoid hammering a website."""

    def __init__(self, min_interval: float = 0.35) -> None:
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self.min_interval - (now - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


class HttpSession:
    """Async HTTP with retries, Retry-After support, SSRF validation and stats."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings,
                 limiter: RateLimiter | None = None, stats: RequestStats | None = None) -> None:
        self.client = client
        self.settings = settings
        self.limiter = limiter or RateLimiter()
        self.stats = stats or RequestStats()

    @staticmethod
    def _safe_url(url: str) -> str:
        try:
            return validate_url(url, resolve_dns=True, require_resolution=False)
        except UnsafeURLError as exc:
            raise UnsafeURLError(f"Blocked outbound request: {exc}") from exc

    async def _request(self, method: str, url: str, *, attempts: int = 3,
                       **kwargs: Any) -> httpx.Response:
        url = self._safe_url(url)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            await self.limiter.wait()
            self.stats.made += 1
            try:
                response = await self.client.request(method, url, **kwargs)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                self.stats.failed += 1
                last_error = exc
                self.stats.error = f"{type(exc).__name__}: {exc}"
                if attempt == attempts:
                    break
                await asyncio.sleep(min(4.0, 0.5 * 2 ** (attempt - 1)))
                continue

            if response.status_code == 429:
                self.stats.rate_limited = True
                retry_after = response.headers.get("Retry-After", "")
                delay = 2.0
                try:
                    delay = min(15.0, float(retry_after))
                except (TypeError, ValueError):
                    pass
                self.stats.error = "HTTP 429 rate limited"
                if attempt < attempts:
                    await asyncio.sleep(delay)
                    continue
                self.stats.failed += 1
                raise RateLimitedError(f"Rate limited by {url.split('/')[2]}")

            if response.status_code in {401, 403}:
                self.stats.failed += 1
                self.stats.restricted = True
                self.stats.error = f"HTTP {response.status_code} (restricted)"
                response.raise_for_status()
            if response.status_code >= 500:
                self.stats.failed += 1
                last_error = httpx.HTTPStatusError(
                    f"Server error {response.status_code}", request=response.request, response=response
                )
                self.stats.error = f"HTTP {response.status_code}"
                if attempt < attempts:
                    await asyncio.sleep(min(4.0, 0.5 * 2 ** (attempt - 1)))
                    continue
                raise last_error
            response.raise_for_status()
            self.stats.ok += 1
            return response
        raise httpx.TransportError(f"Request failed: {last_error}")

    async def get_json(self, url: str, *, params: dict | None = None,
                       headers: dict | None = None) -> Any:
        response = await self._request("GET", url, params=params, headers=headers)
        try:
            return response.json()
        except ValueError as exc:
            raise httpx.DecodingError(f"Invalid JSON from {url}") from exc

    async def get_text(self, url: str, *, params: dict | None = None,
                       headers: dict | None = None) -> str:
        response = await self._request("GET", url, params=params, headers=headers)
        return response.text

    async def post_json(self, url: str, payload: dict, *, headers: dict | None = None) -> Any:
        response = await self._request("POST", url, json=payload, headers=headers)
        try:
            return response.json()
        except ValueError as exc:
            raise httpx.DecodingError(f"Invalid JSON from {url}") from exc


def infer_work_mode(*texts: str) -> WorkMode:
    blob = normalize_text(" ".join(t for t in texts if t))
    for mode, needles in WORK_MODE_PATTERNS:
        for needle in needles:
            if needle in blob:
                return mode
    return WorkMode.UNKNOWN


def infer_employment_type(title: str, *texts: str) -> str:
    blob = normalize_text(" ".join([title] + [t for t in texts if t]))
    if any(k in blob for k in ("werkstudent", "working student", "studentische", "studente lavoratore")):
        return "working_student"
    if any(k in blob for k in ("intern", "internship", "praktikum", "praktikant", "stage ", " stagiair",
                               "prácticas", "practicas", "tirocinio", "estágio", "estagio")):
        return "internship"
    if any(k in blob for k in ("part-time", "part time", "teilzeit", "temps partiel", "tijdelijk")):
        return "part_time"
    if any(k in blob for k in ("contract", "contractor", "freelance", "befristet", "cdd")):
        return "contract"
    if any(k in blob for k in ("graduate", "absolvent", "berufseinsteiger", "entry level", "entry-level")):
        return "graduate"
    return "full_time"


def infer_seniority(title: str) -> str:
    blob = normalize_text(title)
    if any(k in blob for k in ("intern", "praktik", "stage", "stagiair", "werkstudent", "working student", "prácticas", "practicas")):
        return "internship"
    if any(k in blob for k in ("junior", "graduate", "entry", "einstieg", "berufseinsteiger", "trainee", "absolvent")):
        return "entry"
    if any(k in blob for k in ("principal", "head of", "director", "vp ")):
        return "lead"
    if any(k in blob for k in ("lead", "staff")):
        return "lead"
    if "senior" in blob or "sr." in blob:
        return "senior"
    if any(k in blob for k in ("mid-level", "mid level", "experienced")):
        return "mid"
    return "unknown"


def parse_date(value: Any) -> date | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            if ts > 10_000_000_000:  # milliseconds
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text[:len(fmt) + 6], fmt).date()
            except ValueError:
                continue
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
    return None


def clean_html(html: str) -> str:
    """Convert job HTML to readable text while preserving paragraphs and bullets."""
    from core.security import sanitize_html

    if not html:
        return ""
    text = html.replace("\r\n", "\n")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|li|div|h[1-6]|tr)>\s*", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = sanitize_html(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def job_relevant(title: str, ctx: ConnectorContext, extra: str = "") -> bool:
    """Cheap relevance gate before a listing enters the pipeline."""
    normalized_title = normalize_text(title)
    if not normalized_title:
        return False
    if any(term and term in normalized_title for term in ctx.exclude_terms):
        return False
    if not ctx.search_terms:
        return True
    tokens = set(re.findall(r"[a-zäöüßéèêàçñ0-9+#.]+", normalized_title))
    for term in ctx.search_terms:
        if " " in term:
            if term in normalized_title:
                return True
        elif term in tokens:
            return True
    # Fuzzy rescue for close spellings (e.g. "entwicklerin")
    for term in list(ctx.search_terms)[:40]:
        if len(term) >= 5 and any(similarity(term, tok) >= 0.88 for tok in tokens):
            return True
    return False


class BaseConnector:
    """Common connector contract. Every source is independently configurable."""

    key: str = "base"
    display_name: str = "Base connector"
    provider_kind: str = "ats"
    requires: tuple[str, ...] = ()
    description: str = ""

    def missing_config(self, settings: Settings) -> list[str]:
        return []

    def is_configured(self, settings: Settings) -> bool:
        return not self.missing_config(settings)

    def seeds(self, ctx: ConnectorContext, settings: Settings) -> list[CompanySeed]:
        return [c for c in ctx.companies if c.provider == self.key and c.identifier]

    def new_result(self) -> ConnectorResult:
        return ConnectorResult(connector=self.key, display_name=self.display_name)

    def finish(self, result: ConnectorResult, started: float, stats: RequestStats,
               jobs: list[JobRecord], queries_executed: int, *, configured: bool = True,
               error: str = "", detail: str = "") -> ConnectorResult:
        result.jobs = jobs
        result.queries_executed = queries_executed
        result.requests_made = stats.made
        result.requests_ok = stats.ok
        result.requests_failed = stats.failed
        result.duration_seconds = round(time.perf_counter() - started, 3)
        result.error = error or stats.error
        result.detail = detail
        if not configured:
            result.status = SourceHealth.MISSING_CONFIG
        elif stats.ok and jobs:
            result.status = SourceHealth.HEALTHY
            result.last_success = datetime.now(timezone.utc)
        elif stats.ok:
            result.status = SourceHealth.PARTIAL
            result.last_success = datetime.now(timezone.utc)
        elif stats.rate_limited:
            result.status = SourceHealth.RATE_LIMITED
        elif stats.restricted:
            result.status = SourceHealth.RESTRICTED
        else:
            result.status = SourceHealth.UNAVAILABLE
        return result

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:  # pragma: no cover - interface
        raise NotImplementedError

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def make_job(**kwargs: Any) -> JobRecord:
        kwargs.setdefault("last_verified", datetime.now(timezone.utc))
        job = JobRecord(**kwargs)
        job.description = (job.description or "")[:60000]
        if job.status == ListingStatus.UNVERIFIED:
            job.status = ListingStatus.ACTIVE if job.application_url or job.original_url else ListingStatus.UNVERIFIED
        return job


def dedupe_batch(jobs: list[JobRecord]) -> list[JobRecord]:
    """Remove exact duplicates inside a single connector batch."""
    seen: set[str] = set()
    out: list[JobRecord] = []
    for job in jobs:
        key = f"{job.source}|{job.source_job_id}" if job.source_job_id else f"{job.source}|{normalize_text(job.title)}|{normalize_text(job.company)}"
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)[:20000]
    except (TypeError, ValueError):
        return "{}"
