"""Transparent, evidence-based job matching.

Scores are computed from structured comparisons against the verified profile.
The LLM is not asked "is this a good match": every dimension has a weight and a
rationale, and eligibility is always reported separately from suitability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from core.job_taxonomy import category_label, detect_categories
from core.logging_config import get_logger
from core.schemas import (
    CandidateProfileData, DimensionScore, EligiblityStatus, EligibilityAssessment,
    EvidenceItem, JobRecord, MatchClass, MatchResult, SearchPreferences,
)
from core.skill_transfer import find_transferable, transfer_summary
from core.text import (
    canonical_skill, keyword_set, normalize_text, normalize_whitespace,
    skill_tokens, similarity, text_contains_skill,
)

logger = get_logger("scoring")

DEFAULT_WEIGHTS = {
    "technical_skills": 30,
    "experience_evidence": 20,
    "role_responsibilities": 15,
    "education": 10,
    "seniority": 10,
    "location_preferences": 5,
    "languages": 5,
    "work_authorization": 5,
}

PROFICIENCY_RANK = {
    "native": 5, "mother tongue": 5, "muttersprache": 5, "c2": 5,
    "fluent": 4, "full professional": 4, "c1": 4, "business": 4,
    "professional": 4, "advanced": 3, "b2": 3, "intermediate": 3,
    "b1": 2, "basic": 1, "a2": 1, "a1": 1, "elementary": 1,
}

EDU_RANK = {
    "high school": 1, "abitur": 1, "a-level": 1, "apprenticeship": 2, "ausbildung": 2,
    "bachelor": 3, "b.sc": 3, "bsc": 3, "ba ": 3, "licence": 3, "grado": 3,
    "master": 4, "m.sc": 4, "msc": 4, "mba": 4, "máster": 4, "diplom": 4,
    "phd": 5, "doctorate": 5, "doktor": 5,
}

SENIORITY_RANK = {"internship": 1, "entry": 2, "mid": 3, "senior": 4, "lead": 5, "unknown": 0}


@dataclass
class ScoringInputs:
    job: JobRecord
    profile: CandidateProfileData
    evidence: list[EvidenceItem] = field(default_factory=list)
    preferences: SearchPreferences = field(default_factory=SearchPreferences)


def scoring_weights(session=None) -> dict[str, float]:
    """Weights are configurable via user settings."""
    weights = dict(DEFAULT_WEIGHTS)
    if session is None:
        return weights
    from sqlalchemy import select

    from core.models import UserSetting

    row = session.scalars(select(UserSetting).where(UserSetting.key == "scoring_weights")).first()
    if row and row.value:
        import json

        try:
            stored = json.loads(row.value)
            for key, value in stored.items():
                if key in weights:
                    weights[key] = float(value)
        except (ValueError, TypeError):
            pass
    total = sum(weights.values()) or 1
    return {k: round(v / total * 100, 2) for k, v in weights.items()}


def _candidate_text(profile: CandidateProfileData) -> str:
    # Learning and interest entries stay out of demonstrated evidence.
    return profile.searchable_text(include_learning=False)


def _job_keywords(job: JobRecord) -> set[str]:
    return keyword_set(" ".join([job.title, job.description, *job.required_skills]))


def _candidate_skills(profile: CandidateProfileData) -> set[str]:
    return skill_tokens(profile.demonstrated_skills())


def _learning_skills(profile: CandidateProfileData) -> set[str]:
    return skill_tokens(profile.learning_skills())


def _job_required_skills(job: JobRecord) -> list[str]:
    skills = list(job.required_skills)
    return skills


def _level_requirements(job: JobRecord) -> int:
    blob = normalize_text(" ".join(job.education_requirements))
    best = 0
    for key, rank in EDU_RANK.items():
        if key in blob:
            best = max(best, rank)
    return best


def _candidate_education_level(profile: CandidateProfileData) -> int:
    best = 0
    for entry in profile.education:
        blob = normalize_text(" ".join([entry.qualification, entry.degree, entry.subject]))
        for key, rank in EDU_RANK.items():
            if key in blob:
                best = max(best, rank)
    return best


def _candidate_seniority(profile: CandidateProfileData) -> tuple[str, str]:
    """Return (level, rationale)."""
    titles = [normalize_text(e.title) for e in profile.employment]
    years = 0
    for entry in profile.employment:
        start = _year(entry.start_date)
        end = _year(entry.end_date) or date.today().year
        if start:
            years += max(0, end - start)
    if any(re.search(r"\b(senior|lead|principal|head)\b", t) for t in titles) or years >= 6:
        return "senior", f"{years} years of listed employment and senior/lead titles."
    if years >= 3:
        return "mid", f"{years} years of listed employment."
    if years >= 1:
        return "entry", f"{years} year(s) of listed employment."
    studying = any(
        (e.status or "").lower() in {"current", "ongoing", "in progress"} or not e.end_date
        for e in profile.education
    )
    if studying and (profile.projects or profile.skills):
        return "internship", "Current student with project evidence but no employment history."
    return "entry", "Early-career profile without substantial listed employment."


def _year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def _candidate_languages(profile: CandidateProfileData) -> dict[str, int]:
    out: dict[str, int] = {}
    for entry in profile.additional.languages:
        if not entry.language:
            continue
        level = 0
        blob = normalize_text(entry.proficiency)
        for key, rank in PROFICIENCY_RANK.items():
            if key in blob:
                level = max(level, rank)
        out[normalize_text(entry.language)] = level or 3
    return out


def _parse_required_languages(job: JobRecord) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    for entry in job.languages:
        blob = normalize_text(entry)
        name_match = re.match(r"([a-zäöüßéèêàçñ ]{3,20})", blob)
        if not name_match:
            continue
        name = name_match.group(1).strip()
        level = 0
        for key, rank in PROFICIENCY_RANK.items():
            if key in blob:
                level = max(level, rank)
        results.append((name, level or 2))
    return results


def _evidence_ids_for(evidence: list[EvidenceItem], terms: set[str]) -> list[str]:
    ids: list[str] = []
    for item in evidence:
        if item.status.value == "rejected":
            continue
        blob = normalize_text(f"{item.label} {item.value}")
        if any(term and term in blob for term in terms):
            ids.append(item.evidence_id)
    return ids[:6]


def _relevant_entries(profile: CandidateProfileData, job_terms: set[str]) -> tuple[list[str], list[str]]:
    projects: list[str] = []
    experiences: list[str] = []
    for project in profile.projects:
        blob = " ".join([project.name, project.description, project.implementation,
                         " ".join(project.technologies)])
        overlap = job_terms & keyword_set(blob)
        if len(overlap) >= 2 or (overlap and any(t in {canonical_skill(x) for x in project.technologies}
                                                 for t in job_terms)):
            projects.append(project.name or "Unnamed project")
    for entry in profile.employment:
        blob = " ".join([entry.title, entry.employer, *entry.responsibilities,
                         *entry.achievements, " ".join(entry.technologies)])
        if job_terms & keyword_set(blob):
            experiences.append(f"{entry.title} at {entry.employer}".strip(" at"))
    return projects[:4], experiences[:4]


def _job_category(job: JobRecord) -> str | None:
    detected = detect_categories(job.title, job.required_skills, limit=1)
    if not detected:
        detected = detect_categories(job.description, job.required_skills, limit=1)
    return detected[0] if detected else None


def _skill_dimension(inputs: ScoringInputs) -> DimensionScore:
    job = inputs.job
    required = _job_required_skills(job)
    cand_skills = _candidate_skills(inputs.profile)
    blob = _candidate_text(inputs.profile)
    learning = _learning_skills(inputs.profile)

    if not required:
        # No structured requirement: compare advert keywords with the candidate.
        overlap = _job_keywords(job) & keyword_set(blob)
        score = min(65.0, 25 + 5 * len(overlap))
        return DimensionScore(
            name="technical_skills", weight=0, score=round(score, 1),
            rationale="The advert does not list explicit requirements; scored from keyword overlap only.",
        )

    # A requirement is only matched when the candidate has not marked it as
    # learning/interest. Project prose that happens to mention it is not a claim.
    matched = [s for s in required
               if canonical_skill(s) not in learning
               and (canonical_skill(s) in cand_skills or text_contains_skill(blob, s))]
    missing = [s for s in required if s not in matched]
    transfers = find_transferable(required, inputs.profile.demonstrated_skills(),
                                  _job_category(job))
    transfer_requirements = {canonical_skill(requirement) for requirement, _, _ in transfers}
    exact_missing = {canonical_skill(item) for item in missing}
    # Partial credit only for requirements that are still missing exactly.
    credited = len([item for item in transfer_requirements if item in exact_missing])
    score = min(100.0, 100 * (len(matched) + 0.35 * credited) / len(required))
    rationale = (
        f"{len(matched)}/{len(required)} listed requirements are directly evidenced"
        + (f". Missing: {', '.join(missing[:6])}" if missing else ".")
    )
    if credited:
        rationale += (
            f" {credited} adjacent skill(s) earn partial credit, not equivalence: "
            + "; ".join(f"{s} → {r}" for r, s, _ in transfers[:3]) + "."
        )
    learning_hits = [s for s in required if canonical_skill(s) in learning]
    if learning_hits:
        rationale += (
            " Listed as currently learning and therefore not counted as demonstrated: "
            + ", ".join(learning_hits[:6]) + "."
        )
    evidence_terms = {canonical_skill(s) for s in matched}
    evidence_terms |= {canonical_skill(source) for _, source, _ in transfers}
    return DimensionScore(
        name="technical_skills", weight=0, score=round(score, 1), rationale=rationale,
        evidence_ids=_evidence_ids_for(inputs.evidence, evidence_terms),
    )


def _experience_dimension(inputs: ScoringInputs) -> DimensionScore:
    job_terms = _job_keywords(inputs.job)
    projects, experiences = _relevant_entries(inputs.profile, job_terms)
    score = 25.0
    if experiences:
        score = min(100.0, 55 + 15 * len(experiences))
    elif projects:
        score = min(85.0, 45 + 12 * len(projects))
    rationale_parts = []
    if experiences:
        rationale_parts.append(f"{len(experiences)} relevant employment entr{'y' if len(experiences) == 1 else 'ies'}.")
    if projects:
        rationale_parts.append(f"{len(projects)} relevant project(s).")
    if not rationale_parts:
        rationale_parts.append("No relevant experience or project evidence found for this advert.")
    return DimensionScore(
        name="experience_evidence", weight=0, score=round(score, 1),
        rationale=" ".join(rationale_parts),
        evidence_ids=_evidence_ids_for(inputs.evidence, job_terms),
    )


def _role_dimension(inputs: ScoringInputs) -> DimensionScore:
    job = inputs.job
    titles = [inputs.profile.personal.professional_title] + [e.title for e in inputs.profile.employment]
    best = max((similarity(job.title, t) for t in titles if t), default=0.0)
    resp_terms = keyword_set(" ".join(job.responsibilities)) or _job_keywords(job)
    overlap = resp_terms & keyword_set(_candidate_text(inputs.profile))
    resp_score = min(100.0, 20 + 8 * len(overlap)) if resp_terms else 40.0
    score = 0.45 * (best * 100) + 0.55 * resp_score
    return DimensionScore(
        name="role_responsibilities", weight=0, score=round(score, 1),
        rationale=(
            f"Title similarity to the closest candidate role is {best:.0%}; "
            f"{len(overlap)} responsibility keywords are evidenced."
        ),
    )


def _education_dimension(inputs: ScoringInputs) -> DimensionScore:
    required = _level_requirements(inputs.job)
    candidate = _candidate_education_level(inputs.profile)
    if required == 0:
        return DimensionScore(name="education", weight=0, score=60.0,
                              rationale="The advert states no formal education requirement.")
    if candidate >= required:
        return DimensionScore(name="education", weight=0, score=100.0,
                              rationale="The candidate's listed qualification meets the stated requirement.")
    if candidate == required - 1:
        return DimensionScore(name="education", weight=0, score=55.0,
                              rationale="The stated qualification is one level above the candidate's listed education.")
    return DimensionScore(name="education", weight=0, score=20.0,
                          rationale="The listed education does not meet the stated requirement.")


def _seniority_dimension(inputs: ScoringInputs) -> DimensionScore:
    candidate_level, rationale = _candidate_seniority(inputs.profile)
    job_level = inputs.job.seniority or "unknown"
    if job_level not in SENIORITY_RANK or job_level == "unknown":
        return DimensionScore(name="seniority", weight=0, score=60.0,
                              rationale="The advert does not state a seniority level.")
    diff = SENIORITY_RANK[job_level] - SENIORITY_RANK[candidate_level]
    score = {0: 100, 1: 65, -1: 80, 2: 30, -2: 70}.get(diff, 20 if diff > 0 else 60)
    return DimensionScore(
        name="seniority", weight=0, score=float(score),
        rationale=f"Advert level '{job_level}' vs candidate level '{candidate_level}'. {rationale}",
    )


def _location_dimension(inputs: ScoringInputs) -> DimensionScore:
    job = inputs.job
    prefs = inputs.preferences
    modes = [m.lower() for m in prefs.work_modes or []]
    if job.work_mode.value == "remote" and (not modes or "remote" in modes):
        return DimensionScore(name="location_preferences", weight=0, score=100.0,
                              rationale="Remote role and remote work is enabled in preferences.")
    job_country = normalize_text(job.country or job.location)
    if prefs.countries:
        if any(normalize_text(c) in job_country or job_country in normalize_text(c)
               for c in prefs.countries if c):
            score = 100.0
            rationale = "Location matches the preferred countries."
        elif not job_country:
            score = 45.0
            rationale = "The advert does not state a country."
        else:
            score = 25.0
            rationale = f"Job location ('{job.location or job.country}') is outside the preferred countries."
    else:
        score, rationale = 70.0, "No country preference configured."
    if job.work_mode.value == "onsite" and modes and "onsite" not in modes:
        score = min(score, 35.0)
        rationale += " On-site work is not in the selected work modes."
    return DimensionScore(name="location_preferences", weight=0, score=score, rationale=rationale)


def _language_dimension(inputs: ScoringInputs) -> tuple[DimensionScore, list[str]]:
    required = _parse_required_languages(inputs.job)
    candidate = _candidate_languages(inputs.profile)
    if not required:
        return DimensionScore(name="languages", weight=0, score=60.0,
                              rationale="No language requirement is stated in the advert."), []
    concerns: list[str] = []
    satisfied = 0
    details: list[str] = []
    for name, level in required:
        have = 0
        for cand_name, cand_level in candidate.items():
            if normalize_text(name) in cand_name or cand_name in normalize_text(name):
                have = cand_level
                break
        if have and have >= level:
            satisfied += 1
            details.append(f"{name} satisfied")
        elif have:
            details.append(f"{name} listed but below the stated level")
            concerns.append(f"{name} level may be below the advertised requirement.")
        else:
            details.append(f"{name} not evidenced")
            concerns.append(f"Advert requires {name}; no verified proficiency in the profile.")
    score = 100 * satisfied / len(required)
    return DimensionScore(
        name="languages", weight=0, score=round(score, 1),
        rationale="; ".join(details) + ".",
    ), concerns


def _work_auth_dimension(inputs: ScoringInputs) -> tuple[DimensionScore, list[str], EligiblityStatus | None]:
    auth = inputs.profile.work_authorization
    job = inputs.job
    job_country = normalize_text(job.country or job.location)
    residence = normalize_text(auth.residence_country)
    concerns: list[str] = []

    same_country = bool(residence and job_country and residence in job_country) or (
        normalize_text(job.country) and normalize_text(job.country) == residence
    )
    if auth.authorized_to_work is False:
        concerns.append("Profile states the candidate is not currently authorized to work.")
        return DimensionScore(name="work_authorization", weight=0, score=0.0,
                              rationale="Profile explicitly states no current work authorization."), concerns, EligiblityStatus.INELIGIBLE
    if same_country and auth.authorized_to_work is not False:
        return DimensionScore(name="work_authorization", weight=0, score=100.0,
                              rationale=f"Role is in the candidate's country of residence ({auth.residence_country})."), [], EligiblityStatus.ELIGIBLE
    if job.visa_sponsorship is False and auth.sponsorship_required is True:
        concerns.append("The advert does not offer sponsorship and the profile indicates sponsorship is required.")
        return DimensionScore(name="work_authorization", weight=0, score=0.0,
                              rationale="No sponsorship offered; candidate requires sponsorship."), concerns, EligiblityStatus.INELIGIBLE
    if job.visa_sponsorship is True:
        return DimensionScore(name="work_authorization", weight=0, score=85.0,
                              rationale="The advert states that visa sponsorship is available."), [], EligiblityStatus.LIKELY_ELIGIBLE
    if not job_country:
        return DimensionScore(name="work_authorization", weight=0, score=45.0,
                              rationale="The advert does not state a work location, so authorization cannot be assessed."), ["Work authorization could not be assessed."], EligiblityStatus.UNCLEAR
    concerns.append("Cross-border work authorization is unknown; verify the employer's requirements.")
    return DimensionScore(name="work_authorization", weight=0, score=45.0,
                          rationale="The role is in another country and sponsorship is not stated."), concerns, EligiblityStatus.UNCLEAR


def _mandatory_employment_concerns(inputs: ScoringInputs) -> list[str]:
    prefs = inputs.preferences
    concerns: list[str] = []
    job_type = inputs.job.employment_type
    if prefs.employment_types and job_type:
        normalized = {t.lower().replace(" ", "_") for t in prefs.employment_types}
        if job_type not in normalized and not ("graduate" in normalized and job_type == "full_time"):
            concerns.append(f"Employment type '{job_type}' is not in the selected preferences.")
    return concerns


def score_job(inputs: ScoringInputs, *, job_id: str = "",
              weights: dict[str, float] | None = None) -> MatchResult:
    weights = weights or dict(DEFAULT_WEIGHTS)
    total_weight = sum(weights.values()) or 1

    technical = _skill_dimension(inputs)
    experience = _experience_dimension(inputs)
    role = _role_dimension(inputs)
    education = _education_dimension(inputs)
    seniority = _seniority_dimension(inputs)
    location = _location_dimension(inputs)
    language, language_concerns = _language_dimension(inputs)
    auth, auth_concerns, auth_status = _work_auth_dimension(inputs)

    dimensions = [technical, experience, role, education, seniority, location, language, auth]
    for dimension in dimensions:
        dimension.weight = weights.get(dimension.name, 0)

    total = sum(d.score * weights.get(d.name, 0) for d in dimensions) / total_weight
    suitability_weights = {k: weights.get(k, 0) for k in
                           ("technical_skills", "experience_evidence", "role_responsibilities",
                            "education", "seniority")}
    suitability_total = sum(suitability_weights.values()) or 1
    suitability = sum(d.score * suitability_weights.get(d.name, 0) for d in dimensions) / suitability_total

    required = _job_required_skills(inputs.job)
    cand_skills = _candidate_skills(inputs.profile)
    blob = _candidate_text(inputs.profile)
    learning = _learning_skills(inputs.profile)
    matching = [s for s in required
                if canonical_skill(s) not in learning
                and (canonical_skill(s) in cand_skills or text_contains_skill(blob, s))]
    missing = [s for s in required if s not in matching]
    category_key = _job_category(inputs.job)
    transfers = find_transferable(required, inputs.profile.demonstrated_skills(), category_key)
    preferred_owned = [s for s in inputs.job.preferred_skills
                       if canonical_skill(s) in cand_skills or text_contains_skill(blob, s)]
    learning_required = [s for s in required if canonical_skill(s) in learning]
    learning_preferred = [s for s in inputs.job.preferred_skills
                          if canonical_skill(s) in learning]
    projects, experiences = _relevant_entries(inputs.profile, _job_keywords(inputs.job))

    concerns = auth_concerns + language_concerns + _mandatory_employment_concerns(inputs)
    if auth_status == EligiblityStatus.INELIGIBLE:
        eligibility_status = EligiblityStatus.INELIGIBLE
    elif auth_status in (EligiblityStatus.ELIGIBLE, EligiblityStatus.LIKELY_ELIGIBLE) and not language_concerns:
        eligibility_status = auth_status
    elif auth_status == EligiblityStatus.ELIGIBLE and language_concerns:
        eligibility_status = EligiblityStatus.INELIGIBLE
    elif auth_status == EligiblityStatus.UNCLEAR or language_concerns:
        eligibility_status = EligiblityStatus.UNCLEAR
    else:
        eligibility_status = EligiblityStatus.LIKELY_ELIGIBLE

    red_flags: list[str] = []
    if eligibility_status == EligiblityStatus.INELIGIBLE:
        red_flags.append("Mandatory eligibility condition appears unmet — verify before applying.")
    if language_concerns:
        red_flags.extend(language_concerns)
    if missing and len(missing) >= max(3, len(required) // 2):
        red_flags.append(f"Several required skills are not evidenced ({', '.join(missing[:4])}).")
    job_level = SENIORITY_RANK.get(inputs.job.seniority or "unknown", 0)
    candidate_level, _ = _candidate_seniority(inputs.profile)
    if job_level - SENIORITY_RANK.get(candidate_level, 0) >= 2:
        red_flags.append("The role is significantly more senior than the candidate's evidence.")

    classification = _classify(total, eligibility_status)
    explanation = _explain(inputs, total, suitability, matching, missing, eligibility_status,
                           concerns, transfers, category_key)
    action = _recommended_action(classification, eligibility_status)

    return MatchResult(
        job_id=job_id,
        total_score=round(total, 1),
        suitability=round(suitability, 1),
        eligibility=EligibilityAssessment(status=eligibility_status, concerns=concerns),
        dimensions=dimensions,
        matching_skills=matching[:20],
        transferable_skills=transfer_summary(transfers),
        transferability_notes=[note for _, _, note in transfers],
        learning_skills=list(dict.fromkeys([*learning_required, *learning_preferred]))[:20],
        role_family=category_label(category_key) if category_key else "",
        missing_required_skills=missing[:20],
        preferred_skills_held=preferred_owned[:20],
        relevant_projects=projects,
        relevant_experience=experiences,
        education_alignment=education.rationale,
        language_compatibility=language.rationale,
        work_authorization_notes=auth.rationale,
        red_flags=list(dict.fromkeys(red_flags)),
        explanation=explanation,
        classification=classification,
        recommended_action=action,
        created_at=datetime.now(timezone.utc),
    )


def _classify(total: float, eligibility: EligiblityStatus) -> MatchClass:
    if eligibility == EligiblityStatus.INELIGIBLE:
        return MatchClass.NOT_RECOMMENDED if total < 70 else MatchClass.WEAK
    if total >= 85:
        return MatchClass.EXCELLENT
    if total >= 70:
        return MatchClass.STRONG
    if total >= 55:
        return MatchClass.POTENTIAL
    if total >= 40:
        return MatchClass.WEAK
    return MatchClass.NOT_RECOMMENDED


def _explain(inputs: ScoringInputs, total: float, suitability: float,
             matching: list[str], missing: list[str],
             eligibility: EligiblityStatus, concerns: list[str],
             transfers: list[tuple[str, str, str]] | None = None,
             category: str | None = None) -> str:
    job = inputs.job
    parts = [
        f"Overall match {total:.0f}/100 (professional suitability {suitability:.0f}/100) "
        f"for '{job.title}' at {job.company or 'the employer'}"
        + (f", a {category_label(category)} role" if category else "") + "."
    ]
    if matching:
        parts.append(f"Evidenced requirements: {', '.join(matching[:6])}.")
    if transfers:
        parts.append(
            "Transferable but not equivalent: "
            + "; ".join(f"{source} supports {requirement}" for requirement, source, _ in transfers[:3])
            + ". These earn partial credit only; verify the target technology directly."
        )
    if missing:
        parts.append(f"Not evidenced: {', '.join(missing[:6])}.")
    if concerns:
        parts.append(f"Eligibility: {concerns[0]}")
    else:
        parts.append(f"Eligibility assessment: {eligibility.value.replace('_', ' ')}.")
    return " ".join(parts)


def _recommended_action(classification: MatchClass, eligibility: EligiblityStatus) -> str:
    if eligibility == EligiblityStatus.INELIGIBLE:
        return "Verify eligibility before investing time; consider contacting the employer."
    mapping = {
        MatchClass.EXCELLENT: "Apply with a tailored CV — strong evidence across requirements.",
        MatchClass.STRONG: "Tailor the CV to the top requirements and apply.",
        MatchClass.POTENTIAL: "Review the gaps, then tailor the CV if the role still fits.",
        MatchClass.WEAK: "Low priority; only apply if there is a specific reason.",
        MatchClass.NOT_RECOMMENDED: "Skip unless new evidence makes the role relevant.",
    }
    return mapping.get(classification, "Review manually.")


def score_record(job: JobRecord, profile: CandidateProfileData, evidence: list[EvidenceItem],
                 preferences: SearchPreferences, *, job_id: str = "",
                 weights: dict[str, float] | None = None) -> MatchResult:
    return score_job(ScoringInputs(job=job, profile=profile, evidence=evidence,
                                   preferences=preferences), job_id=job_id, weights=weights)
