"""Adzuna aggregator connector (free tier, requires app id/key)."""

from __future__ import annotations

import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord

API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

COUNTRY_CODES = {
    "germany": "de", "deutschland": "de", "austria": "at", "österreich": "at",
    "switzerland": "ch", "schweiz": "ch", "united kingdom": "gb", "uk": "gb",
    "england": "gb", "france": "fr", "spain": "es", "españa": "es",
    "netherlands": "nl", "nederland": "nl", "italy": "it", "italia": "it",
    "poland": "pl", "polska": "pl", "brazil": "br", "portugal": "pt",
    "united states": "us", "usa": "us", "canada": "ca", "australia": "au",
    "new zealand": "nz", "india": "in", "singapore": "sg", "south africa": "za",
}


class AdzunaConnector(BaseConnector):
    key = "adzuna"
    display_name = "Adzuna"
    provider_kind = "aggregator"
    requires = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")
    description = "Adzuna jobs API (aggregates many boards; free developer tier)."

    def missing_config(self, settings: Settings) -> list[str]:
        missing = []
        if not settings.adzuna_app_id:
            missing.append("ADZUNA_APP_ID")
        if not settings.adzuna_app_key:
            missing.append("ADZUNA_APP_KEY")
        return missing

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        missing = self.missing_config(settings)
        if missing:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error=f"Missing configuration: {', '.join(missing)}",
                               detail="Register a free API key at https://developer.adzuna.com/ and set the variables.")

        codes: list[str] = []
        for country in ctx.preferences.countries:
            code = COUNTRY_CODES.get(country.strip().lower())
            if code and code not in codes:
                codes.append(code)
        if not codes:
            codes = [settings.adzuna_country or "de"]
        codes = codes[:3]

        search_queries = [q for q in ctx.queries if q.target in {"any", "search"}][:4]
        if not search_queries:
            search_queries = [q for q in ctx.queries][:4]

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for code in codes:
            for planned in search_queries:
                try:
                    payload = await http.get_json(
                        API.format(country=code, page=1),
                        params={
                            "app_id": settings.adzuna_app_id,
                            "app_key": settings.adzuna_app_key,
                            "what": planned.query.replace('"', ""),
                            "results_per_page": 50,
                            "content-type": "application/json",
                        },
                    )
                    requests_made += 1
                except Exception as exc:
                    errors.append(f"{code}: {type(exc).__name__}")
                    continue
                for raw in (payload or {}).get("results", [])[:50]:
                    title = raw.get("title") or ""
                    if not job_relevant(title, ctx, extra=planned.query):
                        continue
                    company = (raw.get("company") or {}).get("display_name") or ""
                    location = (raw.get("location") or {}).get("display_name") or ""
                    predicted = raw.get("salary_is_predicted") in (1, "1", True)
                    description = clean_html(raw.get("description") or "")
                    jobs.append(self.make_job(
                        source=self.key,
                        source_job_id=str(raw.get("id") or ""),
                        title=title,
                        company=company,
                        company_website=(raw.get("company") or {}).get("url") or "",
                        location=location,
                        country=code.upper() if len(code) == 2 else code,
                        work_mode=infer_work_mode(title, description, location),
                        employment_type=infer_employment_type(
                            title, raw.get("contract_time") or "", raw.get("contract_type") or ""
                        ),
                        seniority=infer_seniority(title),
                        salary_min=None if predicted else raw.get("salary_min"),
                        salary_max=None if predicted else raw.get("salary_max"),
                        salary_currency=ctx.preferences.salary_currency or "",
                        salary_frequency="year",
                        posted_at=parse_date(raw.get("created")),
                        description=description,
                        application_url=raw.get("redirect_url") or "",
                        original_url=raw.get("redirect_url") or "",
                    ))

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]),
                           detail=f"Searched {len(codes)} Adzuna markets.")
