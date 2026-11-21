"""Versioned ATS and AI-screening rules for 2026.

This is the single source of truth for how CONSUL thinks about applicant tracking
systems. Tailoring prompts, validation, export checks and CV Studio's readiness
report all read from here, so a rule change only has to be made once.

The rules distinguish three very different things that are often conflated:

* **Parsing** — can the document be read into clean, ordered text and fields?
* **Knockout questions** — the application form's real auto-reject gate, which a
  CV cannot fix (work authorisation, licence, minimum years, shift availability).
* **Ranking** — keyword/semantic relevance, title alignment and quantified
  evidence. This affects visibility; it is not a documented automatic rejection
  mechanism at the major ATS vendors.

Sources of truth for these rules are the 2026 ATS research notes supplied with
the project. They are deliberately conservative: CONSUL never claims that
formatting alone causes rejection, and never lets keyword coverage justify an
invented fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from core.schemas import CandidateProfileData, EvidenceItem, JobRecord, TailoredCV
from core.text import normalize_text, normalize_whitespace, text_contains_skill

ATS_RULES_VERSION = "2026.1"

# Standard, parser-friendly headings. Section headings are matched case-insensitively.
STANDARD_HEADINGS: frozenset[str] = frozenset({
    "profile", "summary", "professional summary", "professional profile",
    "professional experience", "work experience", "experience", "employment",
    "project experience", "projects", "academic projects",
    "education", "technical skills", "skills", "core skills",
    "languages", "certifications", "certificates", "awards", "publications",
    "volunteering", "additional information",
})

HEADING_TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "Profile": "Profil",
        "Summary": "Zusammenfassung",
        "Professional Experience": "Berufserfahrung",
        "Project Experience": "Projekterfahrung",
        "Academic Projects": "Akademische Projekte",
        "Education": "Ausbildung",
        "Technical Skills": "Technische Kenntnisse",
        "Skills": "Kenntnisse",
        "Languages": "Sprachen",
        "Certifications": "Zertifikate",
        "Awards": "Auszeichnungen",
        "Publications": "Publikationen",
        "Volunteering": "Ehrenamt",
        "Additional Information": "Weitere Informationen",
    },
    "fr": {
        "Profile": "Profil",
        "Summary": "Résumé",
        "Professional Experience": "Expérience professionnelle",
        "Project Experience": "Projets",
        "Academic Projects": "Projets académiques",
        "Education": "Formation",
        "Technical Skills": "Compétences techniques",
        "Skills": "Compétences",
        "Languages": "Langues",
        "Certifications": "Certifications",
        "Awards": "Distinctions",
        "Publications": "Publications",
        "Volunteering": "Bénévolat",
        "Additional Information": "Informations complémentaires",
    },
    "es": {
        "Profile": "Perfil",
        "Summary": "Resumen",
        "Professional Experience": "Experiencia profesional",
        "Project Experience": "Proyectos",
        "Academic Projects": "Proyectos académicos",
        "Education": "Formación",
        "Technical Skills": "Competencias técnicas",
        "Skills": "Competencias",
        "Languages": "Idiomas",
        "Certifications": "Certificaciones",
        "Awards": "Premios",
        "Publications": "Publicaciones",
        "Volunteering": "Voluntariado",
        "Additional Information": "Información adicional",
    },
    "nl": {
        "Profile": "Profiel",
        "Summary": "Samenvatting",
        "Professional Experience": "Werkervaring",
        "Project Experience": "Projectervaring",
        "Academic Projects": "Academische projecten",
        "Education": "Opleiding",
        "Technical Skills": "Technische vaardigheden",
        "Skills": "Vaardigheden",
        "Languages": "Talen",
        "Certifications": "Certificaten",
        "Awards": "Prijzen",
        "Publications": "Publicaties",
        "Volunteering": "Vrijwilligerswerk",
        "Additional Information": "Aanvullende informatie",
    },
}

ALLOWED_FONTS: tuple[str, ...] = ("Arial", "Calibri", "Times New Roman", "Georgia")
SERIF_FALLBACKS: tuple[str, ...] = ("Liberation Serif", "Nimbus Roman")
PREFERRED_FILE_TYPES: tuple[str, ...] = ("docx", "pdf", "txt")

KNOCKOUT_NOTE = (
    "Knockout questions live on the employer's application form, not in the CV. "
    "Work authorisation, location, licences, minimum years, degree and shift "
    "availability can reject an application automatically and cannot be fixed by "
    "editing the document. Answer those questions accurately and separately."
)

ANTI_PATTERNS: tuple[str, ...] = (
    "multi-column, sidebar or grid layouts",
    "tables used for dates, titles or core content",
    "contact details or dates in headers, footers or text boxes",
    "photos, logos, icons, charts, skill bars or emoji",
    "image-only, scanned or password-protected PDFs",
    "creative section headings such as 'My Journey' or 'Where I've Been'",
    "non-standard or decorative fonts",
    "hidden, white or microscopic keyword text",
    "keyword dumps with no supporting context",
    "invented metrics or certifications",
    "generic, repetitive AI-sounding phrasing",
)

RANKING_SIGNALS: tuple[str, ...] = (
    "exact or near-exact must-have terms placed naturally in Skills and recent experience",
    "job-title terminology aligned with the posting where the candidate's real history allows",
    "quantified, result-oriented bullets grounded in evidence",
    "consistent dates, titles and employment type",
    "semantic neighbours only as support, never as a claim of equivalence",
)


@dataclass(frozen=True)
class ATSRule:
    key: str
    label: str
    detail: str


HARD_PARSE_RULES: tuple[ATSRule, ...] = (
    ATSRule("single_column", "Single column", "One linear reading order from top to bottom."),
    ATSRule("no_tables", "No tables", "Dates, titles and content must not be table cells."),
    ATSRule("no_text_boxes", "No text boxes", "Content in text boxes is frequently dropped."),
    ATSRule("body_contact", "Contact in the body", "Name, email, phone and links in the body, never the header/footer."),
    ATSRule("standard_headings", "Standard headings", "Use Summary, Experience, Education, Skills, Certifications."),
    ATSRule("standard_fonts", "Standard fonts", "Arial, Calibri, Times New Roman or Georgia at 10-12 pt body size."),
    ATSRule("plain_bullets", "Plain bullets", "A standard round bullet, not icons or decorative glyphs."),
    ATSRule("text_layer", "Text layer", "A selectable, extractable PDF or a clean DOCX, never an image."),
    ATSRule("file_size", "Reasonable file size", "Keep the document small; some systems reject oversized uploads."),
)


@dataclass(frozen=True)
class JobTerms:
    """High-value terms extracted from the target job."""

    must_have: tuple[str, ...]
    nice_to_have: tuple[str, ...]
    target_title: str = ""
    certifications: tuple[str, ...] = ()
    key_phrases: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "must_have": list(self.must_have),
            "nice_to_have": list(self.nice_to_have),
            "target_title": self.target_title,
            "certifications": list(self.certifications),
            "key_phrases": list(self.key_phrases),
        }

    def prompt_text(self) -> str:
        must = ", ".join(self.must_have) or "(none stated)"
        nice = ", ".join(self.nice_to_have) or "(none stated)"
        certs = ", ".join(self.certifications) or "(none stated)"
        phrases = "; ".join(self.key_phrases) or "(none stated)"
        return (
            f"Target title: {self.target_title or '(not stated)'}\n"
            f"Must-have terms: {must}\n"
            f"Nice-to-have terms: {nice}\n"
            f"Certifications mentioned: {certs}\n"
            f"Key advert phrases: {phrases}\n"
            "Only use a term where the evidence ledger supports it. Never add a term "
            "to satisfy this list."
        )


def standard_heading_set() -> set[str]:
    """All accepted heading spellings, including the supported translations."""
    accepted = {heading.lower() for heading in STANDARD_HEADINGS}
    for translations in HEADING_TRANSLATIONS.values():
        accepted.update(value.lower() for value in translations.values())
    return accepted


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = normalize_whitespace(str(raw or "")).strip(" ,;|")
        key = normalize_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def _language_terms(languages: Iterable[str]) -> list[str]:
    """Turn 'German (C1)' into 'German' without inventing a level."""
    terms: list[str] = []
    for value in languages:
        name = re.split(r"[\(\[]", str(value or ""), maxsplit=1)[0].strip(" ,;-")
        if name:
            terms.append(name)
    return terms


_CERTIFICATION_RE = re.compile(
    r"\b(?:"
    r"AWS Certified[^,.;\n]{0,50}|Microsoft Certified[^,.;\n]{0,50}|"
    r"Azure Certified[^,.;\n]{0,50}|Google Cloud Certified[^,.;\n]{0,50}|"
    r"CKA|CKAD|CKS|PMP|CISSP|CCNA|CCNP|ITIL|ISTQB|"
    r"CompTIA [A-Za-z+]{1,20}|Scrum Master|Terraform Associate"
    r")\b",
    re.IGNORECASE,
)


def _certification_terms(job: JobRecord) -> tuple[str, ...]:
    """Conservative credential names explicitly mentioned in the advert."""
    text = " ".join([job.description, *job.experience_requirements])
    return _dedupe(match.group(0).strip() for match in _CERTIFICATION_RE.finditer(text))


def job_terms(job: JobRecord) -> JobTerms:
    """Extract the job's high-value terms from its structured fields.

    Job enrichment already turns the advert into required/preferred skills and
    language requirements. Using those fields is more reliable (and less prone to
    fabricating phrases) than mining arbitrary noun phrases from prose. Credentials
    and advert phrases are extracted only as prompt context; they never enter the
    keyword-coverage denominator.
    """
    return JobTerms(
        must_have=_dedupe([*job.required_skills, *_language_terms(job.languages)]),
        nice_to_have=_dedupe(job.preferred_skills),
        target_title=normalize_whitespace(job.title),
        certifications=_certification_terms(job),
        key_phrases=_dedupe([job.title, *[r[:160] for r in job.responsibilities[:4]]]),
    )


def ats_prompt_rules() -> str:
    """A compact rule block injected into tailoring and audit prompts."""
    parse = "\n".join(f"- {rule.label}: {rule.detail}" for rule in HARD_PARSE_RULES)
    anti = "\n".join(f"- {item}" for item in ANTI_PATTERNS)
    ranking = "\n".join(f"- {item}" for item in RANKING_SIGNALS)
    headings = ", ".join(sorted(standard_heading_set()))
    return (
        f"ATS RULES (version {ATS_RULES_VERSION})\n"
        f"PARSING\n{parse}\n"
        f"RANKING\n{ranking}\n"
        f"NEVER\n{anti}\n"
        f"ACCEPTED HEADINGS\n{headings}\n"
        "Knockout questions are handled on the application form and are outside the CV."
    )


def _present(text: str, term: str) -> bool:
    """Token-aware presence check; avoids 'Go' matching inside 'Google'."""
    if not term:
        return False
    return text_contains_skill(text, term)


def _coverage(cv_text: str, terms: tuple[str, ...], evidence_text: str) -> dict[str, Any]:
    """Coverage of terms the candidate can actually evidence.

    Terms without evidence are reported separately and are never counted as
    missing. This is what keeps the metric honest: a CV cannot be penalised for
    not claiming a skill the candidate does not have.
    """
    available = [term for term in terms if _present(evidence_text, term)]
    covered = [term for term in available if _present(cv_text, term)]
    missing = [term for term in available if term not in covered]
    unevidenced = [term for term in terms if term not in available]
    ratio = round(len(covered) / len(available), 3) if available else 1.0
    return {
        "total": len(terms),
        "available": len(available),
        "covered": covered,
        "missing_evidenced": missing,
        "unevidenced": unevidenced,
        "ratio": ratio,
    }


def evidence_claim_text(evidence: list[EvidenceItem]) -> str:
    """Public entry point for the evidence a CV is allowed to claim."""
    return _evidence_text(evidence)


def coverage_of(cv_text: str, terms: tuple[str, ...],
                evidence_text: str) -> dict[str, Any]:
    """Public entry point for token-aware coverage of a term set."""
    return _coverage(cv_text, terms, evidence_text)


def _evidence_text(evidence: list[EvidenceItem]) -> str:
    """Evidence the candidate can actually claim.

    Learning and interest entries are recorded honestly in the ledger, but they
    must not make a job term look "available" to the keyword-coverage check, or
    the CV would be nudged to claim a skill the candidate does not have yet.
    """
    from core.text import skill_group_status

    lines: list[str] = []
    for item in evidence:
        if item.status.value == "rejected":
            continue
        if item.category in {"interest", "professional_interest"}:
            continue
        if item.category == "skill" and skill_group_status(item.label) != "demonstrated":
            continue
        lines.append(f"{item.label}: {item.value} {item.source_text}")
    return "\n".join(lines)


def _cv_text(cv: TailoredCV) -> str:
    parts: list[str] = [cv.header.name, cv.header.title, cv.summary]
    parts.extend(cv.header.contact_lines)
    parts.extend([cv.header.visa_status, cv.header.applying_for])
    for section in cv.sections:
        parts.append(section.heading)
        parts.extend(section.skills)
        parts.extend(section.lines)
        for row in section.rows:
            parts.extend([row.label, row.text])
        for entry in section.entries:
            parts.extend([entry.title, entry.organization, entry.location, entry.dates])
            parts.extend(entry.technologies)
            parts.extend(bullet.text for bullet in entry.bullets)
    return "\n".join(part for part in parts if part)


def _layout_checks(layout: dict[str, Any] | None) -> dict[str, bool]:
    if not isinstance(layout, dict):
        return {}
    return {
        str(check.get("name")): bool(check.get("passed"))
        for check in layout.get("checks", []) or []
        if isinstance(check, dict)
    }


_VAGUE_RESPONSIBILITY_RE = re.compile(
    r"^(responsible for|worked on|helped (?:with|to)|assisted (?:with|in)|"
    r"involved in|participated in)\b",
    re.IGNORECASE,
)


def build_ats_report(cv: TailoredCV, profile: CandidateProfileData,
                     evidence: list[EvidenceItem], job: JobRecord, *,
                     layout: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the deterministic ATS readiness report stored with a CV version."""
    headings = [section.heading.strip() for section in cv.sections if section.heading.strip()]
    accepted = standard_heading_set()
    nonstandard = [heading for heading in headings if heading.lower() not in accepted]
    bullets = cv.all_bullets()
    all_text = _cv_text(cv)
    contact = bool(cv.header.contact_lines) and bool(
        profile.personal.email or profile.personal.phone
    )
    has_emoji = bool(re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", all_text))
    terms = job_terms(job)
    evidence_text = _evidence_text(evidence)
    must = _coverage(all_text, terms.must_have, evidence_text)
    nice = _coverage(all_text, terms.nice_to_have, evidence_text)
    quantified = [bullet for bullet in bullets if re.search(r"\d", bullet.text)]
    quantification_ratio = round(len(quantified) / len(bullets), 3) if bullets else 0.0
    vague = [
        bullet.text for bullet in bullets
        if _VAGUE_RESPONSIBILITY_RE.match(bullet.text.strip()) and not re.search(r"\d", bullet.text)
    ]

    checks = {
        "single_column": True,
        "no_tables": True,
        "no_text_boxes": True,
        "contact_in_body": contact,
        "standard_headings": not nonstandard,
        "plain_bullets": not has_emoji,
        "text_layer_expected": bool(all_text.strip()),
        "title_alignment": bool(
            terms.target_title and terms.target_title.lower()
            in (cv.header.applying_for or "").lower()
        ),
    }
    reasons: list[str] = []
    risk = "low"
    if not contact:
        risk = "high"
        reasons.append("No body contact block with an email or phone number.")
    if not (cv.header.name or "").strip():
        risk = "high"
        reasons.append("The candidate name is missing from the document body.")
    if nonstandard:
        risk = "medium" if risk == "low" else risk
        reasons.append("Non-standard heading(s): " + ", ".join(nonstandard[:4]) + ".")
    if has_emoji:
        risk = "medium" if risk == "low" else risk
        reasons.append("Decorative glyphs or emoji were found in the text.")

    layout_flags = _layout_checks(layout)
    if layout_flags:
        severe = {
            "text_layer": "The PDF has little or no extractable text.",
            "no_text_overflow": "Text overflows the page and may be clipped.",
            "no_embedded_images": "The PDF embeds images or graphics.",
            "no_icon_fonts": "An icon or decorative font was detected.",
        }
        moderate = {
            "page_size": "The PDF is not A4.",
            "page_count": "The document is longer than expected.",
            "typography": "Typography differs from the standard template.",
            "file_size": "The file is larger than the common upload limit.",
        }
        for key, message in severe.items():
            if key in layout_flags and not layout_flags[key]:
                risk = "high" if key == "text_layer" else ("medium" if risk == "low" else risk)
                reasons.append(message)
        for key, message in moderate.items():
            if key in layout_flags and not layout_flags[key]:
                risk = "medium" if risk == "low" else risk
                reasons.append(message)
        if "contact_in_body" in layout_flags and not layout_flags["contact_in_body"]:
            risk = "high"
            reasons.append("Contact details were not found in the document body.")

    recommendations: list[str] = []
    for heading in nonstandard[:3]:
        recommendations.append(
            f"Rename the '{heading}' heading to a standard one such as "
            "'Professional Experience' or 'Skills'."
        )
    if not contact:
        recommendations.append(
            "Add an email address and phone number to Ground Truth so they appear "
            "in the body contact block."
        )
    if must["missing_evidenced"]:
        recommendations.append(
            "Use these already-evidenced must-have terms in Skills or a recent "
            "experience bullet: " + ", ".join(must["missing_evidenced"][:8]) + "."
        )
    if bullets and quantification_ratio < 0.3:
        recommendations.append(
            "Add quantified outcomes only where the evidence ledger already "
            "contains the numbers; do not estimate or invent them."
        )
    if vague:
        recommendations.append(
            "Rewrite vague duty statements (for example 'responsible for') around "
            "the concrete outcome already recorded in the evidence ledger."
        )
    if not bullets:
        recommendations.append(
            "Generate at least one evidence-cited experience or project bullet."
        )
    if any("page_count" in key and not passed for key, passed in layout_flags.items()):
        recommendations.append(
            "Trim less relevant bullets so the document stays within two pages."
        )
    if risk != "low":
        recommendations.append(
            "Resolve the parse risks above before submitting; a scrambled parse can "
            "make a strong candidate invisible regardless of fit."
        )
    recommendations.append(
        "Never add a missing keyword, metric or certification just to satisfy the "
        "advert. Knockout questions are answered on the application form, not here."
    )

    return {
        "version": ATS_RULES_VERSION,
        "parse_risk": risk,
        "parse_risk_reasons": reasons,
        "parse_checks": checks,
        "keyword_coverage": {
            "must_have": must,
            "nice_to_have": nice,
            "target_title": terms.target_title,
        },
        "quantified_bullets": {
            "with_metrics": len(quantified),
            "total": len(bullets),
            "ratio": quantification_ratio,
        },
        "content_quality": {
            "vague_responsibility_count": len(vague),
            "vague_responsibility_examples": vague[:5],
        },
        "recommendations": recommendations,
        "knockout_note": KNOCKOUT_NOTE,
        "layout_checked": bool(layout_flags),
    }


def apply_layout_signals(ats_report: dict[str, Any],
                         layout: dict[str, Any] | None) -> dict[str, Any]:
    """Merge measured PDF signals into an existing ATS report.

    Layout verification runs after export, so it cannot participate in the first
    report. This second pass keeps the readiness verdict honest about what the
    renderer actually produced.
    """
    if not isinstance(ats_report, dict) or not ats_report:
        return ats_report
    if not isinstance(layout, dict) or not layout:
        return ats_report
    flags = _layout_checks(layout)
    if not flags:
        return ats_report

    updated = dict(ats_report)
    checks = dict(updated.get("parse_checks") or {})
    updated["layout_checked"] = True
    for key in ("text_layer", "no_text_overflow", "no_embedded_images", "no_icon_fonts",
                "page_size", "page_count", "typography", "file_size"):
        if key in flags:
            checks[f"layout_{key}"] = flags[key]
    updated["parse_checks"] = checks

    risk = str(updated.get("parse_risk") or "low")
    reasons = list(updated.get("parse_risk_reasons") or [])
    if flags.get("text_layer") is False:
        risk = "high"
        reasons.append("The exported PDF has no usable text layer.")
    overflow = flags.get("no_text_overflow")
    if overflow is False:
        risk = "high" if risk == "low" else risk
        reasons.append("Text was measured outside the page boundary.")
    for key, message in (
        ("no_embedded_images", "The exported PDF contains embedded images."),
        ("no_icon_fonts", "An icon or decorative font is present."),
        ("page_size", "The exported PDF is not A4."),
        ("typography", "Typography differs from the standard template."),
        ("page_count", "The document exceeds the expected page count."),
        ("file_size", "The file exceeds the common upload size limit."),
    ):
        if flags.get(key) is False:
            risk = "medium" if risk == "low" else risk
            reasons.append(message)
    updated["parse_risk"] = risk
    updated["parse_risk_reasons"] = list(dict.fromkeys(reasons))
    if risk != "low":
        recommendations = list(updated.get("recommendations") or [])
        note = ("Re-export and re-check the measured layout before submitting; a "
                "version that fails these checks may parse poorly.")
        if note not in recommendations:
            recommendations.append(note)
        updated["recommendations"] = recommendations
    return updated
