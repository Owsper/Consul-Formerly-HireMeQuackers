"""SQLAlchemy ORM models (SQLite now, PostgreSQL-ready)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class CandidateProfile(Base, TimestampMixin):
    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="My profile")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    evidence: Mapped[list["ProfileEvidence"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", lazy="selectin"
    )
    versions: Mapped[list["ProfileVersion"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="ProfileVersion.version"
    )


class ProfileEvidence(Base):
    __tablename__ = "profile_evidence"
    __table_args__ = (UniqueConstraint("profile_id", "evidence_id", name="uq_evidence_profile_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(60), default="general")
    field_path: Mapped[str] = mapped_column(String(300), default="")
    label: Mapped[str] = mapped_column(String(300), default="")
    value: Mapped[str] = mapped_column(Text, default="")
    source_document: Mapped[str] = mapped_column(String(300), default="manual")
    source_text: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    inferred: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="unverified", index=True)

    profile: Mapped[CandidateProfile] = relationship(back_populates="evidence")


class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    __table_args__ = (UniqueConstraint("profile_id", "version", name="uq_profile_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    profile: Mapped[CandidateProfile] = relationship(back_populates="versions")


class SearchPreferenceRow(Base, TimestampMixin):
    __tablename__ = "search_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Default search")
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    profile_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferences_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")

    sources: Mapped[list["ScanSourceReport"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", lazy="selectin"
    )
    queries: Mapped[list["ScanQuery"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", lazy="selectin"
    )


class ScanSourceReport(Base):
    __tablename__ = "scan_source_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_sessions.id", ondelete="CASCADE"), index=True)
    connector: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(40), default="configuration_missing")
    queries_executed: Mapped[int] = mapped_column(Integer, default=0)
    requests_made: Mapped[int] = mapped_column(Integer, default=0)
    requests_ok: Mapped[int] = mapped_column(Integer, default=0)
    requests_failed: Mapped[int] = mapped_column(Integer, default=0)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_accepted: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    last_success: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    scan: Mapped[ScanSession] = relationship(back_populates="sources")


class ScanQuery(Base):
    __tablename__ = "scan_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_sessions.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(20), default="en")
    target: Mapped[str] = mapped_column(String(30), default="any")
    priority: Mapped[int] = mapped_column(Integer, default=3)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    results: Mapped[int] = mapped_column(Integer, default=0)

    scan: Mapped[ScanSession] = relationship(back_populates="queries")


class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("ats_provider", "ats_identifier", name="uq_company_ats"),
        Index("ix_company_norm_name", "normalized_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    career_url: Mapped[str] = mapped_column(String(600), default="")
    ats_provider: Mapped[str] = mapped_column(String(60), default="")
    ats_identifier: Mapped[str] = mapped_column(String(200), default="")
    country: Mapped[str] = mapped_column(String(100), default="")
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    health: Mapped[str] = mapped_column(String(40), default="unknown")
    jobs_seen: Mapped[int] = mapped_column(Integer, default=0)
    user_supplied: Mapped[bool] = mapped_column(Boolean, default=False)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_company_title", "company_normalized", "title_normalized"),
        Index("ix_jobs_fingerprint", "fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(400), index=True)
    title_normalized: Mapped[str] = mapped_column(String(400), default="")
    company: Mapped[str] = mapped_column(String(300), index=True)
    company_normalized: Mapped[str] = mapped_column(String(300), default="")
    company_website: Mapped[str] = mapped_column(String(600), default="")
    location: Mapped[str] = mapped_column(String(400), default="")
    country: Mapped[str] = mapped_column(String(100), default="", index=True)
    work_mode: Mapped[str] = mapped_column(String(30), default="unknown")
    employment_type: Mapped[str] = mapped_column(String(60), default="")
    seniority: Mapped[str] = mapped_column(String(60), default="")
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(10), default="")
    salary_frequency: Mapped[str] = mapped_column(String(20), default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closing_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    responsibilities_json: Mapped[str] = mapped_column(Text, default="[]")
    required_skills_json: Mapped[str] = mapped_column(Text, default="[]")
    preferred_skills_json: Mapped[str] = mapped_column(Text, default="[]")
    education_json: Mapped[str] = mapped_column(Text, default="[]")
    experience_json: Mapped[str] = mapped_column(Text, default="[]")
    languages_json: Mapped[str] = mapped_column(Text, default="[]")
    work_auth_json: Mapped[str] = mapped_column(Text, default="[]")
    visa_sponsorship: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    application_url: Mapped[str] = mapped_column(String(1000), default="")
    original_url: Mapped[str] = mapped_column(String(1000), default="")
    url_key: Mapped[str] = mapped_column(String(500), default="", index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    listing_status: Mapped[str] = mapped_column(String(30), default="unverified", index=True)
    is_snippet: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(20), default="")
    fingerprint: Mapped[str] = mapped_column(String(80), default="")

    sources: Mapped[list["JobSourceRef"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )
    match: Mapped["JobMatchRow | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    saved: Mapped["SavedJob | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    applications: Mapped[list["Application"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )


class JobSourceRef(Base):
    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("connector", "source_job_id", name="uq_job_source_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    connector: Mapped[str] = mapped_column(String(80))
    source_job_id: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000), default="")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    job: Mapped[Job] = relationship(back_populates="sources")


class JobMatchRow(Base):
    __tablename__ = "job_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True)
    profile_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    suitability: Mapped[float] = mapped_column(Float, default=0.0)
    eligibility_status: Mapped[str] = mapped_column(String(30), default="unclear")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    job: Mapped[Job] = relationship(back_populates="match")


class SavedJob(Base):
    __tablename__ = "saved_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    job: Mapped[Job] = relationship(back_populates="saved")


class TailoredCVRow(Base):
    __tablename__ = "tailored_cvs"
    __table_args__ = (UniqueConstraint("job_id", "version", name="uq_tailored_cv_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_map_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_json: Mapped[str] = mapped_column(Text, default="{}")
    docx_path: Mapped[str] = mapped_column(String(1000), default="")
    pdf_path: Mapped[str] = mapped_column(String(1000), default="")
    template_name: Mapped[str] = mapped_column(String(300), default="builtin")
    generator: Mapped[str] = mapped_column(String(30), default="rule_based")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Application(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(60), default="Discovered", index=True)
    tailored_cv_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_letter: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    contact_person: Mapped[str] = mapped_column(String(300), default="")
    follow_up_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    interview_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    salary_notes: Mapped[str] = mapped_column(String(300), default="")
    outcome_notes: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    job: Mapped[Job] = relationship(back_populates="applications")
    activities: Mapped[list["ApplicationActivity"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin",
        order_by="ApplicationActivity.created_at",
    )


class ApplicationActivity(Base):
    __tablename__ = "application_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(60), default="note")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    application: Mapped[Application] = relationship(back_populates="activities")


class UserSetting(Base, TimestampMixin):
    __tablename__ = "user_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
