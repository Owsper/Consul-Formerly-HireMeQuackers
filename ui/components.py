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


PAGE_ICONS = {
    "Dashboard": "M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z",
    "Ground Truth CV": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zm-1 7V3.5L18.5 9zM8 13h8v2H8zm0 4h5v2H8z",
    "Job Discovery": "M15.5 14h-.8l-.3-.3A6.5 6.5 0 1 0 14 15.5l.3.3v.8l5 5 1.5-1.5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z",
    "Search Configuration": "M3 17v2h6v-2zM3 5v2h10V5zm10 16v-2h8v-2h-8v-2h-2v6zM7 9v2H3v2h4v2h2V9zm14 4v-2H11v2zm-6-4h2V7h4V5h-4V3h-2z",
    "Saved Jobs": "M17 3H7a2 2 0 0 0-2 2v16l7-3 7 3V5a2 2 0 0 0-2-2z",
    "CV Studio": "M3 17.25V21h3.75L17.8 9.94l-3.75-3.75zM20.7 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75z",
    "Application Tracker": "M19 3h-4.2A3 3 0 0 0 12 1a3 3 0 0 0-2.8 2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-9 14-4-4 1.4-1.4 2.6 2.6 6.6-6.6L18 9z",
    "Search Diagnostics": "M3.5 18.5 9.5 12.5l4 4L22 6.9 20.6 5.5l-7.1 8-4-4L2 17z",
    "Settings": "M19.4 13a7.5 7.5 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7 7 0 0 0-1.7-1L15 3h-4l-.4 2.7a7 7 0 0 0-1.7 1l-2.5-1-2 3.5L6.6 11a7.5 7.5 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7 7 0 0 0 1.7 1L11 21h4l.4-2.7a7 7 0 0 0 1.7-1l2.5 1 2-3.5zM13 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z",
}


def _page_index(title: str) -> str:
    from ui.nav import PAGES
    for i, (_, label, _) in enumerate(PAGES, 1):
        if label == title:
            return f"{i:02d}"
    return "··"


def icon_svg(path: str, size: int = 20) -> str:
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" aria-hidden="true">'
            f'<path fill="currentColor" d="{path}"/></svg>')


def page_header(title: str, subtitle: str = "", *, kicker: str | None = None) -> None:
    eyebrow = kicker or PAGE_KICKERS.get(title, "consul workspace")
    # A one-sentence subhead reads as a label, so it drops the trailing period.
    if subtitle.endswith(".") and ". " not in subtitle:
        subtitle = subtitle[:-1]
    index = _page_index(title)
    icon = PAGE_ICONS.get(title, PAGE_ICONS["Dashboard"])
    st.markdown(
        '<div class="consul-page-head">'
        f'<div class="consul-page-index" aria-hidden="true">{index}</div>'
        '<div class="consul-page-head-row">'
        f'<div class="consul-page-icon">{icon_svg(icon, 22)}</div>'
        '<div>'
        f'<div class="consul-eyebrow">consul <i>/</i> {esc(eyebrow)} <i>/</i> {index}</div>'
        f'<div class="consul-page-title">{esc(title)}</div>'
        '</div></div>'
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
    for n, (label, value) in enumerate(rows, 1):
        percent = max(0.0, min(100.0, 100 * value / top))
        body.append(
            f'<div class="consul-pipeline-row" style="--i:{n}">'
            f'<div class="consul-pipeline-label"><i>{n:02d}</i>{esc(label)}</div>'
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


_EMPTY_ART = """
<svg class="consul-empty-art" viewBox="0 0 220 150" aria-hidden="true">
  <defs>
    <linearGradient id="ceg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="currentColor" stop-opacity=".16"/>
      <stop offset="1" stop-color="currentColor" stop-opacity=".02"/>
    </linearGradient>
  </defs>
  <g class="sheet s3"><rect x="70" y="22" width="92" height="116" rx="6" fill="url(#ceg)" stroke="currentColor" stroke-opacity=".18"/></g>
  <g class="sheet s2"><rect x="58" y="16" width="92" height="116" rx="6" fill="url(#ceg)" stroke="currentColor" stroke-opacity=".24"/></g>
  <g class="sheet s1">
    <rect x="46" y="10" width="92" height="116" rx="6" fill="var(--consul-surface-alt)" stroke="currentColor" stroke-opacity=".32"/>
    <rect x="60" y="26" width="40" height="6" rx="3" fill="currentColor" opacity=".55"/>
    <rect x="60" y="42" width="64" height="4" rx="2" fill="currentColor" opacity=".22"/>
    <rect x="60" y="52" width="56" height="4" rx="2" fill="currentColor" opacity=".22"/>
    <rect x="60" y="62" width="60" height="4" rx="2" fill="currentColor" opacity=".22"/>
    <rect x="60" y="78" width="36" height="4" rx="2" fill="currentColor" opacity=".22"/>
    <rect x="60" y="88" width="48" height="4" rx="2" fill="currentColor" opacity=".22"/>
  </g>
  <g class="stamp" transform="rotate(-12 150 100)">
    <rect x="112" y="84" width="82" height="30" rx="4" fill="none" stroke="var(--consul-accent)" stroke-width="2" stroke-dasharray="4 3"/>
    <text x="153" y="104" text-anchor="middle" font-family="Geist Mono, monospace" font-size="11" fill="var(--consul-accent)" letter-spacing="1.5">$MARK</text>
  </g>
</svg>
"""


def empty_state(title: str, body: str, *, mark: str = "C") -> None:
    label = mark if len(mark) > 2 else "PENDING"
    art = _EMPTY_ART.replace("$MARK", esc(label.upper()[:8]))
    st.markdown(
        f"""<div class="consul-empty">{art}<div class="consul-empty-copy"><h3>{esc(title)}</h3><p>{esc(body)}</p></div></div>""",
        unsafe_allow_html=True,
    )


def readiness_dial(percent: float, done: int, total: int) -> str:
    """SVG ring that shows how far the workspace setup has progressed."""
    pct = max(0.0, min(100.0, percent))
    r = 64
    circ = 2 * 3.14159 * r
    off = circ * (1 - pct / 100)
    ticks = "".join(
        f'<line x1="90" y1="8" x2="90" y2="{14 if i % 5 else 18}" '
        f'transform="rotate({i * 6} 90 90)" />'
        for i in range(60)
    )
    return (
        '<div class="consul-dial">'
        '<svg viewBox="0 0 180 180" aria-hidden="true">'
        f'<g class="consul-dial-ticks">{ticks}</g>'
        f'<circle cx="90" cy="90" r="{r}" class="consul-dial-track"/>'
        f'<circle cx="90" cy="90" r="{r}" class="consul-dial-fill" '
        f'style="stroke-dasharray:{circ:.1f};stroke-dashoffset:{off:.1f};--dial-from:{circ:.1f}"/>'
        '</svg>'
        f'<div class="consul-dial-center"><b>{pct:.0f}<small>%</small></b>'
        f'<span>setup · {done}/{total}</span></div>'
        '</div>'
    )


def stepper(steps: list[tuple[str, str, bool]]) -> str:
    items = []
    first_open = next((i for i, (_, _, d) in enumerate(steps) if not d), None)
    for i, (label, hint, done) in enumerate(steps):
        state = "done" if done else ("next" if i == first_open else "todo")
        marker = "&#10003;" if done else f"{i + 1:02d}"
        items.append(
            f'<li class="consul-step {state}">'
            f'<div class="consul-step-mark">{marker}</div>'
            f'<div class="consul-step-body"><b>{esc(label)}</b><span>{esc(hint)}</span></div>'
            f'<div class="consul-step-tag">{"done" if done else ("up next" if state == "next" else "pending")}</div>'
            '</li>'
        )
    return '<ol class="consul-stepper">' + "".join(items) + "</ol>"


def stat_tile(label: str, value: int | str, hint: str, index: int, icon: str) -> str:
    return (
        f'<div class="consul-stat" style="--i:{index}">'
        f'<div class="consul-stat-top"><span>{esc(label)}</span>{icon_svg(icon, 18)}</div>'
        f'<div class="consul-stat-value">{esc(str(value))}</div>'
        f'<div class="consul-stat-hint">{esc(hint)}</div>'
        '</div>'
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
        st.markdown('<span class="consul-stamp">evidenced</span> '
                    + ", ".join(esc(s) for s in match.matching_skills),
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


def render_cv_html(cv: TailoredCV, *, preserve_order: bool = False) -> str:
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
    for section in ordered_sections(cv, preserve_order=preserve_order):
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
