"""Ashby public job board API connector."""

from __future__ import annotations

import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord

API = "https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"


class AshbyConnector(BaseConnector):
    key = "ashby"
    display_name = "Ashby"
    provider_kind = "ats"
    requires = ("ASHBY_BOARDS",)
    description = "Ashby public job posting API (posting-api/job-board)."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = self.seeds(ctx, settings)[:15]
        if not seeds:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error="No Ashby board names configured.",
                               detail="Add Ashby organisation names (e.g. 'acme') in Settings.")

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for seed in seeds:
            try:
                payload = await http.get_json(API.format(board=seed.identifier))
                requests_made += 1
            except Exception as exc:
                errors.append(f"{seed.identifier}: {type(exc).__name__}")
                continue
            company = seed.name or seed.identifier.replace("-", " ").title()
            raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else (payload or [])
            for raw in raw_jobs[:300]:
                title = raw.get("title") or ""
                if not job_relevant(title, ctx) or raw.get("isListed") is False:
                    continue
                location = raw.get("location") or ""
                description = raw.get("descriptionPlain") or clean_html(
                    raw.get("descriptionHtml") or raw.get("description") or ""
                )
                work_mode = infer_work_mode(raw.get("workplaceType") or "", location, description)
                employment = raw.get("employmentType") or ""
                jobs.append(self.make_job(
                    source=self.key,
                    source_job_id=str(raw.get("id") or ""),
                    title=title,
                    company=company,
                    company_website=seed.career_url,
                    location=location,
                    country=seed.country,
                    work_mode=work_mode,
                    employment_type=infer_employment_type(title, employment, description),
                    seniority=infer_seniority(title),
                    posted_at=parse_date(raw.get("publishedAt") or raw.get("updatedAt")),
                    description=description,
                    application_url=raw.get("applyUrl") or raw.get("jobUrl") or "",
                    original_url=raw.get("jobUrl") or raw.get("applyUrl") or "",
                ))

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]),
                           detail=f"Scanned {len(seeds)} Ashby boards.")
