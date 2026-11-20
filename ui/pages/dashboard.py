"""Dashboard: a truthful overview of the current workspace."""

from __future__ import annotations

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

    name = profile_payload.data.personal.full_name.split(" ")[0] if profile_payload and profile_payload.data.personal.full_name else ""
    st.markdown(
        f"""
        <div class="consul-hero">
            <div class="consul-eyebrow">Career desk / workspace</div>
            <h1 style="margin:.3rem 0 .45rem 0; font-size:clamp(1.8rem,3vw,2.5rem);">
                {"Welcome back" + (", " + c.esc(name) if name else "") + "." if profile_payload else "A job search you can audit."}
            </h1>
            <p style="margin:0; max-width:660px; opacity:.9; font-size:.98rem; line-height:1.55;">
                Evidence-backed matching, multilingual discovery and CVs that only claim what you can prove.
            </p>
            <div class="consul-hero-note">
                {stats["total_jobs"]} roles discovered · {stats["strong"] + stats["excellent"]} strong matches · {stats["saved"]} shortlisted
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")

    cols = st.columns(5)
    metrics = [
        ("Jobs discovered", stats["total_jobs"]),
        ("Strong matches", stats["strong"] + stats["excellent"]),
        ("Saved", stats["saved"]),
        ("Applications", stats["applications"]),
        ("Interviews", stats["interviews"]),
    ]
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)

    c.pipeline([
        ("Discovered", stats["total_jobs"]),
        ("Strong fit", stats["strong"] + stats["excellent"]),
        ("Shortlisted", stats["saved"]),
        ("Applications", stats["applications"]),
        ("Interviews", stats["interviews"]),
    ], note="live workspace")

    st.write("")
    left, right = st.columns([1.55, 1])

    with left:
        st.subheader("Next steps")
        steps = [
            ("Ground Truth profile approved", bool(profile_payload)),
            ("Search preferences configured", bool(has_prefs)),
            ("At least one source enabled", any(s["enabled"] and s["configured"] for s in catalog)),
            ("Jobs discovered", stats["total_jobs"] > 0),
            ("First application tracked", stats["applications"] > 0),
        ]
        for label, done in steps:
            mark = "✓" if done else "○"
            st.markdown(
                f"<div class='consul-kv'><span>{mark} {c.esc(label)}</span>"
                f"<span>{c.badge('Done' if done else 'Pending', 'success' if done else 'neutral')}</span></div>",
                unsafe_allow_html=True,
            )
        st.write("")
        b1, b2, b3 = st.columns(3)
        if b1.button("Open Ground Truth", use_container_width=True):
            go("profile")
        if b2.button("Configure search", use_container_width=True):
            go("configuration")
        if b3.button("Find jobs", type="primary", use_container_width=True):
            go("discovery")

        st.write("")
        st.subheader("Recently discovered")
        if not recent_data:
            c.empty_state(
                "No jobs yet",
                "Approve your profile, configure search preferences, then run a scan. "
                "Only real results from real requests will appear here.",
                mark="01",
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
        st.subheader("Upcoming")
        if not follow_ups and not interviews:
            st.markdown(
                "<div class='consul-card'><div class='consul-muted' style='font-size:.86rem;'>"
                "No follow-ups or interviews scheduled. Dates you add in the tracker show up here."
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
        st.subheader("Search health")
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
