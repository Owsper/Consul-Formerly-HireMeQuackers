"""CV versioning and persistence.

Ground Truth is never modified here. Each generated CV is a new version tied to
one job, with its content, evidence map, validation report and exported files.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import get_settings
from core.ats_rules import apply_layout_signals
from core.exceptions import JobNotFoundError, ProfileNotFoundError
from core.logging_config import get_logger
from core.models import Job, TailoredCVRow
from core.schemas import MatchResult, TailoredCV, ValidationReport
from services.cv_tailoring import tailor_cv
from services.document_export import export_cv, pdf_render_source
from services.job_scoring import score_record
from services.job_service import get_match, row_to_record
from services.layout_verification import compare_layout
from services.master_template import MASTER_FILENAME
from services.profile_service import get_active_profile
from services.settings_service import get_setting, set_setting

logger = get_logger("cv_service")


def next_version(session: Session, job_id: str) -> int:
    current = session.scalar(
        select(func.max(TailoredCVRow.version)).where(TailoredCVRow.job_id == job_id)
    )
    return int(current or 0) + 1


def generate_cv_for_job(session: Session, job_id: str, *, use_llm: bool = True,
                        language: str | None = None, template_path: str | None = None,
                        formats: tuple[str, ...] = ("docx", "pdf", "txt")) -> tuple[
                            TailoredCVRow, TailoredCV, ValidationReport]:
    job_row = session.get(Job, job_id)
    if job_row is None:
        raise JobNotFoundError("That job no longer exists.")
    active = get_active_profile(session)
    if active is None:
        raise ProfileNotFoundError("Approve a Ground Truth profile before generating a CV.")
    profile_row, payload = active

    job = row_to_record(job_row)
    match = get_match(session, job_id)
    if match is None:
        match = score_record(job, payload.data, payload.evidence,
                             _preferences_for_profile(payload), job_id=job_id)

    cv, report = tailor_cv(payload.data, payload.evidence, job, match,
                           use_llm=use_llm, language=language or job.language or "en")

    version = next_version(session, job_id)
    settings = get_settings()
    settings.ensure_dirs()
    files = export_cv(cv, out_dir=settings.exports_dir, version=version,
                      formats=formats, template_path=template_path)
    _attach_layout_report(report, files)

    row = TailoredCVRow(
        job_id=job_id, profile_id=profile_row.id, version=version,
        content_json=cv.model_dump_json(), evidence_map_json=json.dumps(
            {b.text: b.evidence_ids for b in cv.all_bullets()}, ensure_ascii=False),
        validation_json=report.model_dump_json(),
        docx_path=files.get("docx", ""), pdf_path=files.get("pdf", ""),
        template_name=MASTER_FILENAME,
        generator=cv.generator,
    )
    session.add(row)
    session.flush()
    logger.info("Generated CV v%s for job %s (%s, passed=%s)", version, job_id,
                cv.generator, report.passed)
    return row, cv, report


def _preferences_for_profile(payload) -> "object":
    from core.schemas import SearchPreferences

    return SearchPreferences(target_titles=[payload.data.personal.professional_title],
                             countries=[payload.data.work_authorization.residence_country]
                             if payload.data.work_authorization.residence_country else [])


def load_cv(row: TailoredCVRow) -> tuple[TailoredCV, ValidationReport]:
    try:
        cv = TailoredCV.model_validate_json(row.content_json or "{}")
    except Exception:
        cv = TailoredCV()
    try:
        report = ValidationReport.model_validate_json(row.validation_json or "{}")
    except Exception:
        report = ValidationReport()
    return cv, report


def list_versions(session: Session, job_id: str) -> list[TailoredCVRow]:
    return list(session.scalars(
        select(TailoredCVRow).where(TailoredCVRow.job_id == job_id)
        .order_by(TailoredCVRow.version.desc())
    ))


def get_version(session: Session, cv_id: int) -> TailoredCVRow | None:
    return session.get(TailoredCVRow, cv_id)


def reexport(session: Session, cv_id: int, *, formats: tuple[str, ...] = ("docx", "pdf"),
             template_path: str | None = None) -> dict[str, str]:
    row = get_version(session, cv_id)
    if row is None:
        raise JobNotFoundError("That CV version does not exist.")
    cv, _ = load_cv(row)
    settings = get_settings()
    files = export_cv(cv, out_dir=settings.exports_dir, version=row.version,
                      formats=formats, template_path=template_path)
    if "docx" in files:
        row.docx_path = files["docx"]
    if "pdf" in files:
        row.pdf_path = files["pdf"]
    report = load_cv(row)[1]
    _attach_layout_report(report, files)
    row.validation_json = report.model_dump_json()
    session.flush()
    return files


def _attach_layout_report(report: ValidationReport, files: dict[str, str]) -> None:
    pdf_path = files.get("pdf")
    if not pdf_path or not Path(pdf_path).exists():
        return
    try:
        report.layout = compare_layout(
            pdf_path, source=pdf_render_source(pdf_path),
        )
        report.ats_report = apply_layout_signals(report.ats_report, report.layout)
    except Exception as exc:  # layout verification must never block an export
        logger.warning("Layout verification failed: %s", exc)
        report.layout = {"passed": False, "checks": [], "error": type(exc).__name__}


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------
def _approval_key(cv_id: int) -> str:
    return f"cv_approved_{cv_id}"


def approve_cv(session: Session, cv_id: int) -> None:
    row = get_version(session, cv_id)
    if row is None:
        raise JobNotFoundError("That CV version does not exist.")
    set_setting(session, _approval_key(cv_id), {
        "approved": True,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "version": row.version,
    })


def revoke_cv_approval(session: Session, cv_id: int) -> None:
    set_setting(session, _approval_key(cv_id), {"approved": False})


def is_cv_approved(session: Session, cv_id: int) -> bool:
    value = get_setting(session, _approval_key(cv_id), {}) or {}
    return bool(value.get("approved")) if isinstance(value, dict) else False
