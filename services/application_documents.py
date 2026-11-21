"""Evidence-grounded cover letters and recruiter emails.

Both documents follow the same contract as CV tailoring:

* an LLM drafts the prose from the Ground Truth profile and the target job;
* a deterministic builder is used offline, or when an LLM draft fails validation;
* a deterministic sanitiser removes uncited paragraphs, and a validator checks
  every number, skill claim, recipient and length before the draft is stored.

Greeting, subject, closing and signature are always built here from the
candidate profile and the optional recipient the user entered. The model can
therefore never invent a recruiter name, contact detail or sign-off.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.ats_rules import evidence_claim_text, job_terms
from core.logging_config import get_logger
from core.schemas import (
    CandidateProfileData, CoverLetterDraft, DocumentParagraph, EmailDraft, EvidenceItem,
    JobRecord, LetterValidation, MatchResult, ValidationIssue,
)
from core.text import (
    canonical_skill, filename_stem, normalize_text, normalize_whitespace, skill_group_status,
    text_contains_skill,
)
from services.settings_service import get_setting, set_setting

logger = get_logger("application_documents")

_GREETING_GENERIC = {
    "en": "Dear Hiring Manager,",
    "de": "Sehr geehrte Damen und Herren,",
    "fr": "Madame, Monsieur,",
    "es": "Estimado equipo de selección,",
    "nl": "Geachte heer/mevrouw,",
}

PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "greeting_named": "Dear {name},",
        "applying": "I am applying for the {job} role at {company}.",
        "applying_no_company": "I am applying for the {job} role.",
        "profile": "I am a {title} with {years} of professional experience, focused on {focus}.",
        "profile_no_years": "I am a {title} with hands-on experience in {focus}.",
        "profile_no_focus": "I am a {title}.",
        "profile_projects": "I have hands-on project experience in {focus}.",
        "experience": "At {employer}, where I worked as {title}, my responsibilities and results included: {facts}",
        "project": "In my work on {name}, I delivered the following: {facts}",
        "education": "I hold {qualification} from {institution}.",
        "certification": "I am also certified as {certification}.",
        "closing": "Thank you for considering my application. I would welcome the opportunity to discuss how my experience fits the role.",
        "email_closing": "I have attached my CV and would welcome a short conversation about the role. Thank you for your time.",
        "email_role": "I am contacting you about the {job} role at {company}.",
        "email_role_no_company": "I am contacting you about the {job} role.",
        "years": "{n}+ years",
        "subject": "Application: {job} at {company} — {name}",
        "subject_no_company": "Application: {job} — {name}",
        "conjunction": "and",
    },
    "de": {
        "greeting_named": "Guten Tag {name},",
        "applying": "Ich bewerbe mich auf die Stelle als {job} bei {company}.",
        "applying_no_company": "Ich bewerbe mich auf die ausgeschriebene Stelle als {job}.",
        "profile": "Ich bin {title} mit {years} Berufserfahrung und den Schwerpunkten {focus}.",
        "profile_no_years": "Ich bin {title} mit praktischer Erfahrung in {focus}.",
        "profile_no_focus": "Ich bin {title}.",
        "profile_projects": "Ich verfüge über praktische Projekterfahrung in {focus}.",
        "experience": "Bei {employer} als {title} umfassten meine Aufgaben und Ergebnisse: {facts}",
        "project": "Im Projekt {name} habe ich Folgendes umgesetzt: {facts}",
        "education": "Ich habe {qualification} von {institution}.",
        "certification": "Zusätzlich bin ich zertifiziert als {certification}.",
        "closing": "Vielen Dank für die Prüfung meiner Bewerbung. Ich freue mich auf ein Gespräch darüber, wie meine Erfahrung zur Stelle passt.",
        "email_closing": "Meinen Lebenslauf habe ich beigefügt. Ich freue mich über ein kurzes Gespräch zur Stelle. Vielen Dank für Ihre Zeit.",
        "email_role": "Ich wende mich an Sie bezüglich der Stelle als {job} bei {company}.",
        "email_role_no_company": "Ich wende mich an Sie bezüglich der ausgeschriebenen Stelle als {job}.",
        "years": "{n}+ Jahre",
        "subject": "Bewerbung: {job} bei {company} — {name}",
        "subject_no_company": "Bewerbung: {job} — {name}",
        "conjunction": "und",
    },
    "fr": {
        "greeting_named": "Bonjour {name},",
        "applying": "Je candidate au poste de {job} chez {company}.",
        "applying_no_company": "Je candidate au poste de {job}.",
        "profile": "Je suis {title} avec {years} d'expérience professionnelle, spécialisé(e) en {focus}.",
        "profile_no_years": "Je suis {title} avec une expérience pratique de {focus}.",
        "profile_no_focus": "Je suis {title}.",
        "profile_projects": "Je dispose d'une expérience pratique de projet en {focus}.",
        "experience": "Chez {employer} en tant que {title}, mes missions et résultats comprenaient : {facts}",
        "project": "Dans le cadre du projet {name}, j'ai réalisé les éléments suivants : {facts}",
        "education": "Je suis titulaire de {qualification} de {institution}.",
        "certification": "Je suis également certifié(e) {certification}.",
        "closing": "Merci d'avoir examiné ma candidature. Je serais ravi(e) d'échanger sur la manière dont mon expérience correspond au poste.",
        "email_closing": "J'ai joint mon CV et je serais ravi(e) d'un court échange au sujet du poste. Merci de votre temps.",
        "email_role": "Je vous contacte au sujet du poste de {job} chez {company}.",
        "email_role_no_company": "Je vous contacte au sujet du poste de {job}.",
        "years": "{n}+ ans",
        "subject": "Candidature : {job} chez {company} — {name}",
        "subject_no_company": "Candidature : {job} — {name}",
        "conjunction": "et",
    },
    "es": {
        "greeting_named": "Hola {name},",
        "applying": "Me postulo al puesto de {job} en {company}.",
        "applying_no_company": "Me postulo al puesto de {job}.",
        "profile": "Soy {title} con {years} de experiencia profesional, especializado/a en {focus}.",
        "profile_no_years": "Soy {title} con experiencia práctica en {focus}.",
        "profile_no_focus": "Soy {title}.",
        "profile_projects": "Cuento con experiencia práctica en proyectos de {focus}.",
        "experience": "En {employer} como {title}, mis responsabilidades y resultados incluyeron: {facts}",
        "project": "En el proyecto {name}, entregué lo siguiente: {facts}",
        "education": "Poseo {qualification} de {institution}.",
        "certification": "También estoy certificado/a como {certification}.",
        "closing": "Gracias por considerar mi candidatura. Estaré encantado/a de hablar sobre cómo mi experiencia encaja con el puesto.",
        "email_closing": "Adjunto mi CV y agradecería una breve conversación sobre el puesto. Gracias por su tiempo.",
        "email_role": "Le escribo en relación con el puesto de {job} en {company}.",
        "email_role_no_company": "Le escribo en relación con el puesto de {job}.",
        "years": "{n}+ años",
        "subject": "Candidatura: {job} en {company} — {name}",
        "subject_no_company": "Candidatura: {job} — {name}",
        "conjunction": "y",
    },
    "nl": {
        "greeting_named": "Hallo {name},",
        "applying": "Ik solliciteer naar de functie {job} bij {company}.",
        "applying_no_company": "Ik solliciteer naar de functie {job}.",
        "profile": "Ik ben {title} met {years} professionele ervaring, gericht op {focus}.",
        "profile_no_years": "Ik ben {title} met praktische ervaring in {focus}.",
        "profile_no_focus": "Ik ben {title}.",
        "profile_projects": "Ik heb praktische projectervaring in {focus}.",
        "experience": "Bij {employer} als {title} omvatten mijn taken en resultaten: {facts}",
        "project": "In het project {name} heb ik het volgende opgeleverd: {facts}",
        "education": "Ik heb {qualification} van {institution}.",
        "certification": "Daarnaast ben ik gecertificeerd als {certification}.",
        "closing": "Bedankt voor het overwegen van mijn sollicitatie. Ik ga graag in gesprek over hoe mijn ervaring bij de functie past.",
        "email_closing": "Mijn cv is bijgevoegd. Ik ga graag in gesprek over de functie. Bedankt voor uw tijd.",
        "email_role": "Ik neem contact op over de functie {job} bij {company}.",
        "email_role_no_company": "Ik neem contact op over de functie {job}.",
        "years": "{n}+ jaar",
        "subject": "Sollicitatie: {job} bij {company} — {name}",
        "subject_no_company": "Sollicitatie: {job} — {name}",
        "conjunction": "en",
    },
}

GENERIC_GREETINGS = {normalize_text(value) for value in _GREETING_GENERIC.values()}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _language(value: str | None) -> str:
    code = (value or "en").lower()[:2]
    return code if code in PHRASES else "en"


def _phrases(language: str) -> dict[str, str]:
    return PHRASES[_language(language)]


def _active(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    return [item for item in evidence if item.status.value != "rejected"]


def _clean(text: str) -> str:
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text or "")
    return normalize_whitespace(text.replace("\t", " ").replace("\u00a0", " "))


def _sentence(text: str) -> str:
    text = _clean(text).strip(" -•")
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text[0].upper() + text[1:]


def _join(items: list[str], language: str) -> str:
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" {_phrases(language)['conjunction']} " + items[-1]


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


def _years_of_experience(profile: CandidateProfileData) -> int:
    months = 0
    for entry in profile.employment:
        start = _ym(entry.start_date)
        end = None if entry.current else _ym(entry.end_date)
        if start and (end or entry.current):
            end = end or date.today()
            months += max(0, (end.year - start.year) * 12 + (end.month - start.month))
    return round(months / 12)


def _ids_for_path(evidence: list[EvidenceItem], path: str, text: str = "") -> list[str]:
    active = _active(evidence)
    exact = [item.evidence_id for item in active if item.field_path == path]
    if exact:
        return exact
    if text:
        matches = [
            item.evidence_id for item in active
            if normalize_text(text) == normalize_text(item.value)
            or (len(item.value) > 25 and normalize_text(item.value) in normalize_text(text))
            or (len(text) > 25 and normalize_text(text) in normalize_text(item.value))
        ]
        if matches:
            return matches[:3]
    prefix = path.split("[")[0]
    return [item.evidence_id for item in active if item.field_path.startswith(prefix)][:1]


def _signature(profile: CandidateProfileData) -> tuple[str, list[str]]:
    return profile.personal.full_name, list(profile.personal.contact_lines)


def _greeting(language: str, recipient_name: str = "", recipient_title: str = "") -> str:
    phrases = _phrases(language)
    recipient = normalize_whitespace(recipient_name or recipient_title)
    if recipient:
        return phrases["greeting_named"].format(name=recipient)
    return _GREETING_GENERIC[_language(language)]


def _focus_skills(profile: CandidateProfileData, job: JobRecord) -> list[str]:
    """Demonstrated skills only, ranked by how the posting names them."""
    demonstrated = profile.demonstrated_skills()
    targets = [*job.required_skills, *job.preferred_skills]
    matched = [
        skill for skill in demonstrated
        if any(text_contains_skill(skill, target) or text_contains_skill(target, skill)
               for target in targets)
    ]
    return (matched or demonstrated)[:4]


def _allowed_skill_text(profile: CandidateProfileData,
                        evidence: list[EvidenceItem]) -> tuple[str, set[str]]:
    parts: list[str] = list(profile.demonstrated_skills())
    for entry in profile.employment:
        parts.extend(entry.technologies)
    for project in profile.projects:
        parts.extend(project.technologies)
    for item in _active(evidence):
        if item.category in {"skill", "employment", "project"}:
            parts.append(item.value)
    learning = {canonical_skill(skill) for skill in
                [*profile.learning_skills(), *profile.interest_skills()]}
    return "\n".join(part for part in parts if part), learning


def _skill_ids(profile: CandidateProfileData, evidence: list[EvidenceItem],
               skills: list[str]) -> list[str]:
    _, learning = _allowed_skill_text(profile, evidence)
    ids: list[str] = []
    for item in _active(evidence):
        if item.category == "skill" and skill_group_status(item.label) != "demonstrated":
            continue
        if canonical_skill(item.value) in learning:
            continue
        if any(text_contains_skill(item.value, skill) for skill in skills):
            ids.append(item.evidence_id)
    if ids:
        return list(dict.fromkeys(ids))[:4]
    # Fall back to the entry-level evidence that establishes the experience.
    return [item.evidence_id for item in _active(evidence)
            if item.category in {"employment", "project"}][:2]


def _fact_score(text: str, job: JobRecord) -> float:
    score = 0.0
    for skill in job.required_skills:
        if text_contains_skill(text, skill):
            score += 6
    for skill in job.preferred_skills:
        if text_contains_skill(text, skill):
            score += 2.5
    if re.search(r"\d", text):
        score += 1.0
    return score


def _best_experience_facts(profile: CandidateProfileData, evidence: list[EvidenceItem],
                           job: JobRecord) -> tuple[str, str, list[str], list[str]] | None:
    """Return (employer, title, facts, evidence ids) for the most relevant role."""
    best_score = -1.0
    best_index = -1
    for index, entry in enumerate(profile.employment):
        texts = [*entry.responsibilities, *entry.achievements, *entry.quantified_results]
        if not texts:
            continue
        score = max(_fact_score(text, job) for text in texts)
        if score > best_score:
            best_score, best_index = score, index
    if best_index < 0:
        return None

    entry = profile.employment[best_index]
    candidates = [
        (f"employment[{best_index}].responsibilities[{j}]", text)
        for j, text in enumerate(entry.responsibilities)
    ] + [
        (f"employment[{best_index}].achievements[{j}]", text)
        for j, text in enumerate(entry.achievements)
    ] + [
        (f"employment[{best_index}].quantified_results[{j}]", text)
        for j, text in enumerate(entry.quantified_results)
    ]
    ranked = sorted(candidates, key=lambda item: -_fact_score(item[1], job))
    facts: list[str] = []
    ids: list[str] = []
    for path, text in ranked:
        sentence = _sentence(text)
        if not sentence:
            continue
        facts.append(sentence)
        ids.extend(_ids_for_path(evidence, path, text))
        if len(facts) >= 2:
            break
    if not facts:
        return None
    return entry.employer, entry.title, facts, list(dict.fromkeys(ids))[:4]


def _best_project_facts(profile: CandidateProfileData, evidence: list[EvidenceItem],
                        job: JobRecord) -> tuple[str, list[str], list[str]] | None:
    best_score = -1.0
    best_index = -1
    best_candidates: list[tuple[str, str]] = []
    for index, project in enumerate(profile.projects):
        candidates = [
            (f"projects[{index}].description", project.description),
            (f"projects[{index}].implementation", project.implementation),
            (f"projects[{index}].results", project.measurable_results),
        ] + [
            (f"projects[{index}].achievements[{j}]", text)
            for j, text in enumerate(project.verified_achievements)
        ]
        candidates = [(path, text) for path, text in candidates if text]
        if not candidates:
            continue
        score = max(_fact_score(text, job) for _, text in candidates)
        if score > best_score:
            best_score, best_index, best_candidates = score, index, candidates
    if best_index < 0:
        return None

    ranked = sorted(best_candidates, key=lambda item: -_fact_score(item[1], job))[:2]
    facts: list[str] = []
    ids: list[str] = []
    for path, text in ranked:
        sentence = _sentence(text)
        if sentence:
            facts.append(sentence)
            ids.extend(_ids_for_path(evidence, path, text))
    if not facts:
        return None
    name = profile.projects[best_index].name or profile.projects[best_index].role
    return name, facts, list(dict.fromkeys(ids))[:4]


def _intro_sentences(profile: CandidateProfileData, job: JobRecord, skills: list[str],
                     language: str, *, email: bool = False) -> str:
    phrases = _phrases(language)
    title = (profile.personal.professional_title
             or (profile.employment[0].title if profile.employment else ""))
    years = _years_of_experience(profile)
    focus = _join(skills, language)

    if email:
        if job.company:
            sentences = [phrases["email_role"].format(job=job.title, company=job.company)]
        else:
            sentences = [phrases["email_role_no_company"].format(job=job.title)]
    elif job.company:
        sentences = [phrases["applying"].format(job=job.title, company=job.company)]
    else:
        sentences = [phrases["applying_no_company"].format(job=job.title)]

    if title and years > 0 and focus:
        sentences.append(phrases["profile"].format(
            title=title, years=phrases["years"].format(n=years), focus=focus))
    elif title and focus and profile.employment:
        sentences.append(phrases["profile_no_years"].format(title=title, focus=focus))
    elif title and focus and profile.projects:
        sentences.append(phrases["profile_projects"].format(focus=focus))
    elif title:
        sentences.append(phrases["profile_no_focus"].format(title=title))
    return " ".join(sentences)


def _proof_paragraph(profile: CandidateProfileData, evidence: list[EvidenceItem],
                     job: JobRecord, language: str) -> DocumentParagraph | None:
    phrases = _phrases(language)
    best = _best_experience_facts(profile, evidence, job)
    if best is not None:
        employer, title, facts, ids = best
        if employer and title:
            text = phrases["experience"].format(employer=employer, title=title,
                                                facts=" ".join(facts))
        elif employer:
            text = phrases["experience"].format(employer=employer, title=job.title,
                                                facts=" ".join(facts))
        else:
            text = " ".join(facts)
        return DocumentParagraph(text=_clean(text), evidence_ids=ids)

    project = _best_project_facts(profile, evidence, job)
    if project is not None:
        name, facts, ids = project
        text = phrases["project"].format(name=name, facts=" ".join(facts))
        return DocumentParagraph(text=_clean(text), evidence_ids=ids)
    return None


def _education_paragraph(profile: CandidateProfileData, evidence: list[EvidenceItem],
                         language: str) -> DocumentParagraph | None:
    phrases = _phrases(language)
    sentences: list[str] = []
    ids: list[str] = []
    for index, entry in enumerate(profile.education[:1]):
        qualification = " ".join(x for x in (entry.qualification or entry.degree, entry.subject) if x)
        if qualification and entry.institution:
            sentences.append(phrases["education"].format(
                qualification=qualification, institution=entry.institution))
            ids.extend(_ids_for_path(evidence, f"education[{index}]",
                                     f"{entry.institution} — {qualification}"))
    for index, cert in enumerate(profile.additional.certifications[:1]):
        if cert.name:
            sentences.append(phrases["certification"].format(certification=cert.name))
            ids.extend(_ids_for_path(evidence, f"additional.certifications[{index}]", cert.name))
    if not sentences:
        return None
    return DocumentParagraph(text=_clean(" ".join(sentences)),
                             evidence_ids=list(dict.fromkeys(ids))[:4])


# ---------------------------------------------------------------------------
# Deterministic builders
# ---------------------------------------------------------------------------
def build_rule_based_cover_letter(profile: CandidateProfileData,
                                  evidence: list[EvidenceItem], job: JobRecord,
                                  match: MatchResult | None = None, *,
                                  language: str = "en", recipient_name: str = "",
                                  recipient_title: str = "") -> CoverLetterDraft:
    language = _language(language)
    skills = _focus_skills(profile, job)
    intro = _intro_sentences(profile, job, skills, language)
    paragraphs: list[DocumentParagraph] = []

    intro_ids = _skill_ids(profile, evidence, skills)
    if intro_ids:
        paragraphs.append(DocumentParagraph(text=_clean(intro), evidence_ids=intro_ids))
    proof = _proof_paragraph(profile, evidence, job, language)
    if proof is not None:
        paragraphs.append(proof)
    education = _education_paragraph(profile, evidence, language)
    if education is not None:
        paragraphs.append(education)

    signature, contact_lines = _signature(profile)
    return CoverLetterDraft(
        greeting=_greeting(language, recipient_name, recipient_title),
        paragraphs=paragraphs,
        closing=_phrases(language)["closing"],
        signature=signature,
        contact_lines=contact_lines,
        recipient_name=recipient_name.strip(),
        recipient_title=recipient_title.strip(),
        target_job_title=job.title,
        target_company=job.company,
        language=language,
        generator="rule_based",
        generated_at=datetime.now(timezone.utc),
    )


def build_rule_based_email(profile: CandidateProfileData, evidence: list[EvidenceItem],
                           job: JobRecord, match: MatchResult | None = None, *,
                           language: str = "en", recipient_name: str = "",
                           recipient_title: str = "") -> EmailDraft:
    language = _language(language)
    phrases = _phrases(language)
    skills = _focus_skills(profile, job)
    intro = _intro_sentences(profile, job, skills, language, email=True)
    paragraphs: list[DocumentParagraph] = []

    intro_ids = _skill_ids(profile, evidence, skills)
    if intro_ids:
        paragraphs.append(DocumentParagraph(text=_clean(intro), evidence_ids=intro_ids))
    proof = _proof_paragraph(profile, evidence, job, language)
    if proof is not None:
        paragraphs.append(proof)

    signature, contact_lines = _signature(profile)
    name = profile.personal.full_name
    if job.company:
        subject = phrases["subject"].format(job=job.title, company=job.company, name=name)
    else:
        subject = phrases["subject_no_company"].format(job=job.title, name=name)
    return EmailDraft(
        subject=_clean(subject),
        greeting=_greeting(language, recipient_name, recipient_title),
        paragraphs=paragraphs,
        closing=phrases["email_closing"],
        signature=signature,
        contact_lines=contact_lines,
        recipient_name=recipient_name.strip(),
        recipient_title=recipient_title.strip(),
        target_job_title=job.title,
        target_company=job.company,
        language=language,
        generator="rule_based",
        generated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Sanitising
# ---------------------------------------------------------------------------
def _sanitize_paragraphs(paragraphs: list[DocumentParagraph],
                         evidence: list[EvidenceItem]) -> tuple[list[DocumentParagraph], list[str]]:
    valid_ids = {item.evidence_id for item in _active(evidence)}
    kept: list[DocumentParagraph] = []
    removed: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        text = _clean(paragraph.text)
        if not text:
            continue
        ids = [i for i in paragraph.evidence_ids if i in valid_ids]
        if not ids:
            removed.append(text[:200])
            continue
        key = normalize_text(text)
        if key in seen:
            continue
        seen.add(key)
        kept.append(DocumentParagraph(text=text, evidence_ids=list(dict.fromkeys(ids))))
    return kept, removed


def sanitize_cover_letter(draft: CoverLetterDraft,
                          evidence: list[EvidenceItem]) -> tuple[CoverLetterDraft, list[str]]:
    paragraphs, removed = _sanitize_paragraphs(draft.paragraphs, evidence)
    return draft.model_copy(update={"paragraphs": paragraphs}), removed


def sanitize_email(draft: EmailDraft,
                   evidence: list[EvidenceItem]) -> tuple[EmailDraft, list[str]]:
    paragraphs, removed = _sanitize_paragraphs(draft.paragraphs, evidence)
    return draft.model_copy(update={"paragraphs": paragraphs}), removed


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?%?", normalize_text(text)))


def _validate_body(draft: CoverLetterDraft | EmailDraft, profile: CandidateProfileData,
                   evidence: list[EvidenceItem], job: JobRecord, *,
                   kind: str) -> LetterValidation:
    issues: list[ValidationIssue] = []
    active = _active(evidence)
    valid_ids = {item.evidence_id for item in active}
    corpus = "\n".join(f"{item.label}: {item.value} {item.source_text}" for item in active)
    documented_years = _years_of_experience(profile)
    # Employment dates establish the years figure, so that derived number is
    # allowed in addition to numbers that appear verbatim in the ledger.
    allowed_numbers = (_numbers(corpus) | _numbers(job.title) | _numbers(job.company)
                       | {str(documented_years)})
    has_employment = bool(profile.employment)

    paragraphs = draft.paragraphs
    unsupported: list[str] = []
    cited = 0
    body_chunks: list[str] = []
    for paragraph in paragraphs:
        body_chunks.append(paragraph.text)
        ids = [i for i in paragraph.evidence_ids if i in valid_ids]
        if not ids:
            unsupported.append(paragraph.text)
            continue
        cited += 1
        for number in re.findall(r"\d+(?:[.,]\d+)?%?", paragraph.text):
            if number not in allowed_numbers and number.replace(".", ",") not in allowed_numbers:
                unsupported.append(paragraph.text)
                break
    body = " ".join(body_chunks)
    body_norm = normalize_text(body)

    coverage = cited / len(paragraphs) if paragraphs else 0.0
    if unsupported:
        issues.append(ValidationIssue(
            severity="error", code="uncited_claims",
            message=f"{len(unsupported)} paragraph(s) could not be traced to the evidence ledger.",
        ))
    if not paragraphs:
        issues.append(ValidationIssue(
            severity="warning", code="no_body",
            message="No evidence-backed paragraph could be drafted. Add Ground Truth evidence first.",
        ))

    claimed_years = [int(value) for value in
                     re.findall(r"(\d{1,2})\+?\s*(?:years?|jahre|ans|años|jaar)", body_norm)]
    if claimed_years and max(claimed_years) > documented_years + 1:
        issues.append(ValidationIssue(
            severity="error", code="unsupported_experience_claim",
            message=(f"The draft claims {max(claimed_years)} years of experience, but the "
                     f"profile documents {documented_years}."),
        ))
    if not has_employment and re.search(
            r"\b(experienced|extensive experience|proven track record|years of experience)\b",
            body_norm):
        issues.append(ValidationIssue(
            severity="error", code="unsupported_experience_claim",
            message="The draft describes professional experience, but no employment is recorded.",
        ))
    for skill in profile.learning_skills():
        if text_contains_skill(body, skill):
            issues.append(ValidationIssue(
                severity="error", code="unsupported_skill_claim",
                message=f"'{skill}' is presented as a skill even though it is recorded as learning.",
            ))

    # A job requirement may only be claimed when the ledger supports it.
    evidence_supported = evidence_claim_text(evidence)
    for skill in [*job.required_skills, *job.preferred_skills]:
        if text_contains_skill(body, skill) and not text_contains_skill(evidence_supported, skill):
            issues.append(ValidationIssue(
                severity="error", code="unsupported_skill_claim",
                message=f"The draft claims '{skill}', which the evidence ledger does not support.",
            ))

    if not draft.signature:
        issues.append(ValidationIssue(severity="error", code="missing_signature",
                                      message="The draft has no candidate name to sign it."))
    greeting = normalize_text(draft.greeting)
    if not greeting:
        issues.append(ValidationIssue(severity="error", code="missing_greeting",
                                      message="The draft has no greeting."))
    elif not (draft.recipient_name or draft.recipient_title) and greeting not in GENERIC_GREETINGS:
        issues.append(ValidationIssue(
            severity="error", code="invented_recipient",
            message="The greeting addresses a named person the user did not provide.",
        ))
    elif (draft.recipient_name or draft.recipient_title) and normalize_text(
            draft.recipient_name or draft.recipient_title) not in greeting:
        issues.append(ValidationIssue(
            severity="error", code="recipient_mismatch",
            message="The greeting does not use the recipient the user provided.",
        ))

    words = draft.word_count()
    if kind == "cover_letter":
        if words > 450:
            issues.append(ValidationIssue(
                severity="warning", code="length",
                message=f"The letter is {words} words; aim for one page (250-400 words).",
            ))
        elif words < 120:
            issues.append(ValidationIssue(
                severity="warning", code="length",
                message=f"The letter is only {words} words; add relevant evidence if you have it.",
            ))
    else:
        if words > 180:
            issues.append(ValidationIssue(
                severity="warning", code="length",
                message=f"The email body is {words} words; recruiters read about 80-150.",
            ))

    if isinstance(draft, EmailDraft):
        if not draft.subject:
            issues.append(ValidationIssue(severity="error", code="missing_subject",
                                          message="The email has no subject line."))
        else:
            if len(draft.subject) > 100:
                issues.append(ValidationIssue(
                    severity="warning", code="subject_length",
                    message="The subject line is longer than most phone screens show.",
                ))
            if job.title and normalize_text(job.title) not in normalize_text(draft.subject):
                issues.append(ValidationIssue(
                    severity="warning", code="subject_role",
                    message="The subject line does not name the role.",
                ))

    passed = not any(issue.severity == "error" for issue in issues)
    return LetterValidation(
        passed=passed, issues=issues, unsupported_claims=unsupported[:20],
        evidence_coverage=round(coverage, 3), word_count=words,
        checked_at=datetime.now(timezone.utc),
    )


def validate_cover_letter(draft: CoverLetterDraft, profile: CandidateProfileData,
                          evidence: list[EvidenceItem], job: JobRecord) -> LetterValidation:
    return _validate_body(draft, profile, evidence, job, kind="cover_letter")


def validate_email(draft: EmailDraft, profile: CandidateProfileData,
                   evidence: list[EvidenceItem], job: JobRecord) -> LetterValidation:
    return _validate_body(draft, profile, evidence, job, kind="email")


# ---------------------------------------------------------------------------
# LLM generation
# ---------------------------------------------------------------------------
class _LLMParagraph(BaseModel):
    text: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class _LLMLetterBody(BaseModel):  # local response contract; greeting/signature are ours
    paragraphs: list[_LLMParagraph] = Field(default_factory=list)
    notes: str = ""


def _evidence_prompt_lines(evidence: list[EvidenceItem]) -> str:
    lines: list[str] = []
    for item in _active(evidence):
        marker = ""
        if item.category == "skill" and skill_group_status(item.label) != "demonstrated":
            marker = " [NOT DEMONSTRATED — never present as a skill]"
        elif item.category == "interest":
            marker = " [INTEREST — not a qualification]"
        lines.append(f"[{item.evidence_id}] ({item.category}) {item.label}: {item.value}{marker}")
    return "\n".join(lines)


def _requirements_payload(job: JobRecord, match: MatchResult | None) -> str:
    extracted = job_terms(job)
    return json.dumps({
        "required_skills": job.required_skills,
        "preferred_skills": job.preferred_skills,
        "languages": job.languages,
        "education": job.education_requirements,
        "experience": job.experience_requirements,
        "seniority": job.seniority,
        "responsibilities": job.responsibilities[:8],
        "certifications": list(extracted.certifications),
        "matching_skills": match.matching_skills if match else [],
        "missing_skills": match.missing_required_skills if match else [],
    }, ensure_ascii=False)


def _llm_body(prompt_name: str, profile: CandidateProfileData, evidence: list[EvidenceItem],
              job: JobRecord, match: MatchResult | None, language: str) -> list[DocumentParagraph]:
    from services.llm_service import get_llm_service

    service = get_llm_service()
    if not service.available:
        return []
    extracted = job_terms(job)
    try:
        response = service.prompt_json(
            prompt_name, _LLMLetterBody,
            job_json=job.model_dump_json(indent=2)[:16000],
            profile_json=profile.model_dump_json(indent=2)[:24000],
            evidence_list=_evidence_prompt_lines(evidence)[:24000],
            requirements=_requirements_payload(job, match),
            keyword_targets=extracted.prompt_text(),
            output_language=language,
        )
    except Exception as exc:
        logger.warning("LLM %s draft failed, using the deterministic builder: %s", prompt_name, exc)
        return []

    paragraphs: list[DocumentParagraph] = []
    for raw in response.paragraphs[:6]:
        paragraph = DocumentParagraph(
            text=raw.text,
            evidence_ids=[str(i) for i in raw.evidence_ids if str(i).strip()],
        )
        if paragraph.text.strip():
            paragraphs.append(paragraph)
    return paragraphs


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def generate_cover_letter(profile: CandidateProfileData, evidence: list[EvidenceItem],
                          job: JobRecord, match: MatchResult | None = None, *,
                          use_llm: bool = True, language: str = "en",
                          recipient_name: str = "", recipient_title: str = "",
                          ) -> tuple[CoverLetterDraft, LetterValidation]:
    language = _language(language or job.language)
    signature, contact_lines = _signature(profile)
    paragraphs: list[DocumentParagraph] = []
    generator = "rule_based"
    if use_llm:
        paragraphs = _llm_body("cover_letter", profile, evidence, job, match, language)
        generator = "llm" if paragraphs else "rule_based"

    if paragraphs:
        draft = CoverLetterDraft(
            greeting=_greeting(language, recipient_name, recipient_title),
            paragraphs=paragraphs,
            closing=_phrases(language)["closing"],
            signature=signature,
            contact_lines=contact_lines,
            recipient_name=recipient_name.strip(),
            recipient_title=recipient_title.strip(),
            target_job_title=job.title,
            target_company=job.company,
            language=language,
            generator=generator,
            generated_at=datetime.now(timezone.utc),
        )
    else:
        draft = build_rule_based_cover_letter(
            profile, evidence, job, match, language=language,
            recipient_name=recipient_name, recipient_title=recipient_title,
        )

    draft, removed = sanitize_cover_letter(draft, evidence)
    if not draft.paragraphs:
        draft = build_rule_based_cover_letter(
            profile, evidence, job, match, language=language,
            recipient_name=recipient_name, recipient_title=recipient_title,
        )
    report = validate_cover_letter(draft, profile, evidence, job)
    if removed:
        report.issues.append(ValidationIssue(
            severity="warning", code="removed_uncited_content",
            message=f"{len(removed)} paragraph(s) without evidence citations were removed.",
        ))
    if draft.generator == "llm" and not report.passed:
        fallback = build_rule_based_cover_letter(
            profile, evidence, job, match, language=language,
            recipient_name=recipient_name, recipient_title=recipient_title,
        )
        fallback, removed_fallback = sanitize_cover_letter(fallback, evidence)
        fallback_report = validate_cover_letter(fallback, profile, evidence, job)
        if removed_fallback:
            fallback_report.issues.append(ValidationIssue(
                severity="warning", code="removed_uncited_content",
                message=f"{len(removed_fallback)} paragraph(s) without evidence citations were removed.",
            ))
        fallback_report.issues.append(ValidationIssue(
            severity="warning", code="llm_fallback",
            message="The LLM letter failed validation; the deterministic evidence-only letter was used.",
        ))
        return fallback, fallback_report
    return draft, report


def generate_recruiter_email(profile: CandidateProfileData, evidence: list[EvidenceItem],
                             job: JobRecord, match: MatchResult | None = None, *,
                             use_llm: bool = True, language: str = "en",
                             recipient_name: str = "", recipient_title: str = "",
                             ) -> tuple[EmailDraft, LetterValidation]:
    language = _language(language or job.language)
    phrases = _phrases(language)
    signature, contact_lines = _signature(profile)
    name = profile.personal.full_name
    if job.company:
        subject = phrases["subject"].format(job=job.title, company=job.company, name=name)
    else:
        subject = phrases["subject_no_company"].format(job=job.title, name=name)

    paragraphs: list[DocumentParagraph] = []
    generator = "rule_based"
    if use_llm:
        paragraphs = _llm_body("recruiter_email", profile, evidence, job, match, language)
        generator = "llm" if paragraphs else "rule_based"

    if paragraphs:
        draft = EmailDraft(
            subject=_clean(subject),
            greeting=_greeting(language, recipient_name, recipient_title),
            paragraphs=paragraphs,
            closing=phrases["email_closing"],
            signature=signature,
            contact_lines=contact_lines,
            recipient_name=recipient_name.strip(),
            recipient_title=recipient_title.strip(),
            target_job_title=job.title,
            target_company=job.company,
            language=language,
            generator=generator,
            generated_at=datetime.now(timezone.utc),
        )
    else:
        draft = build_rule_based_email(
            profile, evidence, job, match, language=language,
            recipient_name=recipient_name, recipient_title=recipient_title,
        )

    draft, removed = sanitize_email(draft, evidence)
    if not draft.paragraphs:
        draft = build_rule_based_email(
            profile, evidence, job, match, language=language,
            recipient_name=recipient_name, recipient_title=recipient_title,
        )
    report = validate_email(draft, profile, evidence, job)
    if removed:
        report.issues.append(ValidationIssue(
            severity="warning", code="removed_uncited_content",
            message=f"{len(removed)} paragraph(s) without evidence citations were removed.",
        ))
    if draft.generator == "llm" and not report.passed:
        fallback = build_rule_based_email(
            profile, evidence, job, match, language=language,
            recipient_name=recipient_name, recipient_title=recipient_title,
        )
        fallback, removed_fallback = sanitize_email(fallback, evidence)
        fallback_report = validate_email(fallback, profile, evidence, job)
        if removed_fallback:
            fallback_report.issues.append(ValidationIssue(
                severity="warning", code="removed_uncited_content",
                message=f"{len(removed_fallback)} paragraph(s) without evidence citations were removed.",
            ))
        fallback_report.issues.append(ValidationIssue(
            severity="warning", code="llm_fallback",
            message="The LLM email failed validation; the deterministic evidence-only email was used.",
        ))
        return fallback, fallback_report
    return draft, report


# ---------------------------------------------------------------------------
# Persistence (latest draft per job; no migration required)
# ---------------------------------------------------------------------------
COVER_LETTER_PREFIX = "cover_letter_draft::"
EMAIL_PREFIX = "recruiter_email_draft::"


def _save(session: Session, key: str, draft: CoverLetterDraft | EmailDraft,
          report: LetterValidation) -> None:
    set_setting(session, key, {
        "draft": json.loads(draft.model_dump_json()),
        "report": json.loads(report.model_dump_json()),
    })


def save_cover_letter(session: Session, job_id: str, draft: CoverLetterDraft,
                      report: LetterValidation) -> None:
    _save(session, f"{COVER_LETTER_PREFIX}{job_id}", draft, report)


def save_recruiter_email(session: Session, job_id: str, draft: EmailDraft,
                         report: LetterValidation) -> None:
    _save(session, f"{EMAIL_PREFIX}{job_id}", draft, report)


def _load(session: Session, key: str):
    payload = get_setting(session, key, None)
    if not isinstance(payload, dict):
        return None
    return payload


def load_cover_letter(session: Session, job_id: str
                      ) -> tuple[CoverLetterDraft, LetterValidation] | None:
    payload = _load(session, f"{COVER_LETTER_PREFIX}{job_id}")
    if not payload:
        return None
    try:
        return (CoverLetterDraft.model_validate(payload.get("draft") or {}),
                LetterValidation.model_validate(payload.get("report") or {}))
    except Exception:
        return None


def load_recruiter_email(session: Session, job_id: str
                         ) -> tuple[EmailDraft, LetterValidation] | None:
    payload = _load(session, f"{EMAIL_PREFIX}{job_id}")
    if not payload:
        return None
    try:
        return (EmailDraft.model_validate(payload.get("draft") or {}),
                LetterValidation.model_validate(payload.get("report") or {}))
    except Exception:
        return None


def cover_letter_filename(draft: CoverLetterDraft, extension: str = "txt") -> str:
    stem = filename_stem("consul", "Cover_Letter", draft.signature or "Candidate",
                         draft.target_company or "", draft.target_job_title or "")
    return f"{stem}.{extension.lstrip('.')}"


def email_filename(draft: EmailDraft, extension: str = "txt") -> str:
    stem = filename_stem("consul", "Email", draft.signature or "Candidate",
                         draft.target_company or "", draft.target_job_title or "")
    return f"{stem}.{extension.lstrip('.')}"
