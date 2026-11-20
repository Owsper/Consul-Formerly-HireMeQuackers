"""Application tracker: statuses, notes, follow-ups and duplicate prevention."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.exceptions import (
    DuplicateApplicationError, InvalidStatusError, JobNotFoundError,
)
from core.logging_config import get_logger
from core.models import Application, ApplicationActivity, Job, TailoredCVRow, UserSetting
from core.schemas import (
    DEFAULT_STATUSES, ApplicationRecord, JobRecord, ListingStatus, WorkMode,
)
from services.deduplication import persist_job

logger = get_logger("applications")

CUSTOM_STATUS_KEY = "custom_statuses"
CLOSED_STATUSES = {"Rejected", "Withdrawn", "Archived"}


def _custom_statuses(session: Session) -> list[str]:
    row = session.get(UserSetting, CUSTOM_STATUS_KEY)
    if row is None or not row.value:
        return []
    try:
        values = json.loads(row.value)
        return [str(v).strip() for v in values if str(v).strip()]
    except (json.JSONDecodeError, TypeError):
        return []


def list_statuses(session: Session) -> list[str]:
    statuses = list(DEFAULT_STATUSES)
    for name in _custom_statuses(session):
        if name.lower() not in {s.lower() for s in statuses}:
            statuses.append(name)
    return statuses


def add_custom_status(session: Session, name: str) -> list[str]:
    name = (name or "").strip()[:60]
    if not name:
        return list_statuses(session)
    custom = _custom_statuses(session)
    if name.lower() not in {s.lower() for s in [*DEFAULT_STATUSES, *custom]}:
        custom.append(name)
        row = session.get(UserSetting, CUSTOM_STATUS_KEY)
        value = json.dumps(custom)
        if row is None:
            session.add(UserSetting(key=CUSTOM_STATUS_KEY, value=value))
        else:
            row.value = value
        session.flush()
    return list_statuses(session)


def remove_custom_status(session: Session, name: str) -> list[str]:
    custom = [s for s in _custom_statuses(session) if s.lower() != (name or "").lower()]
    row = session.get(UserSetting, CUSTOM_STATUS_KEY)
    if row is not None:
        row.value = json.dumps(custom)
    session.flush()
    return list_statuses(session)


def canonical_status(session: Session, status: str) -> str:
    status = (status or "").strip()
    for known in list_statuses(session):
        if known.lower() == status.lower():
            return known
    raise InvalidStatusError(f"Unknown application status: {status!r}")


def to_record(row: Application) -> ApplicationRecord:
    return ApplicationRecord(
        id=row.id, job_id=row.job_id, status=row.status,
        tailored_cv_id=row.tailored_cv_id, cover_letter=row.cover_letter,
        notes=row.notes, contact_person=row.contact_person,
        follow_up_date=row.follow_up_date, interview_date=row.interview_date,
        applied_at=row.applied_at, salary_notes=row.salary_notes,
        outcome_notes=row.outcome_notes,
        created_at=row.created_at or datetime.now(timezone.utc),
        updated_at=row.updated_at or datetime.now(timezone.utc),
    )


def get_application(session: Session, application_id: int) -> Application | None:
    return session.get(Application, application_id)


def get_application_for_job(session: Session, job_id: str) -> Application | None:
    return session.scalars(select(Application).where(Application.job_id == job_id)).first()


def log_activity(session: Session, application: Application, kind: str, message: str) -> None:
    session.add(ApplicationActivity(application_id=application.id, kind=kind[:60],
                                    message=message[:2000]))


def activities_for(session: Session, application_id: int) -> list[ApplicationActivity]:
    return list(session.scalars(
        select(ApplicationActivity).where(ApplicationActivity.application_id == application_id)
        .order_by(ApplicationActivity.created_at.desc())
    ))


def create_application(session: Session, job_id: str, *, status: str = "Discovered",
                       notes: str = "", contact_person: str = "", salary_notes: str = "",
                       cover_letter: str = "", tailored_cv_id: int | None = None,
                       applied_at: date | None = None) -> Application:
    """Create one application per job. Raises on duplicates instead of silently overwriting."""
    if session.get(Job, job_id) is None:
        raise JobNotFoundError("That job no longer exists.")
    if get_application_for_job(session, job_id) is not None:
        raise DuplicateApplicationError("An application already exists for this job.")
    resolved = canonical_status(session, status or "Discovered")
    row = Application(
        job_id=job_id, status=resolved, notes=notes.strip(),
        contact_person=contact_person.strip(), salary_notes=salary_notes.strip(),
        cover_letter=cover_letter, tailored_cv_id=tailored_cv_id,
        applied_at=applied_at or (date.today() if resolved == "Applied" else None),
    )
    session.add(row)
    session.flush()
    log_activity(session, row, "created", f"Application created with status '{resolved}'.")
    return row


def ensure_application(session: Session, job_id: str, *, status: str = "Discovered") -> tuple[Application, bool]:
    existing = get_application_for_job(session, job_id)
    if existing is not None:
        return existing, False
    return create_application(session, job_id, status=status), True


def update_application(session: Session, application_id: int, *, status: str | None = None,
                       notes: str | None = None, contact_person: str | None = None,
                       follow_up_date: date | None = None, interview_date: date | None = None,
                       salary_notes: str | None = None, cover_letter: str | None = None,
                       outcome_notes: str | None = None, tailored_cv_id: int | None = None,
                       applied_at: date | None = None) -> Application:
    row = get_application(session, application_id)
    if row is None:
        raise JobNotFoundError("That application no longer exists.")

    if status is not None:
        resolved = canonical_status(session, status)
        if resolved != row.status:
            log_activity(session, row, "status", f"Status changed from '{row.status}' to '{resolved}'.")
            row.status = resolved
            if resolved == "Applied" and not row.applied_at:
                row.applied_at = applied_at or date.today()
    if applied_at is not None:
        row.applied_at = applied_at
    if notes is not None and notes.strip() != row.notes:
        row.notes = notes.strip()
        log_activity(session, row, "note", "Notes updated.")
    if contact_person is not None:
        row.contact_person = contact_person.strip()
    if follow_up_date is not None:
        if follow_up_date != row.follow_up_date:
            log_activity(session, row, "follow_up",
                         f"Follow-up set for {follow_up_date.isoformat()}.")
        row.follow_up_date = follow_up_date
    if interview_date is not None:
        if interview_date != row.interview_date:
            log_activity(session, row, "interview",
                         f"Interview scheduled for {interview_date.isoformat()}.")
        row.interview_date = interview_date
    if salary_notes is not None:
        row.salary_notes = salary_notes.strip()
    if cover_letter is not None:
        row.cover_letter = cover_letter
    if outcome_notes is not None:
        row.outcome_notes = outcome_notes.strip()
    if tailored_cv_id is not None:
        if session.get(TailoredCVRow, tailored_cv_id) is None:
            raise JobNotFoundError("That CV version does not exist.")
        row.tailored_cv_id = tailored_cv_id
        log_activity(session, row, "cv", f"Attached CV version #{tailored_cv_id}.")
    session.flush()
    return row


def clear_follow_up(session: Session, application_id: int) -> None:
    row = get_application(session, application_id)
    if row is not None:
        row.follow_up_date = None
        log_activity(session, row, "follow_up", "Follow-up cleared.")
        session.flush()


def clear_dates(session: Session, application_id: int) -> None:
    """Remove scheduled dates without touching the rest of the record."""
    row = get_application(session, application_id)
    if row is not None:
        row.follow_up_date = None
        row.interview_date = None
        log_activity(session, row, "dates", "Follow-up and interview dates cleared.")
        session.flush()


def set_status(session: Session, application_id: int, status: str) -> Application:
    return update_application(session, application_id, status=status)


def list_applications(session: Session, *, status: str = "", search: str = "",
                      limit: int = 500) -> list[Application]:
    stmt = select(Application).join(Job, Job.id == Application.job_id)
    if status:
        stmt = stmt.where(Application.status == status)
    if search:
        needle = f"%{search.lower()}%"
        stmt = stmt.where(Job.title.ilike(needle) | Job.company.ilike(needle))
    stmt = stmt.order_by(Application.updated_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def kanban(session: Session, *, statuses: list[str] | None = None) -> dict[str, list[Application]]:
    statuses = statuses or list_statuses(session)
    board: dict[str, list[Application]] = {s: [] for s in statuses}
    for row in session.scalars(select(Application).order_by(Application.sort_order, Application.id)):
        board.setdefault(row.status, []).append(row)
    return board


def upcoming(session: Session, days: int = 14) -> dict[str, list[Application]]:
    today = date.today()
    horizon = today + timedelta(days=days)
    follow_ups = list(session.scalars(
        select(Application).where(Application.follow_up_date.isnot(None),
                                  Application.follow_up_date <= horizon,
                                  Application.status.notin_(list(CLOSED_STATUSES)))
        .order_by(Application.follow_up_date)
    ))
    interviews = list(session.scalars(
        select(Application).where(Application.interview_date.isnot(None),
                                  Application.interview_date >= today,
                                  Application.interview_date <= horizon)
        .order_by(Application.interview_date)
    ))
    overdue = [a for a in follow_ups if a.follow_up_date and a.follow_up_date < today]
    return {"follow_ups": follow_ups, "interviews": interviews, "overdue": overdue}


def tracker_stats(session: Session) -> dict:
    rows = list(session.scalars(select(Application)))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "total": len(rows),
        "active": sum(1 for r in rows if r.status not in CLOSED_STATUSES),
        "interviews": sum(1 for r in rows if "interview" in r.status.lower()),
        "offers": counts.get("Offer received", 0),
        "rejected": counts.get("Rejected", 0),
        "by_status": counts,
    }


def delete_application(session: Session, application_id: int) -> bool:
    row = get_application(session, application_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


# ---------------------------------------------------------------------------
# Manual job entry
# ---------------------------------------------------------------------------
def add_manual_job(session: Session, *, title: str, company: str, url: str = "",
                   location: str = "", country: str = "", description: str = "",
                   application_url: str = "", employment_type: str = "full_time",
                   work_mode: WorkMode = WorkMode.UNKNOWN, source: str = "manual",
                   create_tracker_entry: bool = False) -> tuple[Job, bool]:
    title = (title or "").strip()
    if not title:
        raise ValueError("A job title is required.")
    record = JobRecord(
        source=source, source_job_id=f"{source}-{uuid.uuid4().hex[:12]}",
        title=title, company=(company or "").strip(),
        location=(location or "").strip(), country=(country or "").strip(),
        description=(description or "").strip(), employment_type=employment_type,
        work_mode=work_mode, original_url=url or "", application_url=application_url or url or "",
        status=ListingStatus.UNVERIFIED,
    )
    row, created = persist_job(session, record)
    if create_tracker_entry and created:
        ensure_application(session, row.id)
    session.flush()
    return row, created
