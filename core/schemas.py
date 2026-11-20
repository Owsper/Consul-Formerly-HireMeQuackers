"""Pydantic data contracts used across the whole application."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.text import normalize_string_list, normalize_whitespace, skill_group_status


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceStatus(str, Enum):
    UNVERIFIED = "unverified"
    NEEDS_REVIEW = "needs_review"
    USER_VERIFIED = "user_verified"
    REJECTED = "rejected"


class WorkMode(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class ListingStatus(str, Enum):
    ACTIVE = "active"
    POSSIBLY_ACTIVE = "possibly_active"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"
    UNVERIFIED = "unverified"


class MatchClass(str, Enum):
    EXCELLENT = "excellent"
    STRONG = "strong"
    POTENTIAL = "potential"
    WEAK = "weak"
    NOT_RECOMMENDED = "not_recommended"


class EligiblityStatus(str, Enum):
    ELIGIBLE = "eligible"
    LIKELY_ELIGIBLE = "likely_eligible"
    UNCLEAR = "unclear"
    INELIGIBLE = "ineligible"


class SourceHealth(str, Enum):
    HEALTHY = "healthy"
    PARTIAL = "partially_working"
    RATE_LIMITED = "rate_limited"
    RESTRICTED = "restricted"
    MISSING_CONFIG = "configuration_missing"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Candidate profile
# ---------------------------------------------------------------------------
class _Lenient(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class PersonalInfo(_Lenient):
    full_name: str = ""
    professional_title: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    country: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    website: str = ""

    @property
    def contact_lines(self) -> list[str]:
        items = [self.email, self.phone, self.city and ", ".join(x for x in (self.city, self.country) if x)]
        items += [u.replace("https://", "").replace("http://", "").rstrip("/") for u in
                  (self.linkedin, self.github, self.portfolio, self.website) if u]
        return [x for x in items if x]


class WorkAuthorization(_Lenient):
    residence_country: str = ""
    visa_status: str = ""
    authorized_to_work: bool | None = None
    work_hour_restrictions: str = ""
    sponsorship_required: bool | None = None
    relocation_preference: str = ""
    geographic_limitations: str = ""


class EducationEntry(_Lenient):
    id: str = ""
    institution: str = ""
    qualification: str = ""
    degree: str = ""
    subject: str = ""
    start_date: str = ""
    end_date: str = ""
    status: str = ""
    coursework: list[str] = Field(default_factory=list)
    academic_projects: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)


class EmploymentEntry(_Lenient):
    id: str = ""
    employer: str = ""
    title: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    current: bool = False
    responsibilities: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    quantified_results: list[str] = Field(default_factory=list)

    @field_validator("technologies", mode="before")
    @classmethod
    def _normalize_technologies(cls, value: Any) -> list[str]:
        return normalize_string_list(value)


class ProjectEntry(_Lenient):
    id: str = ""
    name: str = ""
    description: str = ""
    team_type: str = ""  # individual | team
    role: str = ""
    technologies: list[str] = Field(default_factory=list)
    implementation: str = ""
    measurable_results: str = ""
    start_date: str = ""
    end_date: str = ""
    github_url: str = ""
    verified_achievements: list[str] = Field(default_factory=list)
    label: str = "project"  # project | academic_project

    @field_validator("technologies", mode="before")
    @classmethod
    def _normalize_technologies(cls, value: Any) -> list[str]:
        return normalize_string_list(value)


class SkillCategory(_Lenient):
    name: str = ""
    # "demonstrated" (default), "learning" or "interest". An empty value falls
    # back to the group name, so "Currently learning" is recognised too.
    proficiency: str = ""
    skills: list[str] = Field(default_factory=list)

    @field_validator("skills", mode="before")
    @classmethod
    def _normalize_skills(cls, value: Any) -> list[str]:
        return normalize_string_list(value)


class Certification(_Lenient):
    id: str = ""
    name: str = ""
    issuer: str = ""
    date: str = ""
    credential_url: str = ""


class Award(_Lenient):
    id: str = ""
    name: str = ""
    issuer: str = ""
    date: str = ""


class Publication(_Lenient):
    id: str = ""
    title: str = ""
    venue: str = ""
    date: str = ""
    url: str = ""


class VolunteeringEntry(_Lenient):
    id: str = ""
    organization: str = ""
    role: str = ""
    dates: str = ""
    description: str = ""


class LanguageEntry(_Lenient):
    language: str = ""
    proficiency: str = ""


class AdditionalInfo(_Lenient):
    certifications: list[Certification] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
    volunteering: list[VolunteeringEntry] = Field(default_factory=list)
    languages: list[LanguageEntry] = Field(default_factory=list)
    professional_interests: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)


class CandidateProfileData(_Lenient):
    """The Ground Truth profile: job-application independent."""

    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    education: list[EducationEntry] = Field(default_factory=list)
    employment: list[EmploymentEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[SkillCategory] = Field(default_factory=list)
    additional: AdditionalInfo = Field(default_factory=AdditionalInfo)
    extra_sections: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("extra_sections", mode="before")
    @classmethod
    def _coerce_extra_sections(cls, value: Any) -> dict[str, list[str]]:
        """Models occasionally return a string or a scalar here; coerce it.

        Rejecting it would cost a full retry (and, on metered plans, a whole
        request), so a slightly loose value is normalised instead.
        """
        if value is None:
            return {}
        if isinstance(value, str):
            return {"notes": [value]} if value.strip() else {}
        if isinstance(value, list):
            return {"notes": [str(v) for v in value if str(v).strip()]}
        if not isinstance(value, dict):
            return {}
        out: dict[str, list[str]] = {}
        for key, item in value.items():
            name = str(key)
            if item is None:
                out[name] = []
            elif isinstance(item, str):
                out[name] = [item] if item.strip() else []
            elif isinstance(item, list):
                out[name] = [str(v) for v in item if str(v).strip()]
            else:
                out[name] = [str(item)]
        return out

    def _skills_by_status(self, status: str) -> list[str]:
        out: list[str] = []
        for group in self.skills:
            if skill_group_status(group.name, group.proficiency) != status:
                continue
            out.extend(group.skills)
        return out

    def demonstrated_skills(self) -> list[str]:
        """Skills the candidate can actually stand behind.

        An explicit learning/interest entry wins over an incidental mention in
        another group or project: the candidate has told us they cannot yet
        claim it.
        """
        excluded = {normalize_whitespace(skill).lower()
                    for skill in [*self.learning_skills(), *self.interest_skills()]}
        return [skill for skill in self._dedupe_skills(self._skills_by_status("demonstrated"))
                if normalize_whitespace(skill).lower() not in excluded]

    def learning_skills(self) -> list[str]:
        """Skills the candidate is learning, not yet demonstrating."""
        return self._dedupe_skills(self._skills_by_status("learning"))

    def interest_skills(self) -> list[str]:
        """Career interests recorded as skill groups (not qualifications)."""
        return self._dedupe_skills(self._skills_by_status("interest"))

    @staticmethod
    def _dedupe_skills(out: list[str]) -> list[str]:
        seen, result = set(), []
        for skill in out:
            key = normalize_whitespace(skill).lower()
            if key and key not in seen:
                seen.add(key)
                result.append(normalize_whitespace(skill))
        return result

    def all_skills(self) -> list[str]:
        out: list[str] = []
        for group in self.skills:
            out.extend(group.skills)
        for job in self.employment:
            out.extend(job.technologies)
        for project in self.projects:
            out.extend(project.technologies)
        return self._dedupe_skills(out)

    def searchable_text(self, *, include_learning: bool = True) -> str:
        """Text used for relevance matching.

        ``include_learning=False`` is used by scoring: a skill the candidate is
        learning must not read as demonstrated hands-on evidence.
        """
        chunks = [self.personal.professional_title]
        chunks += [e.qualification + " " + e.subject for e in self.education]
        for job in self.employment:
            chunks += [job.title, job.employer, *job.responsibilities, *job.achievements]
        for project in self.projects:
            chunks += [project.name, project.description, project.implementation,
                       project.measurable_results, *project.technologies]
        skills = self.all_skills() if include_learning else self.demonstrated_skills()
        chunks += skills
        chunks += [f"{l.language} {l.proficiency}" for l in self.additional.languages]
        return "\n".join(c for c in chunks if c)


class EvidenceItem(BaseModel):
    evidence_id: str
    category: str
    field_path: str = ""
    label: str = ""
    value: str = ""
    source_document: str = "manual"
    source_text: str = ""
    confidence: float = 0.0
    inferred: bool = False
    status: EvidenceStatus = EvidenceStatus.UNVERIFIED


class ProfilePayload(BaseModel):
    data: CandidateProfileData
    evidence: list[EvidenceItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Search preferences / planning
# ---------------------------------------------------------------------------
class SearchPreferences(BaseModel):
    """A reusable, role-agnostic search profile.

    ``target_titles`` are always the highest-priority signal, so a user who knows
    the exact title is never forced into a category. The category, specialisation
    and skill lists enrich and broaden the plan; they do not restrict it.
    """
    model_config = ConfigDict(extra="allow")
    profile_id: str = ""
    active: bool = True
    name: str = "Default search"
    it_category: str = "any_it"
    specialisation: str = ""
    target_titles: list[str] = Field(default_factory=list)
    alternative_titles: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    seniority: str = ""
    industries: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=lambda: ["remote", "hybrid", "onsite"])
    employment_types: list[str] = Field(default_factory=lambda: ["full_time"])
    languages: list[str] = Field(default_factory=lambda: ["English"])
    salary_min: float | None = None
    salary_currency: str = "EUR"
    min_experience_years: int | None = None
    work_authorization_constraints: str = ""
    max_commute_minutes: int | None = None
    willing_to_relocate: bool = False
    sponsorship_required: bool | None = None
    max_posting_age_days: int = 60
    exclude_companies: list[str] = Field(default_factory=list)
    notes: str = ""


class PlannedQuery(BaseModel):
    query: str
    language: str = "en"
    target: Literal["ats", "search", "careers", "any"] = "any"
    priority: int = 3
    rationale: str = ""


class SearchPlan(BaseModel):
    candidate_summary: str = ""
    it_category: str = "any_it"
    specialisation: str = ""
    role_families: list[str] = Field(default_factory=list)
    english_titles: list[str] = Field(default_factory=list)
    local_titles: dict[str, list[str]] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    queries: list[PlannedQuery] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)
    source: str = "llm"  # llm | rule_based
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
class JobRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    source: str
    source_job_id: str = ""
    title: str
    company: str = ""
    company_website: str = ""
    location: str = ""
    country: str = ""
    work_mode: WorkMode = WorkMode.UNKNOWN
    employment_type: str = ""
    seniority: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_frequency: str = ""
    posted_at: date | None = None
    closing_at: date | None = None
    description: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    education_requirements: list[str] = Field(default_factory=list)
    experience_requirements: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    work_authorization_requirements: list[str] = Field(default_factory=list)
    visa_sponsorship: bool | None = None
    application_url: str = ""
    original_url: str = ""
    first_seen: datetime = Field(default_factory=utcnow)
    last_verified: datetime | None = None
    status: ListingStatus = ListingStatus.UNVERIFIED
    is_snippet: bool = False
    language: str = ""
    match_score: float | None = None

    @field_validator("title", "company", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> str:
        return normalize_whitespace(str(value or ""))

    def display_location(self) -> str:
        return self.location or self.country or "Location not stated"


class SalaryInfo(BaseModel):
    minimum: float | None = None
    maximum: float | None = None
    currency: str = ""
    frequency: str = ""


# ---------------------------------------------------------------------------
# Match analysis
# ---------------------------------------------------------------------------
class DimensionScore(BaseModel):
    name: str
    weight: float
    score: float
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class EligibilityAssessment(BaseModel):
    status: EligiblityStatus = EligiblityStatus.UNCLEAR
    concerns: list[str] = Field(default_factory=list)
    notes: str = ""


class MatchResult(BaseModel):
    job_id: str = ""
    total_score: float = 0.0
    suitability: float = 0.0
    eligibility: EligibilityAssessment = Field(default_factory=EligibilityAssessment)
    dimensions: list[DimensionScore] = Field(default_factory=list)
    matching_skills: list[str] = Field(default_factory=list)
    transferable_skills: list[str] = Field(default_factory=list)
    transferability_notes: list[str] = Field(default_factory=list)
    # Requirements the candidate lists as learning: surfaced separately, never
    # counted as demonstrated or used as a CV claim.
    learning_skills: list[str] = Field(default_factory=list)
    role_family: str = ""
    missing_required_skills: list[str] = Field(default_factory=list)
    preferred_skills_held: list[str] = Field(default_factory=list)
    relevant_projects: list[str] = Field(default_factory=list)
    relevant_experience: list[str] = Field(default_factory=list)
    education_alignment: str = ""
    language_compatibility: str = ""
    work_authorization_notes: str = ""
    red_flags: list[str] = Field(default_factory=list)
    explanation: str = ""
    classification: MatchClass = MatchClass.WEAK
    recommended_action: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Tailored CV
# ---------------------------------------------------------------------------
class CVBullet(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class CVEntry(BaseModel):
    title: str = ""
    organization: str = ""
    location: str = ""
    dates: str = ""
    technologies: list[str] = Field(default_factory=list)
    bullets: list[CVBullet] = Field(default_factory=list)


class CVRow(BaseModel):
    """A two-column row: label on the left, wrapped text in the main column."""

    label: str = ""
    text: str = ""


class CVSection(BaseModel):
    heading: str
    kind: Literal["summary", "skills", "entries", "lines"] = "entries"
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    rows: list[CVRow] = Field(default_factory=list)
    entries: list[CVEntry] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)


class CVHeader(BaseModel):
    name: str = ""
    title: str = ""
    contact_lines: list[str] = Field(default_factory=list)
    visa_status: str = ""
    applying_for: str = ""


class TailoredCV(BaseModel):
    header: CVHeader = Field(default_factory=CVHeader)
    summary: str = ""
    sections: list[CVSection] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)
    generator: str = "rule_based"
    target_job_title: str = ""
    target_company: str = ""

    def all_bullets(self) -> list[CVBullet]:
        out: list[CVBullet] = []
        for section in self.sections:
            for entry in section.entries:
                out.extend(entry.bullets)
        return out


class ValidationIssue(BaseModel):
    severity: Literal["warning", "error"] = "warning"
    code: str = ""
    message: str = ""


class ValidationReport(BaseModel):
    passed: bool = True
    issues: list[ValidationIssue] = Field(default_factory=list)
    evidence_coverage: float = 0.0
    unsupported_claims: list[str] = Field(default_factory=list)
    matched_requirements: list[str] = Field(default_factory=list)
    unmet_requirements: list[str] = Field(default_factory=list)
    removed_content: list[str] = Field(default_factory=list)
    ats_checks: dict[str, bool] = Field(default_factory=dict)
    ats_report: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Scan diagnostics
# ---------------------------------------------------------------------------
class SourceReportData(BaseModel):
    connector: str
    display_name: str = ""
    status: SourceHealth = SourceHealth.MISSING_CONFIG
    queries_executed: int = 0
    requests_made: int = 0
    requests_ok: int = 0
    requests_failed: int = 0
    jobs_found: int = 0
    jobs_accepted: int = 0
    duration_seconds: float = 0.0
    error: str = ""
    last_success: datetime | None = None
    detail: str = ""


class ScanSummary(BaseModel):
    scan_id: str = ""
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    sources: list[SourceReportData] = Field(default_factory=list)
    jobs_retrieved: int = 0
    jobs_unique: int = 0
    jobs_new: int = 0
    snippets: int = 0
    not_scanned: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    cancelled: bool = False


# ---------------------------------------------------------------------------
# Application tracker
# ---------------------------------------------------------------------------
DEFAULT_STATUSES = [
    "Discovered", "Shortlisted", "Reviewing", "CV generated", "Ready to apply",
    "Applied", "Assessment", "Interview", "Technical interview", "Final interview",
    "Offer received", "Rejected", "Withdrawn", "Archived",
]


class ApplicationRecord(BaseModel):
    id: int | None = None
    job_id: str
    status: str = "Discovered"
    tailored_cv_id: int | None = None
    cover_letter: str = ""
    notes: str = ""
    contact_person: str = ""
    follow_up_date: date | None = None
    interview_date: date | None = None
    applied_at: date | None = None
    salary_notes: str = ""
    outcome_notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
