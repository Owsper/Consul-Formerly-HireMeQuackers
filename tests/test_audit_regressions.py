"""Regression tests for defects found during the end-to-end CONSUL audit.

Each test reproduces a specific failure that was observed against the running
services before the fix, so the behaviour cannot silently regress.
"""

from __future__ import annotations

import pytest

from core.exceptions import UnsafeURLError
from core.job_taxonomy import guess_from_title
from core.schemas import (
    JobRecord, SearchPreferences, SkillCategory, WorkMode,
)
from core.security import validate_url
from services.cv_tailoring import build_rule_based_cv
from services.job_enrichment import _section_lines, enrich_job, extract_skills
from services.job_scoring import score_record
from services.profile_service import synthesize_evidence
from services.query_planner import build_rule_based_plan


EMBEDDED_DESCRIPTION = (
    "Requirements:\n- C\n- C++\n- RTOS\n- Microcontroller\n- Firmware development\n"
    "Nice to have:\n- Embedded Linux"
)


def test_uppercase_requirement_bullets_do_not_end_the_section():
    requirement_lines, _ = _section_lines(EMBEDDED_DESCRIPTION)
    # All four requirement bullets are retained; "RTOS" and "C" used to reset
    # the section because they are uppercase.
    assert requirement_lines[:4] == ["- C", "- C++", "- RTOS", "- Microcontroller"]


def test_embedded_requirements_are_extracted_and_nice_to_haves_split():
    job = enrich_job(JobRecord(source="manual", title="Embedded Software Engineering Intern",
                              description=EMBEDDED_DESCRIPTION))
    assert {"C", "C++", "RTOS", "Firmware"}.issubset(set(job.required_skills))
    assert "Embedded Systems" in job.required_skills or "Embedded Systems" in job.preferred_skills
    assert "Linux" in job.preferred_skills


def test_short_skill_aliases_use_token_boundaries():
    required, preferred = extract_skills("We use Google Cloud and a great team.", "")
    assert "GCP" in [*required, *preferred]
    assert "Go" not in [*required, *preferred]
    required, preferred = extract_skills("Build and maintain accessible HTML.", "")
    assert "Machine Learning" not in [*required, *preferred]


def test_generic_specialisation_words_do_not_match_every_category():
    from core.job_taxonomy import detect_categories

    detected = detect_categories("Embedded systems Firmware development", [], limit=3)
    assert "embedded_iot" in detected
    assert "database_admin" not in detected


def test_target_title_maps_to_the_right_discipline():
    assert guess_from_title("Backend Engineering Intern") == "software_engineering"
    assert guess_from_title("Embedded Software Engineering Intern") == "embedded_iot"
    assert guess_from_title("Platform Engineering Intern") == "cloud_devops"
    assert guess_from_title("Game Developer") == "game_development"


def test_backend_plan_does_not_seed_game_development_or_duplicate_intern(
        profile_data):
    prefs = SearchPreferences(
        target_titles=["Backend Engineering Intern"], countries=["Germany"],
        employment_types=["internship"], seniority="internship",
    )
    plan = build_rule_based_plan(profile_data, prefs)
    assert plan.role_families[0] == "Backend Engineering Intern"
    assert all("game" not in title.lower() for title in plan.english_titles)
    assert not any(title.lower().count("intern") > 1 for title in plan.english_titles)
    assert any("backend" in title.lower() for title in plan.english_titles)


def test_declared_interest_broadens_the_rule_based_plan(profile_data):
    profile = profile_data.model_copy(deep=True)
    profile.additional.professional_interests = ["Embedded systems", "Firmware development"]
    prefs = SearchPreferences(
        target_titles=["Backend Engineering Intern"], it_category="any_it",
        countries=["Germany"], employment_types=["internship"], seniority="internship",
    )
    plan = build_rule_based_plan(profile, prefs)
    titles = [title.lower() for title in plan.english_titles]
    assert plan.role_families[0] == "Backend Engineering Intern"
    assert any("embedded" in title or "firmware" in title for title in titles)


def test_interest_skill_group_broadens_the_plan(profile_data):
    profile = profile_data.model_copy(deep=True)
    profile.skills.append(SkillCategory(name="Interests", proficiency="interest",
                                        skills=["Embedded systems"]))
    prefs = SearchPreferences(target_titles=["Backend Engineer"], it_category="any_it",
                              countries=["Germany"])
    plan = build_rule_based_plan(profile, prefs)
    assert any("embedded" in title.lower() for title in plan.english_titles)


def test_learning_skills_are_not_scored_or_claimed(profile_data, evidence):
    profile = profile_data.model_copy(deep=True)
    profile.skills.append(SkillCategory(name="Currently learning", skills=["C", "C++"]))
    job = JobRecord(
        source="manual", title="Embedded Software Engineering Intern",
        company="SAP SE", location="Walldorf, Germany", country="Germany",
        employment_type="internship", seniority="internship", work_mode=WorkMode.ONSITE,
        required_skills=["C", "C++", "RTOS", "Firmware"],
    )
    match = score_record(job, profile, evidence, SearchPreferences(countries=["Germany"]))

    assert "C++" in profile.learning_skills()
    assert "C++" not in profile.demonstrated_skills()
    assert "C++" in match.learning_skills
    assert "C++" not in match.matching_skills
    technical = next(d for d in match.dimensions if d.name == "technical_skills")
    assert technical.score < 100
    assert "currently learning" in technical.rationale.lower()

    cv = build_rule_based_cv(profile, evidence, job, match)
    assert "C++" not in cv.summary
    from services.cv_tailoring import sanitize_cv

    cv, _ = sanitize_cv(cv, profile, evidence)
    labels = [row.label for section in cv.sections if section.kind == "skills"
              for row in section.rows]
    assert "Currently learning" not in labels
    assert "C++" not in [skill for section in cv.sections for skill in section.skills]


def test_summary_cannot_claim_experience_without_employment(profile_data, evidence, job_record):
    from core.schemas import CVHeader, CVSection, TailoredCV
    from services.cv_tailoring import validate_cv

    profile = profile_data.model_copy(deep=True)
    profile.employment = []
    cv = TailoredCV(
        header=CVHeader(name="Ada Lovelace"),
        summary="Experienced backend engineer with a proven track record.",
        sections=[CVSection(heading="Technical Skills", kind="skills", skills=["Python"])],
    )
    report = validate_cv(cv, profile, evidence, job_record)
    assert report.passed is False
    assert any(issue.code == "unsupported_experience_claim" for issue in report.issues)


def test_summary_cannot_inflate_years(profile_data, evidence, job_record):
    from core.schemas import CVHeader, CVSection, TailoredCV
    from services.cv_tailoring import validate_cv

    cv = TailoredCV(
        header=CVHeader(name="Ada Lovelace"),
        summary="Backend engineer with 12 years of professional experience.",
        sections=[CVSection(heading="Technical Skills", kind="skills", skills=["Python"])],
    )
    report = validate_cv(cv, profile_data, evidence, job_record)
    assert any(issue.code == "unsupported_experience_claim" for issue in report.issues)


def test_uncited_skills_and_empty_drafts_fail_validation(profile_data, evidence, job_record):
    from core.schemas import CVHeader, CVSection, TailoredCV
    from services.cv_tailoring import sanitize_cv, validate_cv

    draft = TailoredCV(
        header=CVHeader(name="Ada Lovelace"),
        summary="A summary with no evidence-cited bullets.",
        sections=[CVSection(heading="Technical Skills", kind="skills",
                            skills=["Python", "English", "Rust"])],
    )
    clean, removed = sanitize_cv(draft, profile_data, evidence)
    skills = [skill for section in clean.sections for skill in section.skills]
    assert "Python" in skills
    assert "English" not in skills
    assert "Rust" not in skills
    assert any("English" in item for item in removed)

    report = validate_cv(clean, profile_data, evidence, job_record)
    assert report.passed is False
    assert any(issue.code == "no_evidence_bullets" for issue in report.issues)


def test_explicit_group_proficiency_is_honoured_in_evidence(profile_data):
    profile = profile_data.model_copy(deep=True)
    profile.skills.append(SkillCategory(name="Systems Programming", proficiency="learning",
                                        skills=["Rust"]))
    evidence = synthesize_evidence(profile)
    learning_row = next(item for item in evidence
                        if item.category == "skill" and "Rust" in item.value)
    assert "learning" in learning_row.label.lower()
    assert "Rust" not in profile.demonstrated_skills()


def test_ats_coverage_does_not_count_learning_skills(profile_data):
    from core.ats_rules import build_ats_report

    profile = profile_data.model_copy(deep=True)
    profile.skills.append(SkillCategory(name="Currently learning", skills=["C++"]))
    evidence = synthesize_evidence(profile)
    job = JobRecord(source="manual", title="Embedded Intern",
                    required_skills=["C++"], description=EMBEDDED_DESCRIPTION)
    cv = build_rule_based_cv(profile, evidence, job)
    report = build_ats_report(cv, profile, evidence, job)
    coverage = report["keyword_coverage"]["must_have"]
    assert coverage["available"] == 0
    assert "C++" in coverage["unevidenced"]


@pytest.mark.parametrize("url", [
    "http://127.1/",
    "http://2130706433/",
    "http://0x7f000001/",
    "http://0177.0.0.1/",
    "http://10.1/",
    "http://169.254.169.254/latest/meta-data/",
])
def test_obfuscated_private_ipv4_is_blocked(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url, resolve_dns=False)


def test_public_hosts_are_still_allowed():
    assert validate_url("https://jobs.sap.com/search/?q=intern", resolve_dns=False)


def test_http_403_reports_restricted_not_unavailable():
    from connectors.base import BaseConnector, RequestStats
    from core.schemas import SourceHealth

    stats = RequestStats(made=1, failed=1, restricted=True,
                         error="HTTP 403 (restricted)")
    result = BaseConnector().finish(BaseConnector().new_result(), 0.0, stats, [], 0)
    assert result.status == SourceHealth.RESTRICTED
    assert "403" in result.error


def test_a_successful_scan_is_not_downgraded_by_a_blocked_listing():
    from connectors.base import BaseConnector, RequestStats
    from core.schemas import JobRecord, SourceHealth

    stats = RequestStats(made=2, ok=1, failed=1, restricted=True, error="HTTP 403")
    job = JobRecord(source="base", title="Backend Engineer")
    result = BaseConnector().finish(BaseConnector().new_result(), 0.0, stats, [job], 1)
    assert result.status == SourceHealth.HEALTHY


# --- German-market internship search (non-EU student) -----------------------

@pytest.mark.parametrize("text,expected", [
    ("Wir bieten kein Visa-Sponsoring.", False),
    ("Keine Visumsunterstützung möglich.", False),
    ("Ohne Visa-Sponsoring.", False),
    ("We offer visa sponsorship.", True),
])
def test_german_sponsorship_negations_are_not_silently_ignored(text, expected):
    from services.job_enrichment import extract_sponsorship

    assert extract_sponsorship(text) is expected


@pytest.mark.parametrize("text,language", [
    ("Sehr gute Deutschkenntnisse erforderlich", "German (b2)"),
    ("Gute Deutschkenntnisse", "German (b1)"),
    ("Deutschkenntnisse auf B2-Niveau", "German (b2)"),
    ("Verhandlungssicheres Englisch", "English (c1)"),
])
def test_german_language_requirements_keep_their_level(text, language):
    from services.job_enrichment import extract_languages

    assert language in extract_languages(text)


def test_place_names_are_not_language_requirements():
    from services.job_enrichment import extract_languages

    assert "German" not in extract_languages("Location: Berlin, Germany.")
    assert "German" not in extract_languages(
        "#Workingstudent #Werkstudent #Germany #Deutschland #SAPGermanStudentsCareers"
    )
    assert any(e.startswith("English") for e in extract_languages(
        "(Very) good English language skills"))


def test_iso_country_code_still_counts_as_the_candidates_country():
    from core.schemas import CandidateProfileData, EligiblityStatus, JobRecord, SearchPreferences
    from services.job_scoring import score_record

    job = JobRecord(source="sap", title="Working Student (w/m/d) - SAP HANA Cloud Infrastructure",
                    company="SAP", country="DE", location="Berlin, DE; Berlin, Germany",
                    employment_type="working_student", description="Python, Docker, Kubernetes")
    profile = CandidateProfileData.model_validate({
        "work_authorization": {"residence_country": "Germany", "authorized_to_work": True},
    })
    prefs = SearchPreferences(countries=["Germany"], employment_types=["working_student"])
    match = score_record(job, profile, [], prefs)
    assert match.eligibility.status is not EligiblityStatus.UNCLEAR
    assert not any("Cross-border" in concern for concern in match.eligibility.concerns)


def test_very_good_german_is_not_satisfied_by_b1():
    from core.schemas import CandidateProfileData, JobRecord, SearchPreferences
    from services.job_enrichment import enrich_job
    from services.job_scoring import score_record

    job = enrich_job(JobRecord(source="manual", title="Praktikum Softwareentwicklung",
                               country="Germany", city="Berlin", employment_type="internship",
                               description="Dein Profil:\n- Sehr gute Deutschkenntnisse\n- Python"))
    prefs = SearchPreferences(countries=["Germany"], employment_types=["internship"])
    for level, expected in (("B1", 0.0), ("B2", 100.0)):
        profile = CandidateProfileData.model_validate({
            "additional": {"languages": [{"language": "German", "proficiency": level}]},
            "work_authorization": {"residence_country": "Germany", "authorized_to_work": True},
        })
        match = score_record(job, profile, [], prefs)
        languages = next(d for d in match.dimensions if d.name == "languages")
        assert languages.score == expected


def test_in_country_no_sponsorship_advert_is_surfaced_as_a_concern():
    from core.schemas import CandidateProfileData, JobRecord, SearchPreferences
    from services.job_enrichment import enrich_job
    from services.job_scoring import score_record

    job = enrich_job(JobRecord(source="manual", title="Praktikum Softwareentwicklung",
                               country="Germany", city="Berlin", employment_type="internship",
                               description="Aufgaben: Python.\nWir bieten kein Visa-Sponsoring."))
    profile = CandidateProfileData.model_validate({
        "work_authorization": {"residence_country": "Germany", "authorized_to_work": True,
                               "sponsorship_required": True},
    })
    match = score_record(job, profile, [], SearchPreferences(countries=["Germany"],
                                                             employment_types=["internship"]))
    assert any("does not offer sponsorship" in c for c in match.eligibility.concerns)


# --- Pasted job links must not import neighbouring postings ------------------

RELATED_ROLES_PAGE = """<html><head><title>Backend Engineer - Acme</title></head><body>
<nav><a href="/">Home</a></nav>
<main>
  <h1>Backend Engineer</h1>
  <h2>Requirements</h2>
  <ul><li>Python and SQL</li><li>Docker</li></ul>
  <h2>Other open roles</h2>
  <ul>
    <li>Platform Engineer - Go, Kubernetes</li>
    <li>Systems Engineer - Rust and C++</li>
    <li>Web Developer - PHP, WordPress</li>
  </ul>
  <p>Go to our career portal to see more.</p>
</main></body></html>"""


def test_related_postings_do_not_become_required_skills():
    from connectors.company_careers import parse_job_page
    from core.schemas import JobRecord
    from services.job_enrichment import enrich_job

    fields = parse_job_page(RELATED_ROLES_PAGE, "https://example.invalid/jobs/backend")
    assert "Other open roles" not in fields["description"]
    job = enrich_job(JobRecord(source="manual", title=fields["title"],
                               description=fields["description"]))
    assert set(job.required_skills) == {"Python", "SQL", "Docker"}
    for absent in ("Go", "Rust", "PHP", "C++", "WordPress", "Kubernetes"):
        assert absent not in job.required_skills


@pytest.mark.parametrize("text", ["Go to our career portal.", "Please go back.",
                                  "Ready to go live soon?"])
def test_english_verb_go_is_not_the_go_language(text):
    from services.job_enrichment import extract_skills

    assert "Go" not in extract_skills(text, text)[0]


def test_the_go_language_is_still_detected():
    from services.job_enrichment import extract_skills

    required, _ = extract_skills("You will write services in Go and Rust.",
                                 "Requirements\n- Go\n- Rust")
    assert "Go" in required


@pytest.mark.parametrize("marker", ["Weitere Stellen", "Ähnliche Stellen",
                                    "Autres offres", "Otras ofertas"])
def test_non_english_related_posting_blocks_are_trimmed(marker):
    from core.text import strip_listing_boilerplate

    text = f"Anforderungen\n- Python\n{marker}\n- Rust Entwickler"
    assert "Rust" not in strip_listing_boilerplate(text)
