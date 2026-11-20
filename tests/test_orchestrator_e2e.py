"""End-to-end mocked workflow: profile → plan → scan → score → CV → tracker.

No network access: every job-board HTTP call is intercepted by respx.
"""

from pathlib import Path

import httpx
import pytest
import respx

import config
from services.application_service import create_application, kanban, update_application
from services.cv_service import generate_cv_for_job, list_versions
from services.job_service import get_match, list_jobs, save_job
from services.profile_service import get_active_profile, save_profile
from services.query_planner import plan_search
from services.search_orchestrator import ScanRequest, run_scan, scan_history

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/beta"


def _greenhouse_payload():
    return {
        "jobs": [{
            "id": 101,
            "title": "Senior Backend Engineer",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/101",
            "updated_at": "2026-11-01T10:00:00Z",
            "location": {"name": "Berlin, Germany"},
            "content": (
                "&lt;p&gt;We build Python services with FastAPI and PostgreSQL. "
                "Hybrid work in Berlin. German C1 required.&lt;/p&gt;"
            ),
            "metadata": [{"name": "Employment Type", "value": "Full-time"}],
        }]
    }


def _lever_payload():
    return [{
        "id": "lev-77",
        "text": "Backend Engineer",
        "createdAt": 1793500000000,  # 2026-11-01

        "hostedUrl": "https://jobs.lever.co/beta/lev-77",
        "applyUrl": "https://jobs.lever.co/beta/lev-77/apply",
        "descriptionPlain": (
            "Join Beta as a Backend Engineer. You will write Python and PostgreSQL. "
            "Remote-friendly within Germany."
        ),
        "categories": {"location": "Berlin", "commitment": "Full-time"},
        "workplaceType": "remote",
        "lists": [{"text": "Requirements", "content": "<li>Python</li><li>SQL</li>"}],
    }]


@pytest.fixture
def seeded_settings(monkeypatch):
    monkeypatch.setenv("GREENHOUSE_BOARDS", "Acme:acme")
    monkeypatch.setenv("LEVER_COMPANIES", "Beta:beta")
    config.get_settings.cache_clear()
    return config.get_settings()


def test_full_mocked_workflow(session, profile_data, evidence, preferences,
                              seeded_settings, tmp_path):
    # 1. Ground Truth profile saved and approved.
    profile = save_profile(session, profile_data, evidence, approve=True, name="Ada Lovelace")
    active = get_active_profile(session)
    assert active is not None and active[0].id == profile.id

    # 2. Offline query planning (no LLM configured → deterministic fallback).
    plan = plan_search(profile_data, preferences, llm=None)
    assert plan.queries, "planner must produce inspectable queries"
    assert len({q.query.lower() for q in plan.queries}) == len(plan.queries)

    # 3. Scan two real connectors over mocked HTTP.
    from services.search_orchestrator import set_enabled_sources

    set_enabled_sources(session, ["greenhouse", "lever"])
    session.commit()

    with respx.mock(assert_all_called=True) as mock:
        mock.get(url__startswith=GREENHOUSE_URL).mock(
            return_value=httpx.Response(200, json=_greenhouse_payload())
        )
        mock.get(url__startswith=LEVER_URL).mock(
            return_value=httpx.Response(200, json=_lever_payload())
        )
        summary = run_scan(
            session,
            ScanRequest(preferences=preferences, plan=plan, profile_data=profile_data,
                        evidence=evidence, profile_id=profile.id, max_jobs_per_source=20),
        )

    assert summary.jobs_new == 2, [
        (s.connector, s.status, s.error, s.jobs_found, s.jobs_accepted, s.requests_made)
        for s in summary.sources
    ]
    assert {s.connector for s in summary.sources} == {"greenhouse", "lever"}
    assert all(s.status.value == "healthy" for s in summary.sources), summary.sources
    assert all(s.requests_ok >= 1 for s in summary.sources)
    assert scan_history(session)[0].id == summary.scan_id

    # 4. Jobs persisted with provenance and scores.
    jobs = list_jobs(session, limit=10)
    assert len(jobs) == 2
    for job in jobs:
        match = get_match(session, job.id)
        assert match is not None and 0 <= match.total_score <= 100
        assert match.classification.value in {
            "excellent", "strong", "potential", "weak", "not_recommended"
        }
        assert job.application_url.startswith("https://")

    target = next(j for j in jobs if j.company == "Acme")

    # 5. Save, tailor a truthful CV, export DOCX + PDF.
    save_job(session, target.id, notes="Strong fit")
    cv_row, _cv, report = generate_cv_for_job(session, target.id, use_llm=False,
                                              formats=("docx", "pdf"))
    assert report.passed is True
    assert cv_row.docx_path and cv_row.pdf_path
    assert Path(cv_row.docx_path).exists() and Path(cv_row.pdf_path).exists()
    assert list_versions(session, target.id)[0].version == cv_row.version

    # 6. Tracker: no duplicate applications, status changes stick.
    from core.exceptions import DuplicateApplicationError

    app = create_application(session, target.id, status="Shortlisted", tailored_cv_id=cv_row.id)
    with pytest.raises(DuplicateApplicationError):
        create_application(session, target.id)
    update_application(session, app.id, status="Applied")
    assert app.id in [a.id for a in kanban(session)["Applied"]]
    assert cv_row.version == 1


def test_scan_records_failure_without_fake_results(session, profile_data, evidence,
                                                   preferences, seeded_settings):
    from services.search_orchestrator import set_enabled_sources

    set_enabled_sources(session, ["greenhouse"])
    session.commit()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith=GREENHOUSE_URL).mock(
            return_value=httpx.Response(503, text="maintenance")
        )
        summary = run_scan(session, ScanRequest(preferences=preferences,
                                                profile_data=profile_data, evidence=evidence))

    assert summary.jobs_new == 0
    assert len(summary.sources) == 1
    assert summary.sources[0].requests_ok == 0
    assert summary.sources[0].status.value in {"unavailable", "partially_working"}
    assert list_jobs(session) == []


def test_scan_without_enabled_sources_reports_clearly(session, seeded_settings):
    from services.search_orchestrator import set_enabled_sources

    set_enabled_sources(session, [])
    session.commit()
    summary = run_scan(session, ScanRequest())
    assert summary.sources == []
    assert any("No sources are enabled" in note for note in summary.notes)
