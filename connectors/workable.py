"""Workable public widget/jobs feed connector."""

from __future__ import annotations

import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord

API = "https://apply.workable.com/api/v1/widget/accounts/{account}?details=true"


class WorkableConnector(BaseConnector):
    key = "workable"
    display_name = "Workable"
    provider_kind = "ats"
    requires = ("WORKABLE_ACCOUNTS",)
    description = "Workable public account widget API (apply.workable.com/api/v1/widget)."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = self.seeds(ctx, settings)[:15]
        if not seeds:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error="No Workable accounts configured.",
                               detail="Add Workable account slugs (e.g. 'acme') in Settings.")

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for seed in seeds:
            try:
                payload = await http.get_json(API.format(account=seed.identifier))
                requests_made += 1
            except Exception as exc:
                errors.append(f"{seed.identifier}: {type(exc).__name__}")
                continue
            company = seed.name or (payload or {}).get("name") or seed.identifier.title()
            for raw in ((payload or {}).get("jobs") or [])[:300]:
                title = raw.get("title") or ""
                if not job_relevant(title, ctx):
                    continue
                loc = raw.get("location") or {}
                location = loc.get("location_str") or ", ".join(
                    x for x in (loc.get("city"), loc.get("country")) if x
                )
                description = clean_html(raw.get("description") or "")
                requirements = clean_html(raw.get("requirements") or "")
                if requirements:
                    description = f"{description}\n\nRequirements\n{requirements}".strip()
                mode = "remote" if raw.get("telecommuting") else infer_work_mode(location)
                jobs.append(self.make_job(
                    source=self.key,
                    source_job_id=str(raw.get("shortcode") or raw.get("code") or raw.get("url") or ""),
                    title=title,
                    company=company,
                    company_website=seed.career_url,
                    location=location,
                    country=loc.get("country") or seed.country,
                    work_mode=mode,
                    employment_type=infer_employment_type(title, raw.get("employment_type") or "", description),
                    seniority=infer_seniority(title),
                    posted_at=parse_date(raw.get("created_at") or raw.get("published_on")),
                    description=description,
                    application_url=raw.get("url") or raw.get("shortlink") or "",
                    original_url=raw.get("url") or raw.get("shortlink") or "",
                ))

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]),
                           detail=f"Scanned {len(seeds)} Workable accounts.")
