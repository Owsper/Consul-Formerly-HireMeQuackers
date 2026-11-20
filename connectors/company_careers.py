"""Company career page discovery and shared job-page parsing.

Parsing order (also used by job enrichment):
  JSON-LD JobPosting -> Open Graph -> semantic HTML -> visible text.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.logging_config import get_logger
from core.schemas import JobRecord, ListingStatus
from core.security import is_safe_url, sanitize_html
from core.text import normalize_text, normalize_whitespace, similarity

logger = get_logger("careers")

ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.eu.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "apply.workable.com": "workable",
    "recruitee.com": "recruitee",
    "jobs.personio.de": "personio",
    "jobs.personio.com": "personio",
}


def detect_ats_from_url(url: str) -> tuple[str, str] | None:
    """Identify an ATS provider + board identifier from a public URL."""
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]
    if host in ATS_HOSTS:
        provider = ATS_HOSTS[host]
        if not parts:
            return None
        return provider, parts[0]
    if host.endswith(".recruitee.com"):
        return "recruitee", host.split(".")[0]
    if host.endswith(".jobs.personio.de") or host.endswith(".jobs.personio.com"):
        return "personio", host.split(".")[0]
    if host.endswith(".myworkdayjobs.com"):
        tenant = host.split(".")[0]
        site = parts[0] if parts else "External"
        return "workday", f"{tenant}/{site}@{host}"
    if host.endswith(".workable.com"):
        return "workable", host.split(".")[0]
    return None


def parse_jobposting_jsonld(html: str) -> dict[str, Any] | None:
    """Return the first JSON-LD JobPosting found on a page."""
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        nodes: list[Any] = []
        if isinstance(data, list):
            nodes = data
        elif isinstance(data, dict):
            nodes = data.get("@graph", [data]) or [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(t).lower() == "jobposting" for t in types if t):
                return node
    return None


def parse_open_graph(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        prop = tag.get("property") or tag.get("name") or ""
        content = tag.get("content") or ""
        if prop and content:
            meta[prop.lower()] = content
    return meta


def extract_main_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup.body
    return clean_html(str(main)) if main else ""


def jsonld_to_fields(node: dict[str, Any], page_url: str) -> dict[str, Any]:
    def text(value: Any) -> str:
        if isinstance(value, dict):
            return normalize_whitespace(value.get("name") or value.get("value") or "")
        if isinstance(value, list):
            return ", ".join(text(v) for v in value if v)
        return normalize_whitespace(str(value or ""))

    org = node.get("hiringOrganization") or {}
    company = text(org.get("name") if isinstance(org, dict) else org)
    website = text(org.get("sameAs") if isinstance(org, dict) else "")

    locations = node.get("jobLocation")
    if isinstance(locations, dict):
        locations = [locations]
    location_names: list[str] = []
    country = ""
    for loc in locations or []:
        if not isinstance(loc, dict):
            continue
        address = loc.get("address") or {}
        if isinstance(address, dict):
            parts = [text(address.get(k)) for k in
                     ("addressLocality", "addressRegion", "addressCountry")]
            location_names.append(", ".join(p for p in parts if p))
            country = country or text(address.get("addressCountry"))
        elif address:
            location_names.append(text(address))
        if loc.get("name"):
            location_names.append(text(loc.get("name")))
    if node.get("applicantLocationRequirements"):
        location_names.append(text(node.get("applicantLocationRequirements")))
    location = "; ".join(dict.fromkeys(location_names))

    salary_min = salary_max = None
    currency = ""
    frequency = ""
    salary = node.get("baseSalary") or {}
    if isinstance(salary, dict):
        currency = text(salary.get("currency"))
        value = salary.get("value") or {}
        if isinstance(value, dict):
            salary_min = _to_float(value.get("minValue") or value.get("value"))
            salary_max = _to_float(value.get("maxValue") or value.get("value"))
            frequency = text(value.get("unitText")).lower()
        else:
            salary_min = _to_float(value)

    remote = str(node.get("jobLocationType", "")).upper() == "TELECOMMUTE"
    employment_type = text(node.get("employmentType"))
    url = node.get("url") or page_url

    return {
        "title": text(node.get("title")),
        "company": company,
        "company_website": website,
        "location": location,
        "country": country,
        "description": clean_html(node.get("description") or ""),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": currency,
        "salary_frequency": frequency,
        "posted_at": parse_date(node.get("datePosted")),
        "closing_at": parse_date(node.get("validThrough")),
        "employment_type": infer_employment_type(text(node.get("title")), employment_type),
        "work_mode": "remote" if remote else infer_work_mode(location, clean_html(node.get("description") or "")),
        "application_url": url,
        "original_url": page_url,
        "language": normalize_text(text(node.get("inLanguage")))[:5],
    }


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "")) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_job_page(html: str, page_url: str) -> dict[str, Any]:
    """Best-effort structured extraction from a job page (never fabricates)."""
    node = parse_jobposting_jsonld(html)
    if node:
        fields = jsonld_to_fields(node, page_url)
        if fields.get("title"):
            return {**fields, "source": "jsonld"}
    og = parse_open_graph(html)
    soup = BeautifulSoup(html, "lxml")
    heading = soup.find("h1")
    title = og.get("og:title") or (heading.get_text(" ", strip=True) if heading else "")
    title = re.sub(r"\s*[|\-–]\s*[^|\-–]{1,40}$", "", normalize_whitespace(title)) or normalize_whitespace(title)
    company = og.get("og:site_name") or ""
    description = og.get("og:description") or ""
    body = extract_main_text(html)
    if len(body) > len(description):
        description = body
    return {
        "title": title,
        "company": company,
        "location": _find_location(body),
        "country": "",
        "description": description,
        "posted_at": parse_date(og.get("article:published_time")),
        "employment_type": infer_employment_type(title, body),
        "work_mode": infer_work_mode(title, body),
        "application_url": page_url,
        "original_url": page_url,
        "source": "html",
    }


def _find_location(text: str) -> str:
    match = re.search(r"\b(?:Location|Standort|Lieu|Ubicación|Locatie)\s*[:\-]\s*([^\n]{2,80})",
                      text or "", re.I)
    return normalize_whitespace(match.group(1)) if match else ""


def extract_career_links(html: str, base_url: str, ctx: ConnectorContext) -> list[dict[str, str]]:
    """Fallback: links on a career page that look like individual job postings."""
    soup = BeautifulSoup(html, "lxml")
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(base_url, href)
        if not is_safe_url(url) or url in seen:
            continue
        if not any(k in url.lower() for k in ("/job", "/jobs/", "/stelle", "/career", "/position", "/vacanc", "/offre", "/empleo")):
            continue
        label = normalize_whitespace(anchor.get_text(" ", strip=True))
        if len(label) < 3:
            continue
        if ctx.search_terms and not job_relevant(label, ctx):
            continue
        seen.add(url)
        found.append({"title": label[:300], "url": url})
        if len(found) >= 60:
            break
    return found


class CompanyCareersConnector(BaseConnector):
    key = "company_careers"
    display_name = "Company career pages"
    provider_kind = "careers"
    requires = ()
    description = "Direct career pages and JSON-LD JobPosting extraction."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = [c for c in ctx.companies
                 if c.career_url and c.provider in {"", "company_careers", "custom"}][:20]
        if not seeds:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error="No company career pages in the registry.",
                               detail="Add companies with a career page URL, or use company discovery.")

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for seed in seeds:
            try:
                html = await http.get_text(seed.career_url)
                requests_made += 1
            except Exception as exc:
                errors.append(f"{seed.name or seed.career_url}: {type(exc).__name__}")
                continue
            company = seed.name or urlparse(seed.career_url).hostname or ""
            fields = parse_job_page(html, seed.career_url)
            if fields.get("title") and (fields.get("source") == "jsonld" or len(fields.get("description") or "") > 400):
                jobs.append(self.make_job(
                    source=self.key,
                    source_job_id=seed.career_url[:280],
                    title=fields.get("title", ""),
                    company=fields.get("company") or company,
                    company_website=seed.career_url,
                    location=fields.get("location", ""),
                    country=fields.get("country") or seed.country,
                    work_mode=fields.get("work_mode") or infer_work_mode(fields.get("location", "")),
                    employment_type=fields.get("employment_type") or infer_employment_type(fields.get("title", "")),
                    seniority=infer_seniority(fields.get("title", "")),
                    salary_min=fields.get("salary_min"),
                    salary_max=fields.get("salary_max"),
                    salary_currency=fields.get("salary_currency", ""),
                    salary_frequency=fields.get("salary_frequency", ""),
                    posted_at=fields.get("posted_at"),
                    description=fields.get("description", ""),
                    application_url=fields.get("application_url") or seed.career_url,
                    original_url=seed.career_url,
                    language=fields.get("language", ""),
                ))
                continue
            for link in extract_career_links(html, seed.career_url, ctx):
                jobs.append(self.make_job(
                    source=self.key,
                    source_job_id=link["url"][:280],
                    title=link["title"],
                    company=company,
                    company_website=seed.career_url,
                    location="",
                    country=seed.country,
                    work_mode=infer_work_mode(link["title"]),
                    employment_type=infer_employment_type(link["title"]),
                    seniority=infer_seniority(link["title"]),
                    description="",
                    application_url=link["url"],
                    original_url=link["url"],
                    status=ListingStatus.UNVERIFIED,
                ))

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(errors[:5]),
                           detail=f"Scanned {len(seeds)} career pages.")
