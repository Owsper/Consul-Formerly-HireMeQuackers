"""Recruitee public offers API connector."""

from __future__ import annotations

import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord

API = "https://{company}.recruitee.com/api/offers/"


class RecruiteeConnector(BaseConnector):
    key = "recruitee"
    display_name = "Recruitee"
    provider_kind = "ats"
    requires = ("RECRUITEE_COMPANIES",)
    description = "Recruitee public offers API (<company>.recruitee.com/api/offers)."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = self.seeds(ctx, settings)[:15]
        if not seeds:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error="No Recruitee companies configured.",
                               detail="Add Recruitee company subdomains in Settings.")

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for seed in seeds:
            try:
                payload = await http.get_json(API.format(company=seed.identifier))
                requests_made += 1
            except Exception as exc:
                errors.append(f"{seed.identifier}: {type(exc).__name__}")
                continue
            company = seed.name or seed.identifier.title()
            for raw in ((payload or {}).get("offers") or [])[:300]:
                if raw.get("status") and raw.get("status") != "published":
                    continue
                title = raw.get("title") or ""
                if not job_relevant(title, ctx):
                    continue
                location = raw.get("location") or ", ".join(
                    x for x in (raw.get("city"), raw.get("country")) if x
                )
                description = clean_html(raw.get("description") or "")
                requirements = clean_html(raw.get("requirements") or "")
                if requirements:
                    description = f"{description}\n\nRequirements\n{requirements}".strip()
                jobs.append(self.make_job(
                    source=self.key,
                    source_job_id=str(raw.get("id") or raw.get("careers_url") or ""),
                    title=title,
                    company=company,
                    company_website=seed.career_url,
                    location=location,
                    country=raw.get("country_code") or seed.country,
                    work_mode=infer_work_mode(raw.get("remote") and "remote" or "", location, description),
                    employment_type=infer_employment_type(title, raw.get("employment_type_code") or "", description),
                    seniority=infer_seniority(title),
                    posted_at=parse_date(raw.get("created_at")),
                    description=description,
                    application_url=raw.get("careers_apply_url") or raw.get("careers_url") or "",
                    original_url=raw.get("careers_url") or "",
                ))

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]),
                           detail=f"Scanned {len(seeds)} Recruitee companies.")
