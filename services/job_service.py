"""Persistence and query helpers for jobs, matches and saved jobs."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.models import (
    Application, Job, JobMatchRow, JobSourceRef, SavedJob, TailoredCVRow,
)
from core.schemas import JobRecord, ListingStatus, MatchResult, WorkMode


def new_job_id() -> str:
    return uuid.uuid4().hex[:24]


def _parse_list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        return [str(x) for x in value] if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _as_date(value: datetime | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def row_to_record(row: Job) -> JobRecord:
    return JobRecord(
        source=row.sources[0].connector if row.sources else "unknown",
        source_job_id=row.sources[0].source_job_id if row.sources else "",
        title=row.title,
        company=row.company,
        company_website=row.company_website,
        location=row.location,
        country=row.country,
        work_mode=WorkMode(row.work_mode or "unknown"),
        employment_type=row.employment_type,
        seniority=row.seniority,
        salary_min=row.salary_min,
        salary_max=row.salary_max,
        salary_currency=row.salary_currency,
        salary_frequency=row.salary_frequency,
        posted_at=_as_date(row.posted_at),
        closing_at=_as_date(row.closing_at),
        description=row.description,
        responsibilities=_parse_list(row.responsibilities_json),
        required_skills=_parse_list(row.required_skills_json),
        preferred_skills=_parse_list(row.preferred_skills_json),
        education_requirements=_parse_list(row.education_json),
        experience_requirements=_parse_list(row.experience_json),
        languages=_parse_list(row.languages_json),
        work_authorization_requirements=_parse_list(row.work_auth_json),
        visa_sponsorship=row.visa_sponsorship,
        application_url=row.application_url,
        original_url=row.original_url,
        first_seen=row.first_seen,
        last_verified=row.last_verified,
        status=ListingStatus(row.listing_status or "unverified"),
        is_snippet=row.is_snippet,
        language=row.language,
        match_score=row.match.total_score if row.match else None,
    )


def get_job(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def get_job_ids_for_scan(session: Session, limit: int = 500) -> list[str]:
    return list(session.scalars(select(Job.id).order_by(Job.created_at.desc()).limit(limit)))


def list_jobs(session: Session, *, limit: int = 100, offset: int = 0,
              search: str = "", country: str = "", work_mode: str = "",
              employment_type: str = "", seniority: str = "", source: str = "",
              min_score: float | None = None, eligibility: str = "",
              saved_only: bool = False, snippet: bool | None = None,
              include_expired: bool = True) -> list[Job]:
    stmt = select(Job).outerjoin(JobMatchRow, JobMatchRow.job_id == Job.id)
    if saved_only:
        stmt = stmt.join(SavedJob, SavedJob.job_id == Job.id)
    if min_score is not None:
        stmt = stmt.where(JobMatchRow.total_score >= min_score)
    if search:
        needle = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(Job.title).like(needle),
                              func.lower(Job.company).like(needle),
                              func.lower(Job.location).like(needle)))
    if country:
        stmt = stmt.where(Job.country == country)
    if work_mode:
        stmt = stmt.where(Job.work_mode == work_mode)
    if employment_type:
        stmt = stmt.where(Job.employment_type == employment_type)
    if seniority:
        stmt = stmt.where(Job.seniority == seniority)
    if source:
        stmt = stmt.join(JobSourceRef, JobSourceRef.job_id == Job.id).where(
            JobSourceRef.connector == source
        ).distinct()
    if snippet is not None:
        stmt = stmt.where(Job.is_snippet.is_(snippet))
    if not include_expired:
        stmt = stmt.where(Job.listing_status.notin_(["expired", "unavailable"]))
    if eligibility:
        stmt = stmt.where(JobMatchRow.eligibility_status == eligibility)
    stmt = stmt.order_by(JobMatchRow.total_score.desc().nullslast(), Job.first_seen.desc())
    stmt = stmt.limit(limit).offset(offset)
    return list(session.scalars(stmt).unique())


def count_jobs(session: Session) -> int:
    return int(session.scalar(select(func.count(Job.id))) or 0)


def distinct_values(session: Session, column) -> list[str]:
    rows = session.scalars(select(column).where(column.isnot(None)).distinct().order_by(column)).all()
    return [r for r in rows if r]


def sources_for_job(job: Job) -> list[dict]:
    return [
        {"connector": s.connector, "source_job_id": s.source_job_id, "url": s.url,
         "created_at": s.created_at}
        for s in job.sources
    ]


def save_match(session: Session, job_id: str, match: MatchResult, profile_id: int | None = None) -> JobMatchRow:
    row = session.scalars(select(JobMatchRow).where(JobMatchRow.job_id == job_id)).first()
    if row is None:
        row = JobMatchRow(job_id=job_id)
        session.add(row)
    row.profile_id = profile_id
    row.total_score = match.total_score
    row.suitability = match.suitability
    row.eligibility_status = match.eligibility.status.value
    row.payload_json = match.model_dump_json()
    session.flush()
    return row


def get_match(session: Session, job_id: str) -> MatchResult | None:
    row = session.scalars(select(JobMatchRow).where(JobMatchRow.job_id == job_id)).first()
    if row is None:
        return None
    try:
        return MatchResult.model_validate_json(row.payload_json or "{}")
    except Exception:
        return None


def save_job(session: Session, job_id: str, notes: str = "") -> SavedJob:
    row = session.scalars(select(SavedJob).where(SavedJob.job_id == job_id)).first()
    if row is None:
        row = SavedJob(job_id=job_id, notes=notes)
        session.add(row)
    elif notes:
        row.notes = notes
    session.flush()
    return row


def unsave_job(session: Session, job_id: str) -> None:
    row = session.scalars(select(SavedJob).where(SavedJob.job_id == job_id)).first()
    if row is not None:
        session.delete(row)
        session.flush()


def is_saved(session: Session, job_id: str) -> bool:
    return session.scalars(select(SavedJob).where(SavedJob.job_id == job_id)).first() is not None


def latest_cv(session: Session, job_id: str) -> TailoredCVRow | None:
    return session.scalars(
        select(TailoredCVRow).where(TailoredCVRow.job_id == job_id).order_by(
            TailoredCVRow.version.desc()
        )
    ).first()


def cvs_for_job(session: Session, job_id: str) -> list[TailoredCVRow]:
    return list(session.scalars(
        select(TailoredCVRow).where(TailoredCVRow.job_id == job_id).order_by(TailoredCVRow.version.desc())
    ))


def dashboard_stats(session: Session) -> dict:
    total = count_jobs(session)
    excellent = int(session.scalar(
        select(func.count(JobMatchRow.id)).where(JobMatchRow.total_score >= 85)) or 0)
    strong = int(session.scalar(
        select(func.count(JobMatchRow.id)).where(
            JobMatchRow.total_score >= 70, JobMatchRow.total_score < 85)) or 0)
    saved = int(session.scalar(select(func.count(SavedJob.id))) or 0)
    applications = int(session.scalar(select(func.count(Application.id))) or 0)
    applied = int(session.scalar(select(func.count(Application.id)).where(
        Application.applied_at.isnot(None))) or 0)
    interviews = int(session.scalar(select(func.count(Application.id)).where(
        Application.status.in_(["Interview", "Technical interview", "Final interview"]))) or 0)
    offers = int(session.scalar(select(func.count(Application.id)).where(
        Application.status == "Offer received")) or 0)
    ineligible = int(session.scalar(select(func.count(JobMatchRow.id)).where(
        JobMatchRow.eligibility_status == "ineligible")) or 0)
    return {
        "total_jobs": total, "excellent": excellent, "strong": strong, "saved": saved,
        "applications": applications, "applied": applied, "interviews": interviews,
        "offers": offers, "ineligible": ineligible,
    }


def recent_jobs(session: Session, limit: int = 5) -> list[Job]:
    return list(session.scalars(select(Job).order_by(Job.first_seen.desc()).limit(limit)))


def jobs_by_ids(session: Session, ids: Iterable[str]) -> list[Job]:
    ids = list(ids)
    if not ids:
        return []
    return list(session.scalars(select(Job).where(Job.id.in_(ids))))
