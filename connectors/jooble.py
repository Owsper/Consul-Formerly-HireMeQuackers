"""Jooble aggregator connector (free API key required)."""

from __future__ import annotations

import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord

API = "https://jooble.org/api/{key}"


class JoobleConnector(BaseConnector):
    key = "jooble"
    display_name = "Jooble"
    provider_kind = "aggregator"
    requires = ("JOOBLE_API_KEY",)
    description = "Jooble jobs API (POST https://jooble.org/api/{key})."

    def missing_config(self, settings: Settings) -> list[str]:
        return [] if settings.jooble_api_key else ["JOOBLE_API_KEY"]

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        missing = self.missing_config(settings)
        if missing:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error=f"Missing configuration: {', '.join(missing)}",
                               detail="Request a free API key at https://jooble.org/api/about")

        location = (ctx.preferences.cities or ctx.preferences.countries or [""])[0]
        queries = [q for q in ctx.queries if q.target in {"any", "ats"}][:3]

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for planned in queries:
            try:
                payload = await http.post_json(
                    API.format(key=settings.jooble_api_key),
                    {"keywords": planned.query.replace('"', ""), "location": location},
                    headers={"Content-Type": "application/json"},
                )
                requests_made += 1
            except Exception as exc:
                errors.append(f"{type(exc).__name__}")
                continue
            for raw in (payload or {}).get("jobs", [])[:50]:
                title = raw.get("title") or ""
                if not job_relevant(title, ctx):
                    continue
                jobs.append(self.make_job(
                    source=self.key,
                    source_job_id=str(raw.get("id") or f"{title}-{raw.get('company', '')}"),
                    title=title,
                    company=raw.get("company") or "",
                    location=raw.get("location") or "",
                    country=raw.get("location") or "",
                    work_mode=infer_work_mode(title, raw.get("snippet") or "", raw.get("location") or ""),
                    employment_type=infer_employment_type(title, raw.get("type") or ""),
                    seniority=infer_seniority(title),
                    description=clean_html(raw.get("snippet") or ""),
                    application_url=raw.get("link") or "",
                    original_url=raw.get("link") or "",
                    posted_at=parse_date(raw.get("updated")),
                ))

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]),
                           detail="Jooble snippets only — verify each listing before applying.")
