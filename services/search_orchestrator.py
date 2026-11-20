"""Multi-source scan orchestration.

The orchestrator owns the rules that make a scan honest:

* every source is attempted independently and reported independently;
* a source is only reported as having produced jobs if a request succeeded;
* failures, missing configuration and rate limiting are surfaced, never hidden;
* persistence happens after the async I/O so SQLite is only touched from one
  thread, and re-scans merge into existing jobs instead of duplicating them.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import Settings, get_settings
from connectors.adzuna import AdzunaConnector
from connectors.ashby import AshbyConnector
from connectors.base import (
    BaseConnector, CompanySeed, ConnectorContext, ConnectorResult, HttpSession, RateLimiter,
)
from connectors.company_careers import CompanyCareersConnector
from connectors.greenhouse import GreenhouseConnector
from connectors.jooble import JoobleConnector
from connectors.lever import LeverConnector
from connectors.personio import PersonioConnector
from connectors.recruitee import RecruiteeConnector
from connectors.search_engine import SearchEngineConnector
from connectors.smartrecruiters import SmartRecruitersConnector
from connectors.teamtailor import TeamTailorConnector
from connectors.workable import WorkableConnector
from connectors.workday import WorkdayConnector
from core.logging_config import get_logger
from core.models import Company, ScanQuery, ScanSession, ScanSourceReport, UserSetting
from core.schemas import (
    CandidateProfileData, EvidenceItem, JobRecord, ScanSummary, SearchPlan,
    SearchPreferences, SourceHealth, SourceReportData,
)
from services.company_service import mark_company_result, seed_company_registry
from services.deduplication import normalize_company, persist_job
from services.job_enrichment import enrich_job, llm_extract_requirements
from services.job_scoring import score_record, scoring_weights
from services.job_service import save_match

logger = get_logger("orchestrator")

CONNECTOR_CLASSES: list[type[BaseConnector]] = [
    GreenhouseConnector, LeverConnector, AshbyConnector, SmartRecruitersConnector,
    WorkableConnector, RecruiteeConnector, PersonioConnector, WorkdayConnector,
    TeamTailorConnector, AdzunaConnector, JoobleConnector, SearchEngineConnector,
    CompanyCareersConnector,
]

SOURCE_TIMEOUT_SECONDS = 150.0

ProgressCallback = Callable[[dict], None]


@dataclass
class ScanRequest:
    preferences: SearchPreferences = field(default_factory=SearchPreferences)
    plan: SearchPlan | None = None
    profile_data: CandidateProfileData | None = None
    evidence: list[EvidenceItem] = field(default_factory=list)
    profile_id: int | None = None
    only: list[str] | None = None
    max_jobs_per_source: int = 200
    verify_listings: bool = False


def connector_registry(settings: Settings | None = None) -> dict[str, BaseConnector]:
    settings = settings or get_settings()
    registry: dict[str, BaseConnector] = {}
    for cls in CONNECTOR_CLASSES:
        try:
            registry[cls.key] = cls()
        except TypeError:  # pragma: no cover - defensive
            logger.exception("Could not initialise connector %s", cls.key)
    return registry


def get_enabled_sources(session: Session) -> list[str]:
    row = session.get(UserSetting, "enabled_sources")
    if row is None or not row.value:
        return [cls.key for cls in CONNECTOR_CLASSES]
    try:
        stored = json.loads(row.value)
        return [s for s in stored if isinstance(s, str)]
    except (json.JSONDecodeError, TypeError):
        return [cls.key for cls in CONNECTOR_CLASSES]


def set_enabled_sources(session: Session, keys: list[str]) -> None:
    row = session.get(UserSetting, "enabled_sources")
    value = json.dumps([k for k in keys if k in {cls.key for cls in CONNECTOR_CLASSES}])
    if row is None:
        session.add(UserSetting(key="enabled_sources", value=value))
    else:
        row.value = value
    session.flush()


def source_catalog(session: Session, settings: Settings | None = None) -> list[dict]:
    """Everything the diagnostics UI needs before a scan has run."""
    settings = settings or get_settings()
    enabled = set(get_enabled_sources(session))
    catalog: list[dict] = []
    for key, connector in connector_registry(settings).items():
        missing = connector.missing_config(settings)
        configured = not missing
        last = session.scalars(
            select(ScanSourceReport).where(ScanSourceReport.connector == key).order_by(
                ScanSourceReport.id.desc()
            )
        ).first()
        status = last.status if last else (
            SourceHealth.MISSING_CONFIG.value if not configured else "unknown"
        )
        catalog.append({
            "key": key,
            "name": connector.display_name,
            "kind": connector.provider_kind,
            "description": connector.description,
            "requires": list(connector.requires),
            "missing": missing,
            "configured": configured,
            "enabled": key in enabled,
            "status": status,
            "last_scan": last.id if last else None,
        })
    return catalog


def _companies(session: Session) -> list[CompanySeed]:
    rows = session.scalars(select(Company).order_by(Company.name)).all()
    seeds: list[CompanySeed] = []
    inds = set()
    for row in rows:
        provider = (row.ats_provider or "").lower()
        if not row.ats_identifier:
            continue
        key = (provider, row.ats_identifier)
        if key in inds:
            continue
        inds.add(key)
        seeds.append(CompanySeed(name=row.name, identifier=row.ats_identifier,
                                 provider=provider, country=row.country,
                                 career_url=row.career_url))
    return seeds


def build_context(request: ScanRequest, companies: list[CompanySeed]) -> ConnectorContext:
    plan = request.plan
    terms: set[str] = set()
    if plan:
        for title in [*plan.english_titles, *plan.keywords]:
            if title:
                terms.add(title.lower().strip())
        for titles in plan.local_titles.values():
            terms.update(t.lower().strip() for t in titles if t)
    for title in [*request.preferences.target_titles, *request.preferences.alternative_titles]:
        if title:
            terms.add(title.lower().strip())
    exclude = set()
    if plan:
        exclude.update(t.lower() for t in plan.exclude_terms if t)
    exclude.update(normalize_company(c) for c in request.preferences.exclude_companies if c)
    return ConnectorContext(
        queries=list(plan.queries) if plan else [],
        preferences=request.preferences,
        companies=companies,
        search_terms=terms,
        exclude_terms=exclude,
    )


def _preference_reject(record: JobRecord, prefs: SearchPreferences) -> str:
    if prefs.exclude_companies:
        company_key = normalize_company(record.company)
        for blocked in prefs.exclude_companies:
            if blocked and normalize_company(blocked) == company_key:
                return "excluded company"
    if record.posted_at and prefs.max_posting_age_days:
        cutoff = date.today() - timedelta(days=max(1, prefs.max_posting_age_days))
        if record.posted_at < cutoff:
            return "older than the configured maximum posting age"
    return ""


async def _run_connector(connector: BaseConnector, ctx: ConnectorContext,
                         settings: Settings, request: ScanRequest,
                         client: httpx.AsyncClient) -> tuple[ConnectorResult, str]:
    limiter = RateLimiter(0.4 if connector.provider_kind == "ats" else 0.8)
    http = HttpSession(client, settings, limiter=limiter)
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            connector.search(ctx, http, settings), timeout=SOURCE_TIMEOUT_SECONDS
        )
        return result, ""
    except asyncio.TimeoutError:
        result = connector.new_result()
        result.status = SourceHealth.UNAVAILABLE
        result.error = f"Timed out after {int(SOURCE_TIMEOUT_SECONDS)}s"
        result.duration_seconds = round(time.perf_counter() - started, 3)
        result.requests_made = http.stats.made
        result.requests_ok = http.stats.ok
        result.requests_failed = http.stats.failed
        return result, result.error
    except Exception as exc:  # a broken connector must never abort the scan
        logger.exception("Connector %s failed", connector.key)
        result = connector.new_result()
        result.status = SourceHealth.UNAVAILABLE
        result.error = f"{type(exc).__name__}: {exc}"[:500]
        result.duration_seconds = round(time.perf_counter() - started, 3)
        result.requests_made = http.stats.made
        result.requests_ok = http.stats.ok
        result.requests_failed = http.stats.failed
        return result, result.error


def _apply_source_health_fallback(result: ConnectorResult, error: str) -> ConnectorResult:
    if error and result.status == SourceHealth.HEALTHY:
        result.status = SourceHealth.PARTIAL
    if error and not result.requests_ok and result.status in {SourceHealth.HEALTHY, SourceHealth.PARTIAL}:
        result.status = SourceHealth.UNAVAILABLE
    return result


def _source_report(result: ConnectorResult, found: int, accepted: int,
                   error: str = "") -> SourceReportData:
    return SourceReportData(
        connector=result.connector,
        display_name=result.display_name,
        status=result.status,
        queries_executed=result.queries_executed,
        requests_made=result.requests_made,
        requests_ok=result.requests_ok,
        requests_failed=result.requests_failed,
        jobs_found=found,
        jobs_accepted=accepted,
        duration_seconds=result.duration_seconds,
        error=(result.error or error)[:1500],
        last_success=result.last_success,
        detail=result.detail[:2000],
    )


def _record_source(session: Session, scan_id: str, report: SourceReportData) -> None:
    session.add(ScanSourceReport(
        scan_id=scan_id,
        connector=report.connector,
        display_name=report.display_name,
        status=report.status.value,
        queries_executed=report.queries_executed,
        requests_made=report.requests_made,
        requests_ok=report.requests_ok,
        requests_failed=report.requests_failed,
        jobs_found=report.jobs_found,
        jobs_accepted=report.jobs_accepted,
        duration_seconds=report.duration_seconds,
        error=report.error,
        detail=report.detail,
        last_success=report.last_success,
    ))


async def _scan_async(session: Session, request: ScanRequest, settings: Settings,
                      progress: ProgressCallback | None,
                      should_cancel: Callable[[], bool] | None,
                      scan_id: str) -> ScanSummary:
    def notify(payload: dict) -> None:
        if progress:
            try:
                progress(payload)
            except Exception:  # pragma: no cover - UI callback must not break scans
                logger.debug("progress callback raised", exc_info=True)

    registry = connector_registry(settings)
    enabled = set(get_enabled_sources(session))
    selected = [k for k in registry if k in enabled and (not request.only or k in request.only)]
    skipped = [registry[k].display_name for k in registry if k not in selected]

    companies = _companies(session)
    ctx = build_context(request, companies)
    weights = scoring_weights(session)
    summary = ScanSummary(scan_id=scan_id, started_at=datetime.now(timezone.utc),
                          not_scanned=skipped)

    if not selected:
        summary.finished_at = datetime.now(timezone.utc)
        summary.notes.append("No sources are enabled. Enable at least one in Search Configuration.")
        return summary

    notify({"stage": "starting", "total": len(selected), "done": 0,
            "message": f"Scanning {len(selected)} source(s)…"})

    limits = httpx.Limits(max_connections=max(4, settings.max_concurrency * 2),
                          max_keepalive_connections=4)
    headers = {"User-Agent": settings.user_agent, "Accept-Language": "en,de;q=0.8"}
    results: list[tuple[ConnectorResult, str]] = []

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, headers=headers,
                                 follow_redirects=True, limits=limits) as client:
        semaphore = asyncio.Semaphore(max(1, settings.max_concurrency))

        async def guarded(key: str) -> tuple[ConnectorResult, str]:
            connector = registry[key]
            if should_cancel and should_cancel():
                result = connector.new_result()
                result.status = SourceHealth.UNAVAILABLE
                result.error = "Cancelled before this source ran."
                return result, result.error
            async with semaphore:
                return await _run_connector(connector, ctx, settings, request, client)

        tasks = [asyncio.create_task(guarded(key)) for key in selected]
        done = 0
        for task in asyncio.as_completed(tasks):
            result, error = await task
            result = _apply_source_health_fallback(result, error)
            results.append((result, error))
            done += 1
            notify({"stage": "source", "done": done, "total": len(selected),
                    "source": result.connector,
                    "message": f"{result.display_name}: {result.status.value.replace('_', ' ')}"})

    summary.cancelled = bool(should_cancel and should_cancel())

    # ---- persistence (single thread, single transaction) --------------------
    notify({"stage": "saving", "done": len(selected), "total": len(selected),
            "message": "Saving and scoring jobs…"})
    per_source_accepted: dict[str, int] = {}
    seen_job_ids: set[str] = set()

    for result, error in results:
        found = len(result.jobs)
        accepted = 0
        for record in result.jobs[:request.max_jobs_per_source]:
            if should_cancel and should_cancel():
                summary.cancelled = True
                break
            reason = _preference_reject(record, request.preferences)
            if reason:
                logger.info("Skipped '%s': %s", record.title, reason)
                continue
            record = enrich_job(record)
            try:
                record = await llm_extract_requirements(record)
            except Exception:
                logger.debug("LLM enrichment skipped", exc_info=True)
            row, created = persist_job(session, record)
            seen_job_ids.add(row.id)
            accepted += 1
            if created:
                summary.jobs_new += 1
            if row.is_snippet:
                summary.snippets += 1
            if request.profile_data is not None:
                match = score_record(record, request.profile_data, request.evidence,
                                     request.preferences, job_id=row.id, weights=weights)
                save_match(session, row.id, match, profile_id=request.profile_id)
                row.match_score = match.total_score
            session.flush()

        per_source_accepted[result.connector] = accepted
        report = _source_report(result, found, accepted, error)
        summary.sources.append(report)
        _record_source(session, scan_id, report)
        summary.jobs_retrieved += found

        for seed in companies:
            if seed.provider == result.connector:
                mark_company_result(session, seed.provider, seed.identifier,
                                    jobs_seen=accepted,
                                    health=report.status.value,
                                    error=report.error)

    summary.jobs_unique = len(seen_job_ids)

    # Record planned queries so the diagnostics page can show what was asked.
    if request.plan:
        for planned in request.plan.queries[:120]:
            executed = any(s.requests_ok > 0 for s in summary.sources)
            session.add(ScanQuery(scan_id=scan_id, query=planned.query[:500],
                                  language=planned.language, target=planned.target,
                                  priority=planned.priority, executed=executed,
                                  results=summary.jobs_retrieved if executed else 0))

    if not summary.sources:
        summary.notes.append("No source returned a usable response.")
    if summary.snippets:
        summary.notes.append(
            f"{summary.snippets} result(s) came from search snippets and are marked unverified."
        )
    if request.profile_data is None:
        summary.notes.append("No approved Ground Truth profile: jobs were stored but not scored.")

    summary.finished_at = datetime.now(timezone.utc)
    _finish_scan_row(session, scan_id, summary)
    notify({"stage": "done", "done": len(selected), "total": len(selected),
            "message": f"Scan complete — {summary.jobs_new} new job(s)."})
    return summary


def _finish_scan_row(session: Session, scan_id: str, summary: ScanSummary) -> None:
    row = session.get(ScanSession, scan_id)
    if row is None:
        return
    row.finished_at = summary.finished_at
    row.status = "cancelled" if summary.cancelled else "completed"
    row.summary_json = summary.model_dump_json()


def run_scan(session: Session, request: ScanRequest, *, settings: Settings | None = None,
             progress: ProgressCallback | None = None,
             should_cancel: Callable[[], bool] | None = None) -> ScanSummary:
    """Run a full scan synchronously. Safe to call from Streamlit."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    seed_company_registry(session)
    session.commit()

    scan_id = uuid.uuid4().hex[:24]
    session.add(ScanSession(id=scan_id, status="running",
                            profile_id=request.profile_id, started_at=datetime.now(timezone.utc)))
    session.commit()

    summary = asyncio.run(_scan_async(session, request, settings, progress,
                                      should_cancel, scan_id))
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return summary


def last_scan(session: Session) -> ScanSummary | None:
    row = session.scalars(select(ScanSession).order_by(ScanSession.started_at.desc())).first()
    if row is None or not row.summary_json or row.summary_json == "{}":
        return None
    try:
        return ScanSummary.model_validate_json(row.summary_json)
    except Exception:
        return None


def scan_history(session: Session, limit: int = 20) -> list[ScanSession]:
    return list(session.scalars(
        select(ScanSession).order_by(ScanSession.started_at.desc()).limit(limit)
    ))
