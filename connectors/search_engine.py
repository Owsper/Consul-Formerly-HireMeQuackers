"""Search engine discovery connector.

Only providers with documented, paid/free API terms are used (Brave Search API,
Serper, Tavily). Results are discovery candidates: they carry a snippet, not a
verified job description, and are explicitly marked ``is_snippet``.
"""

from __future__ import annotations

import re
import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, dedupe_batch, infer_employment_type,
    infer_seniority, infer_work_mode, parse_date,
)
from core.security import sanitize_html
from core.schemas import JobRecord, ListingStatus, SourceHealth
from core.text import normalize_whitespace

MAX_QUERIES = 6


class SearchEngineConnector(BaseConnector):
    key = "search_engine"
    display_name = "Web search discovery"
    provider_kind = "search"
    requires = ("SEARCH_PROVIDER", "SEARCH_API_KEY")
    description = "Brave / Serper / Tavily search APIs for finding job postings on the open web."

    def missing_config(self, settings: Settings) -> list[str]:
        missing = []
        if settings.search_provider in {"", "none"}:
            missing.append("SEARCH_PROVIDER")
        if not settings.search_api_key:
            missing.append("SEARCH_API_KEY")
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
                               detail="Configure a supported search API (brave, serper or tavily).")
        if settings.search_provider not in {"brave", "serper", "tavily"}:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error=f"Unsupported search provider '{settings.search_provider}'",
                               detail="Supported providers: brave, serper, tavily.")

        queries = sorted(
            [q for q in ctx.queries if q.target in {"search", "careers"}],
            key=lambda q: q.priority,
        )
        if not queries:
            queries = [q for q in ctx.queries][:MAX_QUERIES]

        jobs: list[JobRecord] = []
        errors: list[str] = []
        executed = 0

        for planned in queries[:MAX_QUERIES]:
            try:
                results = await self._query(http, settings, planned.query)
                executed += 1
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {str(exc)[:80]}")
                continue
            for item in results[:20]:
                url = item.get("url") or ""
                if not url:
                    continue
                title_raw = normalize_whitespace(sanitize_html(item.get("title") or ""))
                title, company = _split_title(title_raw, url)
                snippet = normalize_whitespace(sanitize_html(item.get("snippet") or ""))
                if not title:
                    continue
                jobs.append(self.make_job(
                    source=self.key,
                    source_job_id=url[:280],
                    title=title,
                    company=company,
                    location=_guess_location(snippet),
                    work_mode=infer_work_mode(title, snippet),
                    employment_type=infer_employment_type(title, snippet),
                    seniority=infer_seniority(title),
                    description=snippet,
                    application_url=url,
                    original_url=url,
                    posted_at=parse_date(item.get("date")),
                    status=ListingStatus.UNVERIFIED,
                    is_snippet=True,
                ))

        return self.finish(result, started, stats, dedupe_batch(jobs), executed,
                           configured=True, error="; ".join(errors[:5]),
                           detail=f"{settings.search_provider} search: snippets are discovery candidates, not verified listings.")

    async def _query(self, http: HttpSession, settings: Settings, query: str) -> list[dict]:
        provider = settings.search_provider
        key = settings.search_api_key
        if provider == "brave":
            payload = await http.get_json(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 20},
                headers={"Accept": "application/json", "X-Subscription-Token": key},
            )
            return [
                {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("description"),
                 "date": r.get("age") or r.get("page_age")}
                for r in ((payload or {}).get("web") or {}).get("results", [])
            ]
        if provider == "serper":
            payload = await http.post_json(
                "https://google.serper.dev/search",
                {"q": query, "num": 20},
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
            )
            return [
                {"title": r.get("title"), "url": r.get("link"), "snippet": r.get("snippet"),
                 "date": r.get("date")}
                for r in (payload or {}).get("organic", [])
            ]
        if provider == "tavily":
            payload = await http.post_json(
                "https://api.tavily.com/search",
                {"api_key": key, "query": query, "max_results": 20, "search_depth": "basic"},
                headers={"Content-Type": "application/json"},
            )
            return [
                {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content"),
                 "date": None}
                for r in (payload or {}).get("results", [])
            ]
        return []


def _split_title(raw: str, url: str) -> tuple[str, str]:
    """Turn an SEO-style result title into (job title, company)."""
    if not raw:
        return "", ""
    text = re.sub(r"\s*[-–|]\s*(Greenhouse|Lever|Ashby|SmartRecruiters|Workable|Indeed|LinkedIn|Glassdoor).*$",
                  "", raw, flags=re.I)
    parts = re.split(r"\s+(?:\||-|–|—|@)\s+", text)
    if len(parts) >= 2:
        first = parts[0].strip()
        if re.search(r"(job|career|hiring|stelle|offre|empleo)", first, re.I):
            first = parts[1].strip()
            rest = parts[2:]
        else:
            rest = parts[1:]
        company = rest[0].strip() if rest else ""
        company = re.sub(r"\b(jobs?|careers?|hiring)\b", "", company, flags=re.I).strip(" -–|")
        return first[:300], company[:200]
    # fallback: infer company from ATS hostname
    host = re.sub(r"^https?://", "", url).split("/")[0]
    return text[:300], host.split(".")[0].title() if host else ""


def _guess_location(snippet: str) -> str:
    match = re.search(r"\b(?:in|at|based in)\s+([A-ZÄÖÜ][\wäöüßéèêàçñ\- ]{2,40})", snippet or "")
    return match.group(1).strip() if match else ""
