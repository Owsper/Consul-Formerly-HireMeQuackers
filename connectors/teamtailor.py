"""TeamTailor career sites.

TeamTailor has no unauthenticated JSON API; what is public is the career site
itself, which server-renders job pages with schema.org JobPosting JSON-LD. This
connector therefore reads the configured site's job index, follows the postings
and extracts structured data with the shared career-page parser. It never
guesses fields and reports per-site failures without aborting the scan.
"""

from __future__ import annotations

import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, dedupe_batch,
    infer_seniority, job_relevant,
)
from connectors.company_careers import extract_career_links, parse_job_page
from core.logging_config import get_logger
from core.schemas import JobRecord

logger = get_logger("teamtailor")

INDEX_TEMPLATE = "https://{site}.teamtailor.com/jobs"


class TeamTailorConnector(BaseConnector):
    key = "teamtailor"
    display_name = "TeamTailor"
    provider_kind = "ats"
    requires = ("TEAMTAILOR_SITES",)
    description = "TeamTailor career sites (public job index + JobPosting JSON-LD)."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = self.seeds(ctx, settings)[:10]
        if not seeds:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error="No TeamTailor sites configured.",
                               detail="Add sites as 'Company:subdomain' or a full careers URL.")

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for seed in seeds:
            index_url = _index_url(seed.identifier)
            try:
                html = await http.get_text(index_url)
                requests_made += 1
            except Exception as exc:
                errors.append(f"{seed.name or seed.identifier}: {type(exc).__name__}")
                continue

            links = extract_career_links(html, index_url, ctx)
            if not links:
                fields = parse_job_page(html, index_url)
                if fields.get("title"):
                    jobs.append(self._job_from_fields(fields, index_url, seed.name,
                                                      seed.country, index_url))
                continue

            for link in links[:25]:
                if len(jobs) >= 80:
                    break
                try:
                    page = await http.get_text(link["url"])
                    requests_made += 1
                except Exception as exc:
                    errors.append(f"{link['url'][:80]}: {type(exc).__name__}")
                    continue
                fields = parse_job_page(page, link["url"])
                title = fields.get("title") or link["title"]
                if not job_relevant(title, ctx):
                    continue
                jobs.append(self._job_from_fields(fields, title, seed.name,
                                                  seed.country, link["url"]))

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]),
                           detail=f"Scanned {len(seeds)} TeamTailor site(s).")

    def _job_from_fields(self, fields: dict, fallback_title: str, company: str,
                         country: str, page_url: str) -> JobRecord:
        title = fields.get("title") or fallback_title
        return self.make_job(
            source=self.key,
            source_job_id=page_url[:280],
            title=title,
            company=fields.get("company") or company,
            company_website=fields.get("company_website") or "",
            location=fields.get("location", ""),
            country=fields.get("country") or country,
            work_mode=fields.get("work_mode") or "unknown",
            employment_type=fields.get("employment_type", ""),
            seniority=infer_seniority(title),
            salary_min=fields.get("salary_min"),
            salary_max=fields.get("salary_max"),
            salary_currency=fields.get("salary_currency", ""),
            salary_frequency=fields.get("salary_frequency", ""),
            posted_at=fields.get("posted_at"),
            closing_at=fields.get("closing_at"),
            description=fields.get("description", ""),
            application_url=fields.get("application_url") or page_url,
            original_url=page_url,
            language=fields.get("language", ""),
        )


def _index_url(identifier: str) -> str:
    value = (identifier or "").strip().rstrip("/")
    if value.startswith("http://") or value.startswith("https://"):
        return value if value.endswith("/jobs") else f"{value}/jobs"
    return INDEX_TEMPLATE.format(site=value)
