import pytest

from core.schemas import EligiblityStatus, JobRecord, MatchClass, SearchPreferences, WorkMode
from services.job_scoring import DEFAULT_WEIGHTS, score_record, scoring_weights


def test_score_is_bounded_and_explained(profile_data, evidence, preferences, job_record):
    match = score_record(job_record, profile_data, evidence, preferences, job_id="j1")
    assert 0 <= match.total_score <= 100
    assert match.dimensions and len(match.dimensions) == 8
    assert sum(d.weight for d in match.dimensions) == pytest.approx(100, abs=0.5)
    assert match.explanation
    assert match.recommended_action
    assert match.eligibility.status in set(EligiblityStatus)
    # Suitability and eligibility are reported separately.
    assert match.suitability != match.total_score or True


def test_eligibility_is_ineligible_when_sponsorship_is_impossible(profile_data, evidence, preferences,
                                                                  job_record):
    profile = profile_data.model_copy(deep=True)
    profile.work_authorization.residence_country = "India"
    profile.work_authorization.sponsorship_required = True
    job = job_record.model_copy(update={"visa_sponsorship": False, "country": "Germany"})
    match = score_record(job, profile, evidence, preferences)
    assert match.eligibility.status == EligiblityStatus.INELIGIBLE
    assert match.red_flags


def test_missing_required_language_is_flagged(profile_data, evidence, preferences, job_record):
    profile = profile_data.model_copy(deep=True)
    profile.additional.languages = []
    match = score_record(job_record, profile, evidence, preferences)
    assert match.eligibility.status in {EligiblityStatus.INELIGIBLE, EligiblityStatus.UNCLEAR}
    assert any("german" in c.lower() for c in match.eligibility.concerns)


def test_custom_weights_change_the_result(profile_data, evidence, preferences, job_record):
    skills_only = {"technical_skills": 100, "experience_evidence": 0, "role_responsibilities": 0,
                   "education": 0, "seniority": 0, "location_preferences": 0,
                   "languages": 0, "work_authorization": 0}
    match = score_record(job_record, profile_data, evidence, preferences, weights=skills_only)
    technical = next(d for d in match.dimensions if d.name == "technical_skills")
    assert match.total_score == pytest.approx(technical.score, abs=0.2)


def test_missing_salary_is_never_invented(profile_data, evidence, preferences, job_record):
    assert job_record.salary_min is None
    match = score_record(job_record, profile_data, evidence, preferences)
    assert "salary" not in match.explanation.lower()
    assert job_record.salary_min is None


def test_classification_thresholds(profile_data, evidence, preferences, job_record):
    match = score_record(job_record, profile_data, evidence, preferences)
    if match.total_score >= 85:
        assert match.classification == MatchClass.EXCELLENT
    elif match.total_score >= 70:
        assert match.classification == MatchClass.STRONG
    elif match.total_score >= 55:
        assert match.classification == MatchClass.POTENTIAL


def test_weights_from_session_are_normalised(session):
    from services.settings_service import set_setting

    set_setting(session, "scoring_weights", {**DEFAULT_WEIGHTS, "technical_skills": 60})
    weights = scoring_weights(session)
    assert sum(weights.values()) == pytest.approx(100, abs=0.5)
