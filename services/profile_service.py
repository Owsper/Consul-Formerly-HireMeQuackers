"""Ground Truth profile lifecycle: evidence synthesis, persistence, versions."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.exceptions import ProfileNotFoundError
from core.logging_config import get_logger
from core.models import CandidateProfile, ProfileEvidence, ProfileVersion
from core.schemas import (
    CandidateProfileData, EvidenceItem, EvidenceStatus, ProfilePayload,
)
from core.text import slugify

logger = get_logger("profile")


def _eid(prefix: str) -> str:
    return prefix


def ensure_entry_ids(data: CandidateProfileData) -> CandidateProfileData:
    """Assign stable ids to list entries so evidence can point at them."""
    for i, entry in enumerate(data.education):
        if not entry.id:
            entry.id = f"edu-{i + 1}"
    for i, entry in enumerate(data.employment):
        if not entry.id:
            entry.id = f"emp-{i + 1}"
    for i, entry in enumerate(data.projects):
        if not entry.id:
            entry.id = f"prj-{i + 1}"
    for i, entry in enumerate(data.additional.certifications):
        if not entry.id:
            entry.id = f"cert-{i + 1}"
    for i, entry in enumerate(data.additional.awards):
        if not entry.id:
            entry.id = f"award-{i + 1}"
    for i, entry in enumerate(data.additional.publications):
        if not entry.id:
            entry.id = f"pub-{i + 1}"
    for i, entry in enumerate(data.additional.volunteering):
        if not entry.id:
            entry.id = f"vol-{i + 1}"
    return data


def synthesize_evidence(data: CandidateProfileData, *, source_document: str = "manual",
                        status: EvidenceStatus = EvidenceStatus.USER_VERIFIED) -> list[EvidenceItem]:
    """Create a granular, citable evidence ledger from profile content.

    Used for manually entered profiles and to fill gaps left by LLM extraction.
    Bullet-level evidence keeps every generated CV sentence traceable.
    """
    ensure_entry_ids(data)
    items: list[EvidenceItem] = []

    def add(category: str, path: str, label: str, value: str, source_text: str = "") -> None:
        value = (value or "").strip()
        if not value:
            return
        items.append(EvidenceItem(
            evidence_id=f"ev-{len(items) + 1:03d}-{slugify(path, 28) or category}",
            category=category, field_path=path, label=label, value=value,
            source_document=source_document, source_text=source_text or value,
            confidence=1.0 if status == EvidenceStatus.USER_VERIFIED else 0.6,
            inferred=False, status=status,
        ))

    p = data.personal
    for field, label in [
        ("full_name", "Full name"), ("professional_title", "Professional title"),
        ("email", "Email"), ("phone", "Phone"), ("city", "City"), ("country", "Country"),
        ("linkedin", "LinkedIn"), ("github", "GitHub"), ("portfolio", "Portfolio"),
        ("website", "Website"),
    ]:
        add("personal", f"personal.{field}", label, getattr(p, field))

    w = data.work_authorization
    for field, label in [
        ("residence_country", "Country of residence"), ("visa_status", "Visa / residence status"),
        ("work_hour_restrictions", "Working-hour restrictions"),
        ("relocation_preference", "Relocation preference"),
        ("geographic_limitations", "Geographic limitations"),
    ]:
        add("work_authorization", f"work_authorization.{field}", label, getattr(w, field))
    if w.authorized_to_work is not None:
        add("work_authorization", "work_authorization.authorized_to_work", "Work authorization",
            "Authorized to work" if w.authorized_to_work else "Not currently authorized")
    if w.sponsorship_required is not None:
        add("work_authorization", "work_authorization.sponsorship_required", "Sponsorship",
            "Requires sponsorship" if w.sponsorship_required else "No sponsorship required")

    for i, edu in enumerate(data.education):
        headline = ", ".join(x for x in (edu.qualification or edu.degree, edu.subject) if x)
        add("education", f"education[{i}]", "Education",
            " — ".join(x for x in (edu.institution, headline) if x))
        for j, course in enumerate(edu.coursework):
            add("education", f"education[{i}].coursework[{j}]", "Coursework", course)
        for j, proj in enumerate(edu.academic_projects):
            add("education", f"education[{i}].academic_projects[{j}]", "Academic project", proj)
        for j, ach in enumerate(edu.achievements):
            add("education", f"education[{i}].achievements[{j}]", "Academic achievement", ach)

    for i, job in enumerate(data.employment):
        add("employment", f"employment[{i}]", "Employment",
            f"{job.title} at {job.employer}" + (f" ({job.start_date}–{job.end_date or 'present'})" if job.start_date else ""))
        for j, text in enumerate(job.responsibilities):
            add("employment", f"employment[{i}].responsibilities[{j}]", "Responsibility", text)
        for j, text in enumerate(job.achievements):
            add("employment", f"employment[{i}].achievements[{j}]", "Achievement", text)
        for j, tech in enumerate(job.technologies):
            add("employment", f"employment[{i}].technologies[{j}]", "Technology", tech)

    for i, project in enumerate(data.projects):
        add("project", f"projects[{i}]", "Project", project.name)
        add("project", f"projects[{i}].description", "Project description", project.description)
        add("project", f"projects[{i}].implementation", "Implementation", project.implementation)
        add("project", f"projects[{i}].results", "Measurable results", project.measurable_results)
        for j, tech in enumerate(project.technologies):
            add("project", f"projects[{i}].technologies[{j}]", "Project technology", tech)
        for j, ach in enumerate(project.verified_achievements):
            add("project", f"projects[{i}].achievements[{j}]", "Project achievement", ach)

    for i, group in enumerate(data.skills):
        add("skill", f"skills[{i}]", group.name or "Skills", ", ".join(group.skills))

    for i, cert in enumerate(data.additional.certifications):
        add("certification", f"additional.certifications[{i}]", "Certification",
            " — ".join(x for x in (cert.name, cert.issuer, cert.date) if x))
    for i, award in enumerate(data.additional.awards):
        add("award", f"additional.awards[{i}]", "Award",
            " — ".join(x for x in (award.name, award.issuer, award.date) if x))
    for i, pub in enumerate(data.additional.publications):
        add("publication", f"additional.publications[{i}]", "Publication",
            " — ".join(x for x in (pub.title, pub.venue, pub.date) if x))
    for i, vol in enumerate(data.additional.volunteering):
        add("volunteering", f"additional.volunteering[{i}]", "Volunteering",
            " — ".join(x for x in (vol.role, vol.organization, vol.dates) if x))
    for i, lang in enumerate(data.additional.languages):
        add("language", f"additional.languages[{i}]", "Language",
            f"{lang.language} ({lang.proficiency})" if lang.proficiency else lang.language)
    for interest in data.additional.professional_interests:
        add("interest", "additional.professional_interests", "Professional interest", interest)
    for other in data.additional.other:
        add("other", "additional.other", "Additional information", other)

    return items


def normalise_llm_evidence(raw: list[dict], data: CandidateProfileData,
                           source_document: str) -> list[EvidenceItem]:
    """Validate LLM-provided evidence and add missing ids."""
    items: list[EvidenceItem] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            continue
        try:
            item = EvidenceItem.model_validate(entry)
        except Exception:
            continue
        if not item.evidence_id or item.evidence_id in seen:
            item.evidence_id = f"ev-{index + 1:03d}"
        while item.evidence_id in seen:
            item.evidence_id += "x"
        seen.add(item.evidence_id)
        if not item.source_document or item.source_document == "manual":
            item.source_document = source_document
        item.confidence = max(0.0, min(1.0, float(item.confidence or 0.0)))
        if item.inferred:
            item.status = EvidenceStatus.NEEDS_REVIEW
        elif item.status == EvidenceStatus.UNVERIFIED and item.confidence >= 0.85:
            item.status = EvidenceStatus.NEEDS_REVIEW
        items.append(item)
    if not items:
        return synthesize_evidence(data, source_document=source_document,
                                   status=EvidenceStatus.UNVERIFIED)
    return items


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _next_version(session: Session, profile_id: int) -> int:
    current = session.scalar(
        select(func.max(ProfileVersion.version)).where(ProfileVersion.profile_id == profile_id)
    )
    return int(current or 0) + 1


def save_profile(session: Session, data: CandidateProfileData, evidence: list[EvidenceItem],
                 *, name: str = "My profile", note: str = "Profile saved",
                 approve: bool = False, profile_id: int | None = None) -> CandidateProfile:
    data = ensure_entry_ids(data)
    profile = session.get(CandidateProfile, profile_id) if profile_id else None
    if profile_id and profile is None:
        raise ProfileNotFoundError(f"Profile {profile_id} does not exist")
    if profile is None:
        profile = CandidateProfile(name=name)
        session.add(profile)
        session.flush()

    profile.name = name or profile.name
    profile.data_json = data.model_dump_json()

    if approve:
        session.query(CandidateProfile).filter(CandidateProfile.id != profile.id).update(
            {CandidateProfile.is_active: False}
        )
        profile.is_active = True
        profile.approved_at = datetime.now(timezone.utc)
        # Approving the profile activates it; it does not silently upgrade the
        # review status of individual evidence items.

    # Replace evidence rows with the current ledger.
    session.query(ProfileEvidence).filter(ProfileEvidence.profile_id == profile.id).delete()
    for item in evidence:
        item.status = item.status if isinstance(item.status, EvidenceStatus) else EvidenceStatus(item.status)
        session.add(ProfileEvidence(
            profile_id=profile.id, evidence_id=item.evidence_id, category=item.category,
            field_path=item.field_path, label=item.label, value=item.value,
            source_document=item.source_document, source_text=item.source_text,
            confidence=item.confidence, inferred=item.inferred,
            status=item.status.value if hasattr(item.status, "value") else str(item.status),
        ))

    session.flush()
    session.add(ProfileVersion(
        profile_id=profile.id, version=_next_version(session, profile.id),
        data_json=profile.data_json,
        evidence_json=json.dumps([e.model_dump(mode="json") for e in evidence], ensure_ascii=False),
        note=note,
    ))
    session.flush()
    logger.info("Saved profile %s (v%s, approved=%s, %s evidence items)",
                profile.id, _next_version(session, profile.id) - 1, approve, len(evidence))
    return profile


def get_profile(session: Session, profile_id: int) -> CandidateProfile | None:
    return session.get(CandidateProfile, profile_id)


def get_active_profile(session: Session) -> tuple[CandidateProfile, ProfilePayload] | None:
    profile = session.scalars(
        select(CandidateProfile).where(CandidateProfile.is_active.is_(True)).order_by(
            CandidateProfile.approved_at.desc().nullslast(), CandidateProfile.id.desc()
        )
    ).first()
    if profile is None:
        return None
    return profile, profile_to_payload(profile)


def get_latest_profile(session: Session) -> tuple[CandidateProfile, ProfilePayload] | None:
    profile = session.scalars(select(CandidateProfile).order_by(CandidateProfile.id.desc())).first()
    if profile is None:
        return None
    return profile, profile_to_payload(profile)


def profile_to_payload(profile: CandidateProfile) -> ProfilePayload:
    data = CandidateProfileData.model_validate_json(profile.data_json or "{}")
    evidence = [
        EvidenceItem(
            evidence_id=e.evidence_id, category=e.category, field_path=e.field_path,
            label=e.label, value=e.value, source_document=e.source_document,
            source_text=e.source_text, confidence=e.confidence, inferred=e.inferred,
            status=EvidenceStatus(e.status),
        )
        for e in profile.evidence
    ]
    if not evidence:
        evidence = synthesize_evidence(data, source_document="profile")
    return ProfilePayload(data=data, evidence=evidence)


def profile_is_approved(profile: CandidateProfile) -> bool:
    return bool(profile.is_active and profile.approved_at is not None)


def list_profiles(session: Session) -> list[CandidateProfile]:
    return list(session.scalars(select(CandidateProfile).order_by(CandidateProfile.id.desc())))


def activate_profile(session: Session, profile_id: int) -> CandidateProfile:
    profile = session.get(CandidateProfile, profile_id)
    if profile is None:
        raise ProfileNotFoundError(f"Profile {profile_id} does not exist")
    session.query(CandidateProfile).filter(CandidateProfile.id != profile_id).update(
        {CandidateProfile.is_active: False}
    )
    profile.is_active = True
    profile.approved_at = profile.approved_at or datetime.now(timezone.utc)
    session.flush()
    return profile


def delete_profile(session: Session, profile_id: int) -> None:
    profile = session.get(CandidateProfile, profile_id)
    if profile is None:
        raise ProfileNotFoundError(f"Profile {profile_id} does not exist")
    session.delete(profile)
    session.flush()


def update_evidence_status(session: Session, profile_id: int, evidence_id: str,
                           status: EvidenceStatus) -> None:
    row = session.scalars(
        select(ProfileEvidence).where(
            ProfileEvidence.profile_id == profile_id, ProfileEvidence.evidence_id == evidence_id
        )
    ).first()
    if row is None:
        raise ProfileNotFoundError(f"Evidence {evidence_id} not found")
    row.status = status.value
    session.flush()


def get_versions(session: Session, profile_id: int) -> list[ProfileVersion]:
    return list(session.scalars(
        select(ProfileVersion).where(ProfileVersion.profile_id == profile_id).order_by(
            ProfileVersion.version.desc()
        )
    ))


def restore_version(session: Session, profile_id: int, version: int) -> CandidateProfile:
    row = session.scalars(
        select(ProfileVersion).where(
            ProfileVersion.profile_id == profile_id, ProfileVersion.version == version
        )
    ).first()
    if row is None:
        raise ProfileNotFoundError(f"Version {version} not found")
    data = CandidateProfileData.model_validate_json(row.data_json)
    evidence = [EvidenceItem.model_validate(e) for e in json.loads(row.evidence_json or "[]")]
    return save_profile(session, data, evidence, name=session.get(CandidateProfile, profile_id).name,
                        note=f"Restored from version {version}", profile_id=profile_id,
                        approve=True)


def merge_profiles(base: CandidateProfileData, incoming: CandidateProfileData) -> CandidateProfileData:
    """Merge a second CV's verified data into the master profile without duplicates."""
    merged = base.model_copy(deep=True)

    # Personal: fill blanks, never overwrite confirmed values.
    for field, value in incoming.personal.model_dump().items():
        if value and not getattr(merged.personal, field):
            setattr(merged.personal, field, value)

    for field, value in incoming.work_authorization.model_dump().items():
        if value not in (None, "", False) and getattr(merged.work_authorization, field) in (None, "", False):
            setattr(merged.work_authorization, field, value)

    def merge_list(target: list, source: list, key_fields: tuple[str, ...]) -> None:
        existing = {tuple(str(getattr(x, f, "")).lower() for f in key_fields) for x in target}
        for item in source:
            key = tuple(str(getattr(item, f, "")).lower() for f in key_fields)
            if key not in existing and any(key):
                target.append(item)
                existing.add(key)

    merge_list(merged.education, incoming.education, ("institution", "qualification"))
    # Employment is matched on employer + title instead of including dates: a second
    # document often repeats the same role with a different or missing date range.
    for item in incoming.employment:
        match = next(
            (x for x in merged.employment
             if x.employer.strip().lower() == item.employer.strip().lower()
             and x.title.strip().lower() == item.title.strip().lower()),
            None,
        )
        if match is None:
            merged.employment.append(item)
            continue
        for field in ("location", "start_date", "end_date"):
            if not getattr(match, field, "") and getattr(item, field, ""):
                setattr(match, field, getattr(item, field))
        for field in ("responsibilities", "achievements", "technologies", "quantified_results"):
            existing_items = {str(v).strip().lower() for v in getattr(match, field)}
            for value in getattr(item, field):
                if str(value).strip().lower() not in existing_items and str(value).strip():
                    getattr(match, field).append(value)
                    existing_items.add(str(value).strip().lower())
    merge_list(merged.projects, incoming.projects, ("name",))
    merge_list(merged.additional.certifications, incoming.additional.certifications, ("name",))
    merge_list(merged.additional.awards, incoming.additional.awards, ("name",))
    merge_list(merged.additional.publications, incoming.additional.publications, ("title",))
    merge_list(merged.additional.volunteering, incoming.additional.volunteering, ("organization", "role"))
    merge_list(merged.additional.languages, incoming.additional.languages, ("language",))

    for group in incoming.skills:
        existing = next((g for g in merged.skills if g.name.lower() == group.name.lower()), None)
        if existing is None:
            merged.skills.append(group.model_copy())
        else:
            for skill in group.skills:
                if skill.lower() not in {s.lower() for s in existing.skills}:
                    existing.skills.append(skill)

    for section, lines in incoming.extra_sections.items():
        merged.extra_sections.setdefault(section, [])
        for line in lines:
            if line not in merged.extra_sections[section]:
                merged.extra_sections[section].append(line)

    return ensure_entry_ids(merged)


def compress_evidence(evidence: list[EvidenceItem]) -> list[dict]:
    """Compact ledger representation for prompts (keeps token use sane)."""
    compact = []
    for item in evidence:
        if item.status == EvidenceStatus.REJECTED:
            continue
        compact.append({
            "evidence_id": item.evidence_id,
            "category": item.category,
            "value": item.value[:400],
            "inferred": item.inferred,
            "status": item.status.value if isinstance(item.status, EvidenceStatus) else item.status,
        })
    return compact
