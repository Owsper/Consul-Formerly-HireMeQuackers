"""Lever public postings API connector (supports EU-hosted boards)."""

from __future__ import annotations

import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord

US_API = "https://api.lever.co/v0/postings/{company}?mode=json"
EU_API = "https://api.eu.lever.co/v0/postings/{company}?mode=json"


class LeverConnector(BaseConnector):
    key = "lever"
    display_name = "Lever"
    provider_kind = "ats"
    requires = ("LEVER_COMPANIES",)
    description = "Public Lever postings API, including EU-hosted instances."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = self.seeds(ctx, settings)[:15]
        if not seeds:
            return self.finish(
                result, started, stats, [], 0, configured=False,
                error="No Lever company identifiers configured.",
                detail="Add Lever company slugs (e.g. 'acme') in Settings.",
            )

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for seed in seeds:
            use_eu = "eu.lever.co" in (seed.career_url or "").lower()
            url = (EU_API if use_eu else US_API).format(company=seed.identifier)
            try:
                payload = await http.get_json(url)
                requests_made += 1
            except Exception as exc:
                errors.append(f"{seed.identifier}: {type(exc).__name__}")
                continue
            company = seed.name or seed.identifier.replace("-", " ").title()
            for raw in (payload or [])[:300]:
                if not isinstance(raw, dict):
                    continue
                title = raw.get("text") or ""
                if not job_relevant(title, ctx):
                    continue
                categories = raw.get("categories") or {}
                location = categories.get("location") or raw.get("country") or ""
                description = raw.get("descriptionPlain") or clean_html(raw.get("description") or "")
                extra = []
                for block in raw.get("lists") or []:
                    text = block.get("text") or ""
                    content = clean_html(block.get("content") or "")
                    if text or content:
                        extra.append(f"{text}\n{content}".strip())
                if extra:
                    description = (description + "\n\n" + "\n\n".join(extra)).strip()
                workplace = (raw.get("workplaceType") or "").lower()
                work_mode = infer_work_mode(workplace, location, description)
                jobs.append(self.make_job(
                    source=self.key,
                    source_job_id=str(raw.get("id") or ""),
                    title=title,
                    company=company,
                    company_website=seed.career_url,
                    location=location,
                    country=seed.country,
                    work_mode=work_mode,
                    employment_type=infer_employment_type(title, categories.get("commitment") or "", description),
                    seniority=infer_seniority(title),
                    posted_at=parse_date(raw.get("createdAt")),
                    description=description,
                    application_url=raw.get("applyUrl") or raw.get("hostedUrl") or "",
                    original_url=raw.get("hostedUrl") or "",
                ))

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]),
                           detail=f"Scanned {len(seeds)} Lever boards.")
