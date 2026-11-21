import httpx
import pytest
import respx

from config import get_settings
from connectors.base import CompanySeed, ConnectorContext, HttpSession
from connectors.greenhouse import GreenhouseConnector
from connectors.lever import LeverConnector
from connectors.workday import WorkdayConnector, _parse_tenant
from core.schemas import PlannedQuery, SourceHealth
from services.search_orchestrator import connector_registry


def _ctx(*companies: CompanySeed) -> ConnectorContext:
    return ConnectorContext(
        queries=[PlannedQuery(query="Backend Engineer", language="en", target="ats")],
        companies=list(companies),
        search_terms={"backend engineer", "python"},
    )


async def _search(connector, ctx):
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        http = HttpSession(client, settings, limiter=_NoLimit())
        return await connector.search(ctx, http, settings)


class _NoLimit:
    async def wait(self):
        return None


@respx.mock
async def test_greenhouse_returns_normalised_jobs():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": [{
            "id": 42,
            "title": "Backend Engineer",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/42",
            "location": {"name": "Berlin, Germany"},
            "content": "<p>Python and PostgreSQL. Remote friendly.</p>",
            "updated_at": "2024-01-10T10:00:00Z",
            "metadata": [{"name": "Employment Type", "value": "Full-time"}],
        }]})
    )
    result = await _search(GreenhouseConnector(),
                           _ctx(CompanySeed(name="Acme", identifier="acme", provider="greenhouse")))
    assert result.status == SourceHealth.HEALTHY
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.title == "Backend Engineer"
    assert job.company == "Acme"
    assert job.source_job_id == "42"
    assert job.application_url.endswith("/42")
    assert "Python" in job.description


@respx.mock
async def test_lever_eu_board_is_supported():
    respx.get("https://api.eu.lever.co/v0/postings/eu-co").mock(
        return_value=httpx.Response(200, json=[{
            "id": "abc",
            "text": "Python Backend Engineer",
            "hostedUrl": "https://jobs.eu.lever.co/eu-co/abc",
            "applyUrl": "https://jobs.eu.lever.co/eu-co/abc/apply",
            "categories": {"location": "Amsterdam", "team": "Engineering",
                           "commitment": "Full-time"},
            "descriptionPlain": "Build Python services with FastAPI.",
            "createdAt": 1700000000000,
        }])
    )
    result = await _search(LeverConnector(),
                           _ctx(CompanySeed(name="EU Co", identifier="eu-co", provider="lever",
                                            career_url="https://jobs.eu.lever.co/eu-co")))
    assert result.status == SourceHealth.HEALTHY
    assert result.jobs
    assert result.jobs[0].company == "EU Co"


async def test_missing_configuration_is_reported_not_hidden():
    result = await _search(GreenhouseConnector(), _ctx())
    assert result.status == SourceHealth.MISSING_CONFIG
    assert result.requests_made == 0
    assert result.jobs == []
    assert "configured" in result.error.lower()


@respx.mock
async def test_server_error_marks_source_unavailable():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(503, text="down")
    )
    result = await _search(GreenhouseConnector(),
                           _ctx(CompanySeed(name="Acme", identifier="acme", provider="greenhouse")))
    assert result.status in {SourceHealth.UNAVAILABLE, SourceHealth.PARTIAL}
    assert result.requests_ok == 0


@respx.mock
async def test_rate_limit_marks_source_rate_limited():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    result = await _search(GreenhouseConnector(),
                           _ctx(CompanySeed(name="Acme", identifier="acme", provider="greenhouse")))
    assert result.status == SourceHealth.RATE_LIMITED
    assert result.jobs == []


def test_workday_tenant_parsing():
    assert _parse_tenant("acme/External@acme.wd1.myworkdayjobs.com") == (
        "acme", "External", "acme.wd1.myworkdayjobs.com")
    assert _parse_tenant("invalid") is None


def test_all_required_connectors_are_registered():
    keys = set(connector_registry())
    required = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee",
                "personio", "workday", "teamtailor", "adzuna", "jooble", "search_engine",
                "company_careers"}
    assert required <= keys
    assert WorkdayConnector.key == "workday"


# --- JobTeaser --------------------------------------------------------------

JOBTEASER_URL = "https://www.jobteaser.com/en/job-offers?locale=en"


@respx.mock
async def test_jobteaser_reports_cloudflare_restriction_honestly():
    from connectors.jobteaser import JobTeaserConnector

    respx.get(JOBTEASER_URL).mock(return_value=httpx.Response(403, text="<html>blocked</html>"))
    result = await _search(JobTeaserConnector(), _ctx())
    assert result.status == SourceHealth.RESTRICTED
    assert result.jobs == []
    assert "Add a job manually" in result.detail


@respx.mock
async def test_jobteaser_challenge_body_is_not_treated_as_success():
    from connectors.jobteaser import JobTeaserConnector

    respx.get(JOBTEASER_URL).mock(return_value=httpx.Response(
        200, text="<html><title>JobTeaser | Security checkup</title></html>"))
    result = await _search(JobTeaserConnector(), _ctx())
    assert result.status == SourceHealth.RESTRICTED
    assert result.requests_ok == 0  # a challenge body is not a successful page
    assert result.jobs == []


@respx.mock
async def test_jobteaser_parses_jsonld_when_a_real_page_is_served():
    from connectors.jobteaser import JobTeaserConnector

    html = """<html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"JobPosting",
     "title":"Software Engineering Intern",
     "url":"https://www.jobteaser.com/en/job-offers/1234",
     "hiringOrganization":{"@type":"Organization","name":"Acme"},
     "description":"Python and SQL"}
    </script></head><body></body></html>"""
    respx.get(JOBTEASER_URL).mock(return_value=httpx.Response(200, text=html))
    result = await _search(JobTeaserConnector(), _ctx())
    assert result.status == SourceHealth.HEALTHY
    assert len(result.jobs) == 1
    assert result.jobs[0].title == "Software Engineering Intern"
    assert result.jobs[0].company == "Acme"
    assert result.jobs[0].is_snippet is False


@respx.mock
async def test_jobteaser_anchor_fallback_is_marked_as_snippet():
    from connectors.jobteaser import JobTeaserConnector

    html = ("<html><body><a href='/en/job-offers/50f8a3c3-7335-4449-8513-95eebcce97c4-acme-intern'>"
            "Data Science Internship</a><a href='/en/job-offers/50f8a3c3-7335-4449-8513-95eebcce97c4-acme-intern'>"
            "Apply now</a></body></html>")
    respx.get(JOBTEASER_URL).mock(return_value=httpx.Response(200, text=html))
    result = await _search(JobTeaserConnector(), _ctx())
    assert len(result.jobs) == 1
    assert result.jobs[0].is_snippet is True
    assert result.jobs[0].title == "Data Science Internship"


def test_jobteaser_is_registered():
    assert "jobteaser" in connector_registry()
