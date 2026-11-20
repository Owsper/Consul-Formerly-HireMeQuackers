"""Reusable Streamlit / HTML fragments shared by the pages."""

from __future__ import annotations

import html
from datetime import date, datetime

import streamlit as st

from core.models import Job
from core.schemas import JobRecord, MatchResult, TailoredCV
from ui.theme import PAGE_KICKERS

STATUS_TONE = {
    "healthy": "success", "partially_working": "warn", "rate_limited": "warn",
    "restricted": "danger", "configuration_missing": "neutral", "unavailable": "danger",
    "unknown": "neutral",
}

STATUS_LABEL = {
    "healthy": "Healthy", "partially_working": "Partially working", "rate_limited": "Rate limited",
    "restricted": "Restricted", "configuration_missing": "Configuration missing",
    "unavailable": "Unavailable", "unknown": "Not scanned yet",
}

CLASSIFICATION_TONE = {
    "excellent": "success", "strong": "brand", "potential": "warn",
    "weak": "neutral", "not_recommended": "danger",
}

ELIGIBILITY_TONE = {
    "eligible": "success", "likely_eligible": "success", "unclear": "warn", "ineligible": "danger",
}

ELIGIBILITY_LABEL = {
    "eligible": "Eligible", "likely_eligible": "Likely eligible",
    "unclear": "Eligibility unclear", "ineligible": "Eligibility risk",
}


def esc(text: object) -> str:
    return html.escape(str(text or ""))


def page_header(title: str, subtitle: str = "", *, kicker: str | None = None) -> None:
    eyebrow = kicker or PAGE_KICKERS.get(title, "consul workspace")
    st.markdown(
        '<div class="consul-page-head">'
        f'<div class="consul-eyebrow">consul / {esc(eyebrow)}</div>'
        f'<div class="consul-page-title">{esc(title)}</div>'
        f'<div class="consul-page-sub">{esc(subtitle)}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def badge(text: str, tone: str = "neutral") -> str:
    return f'<span class="consul-badge {tone}">{esc(text)}</span>'


def status_badge(status: str) -> str:
    return badge(STATUS_LABEL.get(status, status.replace("_", " ").title()),
                 STATUS_TONE.get(status, "neutral"))


def score_badge(score: float, classification: str = "") -> str:
    tone = CLASSIFICATION_TONE.get(classification, "neutral")
    label = classification.replace("_", " ").title() if classification else ""
    return badge(f"{score:.0f}/100 · {label}".strip(" ·"), tone)


def section_label(text: str) -> None:
    st.markdown(f'<div class="consul-eyebrow" style="margin-bottom:.45rem;">{esc(text)}</div>',
                unsafe_allow_html=True)


def pipeline(rows: list[tuple[str, int]], *, title: str = "Search pipeline",
             note: str = "count") -> None:
    """A compact HTML funnel that stays legible in both themes."""
    top = max([value for _, value in rows] or [1]) or 1
    body = []
    for label, value in rows:
        percent = max(0.0, min(100.0, 100 * value / top))
        body.append(
            '<div class="consul-pipeline-row">'
            f'<div class="consul-pipeline-label">{esc(label)}</div>'
            f'<div class="consul-pipeline-track"><div class="consul-pipeline-fill" '
            f'style="width:{percent:.1f}%"></div></div>'
            f'<div class="consul-pipeline-value">{value}</div>'
            '</div>'
        )
    st.markdown(
        '<div class="consul-pipeline">'
        '<div class="consul-pipeline-head">'
        f'<b>{esc(title)}</b><span>{esc(note)}</span>'
        '</div>'
        + "".join(body)
        + '</div>',
        unsafe_allow_html=True,
    )


def empty_state(title: str, body: str, *, mark: str = "C") -> None:
    st.markdown(
        f"""
        <div class="consul-empty">
            <div class="consul-empty-mark">{esc(mark)}</div>
            <h3>{esc(title)}</h3>
            <p>{esc(body)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def card(inner_html: str) -> None:
    st.markdown(f'<div class="consul-card">{inner_html}</div>', unsafe_allow_html=True)


def kv(label: str, value: str) -> str:
    return f'<div class="consul-kv"><span>{esc(label)}</span><span>{esc(value)}</span></div>'


def human_date(value: date | datetime | None) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d %b %Y")


def time_ago(value: datetime | None) -> str:
    if not value:
        return "never"
    now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
    delta = now - value
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def job_meta(job: Job) -> str:
    parts = [job.location or job.country or "Location not stated"]
    if job.work_mode and job.work_mode != "unknown":
        parts.append(job.work_mode.replace("_", " "))
    if job.employment_type:
        parts.append(job.employment_type.replace("_", " "))
    if job.salary_min or job.salary_max:
        currency = job.salary_currency or ""
        if job.salary_min and job.salary_max:
            parts.append(f"{currency} {job.salary_min:,.0f}–{job.salary_max:,.0f}".strip())
        else:
            amount = job.salary_min or job.salary_max
            parts.append(f"{currency} {amount:,.0f}".strip())
    parts.append(time_ago(job.first_seen))
    return " · ".join(p for p in parts if p)


def job_row(job: Job, match: MatchResult | None = None) -> None:
    score_html = ""
    if match is not None:
        tone = CLASSIFICATION_TONE.get(match.classification.value, "neutral")
        score_html = (
            f'<div class="consul-score" title="{esc(match.classification.value.replace("_", " "))}">'
            f'<b>{match.total_score:.0f}</b><span>match</span></div>'
        )
    elif job.match:
        score_html = (
            f'<div class="consul-score"><b>{job.match.total_score:.0f}</b><span>match</span></div>'
        )
    flags = ""
    if match is not None and match.eligibility.status.value == "ineligible":
        flags = " " + badge("Eligibility risk", "danger")
    if job.is_snippet:
        flags += " " + badge("Snippet — unverified", "warn")
    if job.listing_status in {"expired", "unavailable"}:
        flags += " " + badge(job.listing_status.title(), "neutral")
    st.markdown(
        f"""
        <div style="display:flex; gap:.9rem; align-items:flex-start; justify-content:space-between;">
            <div style="min-width:0;">
                <div class="consul-job-title">{esc(job.title)}</div>
                <div class="consul-job-meta">{esc(job.company or "Company not stated")} · {esc(job_meta(job))}</div>
                <div style="margin-top:.3rem;">{flags}</div>
            </div>
            {score_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def score_breakdown(match: MatchResult) -> None:
    st.markdown(
        badge(ELIGIBILITY_LABEL.get(match.eligibility.status.value, match.eligibility.status.value),
              ELIGIBILITY_TONE.get(match.eligibility.status.value, "neutral"))
        + " " + badge(f"Suitability {match.suitability:.0f}/100", "brand")
        + " " + badge(match.classification.value.replace("_", " ").title(),
                      CLASSIFICATION_TONE.get(match.classification.value, "neutral")),
        unsafe_allow_html=True,
    )
    st.progress(min(1.0, max(0.0, match.total_score / 100)))
    st.caption(match.explanation)
    rows = [
        {"Dimension": d.name.replace("_", " ").title(), "Weight": f"{d.weight:.0f}",
         "Score": round(d.score), "Why": d.rationale}
        for d in match.dimensions
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True,
                 column_config={
                     "Score": st.column_config.ProgressColumn(
                         "Score", min_value=0, max_value=100, format="%d"),
                     "Weight": st.column_config.TextColumn("Weight", width="small"),
                 })
    if match.matching_skills:
        st.markdown("**Evidenced requirements** · " + ", ".join(esc(s) for s in match.matching_skills),
                    unsafe_allow_html=True)
    if match.missing_required_skills:
        st.markdown("**Not evidenced** · " + ", ".join(esc(s) for s in match.missing_required_skills),
                    unsafe_allow_html=True)
    for flag in match.red_flags:
        tone = "error" if "eligibility" in flag.lower() else ""
        st.markdown(f'<div class="consul-flag {tone}">{esc(flag)}</div>', unsafe_allow_html=True)
    if match.eligibility.concerns:
        with st.expander("Eligibility detail"):
            for concern in match.eligibility.concerns:
                st.write(f"- {concern}")


def render_cv_html(cv: TailoredCV) -> str:
    """Lightweight HTML preview. The PDF preview is the authoritative document."""
    from services.document_export import ordered_sections

    parts = ['<div class="consul-cv" style="font-family:Georgia,serif;">']
    parts.append(f"<h1 style='margin:0;font-size:1.5rem;letter-spacing:.01em;'>"
                 f"{esc(cv.header.name.upper())}</h1>")
    if cv.header.contact_lines:
        parts.append(f'<div class="cv-contact">{esc("  |  ".join(cv.header.contact_lines))}</div>')
    if cv.header.visa_status:
        parts.append(f'<div><b>Visa status:</b> {esc(cv.header.visa_status)}</div>')
    if cv.header.applying_for:
        parts.append(f'<div><b>Applying for:</b> {esc(cv.header.applying_for)}</div>')
    if cv.summary:
        parts.append(f"<p style='margin:.55rem 0 0;'>{esc(cv.summary)}</p>")
    for section in ordered_sections(cv):
        parts.append(
            "<h2 style='font-size:.78rem;letter-spacing:.06em;border-bottom:1px solid #111;"
            "text-decoration:underline;text-underline-offset:3px;margin:1rem 0 .35rem;'>"
            f"{esc(section.heading.upper())}</h2>"
        )
        rows = section.rows or (
            [{"label": "Technical", "text": ", ".join(section.skills)}]
            if section.kind == "skills" and section.skills else []
        )
        for row in rows:
            label = row.label if hasattr(row, "label") else row.get("label", "")
            text = row.text if hasattr(row, "text") else row.get("text", "")
            parts.append(
                '<div style="display:flex;gap:.5rem;">'
                f'<div style="flex:0 0 7.8rem;font-weight:400;">{esc(label)}</div>'
                f'<div style="flex:1;">{esc(text)}</div></div>'
            )
        for line in section.lines:
            parts.append(f"<div>{esc(line)}</div>")
        for entry in section.entries:
            title = esc(entry.title)
            org = f"  –  {esc(entry.organization)}" if entry.organization else ""
            parts.append(
                '<div class="cv-entry" style="margin-top:.35rem;">'
                '<div class="cv-entry-head" style="display:flex;gap:.5rem;">'
                f'<div style="flex:0 0 7.8rem;">{esc(entry.dates)}</div>'
                f"<div style='flex:1;'><b>{title}</b>{org}</div></div>"
            )
            if entry.technologies:
                parts.append(
                    '<div style="margin-left:8.3rem;font-style:italic;">'
                    f"{esc(', '.join(entry.technologies))}</div>"
                )
            if entry.bullets:
                parts.append('<ul style="margin:.15rem 0 .2rem 8.3rem;padding-left:1rem;">')
                parts.extend(f"<li>{esc(b.text)}</li>" for b in entry.bullets)
                parts.append("</ul>")
            parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def source_health_table(rows: list[dict]) -> None:
    st.dataframe(
        [
            {
                "Source": r.get("display_name") or r.get("connector", ""),
                "Status": STATUS_LABEL.get(r.get("status", ""), r.get("status", "")),
                "Requests": f"{r.get('requests_ok', 0)}/{r.get('requests_made', 0)} OK",
                "Found": r.get("jobs_found", 0),
                "Accepted": r.get("jobs_accepted", 0),
                "Time": f"{r.get('duration_seconds', 0):.1f}s",
                "Detail": r.get("error") or r.get("detail", ""),
            }
            for r in rows
        ],
        hide_index=True, use_container_width=True,
    )


def disclaimer(text: str) -> None:
    st.caption(text)
