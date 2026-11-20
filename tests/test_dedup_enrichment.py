from core.schemas import JobRecord, ListingStatus, WorkMode
from services.deduplication import canonical_url, compute_fingerprint, find_existing, persist_job
from services.job_enrichment import detect_language, enrich_job, extract_skills


def _job(**overrides):
    base = dict(
        source="greenhouse", source_job_id="1", title="Backend Engineer", company="Acme",
        location="Berlin", description="Python and PostgreSQL. Hybrid role.", required_skills=[],
        application_url="https://boards.greenhouse.io/acme/jobs/1?utm_source=x",
        original_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    base.update(overrides)
    return JobRecord(**base)


def test_canonical_url_strips_tracking():
    assert canonical_url("https://example.com/jobs/1?utm_source=a&ref=b") == \
        "https://example.com/jobs/1"
    assert canonical_url("http://Example.com/Jobs/1/") == "https://example.com/Jobs/1"


def test_persist_merges_same_source_job(session):
    row1, created1 = persist_job(session, _job())
    row2, created2 = persist_job(session, _job(source_job_id="1", description="Updated text"))
    assert created1 is True
    assert created2 is False
    assert row1.id == row2.id
    session.expire_all()
    stored = session.get(type(row1), row1.id)
    # Different provenance for the same vacancy must never create a second job.
    assert stored.description
    assert stored.last_verified is not None


def test_fuzzy_dedup_across_sources(session):
    first, _ = persist_job(session, _job())
    other = _job(source="lever", source_job_id="lev-9",
                 application_url="https://jobs.lever.co/acme/lev-9",
                 original_url="https://jobs.lever.co/acme/lev-9",
                 description=_job().description)
    existing, reason = find_existing(session, other)
    assert existing is not None and existing.id == first.id
    assert reason in {"fuzzy", "url", "source_id"}


def test_no_duplicate_by_different_job(session):
    persist_job(session, _job())
    different = _job(source="lever", source_job_id="lev-2", title="Data Engineer",
                     application_url="https://jobs.lever.co/acme/2",
                     original_url="https://jobs.lever.co/acme/2",
                     description="Completely different role about data pipelines.")
    row, created = persist_job(session, different)
    assert created is True


def test_history_is_kept_when_listing_unavailable(session):
    row, _ = persist_job(session, _job())
    updated = _job(status=ListingStatus.EXPIRED)
    row2, created = persist_job(session, updated)
    session.expire_all()
    stored = session.get(type(row), row.id)
    assert created is False
    assert stored.listing_status == "expired"
    assert stored.description


def test_enrichment_extracts_without_inventing(job_record):
    record = job_record.model_copy(update={"required_skills": [], "languages": [],
                                           "visa_sponsorship": None, "work_mode": WorkMode.UNKNOWN})
    enriched = enrich_job(record)
    assert set(enriched.required_skills) & {"Python", "FastAPI"}
    assert enriched.work_mode in {WorkMode.HYBRID, WorkMode.REMOTE, WorkMode.ONSITE}
    assert enriched.salary_min is None
    assert enriched.country == "Germany"


def test_skill_and_language_detection():
    required, preferred = extract_skills("Must know Python and SQL. Nice to have Kubernetes.",
                                         "Must know Python and SQL. Nice to have Kubernetes.")
    assert "Python" in required
    assert detect_language("Wir suchen einen Softwareentwickler mit Python-Kenntnissen.") == "de"
    assert detect_language("We are looking for a backend engineer with Python skills.") == "en"


def test_fingerprint_is_stable():
    assert compute_fingerprint("Acme GmbH", "Backend Engineer (m/w/d)", "Berlin") == \
        compute_fingerprint("Acme", "Backend Engineer", "Berlin")
