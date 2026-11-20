"""Job deduplication with exact keys first, fuzzy comparison second.

The same vacancy often appears on several boards. We keep one canonical job row
with multiple source references and preserve the most official application link.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.logging_config import get_logger
from core.models import Company, Job, JobSourceRef
from core.schemas import JobRecord, ListingStatus
from core.text import normalize_text, normalize_whitespace, similarity
from services.job_service import new_job_id

logger = get_logger("dedup")

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gh_src",
    "lever-source", "source", "ref", "referrer", "tracking", "fbclid", "gclid",
    "mc_cid", "mc_eid", "src", "campaign", "jobboard",
}

COMPANY_SUFFIXES = re.compile(
    r"\b(gmbh|mbh|ag|se|kg|ug|ohg|inc|incorporated|ltd|limited|llc|plc|bv|nv|sa|sas|sarl|"
    r"spa|srl|oy|ab|as|co|corp|corporation|company|group|holding|holdings|international)\b",
    re.I,
)


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", parsed.path or "")
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
             if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
    scheme = "https" if parsed.scheme in {"http", "https"} else parsed.scheme
    return urlunparse((scheme, host, path, "", urlencode(query), ""))


def normalize_company(name: str) -> str:
    cleaned = COMPANY_SUFFIXES.sub(" ", normalize_text(name))
    return normalize_whitespace(re.sub(r"[^\w\s&.+-]", " ", cleaned)).lower()


def normalize_title(title: str) -> str:
    text = normalize_text(title)
    text = re.sub(r"\((?:m|f|w|d|x|gn|all genders)[^)]*\)", " ", text)
    text = re.sub(r"\b(m/w/d|m/f/d|w/m/d|all genders|h/f|m/f)\b", " ", text)
    return normalize_whitespace(text)


def compute_fingerprint(company: str, title: str, location: str) -> str:
    raw = f"{normalize_company(company)}|{normalize_title(title)}|{normalize_text(location)[:60]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _description_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return similarity(a[:4000], b[:4000])


def find_existing(session: Session, record: JobRecord) -> tuple[Job | None, str]:
    """Find a job row that represents the same vacancy."""
    # 1. exact source identity
    if record.source_job_id:
        ref = session.scalars(
            select(JobSourceRef).where(
                JobSourceRef.connector == record.source,
                JobSourceRef.source_job_id == record.source_job_id,
            )
        ).first()
        if ref is not None:
            return session.get(Job, ref.job_id), "source_id"

    # 2. canonical application URL
    for url in (record.application_url, record.original_url):
        key = canonical_url(url)
        if key:
            row = session.scalars(select(Job).where(Job.url_key == key)).first()
            if row is not None:
                return row, "url"

    # 3. fuzzy on company + title + description
    company_key = normalize_company(record.company)
    if not company_key or not record.title:
        return None, ""
    candidates = session.scalars(
        select(Job).where(Job.company_normalized == company_key).limit(60)
    ).all()
    title_norm = normalize_title(record.title)
    for candidate in candidates:
        candidate_title = normalize_title(candidate.title)
        title_sim = similarity(title_norm, candidate_title)
        same_title = candidate_title == title_norm or title_sim >= 0.92
        loc_sim = similarity(record.location or "", candidate.location or "")
        desc_sim = _description_similarity(record.description, candidate.description)
        if same_title and (loc_sim >= 0.7 or not record.location or not candidate.location) and desc_sim >= 0.8:
            return candidate, "fuzzy"
        if same_title and desc_sim >= 0.9:
            return candidate, "fuzzy"
    return None, ""


def _richer_source(a: Job, b: JobRecord) -> bool:
    """True if the incoming record is a better canonical representation."""
    if a.is_snippet and not b.is_snippet:
        return True
    if len(b.description or "") > len(a.description or "") + 200:
        return True
    if not a.application_url and b.application_url:
        return True
    return False


def merge_into(existing: Job, record: JobRecord) -> Job:
    """Merge an incoming record into an existing job without losing provenance."""
    if not existing.description and record.description:
        existing.description = record.description
    if _richer_source(existing, record):
        existing.description = record.description or existing.description
        existing.responsibilities_json = json.dumps(record.responsibilities)
        existing.required_skills_json = json.dumps(record.required_skills)
        existing.preferred_skills_json = json.dumps(record.preferred_skills)
        existing.education_json = json.dumps(record.education_requirements)
        existing.experience_json = json.dumps(record.experience_requirements)
        existing.languages_json = json.dumps(record.languages)
        existing.work_auth_json = json.dumps(record.work_authorization_requirements)
        existing.is_snippet = record.is_snippet
        existing.application_url = record.application_url or existing.application_url
        existing.original_url = record.original_url or existing.original_url
        existing.url_key = canonical_url(existing.application_url or existing.original_url)
        existing.company_website = record.company_website or existing.company_website
    for field in ("salary_min", "salary_max", "salary_currency", "salary_frequency",
                  "posted_at", "closing_at", "employment_type", "seniority", "country",
                  "company_website", "language"):
        if getattr(existing, field) in (None, "", 0) and getattr(record, field) not in (None, "", 0):
            setattr(existing, field, getattr(record, field).date() if hasattr(getattr(record, field), "date") else getattr(record, field))
    if existing.work_mode == "unknown" and record.work_mode.value != "unknown":
        existing.work_mode = record.work_mode.value
    if record.visa_sponsorship is not None and existing.visa_sponsorship is None:
        existing.visa_sponsorship = record.visa_sponsorship
    if record.status != ListingStatus.UNVERIFIED:
        # Reflect what the source says (active or expired) but never delete the job
        # or its history.
        existing.listing_status = record.status.value
    existing.last_verified = datetime.now(timezone.utc)
    return existing


def _add_source(session: Session, job_id: str, record: JobRecord) -> None:
    if not record.source_job_id:
        return
    exists = session.scalars(
        select(JobSourceRef).where(
            JobSourceRef.connector == record.source,
            JobSourceRef.source_job_id == record.source_job_id,
        )
    ).first()
    if exists is not None:
        return
    session.add(JobSourceRef(
        job_id=job_id, connector=record.source, source_job_id=record.source_job_id,
        url=record.original_url or record.application_url,
        raw_json=json.dumps({"title": record.title, "company": record.company}, ensure_ascii=False),
    ))


def persist_job(session: Session, record: JobRecord) -> tuple[Job, bool]:
    """Insert or merge a job. Returns (job row, created).

    A company registry row is created/updated as a side effect for ATS sources.
    """
    existing, reason = find_existing(session, record)
    if existing is not None:
        merge_into(existing, record)
        _add_source(session, existing.id, record)
        session.flush()
        return existing, False

    job_id = new_job_id()
    row = Job(
        id=job_id,
        title=record.title[:400],
        title_normalized=normalize_title(record.title),
        company=record.company[:300],
        company_normalized=normalize_company(record.company),
        company_website=record.company_website[:600],
        location=record.location[:400],
        country=record.country[:100],
        work_mode=record.work_mode.value,
        employment_type=record.employment_type,
        seniority=record.seniority,
        salary_min=record.salary_min,
        salary_max=record.salary_max,
        salary_currency=record.salary_currency,
        salary_frequency=record.salary_frequency,
        posted_at=datetime.combine(record.posted_at, datetime.min.time()) if record.posted_at else None,
        closing_at=datetime.combine(record.closing_at, datetime.min.time()) if record.closing_at else None,
        description=record.description,
        responsibilities_json=json.dumps(record.responsibilities),
        required_skills_json=json.dumps(record.required_skills),
        preferred_skills_json=json.dumps(record.preferred_skills),
        education_json=json.dumps(record.education_requirements),
        experience_json=json.dumps(record.experience_requirements),
        languages_json=json.dumps(record.languages),
        work_auth_json=json.dumps(record.work_authorization_requirements),
        visa_sponsorship=record.visa_sponsorship,
        application_url=record.application_url[:1000],
        original_url=record.original_url[:1000],
        url_key=canonical_url(record.application_url or record.original_url)[:500],
        first_seen=record.first_seen or datetime.now(timezone.utc),
        last_verified=record.last_verified or datetime.now(timezone.utc),
        listing_status=record.status.value,
        is_snippet=record.is_snippet,
        language=record.language,
        fingerprint=compute_fingerprint(record.company, record.title, record.location),
    )
    session.add(row)
    session.flush()
    _add_source(session, job_id, record)
    return row, True
