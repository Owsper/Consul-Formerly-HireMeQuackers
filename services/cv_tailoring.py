"""Evidence-grounded CV tailoring.

Two generators share one output contract:

* an LLM generator (recruiter-style rewriting, only permitted facts);
* a deterministic generator used when the LLM is unavailable or its output
  fails validation. It only selects, orders and lightly edits existing facts.

Both are followed by a deterministic sanitiser and validator, so an unsupported
bullet can never reach an exported document.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from core.ats_rules import (  # re-exported for compatibility with existing callers
    HEADING_TRANSLATIONS, STANDARD_HEADINGS, ats_prompt_rules, build_ats_report,
    job_terms, standard_heading_set,
)
from core.logging_config import get_logger
from core.schemas import (
    CandidateProfileData, CVBullet, CVEntry, CVHeader, CVRow, CVSection, EvidenceItem,
    JobRecord, MatchResult, TailoredCV, ValidationIssue, ValidationReport,
)
from core.text import (
    canonical_skill, filename_stem, keyword_set, normalize_text, normalize_whitespace,
    text_contains_skill,
)

logger = get_logger("cv")

SUMMARY_TEMPLATES = {
    "en": "{title} with {years}. Focused on {focus}. Applying for the {job_title} role at {company}.",
    "de": "{title} mit {years}. Schwerpunkte: {focus}. Bewerbung auf die Position {job_title} bei {company}.",
    "fr": "{title} avec {years}. Spécialisé en {focus}. Candidature au poste de {job_title} chez {company}.",
    "es": "{title} con {years}. Especializado en {focus}. Candidatura al puesto de {job_title} en {company}.",
    "nl": "{title} met {years}. Gericht op {focus}. Sollicitatie voor de functie {job_title} bij {company}.",
}


class LLMCVResponse(BaseModel):
    header: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    sections: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------
def _active_evidence(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    return [e for e in evidence if e.status.value != "rejected"]


def _evidence_corpus(evidence: list[EvidenceItem]) -> str:
    return "\n".join(f"{e.label}: {e.value} {e.source_text}" for e in evidence)


def _evidence_index(evidence: list[EvidenceItem]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in _active_evidence(evidence):
        out.setdefault(item.field_path, []).append(item.evidence_id)
    return out


def _ids_for_path(evidence: list[EvidenceItem], path: str,
                  text: str = "") -> list[str]:
    exact = [e.evidence_id for e in _active_evidence(evidence) if e.field_path == path]
    if exact:
        return exact
    if text:
        matches = [
            e.evidence_id for e in _active_evidence(evidence)
            if normalize_text(text) == normalize_text(e.value)
            or (len(e.value) > 25 and normalize_text(e.value) in normalize_text(text))
            or (len(text) > 25 and normalize_text(text) in normalize_text(e.value))
        ]
        if matches:
            return matches[:3]
    prefix = path.split("[")[0]
    fallback = [e.evidence_id for e in _active_evidence(evidence)
                if e.field_path.startswith(prefix)]
    return fallback[:1]


def _years_of_experience(profile: CandidateProfileData) -> int:
    months = 0
    for entry in profile.employment:
        start = _ym(entry.start_date)
        end = None if entry.current else _ym(entry.end_date)
        if start and (end or entry.current):
            end = end or date.today()
            months += max(0, (end.year - start.year) * 12 + (end.month - start.month))
    return round(months / 12)


def _ym(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value)
    match = re.search(r"(19|20)\d{2}", text)
    if not match:
        return None
    year = int(match.group(0))
    month_match = re.search(r"(?:^|[-/.])(0?[1-9]|1[0-2])(?:$|[-/.])", text)
    month = int(month_match.group(1)) if month_match else 1
    try:
        return date(year, month, 1)
    except ValueError:
        return date(year, 1, 1)


def _relevant_terms(job: JobRecord) -> set[str]:
    """Job vocabulary used to rank existing bullets and projects."""
    extracted = job_terms(job)
    return keyword_set(" ".join([
        job.title, job.description, *extracted.must_have, *extracted.nice_to_have,
    ]))


def _bullet_score(text: str, job: JobRecord, terms: set[str]) -> float:
    blob = normalize_text(text)
    score = 0.0
    # Must-have terms dominate; preferred terms only break ties. Terms are still
    # only ever selected from facts already present in the evidence ledger.
    for skill in job.required_skills:
        if text_contains_skill(text, skill):
            score += 6
    for skill in job.preferred_skills:
        if text_contains_skill(text, skill):
            score += 2.5
    score += len(terms & keyword_set(blob)) * 1.5
    if re.search(r"\d", text):
        score += 0.5
    return score


def _project_must_terms(job: JobRecord) -> list[str]:
    """Requirements a project must satisfy to be worth showing for this job.

    Languages are included because ``job_terms`` already treats them as
    must-haves. Preferred skills deliberately do not qualify a project: they
    only affect ordering, so an adjacent technology such as REST APIs cannot
    pull an unrelated project into a specialised frontend CV.
    """
    return list(job_terms(job).must_have)


def _project_relevance(project: Any, job: JobRecord, terms: set[str]) -> tuple[float, bool]:
    """Score a project using its prose, name, role and verified technologies."""
    blob = " ".join([
        project.name or "", project.role or "", project.description or "",
        project.implementation or "", project.measurable_results or "",
        *project.verified_achievements, *project.technologies,
    ])
    must_terms = _project_must_terms(job)
    must_match = any(text_contains_skill(blob, term) for term in must_terms)
    return _bullet_score(blob, job, terms), must_match


def _pick_bullets(texts: list[str], ids: list[list[str]], job: JobRecord,
                  terms: set[str], limit: int = 5) -> list[CVBullet]:
    scored = []
    for text, ev_ids in zip(texts, ids):
        clean = normalize_whitespace(text).strip(" -•\t")
        if not clean:
            continue
        scored.append((_bullet_score(clean, job, terms), clean, ev_ids))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return [
        CVBullet(text=_sentence(clean), evidence_ids=list(dict.fromkeys(ev_ids))[:4])
        for _, clean, ev_ids in scored[:limit]
    ]


def _sentence(text: str) -> str:
    text = normalize_whitespace(text)
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text[0].upper() + text[1:]


def _dates(entry_start: str, entry_end: str, current: bool = False, language: str = "en") -> str:
    if not entry_start and not entry_end and not current:
        return ""
    end = ("present" if language == "en" else "heute") if (current or not entry_end) else entry_end
    return f"{entry_start} – {end}".strip(" –")


def _visa_summary(profile: CandidateProfileData) -> str:
    """Only state work-authorisation facts present in Ground Truth."""
    auth = profile.work_authorization
    parts: list[str] = []
    if auth.visa_status:
        parts.append(auth.visa_status)
    if auth.authorized_to_work is True and auth.residence_country:
        parts.append(f"Authorised to work in {auth.residence_country}")
    if auth.sponsorship_required is False:
        parts.append("No sponsorship required")
    if auth.work_hour_restrictions:
        parts.append(auth.work_hour_restrictions)
    return " · ".join(dict.fromkeys(parts))


def _applying_for(job: JobRecord) -> str:
    parts = [job.title, job.company, job.location]
    return "  |  ".join(p.strip() for p in parts if p and p.strip())


# ---------------------------------------------------------------------------
# Deterministic generator
# ---------------------------------------------------------------------------
def build_rule_based_cv(profile: CandidateProfileData, evidence: list[EvidenceItem],
                        job: JobRecord, match: MatchResult | None = None,
                        *, language: str = "en") -> TailoredCV:
    language = (language or "en").lower()[:2]
    terms = _relevant_terms(job)
    header = CVHeader(
        name=profile.personal.full_name,
        title=profile.personal.professional_title or (profile.employment[0].title if profile.employment else ""),
        contact_lines=profile.personal.contact_lines,
        visa_status=_visa_summary(profile),
        applying_for=_applying_for(job),
    )

    demonstrated = profile.demonstrated_skills()
    demonstrated_keys = {canonical_skill(s) for s in demonstrated}
    # Only demonstrated skills may appear as a summary focus. A requirement
    # matched from project prose (or marked as learning) is not a proficiency.
    matched_skills = [s for s in (match.matching_skills if match else [])
                      if canonical_skill(s) in demonstrated_keys]
    if not matched_skills:
        matched_skills = [s for s in demonstrated
                          if any(text_contains_skill(s, r) or text_contains_skill(r, s)
                                 for r in job.required_skills)]
    focus_terms = matched_skills[:5] or demonstrated[:4]
    focus = _join_list(focus_terms, language) or (
        "software delivery" if language == "en" else "Softwareentwicklung"
    )
    years = _years_of_experience(profile)
    has_projects = bool(profile.projects or any(e.academic_projects for e in profile.education))
    if years:
        years_text = (f"{years}+ year{'s' if years != 1 else ''} of professional experience"
                      if language == "en" else f"{years}+ Jahre Berufserfahrung")
    elif has_projects:
        years_text = ("hands-on project experience" if language == "en"
                      else "praktische Projekterfahrung")
    else:
        # Never claim professional or project experience that is not recorded.
        years_text = {"en": "an early-career background", "de": "einen Berufseinstieg",
                      "fr": "un profil débutant", "es": "un perfil junior",
                      "nl": "een startersprofiel"}.get(language, "an early-career background")
    template = SUMMARY_TEMPLATES.get(language, SUMMARY_TEMPLATES["en"])
    summary = template.format(
        title=header.title or ("Professional" if language == "en" else "Fachkraft"),
        years=years_text,
        focus=focus,
        job_title=job.title,
        company=job.company or ("your team" if language == "en" else "Ihr Team"),
    )

    sections: list[CVSection] = []

    if profile.employment:
        entries: list[CVEntry] = []
        for i, entry in enumerate(profile.employment):
            texts = [*entry.responsibilities, *entry.achievements, *entry.quantified_results]
            ids = [
                _ids_for_path(evidence, f"employment[{i}].responsibilities[{j}]", t)
                for j, t in enumerate(entry.responsibilities)
            ] + [
                _ids_for_path(evidence, f"employment[{i}].achievements[{j}]", t)
                for j, t in enumerate(entry.achievements)
            ] + [
                _ids_for_path(evidence, f"employment[{i}].quantified_results[{j}]", t)
                for j, t in enumerate(entry.quantified_results)
            ]
            bullets = _pick_bullets(texts, ids, job, terms, limit=5)
            if not bullets:
                continue
            entries.append(CVEntry(
                title=entry.title, organization=entry.employer, location=entry.location,
                dates=_dates(entry.start_date, entry.end_date, entry.current, language),
                technologies=list(entry.technologies),
                bullets=bullets,
            ))
        if entries:
            sections.append(CVSection(heading=_heading("Professional Experience", language),
                                      kind="entries", entries=entries))

    project_sections = _project_sections(profile, evidence, job, terms, language)
    sections.extend(project_sections)

    if profile.education:
        entries = []
        for i, edu in enumerate(profile.education):
            headline = " ".join(x for x in (edu.qualification or edu.degree, edu.subject) if x)
            focus = [item for item in edu.achievements
                     if item.strip().lower().startswith(("focus:", "focus ", "schwerpunkt"))]
            bullets: list[CVBullet] = []
            remainder = [item for item in edu.achievements if item not in focus]
            for j, item in enumerate([*remainder, *edu.academic_projects][:4]):
                path = (f"education[{i}].achievements[{j}]" if j < len(remainder)
                        else f"education[{i}].academic_projects[{j - len(remainder)}]")
                bullets.append(CVBullet(text=_sentence(item),
                                        evidence_ids=_ids_for_path(evidence, path, item)))
            entries.append(CVEntry(
                title=headline or edu.institution, organization=edu.institution if headline else "",
                location="", dates=_dates(edu.start_date, edu.end_date, False, language),
                technologies=focus,
                bullets=bullets,
            ))
        sections.append(CVSection(heading=_heading("Education", language),
                                  kind="entries", entries=entries))

    skills = _skills_section(profile, job, language)
    if skills:
        sections.append(skills)

    if profile.additional.languages:
        sections.append(CVSection(
            heading=_heading("Languages", language), kind="lines",
            rows=[CVRow(label=l.language, text=l.proficiency or "")
                  for l in profile.additional.languages if l.language],
        ))
    if profile.additional.certifications:
        sections.append(CVSection(
            heading=_heading("Certifications", language), kind="lines",
            lines=[_join_nonempty([c.name, c.issuer, c.date], " — ")
                   for c in profile.additional.certifications],
        ))
    if profile.additional.awards:
        sections.append(CVSection(
            heading=_heading("Awards", language), kind="lines",
            lines=[_join_nonempty([a.name, a.issuer, a.date], " — ") for a in profile.additional.awards],
        ))

    return TailoredCV(
        header=header, summary=summary, sections=sections, generator="rule_based",
        target_job_title=job.title, target_company=job.company,
        generated_at=datetime.now(timezone.utc),
    )


def _project_sections(profile: CandidateProfileData, evidence: list[EvidenceItem],
                      job: JobRecord, terms: set[str], language: str) -> list[CVSection]:
    professional: list[CVEntry] = []
    academic: list[CVEntry] = []
    for i, project in enumerate(profile.projects):
        texts = [project.description, project.implementation, project.measurable_results,
                 *project.verified_achievements]
        ids = [
            _ids_for_path(evidence, f"projects[{i}].description", project.description),
            _ids_for_path(evidence, f"projects[{i}].implementation", project.implementation),
            _ids_for_path(evidence, f"projects[{i}].results", project.measurable_results),
        ] + [
            _ids_for_path(evidence, f"projects[{i}].achievements[{j}]", a)
            for j, a in enumerate(project.verified_achievements)
        ]
        relevance, must_match = _project_relevance(project, job, terms)
        must_terms = _project_must_terms(job)
        if must_terms:
            # Matching one must-have requirement is enough. A project does not
            # have to satisfy every requirement in the advert.
            if not must_match:
                continue
        elif relevance < 3:
            # No structured must-haves at all: fall back to the text score.
            continue
        bullets = _pick_bullets(texts, ids, job, terms, limit=4)
        if not bullets:
            continue
        entry = CVEntry(
            title=project.name or project.role, organization=project.role if project.name else "",
            dates=_dates(project.start_date, project.end_date, False, language),
            technologies=list(project.technologies),
            bullets=bullets,
        )
        (academic if project.label == "academic_project" else professional).append(entry)

    sections: list[CVSection] = []
    if professional:
        sections.append(CVSection(heading=_heading("Project Experience", language),
                                  kind="entries", entries=professional))
    if academic:
        sections.append(CVSection(heading=_heading("Academic Projects", language),
                                  kind="entries", entries=academic))
    return sections


def _skills_section(profile: CandidateProfileData, job: JobRecord, language: str) -> CVSection | None:
    """Preserve the profile's skill categories as label/text rows."""
    ranked: list[str] = []
    seen: set[str] = set()

    def add(skill: str) -> None:
        key = canonical_skill(skill)
        if key and key not in seen:
            seen.add(key)
            ranked.append(normalize_whitespace(skill))

    extracted = job_terms(job)
    must = {canonical_skill(s) for s in extracted.must_have}
    nice = {canonical_skill(s) for s in extracted.nice_to_have}

    def priority(skill: str) -> int:
        key = canonical_skill(skill)
        if key in must or any(
            text_contains_skill(skill, r) or text_contains_skill(r, skill)
            for r in extracted.must_have
        ):
            return 0
        if key in nice or any(
            text_contains_skill(skill, r) or text_contains_skill(r, skill)
            for r in extracted.nice_to_have
        ):
            return 1
        return 2

    rows: list[CVRow] = []
    for group in profile.skills:
        ordered = sorted(
            [(index, normalize_whitespace(s)) for index, s in enumerate(group.skills)
             if s.strip()],
            key=lambda item: (priority(item[1]), item[0]),
        )
        ordered = [skill for _, skill in ordered]
        values: list[str] = []
        for skill in ordered:
            add(skill)
            if skill.lower() not in {v.lower() for v in values}:
                values.append(skill)
        if values:
            rows.append(CVRow(label=group.name or "Technical", text=", ".join(values[:12])))

    if not ranked:
        return None
    if not rows:
        rows = [CVRow(label="Technical", text=", ".join(ranked[:24]))]
    return CVSection(heading=_heading("Technical Skills", language), kind="skills",
                     skills=ranked[:24], rows=rows)


def _heading(text: str, language: str) -> str:
    return HEADING_TRANSLATIONS.get(language, {}).get(text, text)


def _join_list(items: list[str], language: str) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    conjunction = {"de": "und", "fr": "et", "es": "y", "nl": "en"}.get(language, "and")
    return ", ".join(items[:-1]) + f" {conjunction} " + items[-1]


def _join_nonempty(items: list[str], sep: str) -> str:
    return sep.join(i for i in items if i)


# ---------------------------------------------------------------------------
# Sanitising and validation
# ---------------------------------------------------------------------------
def _allowed_skill_text(profile: CandidateProfileData,
                        evidence: list[EvidenceItem]) -> tuple[str, set[str]]:
    """Everything the ledger actually supports as a skill claim."""
    parts: list[str] = list(profile.demonstrated_skills())
    for entry in profile.employment:
        parts.extend(entry.technologies)
    for project in profile.projects:
        parts.extend(project.technologies)
    for item in _active_evidence(evidence):
        if item.category in {"skill", "employment", "project"}:
            parts.append(item.value)
    learning = {canonical_skill(skill) for skill in
                [*profile.learning_skills(), *profile.interest_skills()]}
    return "\n".join(part for part in parts if part), learning


def _skill_is_supported(skill: str, allowed_text: str, learning: set[str]) -> bool:
    key = canonical_skill(skill)
    if not key or key in learning:
        return False
    return text_contains_skill(allowed_text, skill)


def sanitize_cv(cv: TailoredCV, profile: CandidateProfileData,
                evidence: list[EvidenceItem]) -> tuple[TailoredCV, list[str]]:
    """Remove unsupported bullets/skills and normalise contact details."""
    valid_ids = {e.evidence_id for e in _active_evidence(evidence)}
    allowed_skill_text, learning_skills = _allowed_skill_text(profile, evidence)
    removed: list[str] = []
    sections: list[CVSection] = []
    for section in cv.sections:
        heading = section.heading.strip()
        if heading.lower() in {"references", "hobbies", "interests"}:
            removed.append(f"Removed section '{heading}' (not requested by this job).")
            continue
        section.heading = _clean_text(heading) or section.heading
        entries: list[CVEntry] = []
        for entry in section.entries:
            bullets: list[CVBullet] = []
            seen: set[str] = set()
            for bullet in entry.bullets:
                text = _clean_text(bullet.text)
                if not text:
                    continue
                ids = [i for i in bullet.evidence_ids if i in valid_ids]
                if not ids:
                    removed.append(text[:160])
                    continue
                key = normalize_text(text)
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(CVBullet(text=text, evidence_ids=list(dict.fromkeys(ids))[:4]))
            # Education and similar factual entries are valid without bullets.
            if bullets or entry.title or entry.organization:
                entry.bullets = bullets
                entries.append(entry)
        section.entries = entries
        if section.kind == "entries" and not entries:
            continue
        if section.kind == "skills":
            supported = [s for s in section.skills
                         if _skill_is_supported(s, allowed_skill_text, learning_skills)]
            for dropped in [s for s in section.skills if s not in supported]:
                removed.append(f"Removed unsupported skill '{dropped}'.")
            section.skills = supported
            kept_rows: list[CVRow] = []
            for row in section.rows:
                values = [value.strip() for value in (row.text or "").split(",") if value.strip()]
                kept = [value for value in values
                        if _skill_is_supported(value, allowed_skill_text, learning_skills)]
                for dropped in [value for value in values if value not in kept]:
                    removed.append(f"Removed unsupported skill '{dropped}'.")
                if kept:
                    kept_rows.append(row.model_copy(update={"text": ", ".join(kept)}))
            section.rows = kept_rows
            if not section.skills and not section.rows:
                continue
        sections.append(section)

    header = CVHeader(
        name=profile.personal.full_name or cv.header.name,
        title=profile.personal.professional_title or cv.header.title,
        contact_lines=profile.personal.contact_lines or cv.header.contact_lines,
        visa_status=cv.header.visa_status or _visa_summary(profile),
        applying_for=cv.header.applying_for,
    )
    cleaned = cv.model_copy(update={"sections": sections, "header": header,
                                    "summary": _clean_text(cv.summary)})
    return cleaned, removed


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
    text = text.replace("\t", " ").replace("\u00a0", " ")
    return normalize_whitespace(text)


def _cv_includes_profile_project(cv: TailoredCV,
                                 profile: CandidateProfileData) -> bool:
    """Whether any verified profile project survived into the CV."""
    titles = [normalize_text(entry.title) for section in cv.sections
              for entry in section.entries if entry.title]
    for project in profile.projects:
        key = normalize_text(project.name or project.role)
        if key and any(key in title or title in key for title in titles):
            return True
    return False


def validate_cv(cv: TailoredCV, profile: CandidateProfileData,
                evidence: list[EvidenceItem], job: JobRecord,
                *, removed_content: list[str] | None = None) -> ValidationReport:
    issues: list[ValidationIssue] = []
    active = _active_evidence(evidence)
    valid_ids = {e.evidence_id for e in active}
    corpus = _evidence_corpus(active)
    corpus_norm = normalize_text(corpus)
    numbers_in_corpus = set(re.findall(r"\d+(?:[.,]\d+)?%?", corpus.replace(",", ".")))

    bullets = cv.all_bullets()
    has_career_content = bool(profile.employment or profile.projects or any(
        entry.academic_projects or entry.achievements for entry in profile.education
    ))
    unsupported: list[str] = []
    missing_citations = 0
    for bullet in bullets:
        if not bullet.evidence_ids:
            missing_citations += 1
            unsupported.append(bullet.text)
            continue
        bogus = [i for i in bullet.evidence_ids if i not in valid_ids]
        if bogus:
            missing_citations += 1
            unsupported.append(bullet.text)
            continue
        # Numbers must exist in the evidence corpus (allows reordering, not invention).
        for number in re.findall(r"\d+(?:[.,]\d+)?%?", bullet.text):
            if number not in numbers_in_corpus and number.replace(".", ",") not in numbers_in_corpus:
                unsupported.append(bullet.text)
                break

    coverage = (len(bullets) - missing_citations) / len(bullets) if bullets else 0.0

    # The summary is prose too. It must not claim experience, seniority or a
    # learning skill that the Ground Truth does not support.
    summary_text = normalize_text(cv.summary)
    claimed_years = [int(value) for value in
                     re.findall(r"(\d{1,2})\+?\s*(?:years?|jahre|ans|años|jaar)", summary_text)]
    documented_years = _years_of_experience(profile)
    if claimed_years and max(claimed_years) > documented_years + 1:
        issues.append(ValidationIssue(
            severity="error", code="unsupported_experience_claim",
            message=(f"The summary claims {max(claimed_years)} years of experience, but the "
                     f"profile documents {documented_years}."),
        ))
    if not profile.employment and re.search(
            r"\b(experienced|extensive experience|proven track record|years of experience)\b",
            summary_text):
        issues.append(ValidationIssue(
            severity="error", code="unsupported_experience_claim",
            message="The summary describes professional experience, but no employment is recorded.",
        ))
    for skill in profile.learning_skills():
        if text_contains_skill(cv.summary, skill):
            issues.append(ValidationIssue(
                severity="error", code="unsupported_skill_claim",
                message=(f"The summary presents '{skill}' as a skill even though it is "
                         "recorded as currently learning."),
            ))
    if not bullets and not has_career_content:
        issues.append(ValidationIssue(
            severity="warning", code="no_experience_evidence",
            message="No employment, project or academic evidence exists yet; the CV has no "
                    "experience bullets. Add Ground Truth evidence before applying.",
        ))

    if unsupported:
        issues.append(ValidationIssue(
            severity="error", code="unsupported_claims",
            message=f"{len(unsupported)} claim(s) could not be traced to the evidence ledger.",
        ))
    if not bullets and not any(s.entries or s.lines or s.skills or s.rows for s in cv.sections):
        issues.append(ValidationIssue(severity="error", code="empty_cv",
                                      message="The CV contains no evidence-backed content."))
    # A professional CV must actually cite the evidence ledger. A summary plus
    # an uncited skill list is not a tailored CV and must not pass validation.
    if not bullets and has_career_content:
        issues.append(ValidationIssue(
            severity="error", code="no_evidence_bullets",
            message=("The draft contains no evidence-cited experience or project bullets. "
                     "Regenerate with the deterministic builder and review the result."),
        ))
    if profile.projects and not _cv_includes_profile_project(cv, profile):
        issues.append(ValidationIssue(
            severity="warning", code="no_relevant_projects",
            message=("No verified project matched this job's must-have requirements, so the "
                     "CV has no Project Experience section. Add a relevant project or review "
                     "the target role."),
        ))

    # Contact details
    if not profile.personal.email:
        issues.append(ValidationIssue(severity="warning", code="missing_email",
                                      message="No email address in the Ground Truth profile."))
    if not profile.personal.phone:
        issues.append(ValidationIssue(severity="warning", code="missing_phone",
                                      message="No phone number in the Ground Truth profile."))

    # Numbers that are section-level claims (e.g. "5 years") need a check too.
    summary_numbers = set(re.findall(r"\d+", cv.summary))
    suspicious_summary = [n for n in summary_numbers if n not in numbers_in_corpus
                          and n not in {str(_years_of_experience(profile)), "1", "2"}]
    if suspicious_summary:
        issues.append(ValidationIssue(
            severity="warning", code="summary_metric",
            message=f"Summary contains numeric claims not in the ledger: {', '.join(suspicious_summary)}.",
        ))

    # Deterministic ATS readiness (shared rules module; no LLM involved).
    headings = [s.heading for s in cv.sections]
    ats = build_ats_report(cv, profile, evidence, job)
    parse_checks = ats.get("parse_checks", {})
    ats_checks = {
        "single_column": bool(parse_checks.get("single_column", True)),
        "standard_headings": bool(parse_checks.get("standard_headings", True)),
        "no_tables": bool(parse_checks.get("no_tables", True)),
        "no_images_or_icons": bool(parse_checks.get("plain_bullets", True)),
        "no_skill_bars": True,
        "contact_details": bool(parse_checks.get("contact_in_body", True)),
        "selectable_text": bool(parse_checks.get("text_layer_expected", True)),
        "chronological_order": _chronological(cv),
        "title_alignment": bool(parse_checks.get("title_alignment", False)),
    }
    accepted = standard_heading_set()
    nonstandard = [h for h in headings if h.strip().lower() not in accepted]
    if nonstandard:
        issues.append(ValidationIssue(
            severity="warning", code="nonstandard_heading",
            message=f"Non-standard section heading(s): {', '.join(nonstandard)}.",
        ))
    if not ats_checks["contact_details"]:
        issues.append(ValidationIssue(severity="warning", code="contact_details",
                                      message="The header has no email or phone number; add one before sending."))
    if ats.get("parse_risk") == "high":
        issues.append(ValidationIssue(
            severity="warning", code="ats_parse_risk",
            message="High parse risk: " + " ".join(ats.get("parse_risk_reasons", []))[:400],
        ))
    must = (ats.get("keyword_coverage") or {}).get("must_have") or {}
    if must.get("available") and must.get("ratio", 1.0) < 0.7:
        issues.append(ValidationIssue(
            severity="warning", code="keyword_coverage",
            message=(f"{len(must.get('covered') or [])} of "
                     f"{must['available']} evidenced must-have terms appear in this CV. "
                     "Only add missing terms where the evidence already supports them."),
        ))

    estimated_lines = 6 + sum(
        3 + len(e.bullets) for s in cv.sections for e in s.entries
    ) + sum(1 for s in cv.sections if s.kind == "skills" and (s.skills or s.rows)) * 3
    if estimated_lines > 58:
        issues.append(ValidationIssue(severity="warning", code="length",
                                      message="The CV is likely longer than two pages; remove less relevant bullets."))

    # Requirement coverage
    cv_text = " ".join([
        cv.summary, *[b.text for b in bullets],
        *[sk for s in cv.sections for sk in s.skills],
        *[row.text for s in cv.sections for row in s.rows],
        *[value for s in cv.sections for e in s.entries
          for value in (e.title, e.organization, *e.technologies)],
    ])
    matched = [r for r in job.required_skills if text_contains_skill(cv_text, r)]
    unmet = [r for r in job.required_skills if r not in matched]
    if unmet:
        issues.append(ValidationIssue(
            severity="warning", code="unmet_requirements",
            message=f"Not evidenced in this CV: {', '.join(unmet[:8])}.",
        ))

    # Academic work mislabelled as employment
    for section in cv.sections:
        if section.heading.lower() in {"professional experience", "work experience", "berufserfahrung"}:
            academic_names = {p.name for p in profile.projects if p.label == "academic_project"}
            for entry in section.entries:
                if entry.organization in academic_names or entry.title in academic_names:
                    issues.append(ValidationIssue(
                        severity="error", code="academic_as_employment",
                        message="An academic project appears under Professional Experience.",
                    ))

    passed = not any(i.severity == "error" for i in issues)
    return ValidationReport(
        passed=passed, issues=issues, evidence_coverage=round(coverage, 3),
        unsupported_claims=unsupported[:20], matched_requirements=matched,
        unmet_requirements=unmet, removed_content=removed_content or [],
        ats_checks=ats_checks, ats_report=ats, checked_at=datetime.now(timezone.utc),
    )


def _chronological(cv: TailoredCV) -> bool:
    for section in cv.sections:
        years: list[int] = []
        for entry in section.entries:
            match = re.search(r"(19|20)\d{2}", entry.dates or "")
            if match:
                years.append(int(match.group(0)))
        if years and years != sorted(years, reverse=True):
            return False
    return True


# ---------------------------------------------------------------------------
# LLM generation
# ---------------------------------------------------------------------------
def _llm_generate(profile: CandidateProfileData, evidence: list[EvidenceItem],
                  job: JobRecord, match: MatchResult | None, language: str) -> TailoredCV | None:
    from services.llm_service import get_llm_service

    service = get_llm_service()
    if not service.available:
        return None

    def _evidence_line(item: EvidenceItem) -> str:
        from core.text import skill_group_status

        marker = ""
        if item.category == "skill" and skill_group_status(item.label) != "demonstrated":
            marker = " [NOT DEMONSTRATED — do not present as a skill or proficiency]"
        elif item.category == "interest":
            marker = " [CAREER INTEREST — not a qualification]"
        return f"[{item.evidence_id}] ({item.category}) {item.label}: {item.value}{marker}"

    evidence_lines = [_evidence_line(item) for item in _active_evidence(evidence)]
    extracted = job_terms(job)
    requirements = json.dumps({
        "required_skills": job.required_skills,
        "preferred_skills": job.preferred_skills,
        "languages": job.languages,
        "education": job.education_requirements,
        "seniority": job.seniority,
        "certifications": list(extracted.certifications),
        "key_phrases": list(extracted.key_phrases),
        "matching_skills": match.matching_skills if match else [],
        "missing_skills": match.missing_required_skills if match else [],
    }, ensure_ascii=False)
    try:
        response = service.prompt_json(
            "cv_tailoring", LLMCVResponse,
            job_json=job.model_dump_json(indent=2)[:16000],
            profile_json=profile.model_dump_json(indent=2)[:24000],
            evidence_list="\n".join(evidence_lines)[:24000],
            requirements=requirements,
            keyword_targets=extracted.prompt_text(),
            ats_rules=ats_prompt_rules(),
            output_language=language,
            task="reasoning",
        )
        cv = TailoredCV(
            header=CVHeader.model_validate(response.header or {}),
            summary=response.summary,
            sections=[CVSection.model_validate(s) for s in response.sections if isinstance(s, dict)],
            generator="llm", target_job_title=job.title, target_company=job.company,
            generated_at=datetime.now(timezone.utc),
        )
        return cv if cv.sections else None
    except Exception as exc:
        logger.warning("LLM CV generation failed, using the deterministic generator: %s", exc)
        return None


async def audit_cv_with_llm(cv: TailoredCV, profile: CandidateProfileData,
                            evidence: list[EvidenceItem], job: JobRecord) -> list[ValidationIssue]:
    """Optional second-pass LLM audit (used by CV Studio after deterministic checks)."""
    from services.llm_service import get_llm_service

    service = get_llm_service()
    if not service.available:
        return []

    class Audit(BaseModel):
        passed: bool = True
        unsupported_claims: list[str] = Field(default_factory=list)
        issues: list[dict[str, Any]] = Field(default_factory=list)
        suggested_removals: list[str] = Field(default_factory=list)

    try:
        audit = service.prompt_json(
            "cv_validation", Audit,
            cv_json=cv.model_dump_json(indent=2)[:24000],
            profile_json=profile.model_dump_json(indent=2)[:24000],
            evidence_list="\n".join(f"[{e.evidence_id}] {e.value}" for e in _active_evidence(evidence))[:24000],
            job_json=job.model_dump_json(indent=2)[:12000],
            ats_rules=ats_prompt_rules(),
            keyword_targets=job_terms(job).prompt_text(),
            task="reasoning",
        )
    except Exception as exc:
        logger.info("LLM CV audit skipped: %s", exc)
        return []
    issues = []
    for item in audit.issues[:10]:
        try:
            issues.append(ValidationIssue.model_validate(item))
        except Exception:
            continue
    for claim in audit.unsupported_claims[:10]:
        issues.append(ValidationIssue(severity="error", code="llm_unsupported_claim",
                                      message=f"Auditor flagged: {claim[:240]}"))
    return issues


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def tailor_cv(profile: CandidateProfileData, evidence: list[EvidenceItem], job: JobRecord,
              match: MatchResult | None = None, *, use_llm: bool = True,
              language: str = "en") -> tuple[TailoredCV, ValidationReport]:
    language = (language or job.language or "en").lower()[:2]
    if language not in SUMMARY_TEMPLATES:
        language = "en"

    cv = None
    if use_llm:
        cv = _llm_generate(profile, evidence, job, match, language)
    if cv is None:
        cv = build_rule_based_cv(profile, evidence, job, match, language=language)

    cv, removed = sanitize_cv(cv, profile, evidence)
    cv.header.visa_status = cv.header.visa_status or _visa_summary(profile)
    cv.header.applying_for = cv.header.applying_for or _applying_for(job)
    report = validate_cv(cv, profile, evidence, job, removed_content=removed)

    # If the LLM output had unsupported claims, fall back to the safe generator.
    if cv.generator == "llm" and not report.passed:
        fallback = build_rule_based_cv(profile, evidence, job, match, language=language)
        fallback, removed_fallback = sanitize_cv(fallback, profile, evidence)
        fallback_report = validate_cv(fallback, profile, evidence, job,
                                      removed_content=removed + removed_fallback)
        fallback_report.issues.append(ValidationIssue(
            severity="warning", code="llm_fallback",
            message="LLM draft failed validation; the deterministic evidence-only draft was used.",
        ))
        return fallback, fallback_report
    return cv, report


def evidence_map(cv: TailoredCV) -> dict[str, list[str]]:
    return {bullet.text: bullet.evidence_ids for bullet in cv.all_bullets()}


def filename_for(cv: TailoredCV, extension: str, version: int = 1) -> str:
    stem = filename_stem("consul", "CV", cv.header.name or "Candidate",
                         cv.target_company or "", cv.target_job_title or "",
                         f"v{version}")
    return f"{stem}.{extension.lstrip('.')}"
