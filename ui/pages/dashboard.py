"""Dashboard: a truthful overview of the current workspace."""

from __future__ import annotations

from datetime import date

import streamlit as st

from core.database import session_scope
from services.application_service import to_record, upcoming
from services.job_service import dashboard_stats, recent_jobs
from services.profile_service import get_active_profile
from services.search_orchestrator import last_scan, source_catalog
from services.search_profile_service import list_profiles
from ui import components as c
from ui.nav import go


def render() -> None:
    with session_scope() as session:
        active = get_active_profile(session)
        stats = dashboard_stats(session)
        recent = recent_jobs(session, limit=5)
        upcoming_items = upcoming(session, days=14)
        scan = last_scan(session)
        catalog = source_catalog(session)
        has_prefs = bool(list_profiles(session))
        profile_payload = active[1] if active else None
        recent_data = [
            {
                "id": job.id, "title": job.title, "company": job.company,
                "location": job.location, "first_seen": job.first_seen,
                "score": job.match.total_score if job.match else None,
            }
            for job in recent
        ]
        follow_ups = [(a, to_record(a)) for a in upcoming_items["follow_ups"]]
        interviews = [(a, to_record(a)) for a in upcoming_items["interviews"]]

    steps = [
        ("Approve your Ground Truth CV", "The evidence every score is checked against",
         bool(profile_payload)),
        ("Configure search preferences", "Roles, countries, languages and deal-breakers",
         bool(has_prefs)),
        ("Enable at least one source", "Job boards and company career pages",
         any(s["enabled"] and s["configured"] for s in catalog)),
        ("Run your first scan", "Real requests only, nothing invented",
         stats["total_jobs"] > 0),
        ("Track an application", "Notes, dates and follow-ups in one place",
         stats["applications"] > 0),
    ]
    done = sum(1 for *_, d in steps if d)
    strong = stats["strong"] + stats["excellent"]

    st.markdown(
        f"""
        <div class="consul-hero">
            <div class="consul-hero-copy">
                <div class="consul-eyebrow">consul <i>/</i> overview <i>/</i> 01</div>
                <h1>Roles scored against what your CV can <em>prove</em></h1>
                <p>Evidence-backed matching, multilingual discovery and tailored CVs that never
                claim more than your record shows.</p>
                <div class="consul-hero-chips">
                    <span><b>{stats["total_jobs"]}</b> discovered</span>
                    <span><b>{strong}</b> strong matches</span>
                    <span><b>{stats["saved"]}</b> shortlisted</span>
                </div>
            </div>
            {c.readiness_dial(100 * done / len(steps), done, len(steps))}
        </div>
        """,
        unsafe_allow_html=True,
    )

    tiles = [
        ("Strong matches", strong, "excellent + strong fit", c.PAGE_ICONS["Job Discovery"]),
        ("Shortlisted", stats["saved"], "saved for a closer look", c.PAGE_ICONS["Saved Jobs"]),
        ("Applications", stats["applications"], "tracked end to end", c.PAGE_ICONS["Application Tracker"]),
        ("Interviews", stats["interviews"], "scheduled or done", c.PAGE_ICONS["CV Studio"]),
    ]
    st.markdown(
        '<div class="consul-stats">'
        + "".join(c.stat_tile(l, v, h, i, ic) for i, (l, v, h, ic) in enumerate(tiles))
        + "</div>",
        unsafe_allow_html=True,
    )

    c.pipeline([
        ("Discovered", stats["total_jobs"]),
        ("Strong fit", strong),
        ("Shortlisted", stats["saved"]),
        ("Applications", stats["applications"]),
        ("Interviews", stats["interviews"]),
    ], note="live workspace")

    st.write("")
    left, right = st.columns([1.55, 1], gap="large")

    with left:
        st.markdown(
            f'<div class="consul-section-head"><h3>Next steps</h3>'
            f'<span>{done} of {len(steps)} complete</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(c.stepper(steps), unsafe_allow_html=True)
        st.write("")
        b1, b2, b3 = st.columns(3)
        if b1.button("Open Ground Truth", use_container_width=True):
            go("profile")
        if b2.button("Configure search", use_container_width=True):
            go("configuration")
        if b3.button("Find jobs", type="primary", use_container_width=True):
            go("discovery")

        st.write("")
        st.markdown('<div class="consul-section-head"><div class="t">Recently discovered</div><div class="n">latest 5</div></div>', unsafe_allow_html=True)
        if not recent_data:
            c.empty_state(
                "No jobs yet",
                "Approve your profile, configure search preferences, then run a scan. "
                "Only real results from real requests will appear here.",
                mark="NO SCAN",
            )
        else:
            for item in recent_data:
                st.markdown(
                    f"""
                    <div class="consul-card" style="padding:.75rem 1rem; margin-bottom:.5rem;">
                        <div style="display:flex; justify-content:space-between; gap:1rem;">
                            <div>
                                <div style="font-weight:650;">{c.esc(item['title'])}</div>
                                <div class="consul-muted" style="font-size:.82rem;">{c.esc(item['company'] or 'Company not stated')} · {c.esc(item['location'] or 'Location not stated')}</div>
                            </div>
                            <div>{c.badge(f"{item['score']:.0f}/100", "brand") if item['score'] is not None else c.badge("Not scored", "neutral")}</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            if st.button("Open Job Discovery →", key="dash_jobs"):
                go("discovery")

    with right:
        st.markdown('<div class="consul-section-head"><div class="t">Upcoming</div><div class="n">next 14 days</div></div>', unsafe_allow_html=True)
        if not follow_ups and not interviews:
            st.markdown(
                "<div class='consul-card consul-calendar-empty'>"
                "<div class='consul-cal'><b>" + date.today().strftime('%d') + "</b><span>"
                + date.today().strftime('%b') + "</span></div>"
                "<div class='consul-muted' style='font-size:.86rem;'>"
                "Nothing scheduled. Follow-up and interview dates you add in the tracker land here."
                "</div></div>", unsafe_allow_html=True,
            )
        else:
            for _, rec in follow_ups:
                st.markdown(
                    f"<div class='consul-card' style='padding:.6rem .8rem; margin-bottom:.4rem;'>"
                    f"<div style='font-size:.85rem; font-weight:600;'>Follow up · {rec.follow_up_date}</div>"
                    f"<div class='consul-muted' style='font-size:.8rem;'>Application #{rec.id}</div></div>",
                    unsafe_allow_html=True,
                )
            for _, rec in interviews:
                st.markdown(
                    f"<div class='consul-card' style='padding:.6rem .8rem; margin-bottom:.4rem;'>"
                    f"<div style='font-size:.85rem; font-weight:600;'>Interview · {rec.interview_date}</div>"
                    f"<div class='consul-muted' style='font-size:.8rem;'>{c.esc(rec.status)}</div></div>",
                    unsafe_allow_html=True,
                )

        st.write("")
        st.markdown('<div class="consul-section-head"><div class="t">Search health</div><div class="n">sources</div></div>', unsafe_allow_html=True)
        configured = [s for s in catalog if s["configured"]]
        enabled = [s for s in configured if s["enabled"]]
        st.markdown(
            c.kv("Sources available", f"{len(configured)} of {len(catalog)}")
            + c.kv("Sources enabled", str(len(enabled)))
            + c.kv("Last scan", c.time_ago(scan.finished_at) if scan else "never"),
            unsafe_allow_html=True,
        )
        if scan:
            healthy = sum(1 for s in scan.sources if s.status.value == "healthy")
            st.markdown(c.kv("Healthy in last scan", f"{healthy}/{len(scan.sources)}"),
                        unsafe_allow_html=True)
        if st.button("Open diagnostics →", key="dash_diag", use_container_width=True):
            go("diagnostics")

        missing = [s for s in catalog if not s["configured"]]
        if missing:
            st.caption("Optional integrations needing configuration: "
                       + ", ".join(f"{s['name']} ({', '.join(s['missing'])})" for s in missing[:3])
                       + ("…" if len(missing) > 3 else ""))
