"""JobTeaser connector (student and graduate job board).

JobTeaser protects its pages with a Cloudflare managed challenge and its
``robots.txt`` disallows keyword query strings (only ``?locale=`` and
``?page=`` are allowed). This connector therefore:

* requests only the robots-allowed listing URL (path plus ``locale``),
* never retries a challenge, never solves it and never imitates a browser
  session to get past it,
* reports ``restricted`` with an actionable message when challenged, so the
  UI can point the user at their browser and the manual import form,
* parses structured data only when a real listing page is served, and marks
  every record as a snippet that still needs verification.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode,
)
from core.schemas import JobRecord, ListingStatus
from core.text import normalize_whitespace

BASE = "https://www.jobteaser.com/{locale}/job-offers?locale={locale}"

COUNTRY_LOCALES = {
    "germany": "de", "deutschland": "de", "austria": "de", "österreich": "de",
    "switzerland": "de", "schweiz": "de", "france": "fr", "belgium": "fr",
    "belgique": "fr", "spain": "es", "españa": "es", "italy": "it", "italia": "it",
    "netherlands": "nl", "nederland": "nl", "poland": "pl", "polska": "pl",
    "portugal": "pt", "sweden": "sv", "denmark": "da", "finland": "fi",
    "norway": "no", "czech republic": "cs", "united kingdom": "en", "uk": "en",
    "ireland": "en", "united states": "en", "usa": "en",
}

JOB_LINK_RE = re.compile(r"/job-offers/[0-9a-f]{8}-[0-9a-f]{4}-", re.I)
CHALLENGE_MARKERS = ("security checkup", "cf-mitigated", "just a moment",
                     "attention required", "challenge-platform")
GENERIC_ANCHORS = {"apply", "apply now", "view job", "see offer", "details",
                   "learn more", "read more", "see more", "postuler",
                   "bewerben", "jetzt bewerben"}


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return normalize_whitespace(value.get("name") or value.get("value") or "")
    if isinstance(value, list):
        return normalize_whitespace(", ".join(_text(v) for v in value if v))
    return normalize_whitespace(str(value or ""))


def _jsonld_jobpostings(html: str) -> list[dict[str, Any]]:
    """Return every JSON-LD JobPosting on a page (direct or inside an ItemList)."""
    soup = BeautifulSoup(html, "lxml")
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            queue: list[Any] = [node, *node.get("@graph", [])]
            for item in node.get("itemListElement", []) or []:
                if isinstance(item, dict):
                    queue.extend([item, item.get("item")])
            for candidate in queue:
                if not isinstance(candidate, dict):
                    continue
                types = candidate.get("@type")
                types = types if isinstance(types, list) else [types]
                if not any(str(t).lower() == "jobposting" for t in types if t):
                    continue
                key = str(candidate.get("url") or candidate.get("title") or id(candidate))
                if key in seen:
                    continue
                seen.add(key)
                found.append(candidate)
    return found


class JobTeaserConnector(BaseConnector):
    key = "jobteaser"
    display_name = "JobTeaser"
    provider_kind = "aggregator"
    requires = ()
    description = ("Student and graduate job board (jobteaser.com). Browser-only: "
                   "Cloudflare blocks automated access, so only pages served "
                   "without a challenge can be read.")

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()

        locales: list[str] = []
        for country in ctx.preferences.countries:
            code = COUNTRY_LOCALES.get(country.strip().lower())
            if code and code not in locales:
                locales.append(code)
        if not locales:
            locales = ["en"]

        jobs: list[JobRecord] = []
        executed = 0
        errors: list[str] = []

        for locale in locales[:2]:
            url = BASE.format(locale=locale)
            try:
                html = await http.get_text(url)
                executed += 1
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {str(exc)[:60]}")
                continue

            if self._looks_challenged(html):
                # A 200 status with a challenge body is not a successful page.
                stats.ok = max(0, stats.ok - 1)
                stats.failed += 1
                stats.restricted = True
                stats.error = "Cloudflare challenge (restricted)"
                continue

            jobs.extend(self._parse_listing(html, url, locale))

        if stats.restricted:
            detail = ("JobTeaser serves a Cloudflare security check to automated clients and its "
                      "robots.txt disallows search query strings. The app does not bypass it. "
                      "Open JobTeaser in your browser, then use Job Discovery → Add a job "
                      "manually to score a posting.")
        elif jobs:
            detail = ("Listing pages only: titles and links are snippets. Open the posting "
                      "and add it manually to score the real requirements.")
        else:
            detail = ("No structured listings were found on the served page; JobTeaser may have "
                      "changed its layout or returned a reduced page.")

        return self.finish(result, started, stats, dedupe_batch(jobs), executed,
                           error="; ".join(errors[:3]), detail=detail)

    @staticmethod
    def _looks_challenged(html: str) -> bool:
        blob = (html or "")[:4000].lower()
        return any(marker in blob for marker in CHALLENGE_MARKERS)

    def _parse_listing(self, html: str, page_url: str, locale: str) -> list[JobRecord]:
        jobs: list[JobRecord] = []
        for node in _jsonld_jobpostings(html):
            title = normalize_whitespace(str(node.get("title") or ""))
            link = node.get("url") or node.get("sameAs") or ""
            if not title or not link:
                continue
            jobs.append(self._record(
                title=title,
                company=_text(node.get("hiringOrganization")),
                locale=locale,
                url=urljoin(page_url, str(link)),
                description=_text(node.get("description")),
                is_snippet=False,
            ))
        if jobs:
            return jobs

        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if not JOB_LINK_RE.search(urlparse(href).path or href):
                continue
            url = urljoin(page_url, href)
            if url in seen:
                continue
            label = normalize_whitespace(anchor.get("aria-label") or anchor.get_text(" ", strip=True))
            if not label or label.lower() in GENERIC_ANCHORS or len(label) < 4:
                continue
            seen.add(url)
            jobs.append(self._record(title=label[:300], company="", locale=locale,
                                     url=url, description="", is_snippet=True))
        return jobs

    def _record(self, *, title: str, company: str, locale: str, url: str,
                description: str, is_snippet: bool) -> JobRecord:
        return self.make_job(
            source=self.key,
            source_job_id=url[:280],
            title=title,
            company=company,
            location="",
            description=description[:20000],
            employment_type=infer_employment_type(title, description),
            seniority=infer_seniority(title),
            work_mode=infer_work_mode(title, description),
            application_url=url,
            original_url=url,
            status=ListingStatus.UNVERIFIED,
            is_snippet=is_snippet,
            language=locale,
        )
