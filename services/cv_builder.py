"""CV Builder: a direct-manipulation editor over Consul's evidence contract.

The builder behaves like a document editor — reorder sections, add entries and
bullets, hide what the advert does not need, and see the page as you type — but
every rule that decides *what may appear* still comes from Consul:

* bullets and skills are checked against the evidence ledger (``sanitize_cv``),
* the document is validated with the same ``validate_cv`` used by CV Studio,
* export goes through the master template and the measured/Chromium PDF path,
* an export requires an explicit approval of exactly the CV being exported.

Drafts live in ``user_settings`` per scope (``master`` or a job id) so they can
be resumed, and exported files are versioned in ``DATA_DIR/exports``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from config import get_settings
from core.exceptions import consulError
from core.schemas import (
    BuilderDraft, CandidateProfileData, CVBullet, CVEntry, CVHeader, CVRow, CVSection,
    EvidenceItem, JobRecord, MatchResult, TailoredCV, ValidationReport,
)
from services.cv_tailoring import (
    _active_evidence, _allowed_skill_text, _dates, _heading, _ids_for_path, _join_nonempty,
    _sentence, _skill_is_supported, _visa_summary, _years_of_experience,
)
from services.document_export import export_cv

DRAFT_KEY_PREFIX = "cv_builder_draft_"
MASTER_SCOPE = "master"

# Sections offered in the "add section" picker. The value is the section kind
# understood by the master template.
# The summary is a document-level field (it prints without a heading), so it is
# edited above the section list rather than added as a section.
SECTION_CATALOG: list[tuple[str, str]] = [
    ("Professional Experience", "entries"),
    ("Project Experience", "entries"),
    ("Academic Projects", "entries"),
    ("Education", "entries"),
    ("Technical Skills", "skills"),
    ("Languages", "lines"),
    ("Certifications", "lines"),
    ("Awards", "lines"),
    ("Publications", "lines"),
    ("Volunteering", "lines"),
    ("Additional Information", "lines"),
]

# The master template's section order, used by "restore master order".
MASTER_ORDER = [
    "profile", "professional experience", "work experience", "experience",
    "project experience", "projects", "academic projects", "education",
    "technical skills", "skills", "languages", "certifications", "awards",
    "publications", "volunteering", "additional information",
]


class BuilderError(consulError):
    code = "builder_error"


@dataclass
class BuilderEvaluation:
    """What the builder shows in its Checks tab and what export is based on."""

    cv: TailoredCV
    report: ValidationReport
    ats: dict[str, Any]
    removed: list[str] = field(default_factory=list)

    @property
    def exportable(self) -> bool:
        return self.report.passed


# ---------------------------------------------------------------------------
# Editor handles
# ---------------------------------------------------------------------------
def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def ensure_ids(cv: TailoredCV) -> TailoredCV:
    """Give every editable node a stable handle used only by the editor."""
    for section in cv.sections:
        section.id = section.id or _new_id("sec")
        for row in section.rows:
            row.id = row.id or _new_id("row")
        for entry in section.entries:
            entry.id = entry.id or _new_id("ent")
            for bullet in entry.bullets:
                bullet.id = bullet.id or _new_id("blt")
    return cv


def content_hash(cv: TailoredCV) -> str:
    """Hash of exactly the rendered content, ignoring editor handles.

    Ids are excluded so that sanitising (which rebuilds bullets) cannot change
    the hash. Any edit that would change the document does.
    """
    payload = cv.model_dump(mode="json", exclude={"generated_at"})

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "id"}
        if isinstance(node, list):
            return [strip(item) for item in node]
        return node

    canonical = json.dumps(strip(payload), sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------
def draft_key(scope: str) -> str:
    return f"{DRAFT_KEY_PREFIX}{scope or MASTER_SCOPE}"


def load_draft(session: Session, scope: str) -> BuilderDraft | None:
    from services.settings_service import get_setting

    raw = get_setting(session, draft_key(scope))
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        draft = BuilderDraft.model_validate(raw)
    except Exception:
        return None
    draft.scope = scope or MASTER_SCOPE
    draft.cv = ensure_ids(draft.cv)
    return draft


def save_draft(session: Session, draft: BuilderDraft) -> BuilderDraft:
    from services.settings_service import set_setting

    draft.updated_at = datetime.now(timezone.utc)
    draft.cv = ensure_ids(draft.cv)
    set_setting(session, draft_key(draft.scope), draft.model_dump(mode="json"))
    return draft


def delete_draft(session: Session, scope: str) -> None:
    from services.settings_service import get_setting, set_setting

    if get_setting(session, draft_key(scope)) is not None:
        set_setting(session, draft_key(scope), {})


def has_draft(session: Session, scope: str) -> bool:
    return load_draft(session, scope) is not None


def _draft(scope: str, cv: TailoredCV, *, language: str, source: str,
           source_label: str) -> BuilderDraft:
    return BuilderDraft(
        scope=scope or MASTER_SCOPE, cv=ensure_ids(cv), language=language or "en",
        source=source, source_label=source_label,
    )


def master_draft(profile: CandidateProfileData, evidence: list[EvidenceItem], *,
                 scope: str = MASTER_SCOPE, language: str = "en") -> BuilderDraft:
    return _draft(scope, build_master_cv(profile, evidence, language=language),
                  language=language, source="ground_truth",
                  source_label="Ground Truth (all verified content)")


def job_draft(profile: CandidateProfileData, evidence: list[EvidenceItem], job: JobRecord,
              match: MatchResult | None, *, scope: str, language: str = "en") -> BuilderDraft:
    from services.cv_tailoring import build_rule_based_cv

    cv = build_rule_based_cv(profile, evidence, job, match, language=language)
    cv, _ = _sanitize_copy(cv, profile, evidence)
    label = f"{job.title} — {job.company}" if job.company else job.title
    return _draft(scope, cv, language=language, source="job", source_label=label)


def version_draft(cv: TailoredCV, *, scope: str, language: str = "en",
                  label: str = "") -> BuilderDraft:
    return _draft(scope, cv.model_copy(deep=True), language=language, source="version",
                  source_label=label or "Saved CV version")


def blank_draft(profile: CandidateProfileData, *, scope: str, language: str = "en") -> BuilderDraft:
    personal = profile.personal
    header = CVHeader(
        name=personal.full_name, title=personal.professional_title,
        contact_lines=list(personal.contact_lines), visa_status=_visa_summary(profile),
    )
    cv = TailoredCV(header=header, generator="builder")
    cv.sections = [
        CVSection(id=_new_id("sec"), heading=_heading("Professional Experience", language),
                  kind="entries"),
        CVSection(id=_new_id("sec"), heading=_heading("Technical Skills", language),
                  kind="skills"),
    ]
    return _draft(scope, cv, language=language, source="scratch", source_label="Blank document")


# ---------------------------------------------------------------------------
# Master CV: every verified fact, no job filter
# ---------------------------------------------------------------------------
def build_master_cv(profile: CandidateProfileData, evidence: list[EvidenceItem], *,
                    language: str = "en") -> TailoredCV:
    """Lay out the whole Ground Truth profile for the builder.

    Unlike a tailored CV nothing is ranked away: the master document is the
    candidate's complete, verified history, and the builder trims it per job.
    """
    personal = profile.personal
    header = CVHeader(
        name=personal.full_name, title=personal.professional_title,
        contact_lines=list(personal.contact_lines), visa_status=_visa_summary(profile),
    )
    cv = TailoredCV(header=header, summary=_master_summary(profile), generator="builder",
                    target_job_title="", target_company="")
    sections: list[CVSection] = []

    if profile.employment:
        entries: list[CVEntry] = []
        for i, entry in enumerate(profile.employment):
            paths = [
                (f"employment[{i}].responsibilities[{j}]", text)
                for j, text in enumerate(entry.responsibilities)
            ] + [
                (f"employment[{i}].achievements[{j}]", text)
                for j, text in enumerate(entry.achievements)
            ] + [
                (f"employment[{i}].quantified_results[{j}]", text)
                for j, text in enumerate(entry.quantified_results)
            ]
            bullets = _master_bullets(evidence, paths)
            entries.append(CVEntry(
                id=_new_id("ent"), title=entry.title, organization=entry.employer,
                location=entry.location,
                dates=_dates(entry.start_date, entry.end_date, entry.current, language),
                technologies=list(entry.technologies), bullets=bullets,
            ))
        sections.append(CVSection(id=_new_id("sec"),
                                  heading=_heading("Professional Experience", language),
                                  kind="entries", entries=entries))

    professional: list[CVEntry] = []
    academic: list[CVEntry] = []
    for i, project in enumerate(profile.projects):
        paths = [
            (f"projects[{i}].description", project.description),
            (f"projects[{i}].implementation", project.implementation),
            (f"projects[{i}].results", project.measurable_results),
        ] + [
            (f"projects[{i}].achievements[{j}]", text)
            for j, text in enumerate(project.verified_achievements)
        ]
        entry = CVEntry(
            id=_new_id("ent"), title=project.name or project.role,
            organization=project.role if project.name else "",
            dates=_dates(project.start_date, project.end_date, False, language),
            technologies=list(project.technologies),
            bullets=_master_bullets(evidence, paths),
        )
        (academic if project.label == "academic_project" else professional).append(entry)
    if professional:
        sections.append(CVSection(id=_new_id("sec"),
                                  heading=_heading("Project Experience", language),
                                  kind="entries", entries=professional))
    if academic:
        sections.append(CVSection(id=_new_id("sec"),
                                  heading=_heading("Academic Projects", language),
                                  kind="entries", entries=academic))

    if profile.education:
        entries = []
        for i, edu in enumerate(profile.education):
            headline = " ".join(x for x in (edu.qualification or edu.degree, edu.subject) if x)
            paths = [
                (f"education[{i}].achievements[{j}]", text)
                for j, text in enumerate(edu.achievements)
            ] + [
                (f"education[{i}].academic_projects[{j}]", text)
                for j, text in enumerate(edu.academic_projects)
            ]
            entries.append(CVEntry(
                id=_new_id("ent"), title=headline or edu.institution,
                organization=edu.institution if headline else "", location="",
                dates=_dates(edu.start_date, edu.end_date, False, language),
                bullets=_master_bullets(evidence, paths),
            ))
        sections.append(CVSection(id=_new_id("sec"),
                                  heading=_heading("Education", language),
                                  kind="entries", entries=entries))

    skill_rows = [
        CVRow(id=_new_id("row"), label=group.name or "Technical",
              text=", ".join(dict.fromkeys(s for s in group.skills if s.strip())))
        for group in profile.skills
    ]
    skill_rows = [row for row in skill_rows if row.text]
    if skill_rows:
        sections.append(CVSection(
            id=_new_id("sec"), heading=_heading("Technical Skills", language), kind="skills",
            skills=list(profile.demonstrated_skills()), rows=skill_rows,
        ))

    extra = profile.additional
    if extra.languages:
        sections.append(CVSection(
            id=_new_id("sec"), heading=_heading("Languages", language), kind="lines",
            rows=[CVRow(id=_new_id("row"), label=item.language, text=item.proficiency or "")
                  for item in extra.languages if item.language],
        ))
    if extra.certifications:
        sections.append(CVSection(
            id=_new_id("sec"), heading=_heading("Certifications", language), kind="lines",
            lines=[_join_nonempty([item.name, item.issuer, item.date], " — ")
                   for item in extra.certifications],
        ))
    if extra.awards:
        sections.append(CVSection(
            id=_new_id("sec"), heading=_heading("Awards", language), kind="lines",
            lines=[_join_nonempty([item.name, item.issuer, item.date], " — ")
                   for item in extra.awards],
        ))
    if extra.publications:
        sections.append(CVSection(
            id=_new_id("sec"), heading=_heading("Publications", language), kind="lines",
            lines=[_join_nonempty([item.title, item.venue, item.date], " — ")
                   for item in extra.publications],
        ))
    if extra.volunteering:
        sections.append(CVSection(
            id=_new_id("sec"), heading=_heading("Volunteering", language), kind="lines",
            lines=[_join_nonempty([item.role, item.organization, item.dates, item.description],
                                  " — ")
                   for item in extra.volunteering],
        ))
    other = [*extra.professional_interests, *extra.other]
    if other:
        sections.append(CVSection(
            id=_new_id("sec"), heading=_heading("Additional Information", language),
            kind="lines", lines=list(dict.fromkeys(other)),
        ))
    for heading, lines in profile.extra_sections.items():
        if lines:
            sections.append(CVSection(id=_new_id("sec"), heading=heading, kind="lines",
                                      lines=list(lines)))

    cv.sections = sections
    return ensure_ids(cv)


def _master_bullets(evidence: list[EvidenceItem], paths: list[tuple[str, str]]) -> list[CVBullet]:
    bullets: list[CVBullet] = []
    seen: set[str] = set()
    for path, text in paths:
        clean = (text or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        bullets.append(CVBullet(id=_new_id("blt"), text=_sentence(clean),
                                evidence_ids=_ids_for_path(evidence, path, clean)[:4]))
    return bullets


def _master_summary(profile: CandidateProfileData) -> str:
    title = profile.personal.professional_title
    if not title and profile.education:
        first = profile.education[0]
        title = " ".join(x for x in (first.qualification or first.degree, first.subject) if x)
    title = title or "Professional"
    focus = list(profile.demonstrated_skills())[:4]
    years = _years_of_experience(profile)
    if years:
        experience = f"{years}+ year{'s' if years != 1 else ''} of experience"
    elif profile.projects:
        experience = "hands-on project experience"
    else:
        experience = "an early-career background"
    summary = f"{title} with {experience}"
    if focus:
        summary += " across " + ", ".join(focus)
    return summary + "."


# ---------------------------------------------------------------------------
# Editing operations (kept here so the page stays presentational)
# ---------------------------------------------------------------------------
def move_section(cv: TailoredCV, index: int, delta: int) -> None:
    target = index + delta
    if 0 <= index < len(cv.sections) and 0 <= target < len(cv.sections):
        cv.sections[index], cv.sections[target] = cv.sections[target], cv.sections[index]


def hide_section(draft: BuilderDraft, index: int) -> None:
    if 0 <= index < len(draft.cv.sections):
        draft.hidden.append(draft.cv.sections.pop(index))


def restore_section(draft: BuilderDraft, index: int) -> None:
    if 0 <= index < len(draft.hidden):
        draft.cv.sections.append(draft.hidden.pop(index))


def drop_hidden_section(draft: BuilderDraft, index: int) -> None:
    if 0 <= index < len(draft.hidden):
        draft.hidden.pop(index)


def add_section(draft: BuilderDraft, heading: str, kind: str) -> CVSection:
    if kind not in {"entries", "skills", "lines"}:
        kind = "entries"
    section = CVSection(id=_new_id("sec"), heading=heading.strip() or "Section", kind=kind)
    draft.cv.sections.append(section)
    return section


def restore_master_order(draft: BuilderDraft) -> None:
    ranked = []
    for index, section in enumerate(draft.cv.sections):
        try:
            rank = MASTER_ORDER.index(section.heading.strip().lower())
        except ValueError:
            rank = len(MASTER_ORDER)
        ranked.append((rank, index, section))
    ranked.sort(key=lambda item: (item[0], item[1]))
    draft.cv.sections = [item[2] for item in ranked]


def add_entry(section: CVSection) -> CVEntry:
    entry = CVEntry(id=_new_id("ent"))
    section.entries.append(entry)
    return entry


def add_bullet(entry: CVEntry) -> CVBullet:
    bullet = CVBullet(id=_new_id("blt"), text="")
    entry.bullets.append(bullet)
    return bullet


def add_skill_row(section: CVSection) -> CVRow:
    row = CVRow(id=_new_id("row"))
    section.rows.append(row)
    return row


def remove_at(items: list[Any], index: int) -> None:
    if 0 <= index < len(items):
        items.pop(index)


# ---------------------------------------------------------------------------
# Evaluation and export
# ---------------------------------------------------------------------------
def _neutral_job(cv: TailoredCV) -> JobRecord:
    return JobRecord(source="builder", title=cv.target_job_title or "")


def _sanitize_copy(cv: TailoredCV, profile: CandidateProfileData,
                   evidence: list[EvidenceItem]) -> tuple[TailoredCV, list[str]]:
    from services.cv_tailoring import sanitize_cv

    # sanitize_cv normalises in place before copying; never let it touch the draft.
    return sanitize_cv(cv.model_copy(deep=True), profile, evidence)


def evaluate(cv: TailoredCV, profile: CandidateProfileData, evidence: list[EvidenceItem],
             job: JobRecord | None = None) -> BuilderEvaluation:
    from core.ats_rules import build_ats_report
    from services.cv_tailoring import validate_cv

    clean, removed = _sanitize_copy(cv, profile, evidence)
    target = job or _neutral_job(clean)
    report = validate_cv(clean, profile, evidence, target, removed_content=removed)
    ats = build_ats_report(clean, profile, evidence, target)
    return BuilderEvaluation(cv=clean, report=report, ats=ats, removed=removed)


def approve(draft: BuilderDraft, evaluation: BuilderEvaluation) -> None:
    if not evaluation.exportable:
        raise BuilderError("Resolve the blocking checks before approving this CV.")
    draft.approved_hash = content_hash(evaluation.cv)
    draft.approved_at = datetime.now(timezone.utc)


def revoke(draft: BuilderDraft) -> None:
    draft.approved_hash = ""
    draft.approved_at = None


def is_approved(draft: BuilderDraft, evaluation: BuilderEvaluation | None = None) -> bool:
    if not draft.approved_hash:
        return False
    if evaluation is None:
        return False
    return draft.approved_hash == content_hash(evaluation.cv)


def export_draft(draft: BuilderDraft, profile: CandidateProfileData,
                 evidence: list[EvidenceItem], job: JobRecord | None = None,
                 *, formats: tuple[str, ...] = ("docx", "pdf", "txt"),
                 ) -> tuple[dict[str, str], BuilderEvaluation]:
    evaluation = evaluate(draft.cv, profile, evidence, job)
    if not evaluation.exportable:
        raise BuilderError("This CV is not complete enough to export; fix the blocking checks.")
    if not is_approved(draft, evaluation):
        raise BuilderError("Approve this exact CV before exporting it. Editing it revokes approval.")

    version = max(1, int(draft.export_version or 0) + 1)
    files = export_cv(
        evaluation.cv, out_dir=get_settings().exports_dir, version=version,
        formats=formats, preserve_order=True,
    )
    draft.export_version = version
    draft.last_exports = files
    return files, evaluation


# ---------------------------------------------------------------------------
# Editor helpers for the page
# ---------------------------------------------------------------------------
def skill_checker(profile: CandidateProfileData,
                  evidence: list[EvidenceItem]) -> Callable[[str], bool]:
    allowed_text, learning = _allowed_skill_text(profile, evidence)
    return lambda skill: _skill_is_supported(skill, allowed_text, learning)


def evidence_labels(evidence: list[EvidenceItem]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in _active_evidence(evidence):
        value = item.value if len(item.value) <= 72 else item.value[:69] + "…"
        labels[item.evidence_id] = f"{value} · {item.field_path}"
    return labels


def empty_section(section: CVSection) -> bool:
    """Whether a section would render as a heading with nothing under it."""
    return not (section.entries or section.lines or section.rows or section.summary
                or section.skills)
