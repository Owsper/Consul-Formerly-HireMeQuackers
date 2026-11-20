"""SmartRecruiters public postings API connector."""

from __future__ import annotations

import asyncio
import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord

LIST_API = "https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100"
DETAIL_API = "https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting}"
PUBLIC_URL = "https://jobs.smartrecruiters.com/{company}/{posting}"


class SmartRecruitersConnector(BaseConnector):
    key = "smartrecruiters"
    display_name = "SmartRecruiters"
    provider_kind = "ats"
    requires = ("SMARTRECRUITERS_COMPANIES",)
    description = "SmartRecruiters public company postings API (list + detail)."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = self.seeds(ctx, settings)[:10]
        if not seeds:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error="No SmartRecruiters company identifiers configured.",
                               detail="Add company identifiers in Settings.")

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0
        detail_targets: list[tuple[dict, object]] = []

        for seed in seeds:
            try:
                payload = await http.get_json(LIST_API.format(company=seed.identifier))
                requests_made += 1
            except Exception as exc:
                errors.append(f"{seed.identifier}: {type(exc).__name__}")
                continue
            company = seed.name or seed.identifier.replace("-", " ").title()
            for raw in (payload or {}).get("content", [])[:300]:
                title = raw.get("name") or ""
                if not job_relevant(title, ctx):
                    continue
                loc = raw.get("location") or {}
                location = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
                posting_id = str(raw.get("id") or "")
                job = self.make_job(
                    source=self.key,
                    source_job_id=posting_id,
                    title=title,
                    company=(raw.get("company") or {}).get("name") or company,
                    company_website=seed.career_url,
                    location=location,
                    country=loc.get("country") or seed.country,
                    work_mode=infer_work_mode("remote" if loc.get("remote") else "", location),
                    employment_type=infer_employment_type(
                        title, (raw.get("typeOfEmployment") or {}).get("label") or ""
                    ),
                    seniority=infer_seniority(title),
                    posted_at=parse_date(raw.get("releasedDate")),
                    description="",
                    application_url=PUBLIC_URL.format(company=seed.identifier, posting=posting_id),
                    original_url=PUBLIC_URL.format(company=seed.identifier, posting=posting_id),
                )
                jobs.append(job)
                if len(detail_targets) < 20:
                    detail_targets.append(({"seed": seed, "posting": posting_id}, job))

        # Fetch descriptions for a bounded number of listings.
        async def enrich(seed, posting_id, job) -> None:
            try:
                detail = await http.get_json(DETAIL_API.format(company=seed.identifier, posting=posting_id))
            except Exception:
                return
            sections = ((detail or {}).get("jobAd") or {}).get("sections") or {}
            parts = [sections.get(k, {}).get("text", "") for k in
                     ("companyDescription", "jobDescription", "qualifications", "additionalInformation")]
            description = "\n\n".join(clean_html(part) for part in parts if part)
            if description:
                job.description = description
                job.work_mode = infer_work_mode(description, job.location)

        semaphore = asyncio.Semaphore(max(1, settings.per_source_concurrency))

        async def guarded(seed, posting_id, job) -> None:
            async with semaphore:
                await enrich(seed, posting_id, job)

        await asyncio.gather(*(guarded(item[0]["seed"], item[0]["posting"], item[1])
                               for item in detail_targets), return_exceptions=True)

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]),
                           detail=f"Scanned {len(seeds)} companies; enriched {len(detail_targets)} descriptions.")
