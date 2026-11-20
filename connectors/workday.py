"""Workday career search connector.

Workday installations differ. A tenant is configured as
``tenant/site@host`` (e.g. ``acme/External@acme.wd1.myworkdayjobs.com``) and the
connector uses the publicly reachable ``/wday/cxs`` search endpoint. Failures are
reported per tenant; they never abort a scan.
"""

from __future__ import annotations

import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord, SourceHealth


class WorkdayConnector(BaseConnector):
    key = "workday"
    display_name = "Workday"
    provider_kind = "ats"
    requires = ("WORKDAY_TENANTS",)
    description = "Workday public CXS job search (tenant/site@host configuration)."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = self.seeds(ctx, settings)[:10]
        if not seeds:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error="No Workday tenants configured.",
                               detail="Configure Workday as tenant/site@host, e.g. acme/External@acme.wd1.myworkdayjobs.com")

        terms = [q.query for q in ctx.queries if q.target in {"ats", "any"}][:3] or ["software"]
        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for seed in seeds:
            parsed = _parse_tenant(seed.identifier)
            if not parsed:
                errors.append(f"{seed.identifier}: invalid tenant format")
                continue
            tenant, site, host = parsed
            base = f"https://{host}/wday/cxs/{tenant}/{site}"
            company = seed.name or tenant.title()
            accepted = 0
            for term in terms:
                if accepted >= 25:
                    break
                try:
                    payload = await http.post_json(
                        f"{base}/jobs",
                        {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term},
                        headers={"Accept": "application/json", "Content-Type": "application/json"},
                    )
                    requests_made += 1
                except Exception as exc:
                    errors.append(f"{seed.identifier}: {type(exc).__name__}")
                    continue
                for raw in (payload or {}).get("jobPostings", [])[:20]:
                    title = raw.get("title") or ""
                    if not job_relevant(title, ctx):
                        continue
                    external_path = raw.get("externalPath") or ""
                    job = self.make_job(
                        source=self.key,
                        source_job_id=external_path or f"{title}-{raw.get('postedOn', '')}",
                        title=title,
                        company=company,
                        company_website=seed.career_url,
                        location=raw.get("locationsText") or "",
                        country=seed.country,
                        work_mode=infer_work_mode(raw.get("locationsText") or ""),
                        employment_type=infer_employment_type(title),
                        seniority=infer_seniority(title),
                        posted_at=parse_date(raw.get("postedOn")),
                        description="",
                        application_url=(f"https://{host}/en-US/{site}{external_path}"
                                         if external_path else ""),
                        original_url=(f"https://{host}/en-US/{site}{external_path}"
                                      if external_path else ""),
                    )
                    jobs.append(job)
                    accepted += 1
                    if external_path and len(jobs) <= 8:
                        description = await self._detail(http, base, external_path)
                        if description:
                            job.description = description
                            job.work_mode = infer_work_mode(description, job.location)
            if accepted:
                result.detail = f"Scanned {len(seeds)} tenants; {len(jobs)} postings."
        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]))

    async def _detail(self, http: HttpSession, base: str, external_path: str) -> str:
        try:
            payload = await http.get_json(f"{base}{external_path}")
        except Exception:
            return ""
        info = (payload or {}).get("jobPostingInfo") or {}
        return clean_html(info.get("jobDescription") or "")


def _parse_tenant(value: str) -> tuple[str, str, str] | None:
    if not value or "@" not in value or "/" not in value:
        return None
    head, host = value.split("@", 1)
    if "/" not in head:
        return None
    tenant, site = head.split("/", 1)
    if not (tenant and site and host):
        return None
    return tenant.strip(), site.strip(), host.strip()
