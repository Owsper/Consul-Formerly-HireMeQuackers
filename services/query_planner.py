"""Multilingual job search planning.

The LLM proposes a structured plan when available; a deterministic rule-based
planner always exists as a fallback so the product remains usable offline.
Plans are validated, deduplicated and capped before execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from core.exceptions import LLMUnavailableError
from core.job_taxonomy import (
    ANY_IT, CATEGORIES, GENERIC_IT_TITLES, all_category_titles, category_label,
    detect_categories, get_category, guess_from_title, load_category_file,
    specialisations_for, title_translations, titles_for,
)
from core.logging_config import get_logger
from core.schemas import CandidateProfileData, PlannedQuery, SearchPlan, SearchPreferences
from core.text import normalize_whitespace, slugify

logger = get_logger("query_planner")

MAX_QUERIES = 40

# Optional deployment-level taxonomy extension (new industries/families).
_TAXONOMY_FILE = Path(__file__).resolve().parents[1] / "config" / "job_categories.json"
try:
    load_category_file(_TAXONOMY_FILE)
except Exception:  # a bad extension file must never stop search planning
    pass

COUNTRY_LANGUAGE = {
    "germany": "de", "deutschland": "de", "austria": "de", "österreich": "de",
    "switzerland": "de", "schweiz": "de",
    "france": "fr", "belgium": "nl", "belgique": "fr",
    "spain": "es", "españa": "es", "netherlands": "nl", "nederland": "nl",
    "italy": "it", "italia": "it", "poland": "pl", "polska": "pl",
    "portugal": "pt", "brazil": "pt", "united kingdom": "en", "uk": "en",
    "ireland": "en", "united states": "en", "usa": "en", "canada": "en",
    "australia": "en", "india": "en", "sweden": "en", "denmark": "en",
    "norway": "en", "finland": "en", "czech republic": "en", "hungary": "en",
}

LANGUAGE_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "nl": "Dutch", "it": "Italian", "pl": "Polish", "pt": "Portuguese",
}

# Local recruitment terminology (not literal translations).
LOCAL_TERMS = {
    "de": {"internship": "Praktikum", "working_student": "Werkstudent",
           "entry": "Berufseinsteiger", "junior": "Junior", "suffix": " (m/w/d)"},
    "fr": {"internship": "Stage", "working_student": "Alternance",
           "entry": "Débutant", "junior": "junior", "suffix": " (H/F)"},
    "es": {"internship": "Prácticas", "working_student": "Becario",
           "entry": "Recién graduado", "junior": "junior", "suffix": ""},
    "nl": {"internship": "Stage", "working_student": "Stagiair",
           "entry": "Junior", "junior": "Junior", "suffix": ""},
    "it": {"internship": "Tirocinio", "working_student": "Studente lavoratore",
           "entry": "Neolaureato", "junior": "junior", "suffix": ""},
    "pl": {"internship": "Praktyki", "working_student": "Student",
           "entry": "Junior", "junior": "Junior", "suffix": ""},
    "pt": {"internship": "Estágio", "working_student": "Estudante trabalhador",
           "entry": "Júnior", "junior": "júnior", "suffix": ""},
    "en": {"internship": "Internship", "working_student": "Working Student",
           "entry": "Entry Level", "junior": "Junior", "suffix": ""},
}

ROLE_TRANSLATIONS = {
    "software engineer": {
        "de": "Softwareentwickler", "fr": "ingénieur logiciel", "es": "ingeniero de software",
        "nl": "software engineer", "it": "ingegnere del software",
        "pl": "inżynier oprogramowania", "pt": "engenheiro de software", "en": "Software Engineer",
    },
    "software developer": {
        "de": "Softwareentwickler", "fr": "développeur logiciel", "es": "desarrollador de software",
        "nl": "softwareontwikkelaar", "it": "sviluppatore software",
        "pl": "programista", "pt": "desenvolvedor de software", "en": "Software Developer",
    },
    "python developer": {
        "de": "Python-Entwickler", "fr": "développeur Python", "es": "desarrollador Python",
        "nl": "Python developer", "it": "sviluppatore Python",
        "pl": "programista Python", "pt": "desenvolvedor Python", "en": "Python Developer",
    },
    "backend developer": {
        "de": "Backend-Entwickler", "fr": "développeur backend", "es": "desarrollador backend",
        "nl": "backend developer", "it": "sviluppatore backend",
        "pl": "programista backend", "pt": "desenvolvedor backend", "en": "Backend Developer",
    },
    "frontend developer": {
        "de": "Frontend-Entwickler", "fr": "développeur frontend", "es": "desarrollador frontend",
        "nl": "frontend developer", "it": "sviluppatore frontend",
        "pl": "programista frontend", "pt": "desenvolvedor frontend", "en": "Frontend Developer",
    },
    "full stack developer": {
        "de": "Full-Stack-Entwickler", "fr": "développeur full stack", "es": "desarrollador full stack",
        "nl": "full stack developer", "it": "sviluppatore full stack",
        "pl": "programista full stack", "pt": "desenvolvedor full stack", "en": "Full Stack Developer",
    },
    "data engineer": {
        "de": "Data Engineer", "fr": "ingénieur données", "es": "ingeniero de datos",
        "nl": "data engineer", "it": "data engineer", "pl": "inżynier danych",
        "pt": "engenheiro de dados", "en": "Data Engineer",
    },
    "data analyst": {
        "de": "Datenanalyst", "fr": "analyste données", "es": "analista de datos",
        "nl": "data-analist", "it": "analista dati", "pl": "analityk danych",
        "pt": "analista de dados", "en": "Data Analyst",
    },
    "machine learning engineer": {
        "de": "Machine Learning Engineer", "fr": "ingénieur machine learning",
        "es": "ingeniero de machine learning", "nl": "machine learning engineer",
        "it": "machine learning engineer", "pl": "inżynier uczenia maszynowego",
        "pt": "engenheiro de machine learning", "en": "Machine Learning Engineer",
    },
    "ai engineer": {
        "de": "KI-Entwickler", "fr": "ingénieur IA", "es": "ingeniero de IA",
        "nl": "AI engineer", "it": "ingegnere IA", "pl": "inżynier AI",
        "pt": "engenheiro de IA", "en": "AI Engineer",
    },
    "devops engineer": {
        "de": "DevOps Engineer", "fr": "ingénieur DevOps", "es": "ingeniero DevOps",
        "nl": "DevOps engineer", "it": "DevOps engineer", "pl": "inżynier DevOps",
        "pt": "engenheiro DevOps", "en": "DevOps Engineer",
    },
}

ATS_SITES = ["boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com",
             "jobs.smartrecruiters.com", "apply.workable.com"]


class SearchPlanResponse(BaseModel):
    model_config = {"extra": "allow"}
    candidate_summary: str = ""
    role_families: list[str] = Field(default_factory=list)
    english_titles: list[str] = Field(default_factory=list)
    local_titles: dict[str, list[str]] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    queries: list[PlannedQuery] = Field(default_factory=list)


def languages_for_countries(countries: list[str], explicit: list[str] | None = None) -> list[str]:
    langs: list[str] = []
    for name in explicit or []:
        key = normalize_whitespace(name).lower()
        for code, label in LANGUAGE_NAMES.items():
            if key == code or key == label.lower():
                langs.append(code)
    for country in countries or []:
        code = COUNTRY_LANGUAGE.get(normalize_whitespace(country).lower())
        if code:
            langs.append(code)
    langs.append("en")
    seen, ordered = set(), []
    for code in langs:
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return ordered


def _dedupe_queries(queries: list[PlannedQuery]) -> list[PlannedQuery]:
    seen: set[str] = set()
    result: list[PlannedQuery] = []
    # Stable sort preserves planner order within each priority, so explicit
    # custom titles stay ahead of generic category sweeps.
    for query in sorted(queries, key=lambda q: q.priority):
        text = normalize_whitespace(query.query)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        query.query = text
        query.priority = max(1, min(5, int(query.priority or 3)))
        result.append(query)
    return result[:MAX_QUERIES]


def _selected_category(profile: CandidateProfileData, prefs: SearchPreferences) -> str | None:
    """Resolve the category without restricting an explicit custom title."""
    # An explicit title defines the discipline; it must never inherit an
    # unrelated category from the candidate's existing skills.
    for title in prefs.target_titles:
        guessed = guess_from_title(title)
        if guessed:
            return guessed
    if prefs.target_titles:
        detected = detect_categories(
            " ".join([prefs.specialisation, *prefs.target_titles]), [], limit=1)
        if detected:
            return detected[0]
    if prefs.it_category and prefs.it_category != ANY_IT:
        return prefs.it_category if get_category(prefs.it_category) else None
    probe = " ".join([prefs.specialisation, profile.personal.professional_title])
    detected = detect_categories(probe, profile.all_skills(), limit=1)
    if detected:
        return detected[0]
    return guess_from_title(profile.personal.professional_title) or None


def _guess_role_family(profile: CandidateProfileData, prefs: SearchPreferences) -> list[str]:
    """Build role families from profile choices first, taxonomy second.

    Explicit target titles always outrank category seeds, so a user who enters a
    custom title is never forced into a predefined category. When no title is
    supplied, the category (or the best-matching category for an "Any IT"
    profile) supplies employer-realistic alternatives.
    """
    explicit = [normalize_whitespace(t) for t in prefs.target_titles if t]
    alternatives = [normalize_whitespace(t) for t in prefs.alternative_titles if t]
    category_key = _selected_category(profile, prefs)
    candidates: list[str] = list(explicit)

    if prefs.specialisation and category_key:
        candidates += titles_for(category_key, prefs.specialisation, limit=3)

    # Declared interests broaden discovery (for example embedded systems next to
    # a backend title). They only generate searches; scoring still requires
    # demonstrated evidence, so an interest never becomes a qualification.
    # Extraction may record an interest in `additional.professional_interests`
    # or in a skill group marked as an interest; both are equally valid.
    interest_values = [*(profile.additional.professional_interests or []),
                       *profile.interest_skills()]
    interests = list(dict.fromkeys(normalize_whitespace(i) for i in interest_values if i))
    if prefs.it_category == ANY_IT and interests:
        for interest_key in detect_categories(" ".join(interests), [], limit=2):
            candidates += titles_for(interest_key, limit=2)

    if category_key:
        candidates += titles_for(category_key, limit=4)

    if not explicit:
        if not category_key:
            detected = detect_categories(
                " ".join([prefs.specialisation, profile.personal.professional_title]),
                profile.all_skills(), limit=2,
            )
            for key in detected:
                candidates += titles_for(key, prefs.specialisation, limit=2)
        if profile.personal.professional_title and category_key is None:
            candidates.append(profile.personal.professional_title)
        if not candidates and prefs.it_category == ANY_IT:
            candidates += all_category_titles(limit_per_category=1, limit=4)
        if not candidates:
            candidates += GENERIC_IT_TITLES[:2]

    # If the user gave only a custom title, infer adjacent titles from that title.
    if explicit and not category_key:
        guessed = guess_from_title(explicit[0])
        if guessed:
            candidates += titles_for(guessed, limit=2)

    candidates += alternatives
    seen, families = set(), []
    for candidate in candidates:
        cleaned = normalize_whitespace(candidate)
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            families.append(cleaned)
    return families[:6]


EARLY_CAREER_MARKERS = (
    "intern", "internship", "junior", "graduate", "working student", "student",
    "trainee", "werkstudent", "praktikum", "praktikant", "stage", "alternance",
    "prácticas", "practicas", "becario", "stagiair", "entry level",
)


def _has_early_marker(title: str) -> bool:
    lowered = normalize_whitespace(title).lower()
    return any(marker in lowered for marker in EARLY_CAREER_MARKERS)


def _english_titles(role_families: list[str], prefs: SearchPreferences) -> list[str]:
    titles: list[str] = []
    seniority = (prefs.seniority or "").lower()
    early = seniority in {"internship", "working_student", "graduate", "junior", "entry"}
    for role in role_families:
        titles.append(role)
        if early and not role.lower().startswith(("junior", "graduate", "working student", "intern")) \
                and not _has_early_marker(role):
            titles.append(f"Junior {role}")
    titles += [t for t in prefs.alternative_titles if t]
    employment = {e.lower() for e in prefs.employment_types}
    # Never stack a second early-career marker on a title that already has one
    # ("Backend Engineering Intern Intern").
    if ("working_student" in employment or seniority == "working_student"):
        for role in role_families[:2]:
            if not _has_early_marker(role):
                titles.append(f"Working Student {role}")
    if "internship" in employment or seniority == "internship":
        for role in role_families[:2]:
            if _has_early_marker(role):
                continue
            titles.append(f"{role} Intern")
            titles.append(f"Internship {role}")
    if "graduate" in employment or seniority == "graduate":
        for role in role_families[:2]:
            if not _has_early_marker(role):
                titles.append(f"Graduate {role}")
    seen, out = set(), []
    for title in titles:
        key = normalize_whitespace(title).lower()
        if key not in seen:
            seen.add(key)
            out.append(normalize_whitespace(title))
    return out[:12]


def _local_titles(role_families: list[str], languages: list[str],
                  prefs: SearchPreferences) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    employment = {e.lower() for e in prefs.employment_types}
    selected = prefs.it_category if prefs.it_category != ANY_IT else ""
    for lang in languages:
        if lang == "en":
            continue
        terms = LOCAL_TERMS.get(lang, LOCAL_TERMS["en"])
        titles: list[str] = []
        for role in role_families:
            translated = ROLE_TRANSLATIONS.get(role.lower(), {}).get(lang)
            category_key = selected or guess_from_title(role)
            if not translated:
                translated = next(iter(title_translations(category_key, lang)), "")
            translated = translated or role
            titles.append(f"{translated}{terms['suffix']}")
            if _has_early_marker(translated) or _has_early_marker(role):
                continue
            if prefs.seniority in {"junior", "entry"} or "graduate" in employment:
                titles.append(f"{terms['junior']} {translated}".strip())
            if "working_student" in employment or prefs.seniority == "working_student":
                titles.append(f"{terms['working_student']} {translated}")
            if "internship" in employment or prefs.seniority == "internship":
                titles.append(f"{terms['internship']} {translated}")
            if "entry" in employment or "graduate" in employment or prefs.seniority == "graduate":
                titles.append(f"{terms['entry']} {translated}")
        seen, ordered = set(), []
        for title in titles:
            key = normalize_whitespace(title).lower()
            if key and key not in seen:
                seen.add(key)
                ordered.append(normalize_whitespace(title))
        result[lang] = ordered[:10]
    return result


def _locations(prefs: SearchPreferences) -> list[str]:
    places = [normalize_whitespace(c) for c in (prefs.cities or []) if c]
    if not places:
        places = [normalize_whitespace(c) for c in (prefs.countries or []) if c]
    if not places and prefs.work_modes and "remote" in [w.lower() for w in prefs.work_modes]:
        places = ["Remote"]
    return places[:4] or [""]


def build_rule_based_plan(profile: CandidateProfileData, prefs: SearchPreferences,
                          *, reason: str = "") -> SearchPlan:
    """Deterministic plan used when the LLM is unavailable or fails."""
    languages = languages_for_countries(prefs.countries, prefs.languages)
    role_families = _guess_role_family(profile, prefs)
    titles = _english_titles(role_families, prefs)
    local = _local_titles(role_families, languages, prefs)
    category_key = _selected_category(profile, prefs)
    category = get_category(category_key)
    requested = [*prefs.required_skills, *prefs.preferred_skills, *prefs.technologies]
    keywords = list(dict.fromkeys(
        normalize_whitespace(s) for s in [*requested, *profile.all_skills()] if normalize_whitespace(s)
    ))
    if not keywords and category:
        keywords = list(category.core_skills)
    keywords = keywords[:15]
    locations = _locations(prefs)

    # Seniority words are deliberately not excluded here: they are assessed by the
    # scoring engine, and filtering them would hide roles the candidate may want.
    exclude = ["10+ years", "Ausbildung", "Duales Studium", "Commission only"]
    for company in prefs.exclude_companies:
        if company:
            exclude.append(company)

    queries: list[PlannedQuery] = []
    broad_any = prefs.it_category == ANY_IT and not prefs.target_titles

    for title in titles[:(4 if broad_any else 6)]:
        for location in locations:
            suffix = f" {location}" if location else ""
            queries.append(PlannedQuery(
                query=f'"{title}"{suffix}', language="en", target="any",
                priority=1 if title in prefs.target_titles else 2,
                rationale=f'Broader market search for "{title}" roles.',
            ))
        for site in ATS_SITES[:(2 if broad_any else 4)]:
            queries.append(PlannedQuery(
                query=f'site:{site} "{title}"', language="en", target="search", priority=1,
                rationale=f"Find official ATS postings for {title} on {site}.",
            ))
        queries.append(PlannedQuery(
            query=f"{title} {' '.join(keywords[:3])}".strip(), language="en", target="ats",
            priority=3, rationale="ATS keyword search across connected boards.",
        ))
        if keywords:
            queries.append(PlannedQuery(
                query=f'"{title}" "{keywords[0]}"', language="en", target="search", priority=2,
                rationale=f"Skill-driven discovery for {title} using verified candidate skills.",
            ))

    if broad_any:
        # Any IT means every registered discipline gets a query, not just the one
        # detected from the candidate's current title.
        for category in CATEGORIES.values():
            if not category.titles:
                continue
            queries.append(PlannedQuery(
                query=f'"{category.titles[0]}" {locations[0]}'.strip(), language="en",
                target="search", priority=2,
                rationale=f"Any-IT coverage for {category.label}.",
            ))
        queries.append(PlannedQuery(
            query='"IT Specialist" OR "Technology Graduate"', language="en", target="search",
            priority=4, rationale="Broad Any-IT sweep so no technology discipline is excluded.",
        ))

    for lang, lang_titles in local.items():
        for title in lang_titles[:4]:
            location = locations[0] if locations else ""
            queries.append(PlannedQuery(
                query=f'"{title}" {location}'.strip(), language=lang, target="any", priority=2,
                rationale=f"Local {LANGUAGE_NAMES.get(lang, lang)} recruitment terminology.",
            ))
        if lang_titles:
            queries.append(PlannedQuery(
                query=f'{lang_titles[0]} Deutschland' if lang == "de" else f'{lang_titles[0]} {locations[0]}'.strip(),
                language=lang, target="search", priority=3,
                rationale="Local-language web discovery query.",
            ))

    summary = (
        f"{profile.personal.full_name or 'Candidate'} — "
        f"{profile.personal.professional_title or (role_families[0] if role_families else 'professional')}. "
        f"Rule-based plan for {category_label(category_key) if category_key else category_label(ANY_IT)}"
        f"{(' / ' + prefs.specialisation) if prefs.specialisation else ''}, targeting "
        f"{len(role_families)} role families across {', '.join(prefs.countries) or 'remote'}."
    )
    plan = SearchPlan(
        candidate_summary=summary,
        it_category=category_key or prefs.it_category or ANY_IT,
        specialisation=prefs.specialisation,
        role_families=role_families,
        english_titles=titles,
        local_titles=local,
        keywords=keywords,
        exclude_terms=exclude,
        queries=_dedupe_queries(queries),
        generated_at=datetime.now(timezone.utc),
        source="rule_based",
        warnings=[reason] if reason else [],
    )
    logger.info("Rule-based search plan: %s queries, %s languages", len(plan.queries), len(local) + 1)
    return plan


def plan_search(profile: CandidateProfileData, prefs: SearchPreferences, llm=None) -> SearchPlan:
    """Generate a validated search plan, degrading gracefully without an LLM."""
    from services.llm_service import get_llm_service

    service = llm or get_llm_service()
    languages = languages_for_countries(prefs.countries, prefs.languages)
    language_labels = [f"{code} ({LANGUAGE_NAMES[code]})" for code in languages]

    if not service.available:
        return build_rule_based_plan(
            profile, prefs,
            reason="No LLM configured — queries were generated with the built-in multilingual planner.",
        )

    category_key = _selected_category(profile, prefs)
    category = get_category(category_key)
    selected_title_hints = titles_for(category_key, prefs.specialisation, limit=10) if category else []
    category_context = {
        "category_key": category_key or ANY_IT,
        "category_label": category_label(category_key),
        "specialisation": prefs.specialisation,
        "specialisations": specialisations_for(category_key),
        "suggested_titles": selected_title_hints,
        "explicit_target_titles": prefs.target_titles,
        "must_respect_custom_titles": bool(prefs.target_titles),
        "verified_candidate_skills": profile.all_skills(),
        "requested_skills": [*prefs.required_skills, *prefs.preferred_skills,
                             *prefs.technologies],
    }
    try:
        response = service.prompt_json(
            "search_planning",
            SearchPlanResponse,
            profile_json=profile.model_dump_json(indent=2),
            preferences_json=prefs.model_dump_json(indent=2),
            languages=", ".join(language_labels),
            category_context=category_context,
            taxonomy_categories=[
                {"key": c.key, "label": c.label, "titles": list(c.titles[:6]),
                 "specialisations": list(c.specialisations)}
                for c in CATEGORIES.values()
            ],
            task="planning",
        )
    except LLMUnavailableError as exc:
        return build_rule_based_plan(profile, prefs, reason=f"LLM unavailable: {exc}")
    except Exception as exc:  # invalid output, quota, timeout
        logger.warning("LLM search planning failed: %s", exc)
        return build_rule_based_plan(profile, prefs, reason=f"AI planning failed ({exc}); used the rule-based planner.")

    queries = _dedupe_queries(response.queries)
    if not queries:
        return build_rule_based_plan(profile, prefs, reason="AI returned no usable queries; fallback used.")
    if not response.english_titles:
        response.english_titles = _english_titles(
            response.role_families or _guess_role_family(profile, prefs), prefs)
    if prefs.target_titles:
        # A custom title is a hard requirement, not a suggestion.
        response.english_titles = list(dict.fromkeys(
            [*prefs.target_titles, *response.english_titles]))[:15]

    plan = SearchPlan(
        candidate_summary=response.candidate_summary,
        it_category=category_key or prefs.it_category or ANY_IT,
        specialisation=prefs.specialisation,
        role_families=response.role_families,
        english_titles=response.english_titles,
        local_titles=response.local_titles,
        keywords=response.keywords,
        exclude_terms=response.exclude_terms,
        queries=queries,
        generated_at=datetime.now(timezone.utc),
        source="llm",
    )
    logger.info("AI search plan: %s queries across %s languages", len(queries), len(plan.local_titles) + 1)
    return plan


def plan_to_query_rows(plan: SearchPlan) -> list[dict]:
    return [
        {"query": q.query, "language": q.language, "target": q.target, "priority": q.priority}
        for q in plan.queries
    ]


def plan_fingerprint(plan: SearchPlan) -> str:
    return slugify("|".join(q.query for q in plan.queries))[:60]
