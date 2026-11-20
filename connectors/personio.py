"""Personio public XML career feed connector."""

from __future__ import annotations

import time

from config import Settings
from connectors.base import (
    BaseConnector, ConnectorContext, ConnectorResult, HttpSession, clean_html, dedupe_batch,
    infer_employment_type, infer_seniority, infer_work_mode, job_relevant, parse_date,
)
from core.schemas import JobRecord

FEEDS = [
    "https://{company}.jobs.personio.de/xml",
    "https://{company}.jobs.personio.com/xml",
]


class PersonioConnector(BaseConnector):
    key = "personio"
    display_name = "Personio"
    provider_kind = "ats"
    requires = ("PERSONIO_COMPANIES",)
    description = "Personio public XML career feeds."

    async def search(self, ctx: ConnectorContext, http: HttpSession,
                     settings: Settings) -> ConnectorResult:
        started = time.perf_counter()
        stats = http.stats
        result = self.new_result()
        seeds = self.seeds(ctx, settings)[:15]
        if not seeds:
            return self.finish(result, started, stats, [], 0, configured=False,
                               error="No Personio companies configured.",
                               detail="Add Personio subdomains (e.g. 'acme' for acme.jobs.personio.de).")

        jobs: list[JobRecord] = []
        errors: list[str] = []
        requests_made = 0

        for seed in seeds:
            xml_text = ""
            for template in FEEDS:
                try:
                    xml_text = await http.get_text(template.format(company=seed.identifier))
                    requests_made += 1
                    break
                except Exception as exc:
                    errors.append(f"{seed.identifier}: {type(exc).__name__}")
            if not xml_text:
                continue
            parsed = _parse_feed(xml_text, seed.identifier)
            company = seed.name or seed.identifier.title()
            for raw in parsed[:300]:
                if not job_relevant(raw["title"], ctx):
                    continue
                jobs.append(self.make_job(
                    source=self.key,
                    source_job_id=raw["id"],
                    title=raw["title"],
                    company=raw.get("subcompany") or company,
                    company_website=seed.career_url,
                    location=raw.get("office") or "",
                    country=seed.country,
                    work_mode=infer_work_mode(raw.get("office", ""), raw.get("description", "")),
                    employment_type=infer_employment_type(raw["title"], raw.get("employment_type", "")),
                    seniority=raw.get("seniority") or infer_seniority(raw["title"]),
                    posted_at=parse_date(raw.get("created_at")),
                    description=raw.get("description", ""),
                    application_url=raw.get("url", ""),
                    original_url=raw.get("url", ""),
                ))

        return self.finish(result, started, stats, dedupe_batch(jobs), requests_made,
                           configured=True, error="; ".join(sorted(set(errors))[:5]),
                           detail=f"Scanned {len(seeds)} Personio career feeds.")


def _parse_feed(xml_text: str, company_slug: str = "") -> list[dict]:
    from lxml import etree

    try:
        root = etree.fromstring(xml_text.encode("utf-8", errors="ignore"))
    except Exception:
        return []
    results: list[dict] = []

    def text(node, path: str) -> str:
        found = node.find(path)
        return (found.text or "").strip() if found is not None and found.text else ""

    for position in root.findall(".//position"):
        title = text(position, "name")
        if not title:
            continue
        pieces: list[str] = []
        for jd in position.findall(".//jobDescriptions/jobDescription"):
            heading = text(jd, "name")
            value = jd.find("value")
            body = clean_html(value.text or "") if value is not None and value.text else ""
            if heading:
                pieces.append(heading)
            if body:
                pieces.append(body)
        job_id = text(position, "id")
        results.append({
            "id": job_id,
            "title": title,
            "office": text(position, "office"),
            "subcompany": text(position, "subcompany"),
            "department": text(position, "department"),
            "employment_type": text(position, "employmentType"),
            "seniority": text(position, "seniority"),
            "created_at": text(position, "createdAt"),
            "description": "\n\n".join(pieces),
            "url": (f"https://{company_slug}.jobs.personio.de/job/{job_id}"
                    if company_slug and job_id else ""),
        })
    return results
