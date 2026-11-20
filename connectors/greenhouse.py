"""Greenhouse public job board API connector."""

from __future__ import annotations

import asyncio

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, RequestStats, clean_html,
    dedupe_batch, infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord, SourceHealth

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


class GreenhouseConnector(BaseConnector):
    key = "greenhouse"
    display_name = "Greenhouse"
    provider_kind = "ats"
    requires = ("GREENHOUSE_BOARDS",)
    description = "Public Greenhouse job boards (GET /v1/boards/{token}/jobs)."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = __import__("time").perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = self.seeds(ctx, settings)[:15]
        if not seeds:
            return self.finish(
                result, started, stats, [], 0, configured=False,
                error="No Greenhouse board tokens configured.",
                detail="Add company board tokens (e.g. 'acme') in Settings or let company discovery find them.",
            )

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for seed in seeds:
            try:
                payload = await http.get_json(API.format(token=seed.identifier))
                requests_made += 1
            except Exception as exc:
                errors.append(f"{seed.identifier}: {type(exc).__name__}")
                continue
            company = seed.name or seed.identifier.replace("-", " ").title()
            for raw in (payload or {}).get("jobs", [])[:300]:
                title = raw.get("title") or ""
                if not job_relevant(title, ctx):
                    continue
                meta = {str(m.get("name", "")).lower(): m.get("value") for m in raw.get("metadata", []) or []}
                location = (raw.get("location") or {}).get("name") or ""
                description = clean_html(raw.get("content") or "")
                employment = meta.get("employment type") or ""
                job = self.make_job(
                    source=self.key,
                    source_job_id=str(raw.get("id") or ""),
                    title=title,
                    company=company,
                    company_website=seed.career_url,
                    location=location,
                    country=seed.country,
                    work_mode=infer_work_mode(location, description),
                    employment_type=infer_employment_type(title, employment, description),
                    seniority=infer_seniority(title),
                    posted_at=parse_date(raw.get("updated_at") or raw.get("created_at")),
                    description=description,
                    application_url=raw.get("absolute_url") or "",
                    original_url=raw.get("absolute_url") or "",
                )
                jobs.append(job)

        jobs = dedupe_batch(jobs)
        if not stats.ok and errors:
            result.status = SourceHealth.UNAVAILABLE
        error = "; ".join(errors[:5])
        return self.finish(result, started, stats, jobs, requests_made, configured=True,
                           error=error, detail=f"Scanned {len(seeds)} Greenhouse boards.")
