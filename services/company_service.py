"""Company / ATS board registry."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import get_settings
from core.logging_config import get_logger
from core.models import Company
from core.text import normalize_text, normalize_whitespace, slugify
from connectors.company_careers import detect_ats_from_url

logger = get_logger("companies")

ATS_SLUGS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee",
             "personio", "workday", "teamtailor"}


def upsert_company(session: Session, *, name: str, provider: str = "", identifier: str = "",
                   country: str = "", career_url: str = "", user_supplied: bool = False,
                   error: str = "", health: str = "", jobs_seen: int | None = None) -> Company:
    name = normalize_whitespace(name)
    provider = (provider or "").strip().lower()
    identifier = normalize_whitespace(identifier)
    row = None
    if provider and identifier:
        row = session.scalars(
            select(Company).where(Company.ats_provider == provider,
                                  Company.ats_identifier == identifier)
        ).first()
    if row is None and name:
        row = session.scalars(                                  select(Company).where(Company.normalized_name == normalize_text(name))
        ).first()
    if row is None:
        row = Company(name=name or identifier or "Unknown company",
                      normalized_name=normalize_text(name or identifier or "unknown"),
                      ats_provider=provider, ats_identifier=identifier)
        session.add(row)
    if provider and not row.ats_provider:
        row.ats_provider = provider
    if identifier and not row.ats_identifier:
        row.ats_identifier = identifier
    if country and not row.country:
        row.country = country
    if career_url and not row.career_url:
        row.career_url = career_url
    if user_supplied:
        row.user_supplied = True
    if health:
        row.health = health
        row.last_scanned_at = datetime.now(timezone.utc)
    if error:
        row.last_error = error[:1000]
    if jobs_seen is not None:
        row.jobs_seen = jobs_seen
    session.flush()
    return row


def seed_company_registry(session: Session) -> int:
    """Register the default ATS boards from configuration (idempotent)."""
    settings = get_settings()
    added = 0
    for provider, boards in settings.seed_boards.items():
        for board in boards or []:
            if not board:
                continue
            # Format: "identifier" or "Display name:identifier".
            name, _, identifier = board.rpartition(":")
            name = name.strip()
            identifier = identifier.strip()
            if not name:
                name, identifier = identifier, identifier
            upsert_company(session, name=name, provider=provider, identifier=identifier)
            added += 1
    return added


def add_company(session: Session, name: str, career_url: str = "", country: str = "") -> Company:
    """Add a user-supplied company, detecting the ATS from its careers URL if possible."""
    detected = detect_ats_from_url(career_url) if career_url else None
    provider, identifier = detected or ("", "")
    if not provider:
        provider, identifier = "company_careers", slugify(name) if name else ""
    return upsert_company(session, name=name, provider=provider, identifier=identifier,
                          country=country, career_url=career_url, user_supplied=True)


def list_companies(session: Session, *, only_with_jobs: bool = False) -> list[Company]:
    rows = session.scalars(select(Company).order_by(Company.name)).all()
    if only_with_jobs:
        return [r for r in rows if r.jobs_seen > 0]
    return list(rows)


def mark_company_result(session: Session, provider: str, identifier: str, *,
                        jobs_seen: int, health: str, error: str = "") -> Company | None:
    row = session.scalars(
        select(Company).where(Company.ats_provider == provider,
                              Company.ats_identifier == identifier)
    ).first()
    if row is None:
        return None
    row.jobs_seen = jobs_seen
    row.health = health
    row.last_scanned_at = datetime.now(timezone.utc)
    row.last_error = error[:1000] if error else ""
    return row
