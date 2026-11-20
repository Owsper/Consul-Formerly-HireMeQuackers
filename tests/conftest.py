"""Shared fixtures. Every test runs against a disposable SQLite database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import config
import core.database as database
from core.schemas import CandidateProfileData, EvidenceItem, SearchPreferences


def _clear_settings_cache() -> None:
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'consul.db').as_posix()}")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("ADZUNA_APP_ID", "")
    monkeypatch.setenv("ADZUNA_APP_KEY", "")
    monkeypatch.setenv("JOOBLE_API_KEY", "")
    monkeypatch.setenv("SEARCH_PROVIDER", "none")
    monkeypatch.setenv("SEARCH_API_KEY", "")
    monkeypatch.setenv("GREENHOUSE_BOARDS", "")
    monkeypatch.setenv("LEVER_COMPANIES", "")
    monkeypatch.setenv("WORKDAY_TENANTS", "")
    monkeypatch.setenv("TEAMTAILOR_SITES", "")
    _clear_settings_cache()
    database.configure_database(os.environ["DATABASE_URL"])
    database.init_db()
    yield
    database.get_engine().dispose()
    _clear_settings_cache()


@pytest.fixture
def session():
    with database.session_scope() as session:
        yield session


@pytest.fixture
def profile_data() -> CandidateProfileData:
    return CandidateProfileData.model_validate({
        "personal": {
            "full_name": "Ada Lovelace",
            "professional_title": "Backend Engineer",
            "email": "ada@example.com",
            "phone": "+49 30 123456",
            "city": "Berlin",
            "country": "Germany",
            "github": "https://github.com/ada",
        },
        "work_authorization": {
            "residence_country": "Germany",
            "authorized_to_work": True,
            "sponsorship_required": False,
        },
        "education": [{
            "institution": "TU Berlin",
            "qualification": "M.Sc.",
            "subject": "Computer Science",
            "start_date": "2018",
            "end_date": "2020",
        }],
        "employment": [{
            "employer": "Shop GmbH",
            "title": "Software Engineer",
            "location": "Berlin",
            "start_date": "2021",
            "end_date": "2024",
            "responsibilities": [
                "Built Python APIs with FastAPI and PostgreSQL",
                "Reduced p95 latency by 40% by adding caching",
            ],
            "technologies": ["Python", "FastAPI", "PostgreSQL"],
        }],
        "projects": [{
            "name": "Job Tracker",
            "label": "project",
            "description": "A Streamlit app for tracking job applications",
            "technologies": ["Python", "SQLite"],
            "implementation": "Built with SQLAlchemy",
        }, {
            "name": "Thesis prototype",
            "label": "academic_project",
            "description": "Research prototype for distributed caching",
            "technologies": ["Python"],
        }],
        "skills": [{"name": "Languages", "skills": ["Python", "SQL"]}],
        "additional": {
            "languages": [{"language": "German", "proficiency": "C1"}],
            "certifications": [{"name": "AWS Cloud Practitioner", "issuer": "Amazon", "date": "2023"}],
        },
    })


@pytest.fixture
def evidence(profile_data: CandidateProfileData) -> list[EvidenceItem]:
    from services.profile_service import synthesize_evidence

    return synthesize_evidence(profile_data)


@pytest.fixture
def approved_profile(session, profile_data, evidence):
    from services.profile_service import save_profile

    return save_profile(session, profile_data, evidence, approve=True, name="Ada Lovelace")


@pytest.fixture
def preferences() -> SearchPreferences:
    return SearchPreferences(
        target_titles=["Backend Engineer"],
        countries=["Germany"],
        cities=["Berlin"],
        work_modes=["remote", "hybrid"],
        employment_types=["full_time"],
        languages=["English", "German"],
    )


@pytest.fixture
def job_record():
    from core.schemas import JobRecord

    return JobRecord(
        source="greenhouse",
        source_job_id="gh-1",
        title="Senior Backend Engineer",
        company="Acme",
        location="Berlin, Germany",
        country="Germany",
        description=(
            "We are looking for a Senior Backend Engineer. You will build Python services "
            "with FastAPI and PostgreSQL. German C1 is required. Hybrid work in Berlin."
        ),
        responsibilities=["Build Python services", "Own PostgreSQL performance"],
        required_skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
        preferred_skills=["Kubernetes"],
        languages=["German (C1)"],
        education_requirements=["Bachelor's degree in Computer Science"],
        seniority="senior",
        employment_type="full_time",
        work_mode="hybrid",
        application_url="https://boards.greenhouse.io/acme/jobs/1",
        original_url="https://boards.greenhouse.io/acme/jobs/1",
    )
