"""Saved jobs: the shortlist between discovery and applying."""

from __future__ import annotations

import streamlit as st

from core.database import session_scope
from core.exceptions import consulError
from services.application_service import ensure_application, get_application_for_job
from services.cv_service import generate_cv_for_job
from services.job_service import get_match, list_jobs, save_job, unsave_job
from ui import components as c
from ui.nav import go


def render() -> None:
    c.page_header("Saved Jobs", "Your shortlist. Save from discovery, then decide where to invest time.")
    with session_scope() as session:
        jobs = list_jobs(session, saved_only=True, limit=500)
        items = []
        for job in jobs:
            saved = job.saved
            items.append({
                "id": job.id, "title": job.title, "company": job.company,
                "location": job.location, "url": job.application_url,
                "notes": saved.notes if saved else "",
                "match": get_match(session, job.id),
                "application": get_application_for_job(session, job.id) is not None,
            })

    if not items:
        c.empty_state(
            "Nothing saved yet",
            "Use Save on any discovered job. Saved jobs keep your notes and stay linked to their match evidence.",
            mark="★",
        )
        if st.button("Go to Job Discovery", type="primary"):
            go("discovery")
        return

    st.caption(f"{len(items)} saved job(s).")
    for index, item in enumerate(items):
        label = f"{item['title']} · {item['company'] or 'Unknown company'}"
        if item["match"] is not None:
            label += f" — {item['match'].total_score:.0f}/100"
        with st.expander(label, expanded=index == 0):
            st.markdown(
                f"<div class='consul-job-meta'>{c.esc(item['location'] or 'Location not stated')}</div>",
                unsafe_allow_html=True,
            )
            if item["match"] is not None:
                c.score_breakdown(item["match"])
            notes = st.text_area("Your notes", item["notes"], key=f"saved_notes_{item['id']}",
                                 height=100, placeholder="Contacts, questions, salary expectations…")
            col1, col2, col3, col4 = st.columns(4)
            if col1.button("Save notes", key=f"saved_notes_btn_{item['id']}",
                           use_container_width=True):
                with session_scope() as session:
                    save_job(session, item["id"], notes)
                st.success("Notes saved.")
            if col2.button("Remove from saved", key=f"saved_remove_{item['id']}",
                           use_container_width=True):
                with session_scope() as session:
                    unsave_job(session, item["id"])
                st.rerun()
            if col3.button("Track" if not item["application"] else "Open tracker",
                           key=f"saved_track_{item['id']}", use_container_width=True):
                if item["application"]:
                    go("tracker")
                try:
                    with session_scope() as session:
                        ensure_application(session, item["id"], status="Shortlisted")
                    st.success("Added to the application tracker as Shortlisted.")
                    go("tracker")
                except consulError as exc:
                    st.error(exc.message)
            if col4.button("Generate CV", key=f"saved_cv_{item['id']}", use_container_width=True):
                try:
                    with st.spinner("Generating and validating…"):
                        with session_scope() as session:
                            row, _, report = generate_cv_for_job(session, item["id"])
                    st.success(f"CV v{row.version} ready." if report.passed
                               else f"CV v{row.version} generated with validation warnings.")
                    st.session_state.cv_focus_job = item["id"]
                    go("cv_studio")
                except consulError as exc:
                    st.error(exc.message)
            if item["url"]:
                st.link_button("Open official application page ↗", item["url"])
            else:
                st.caption("No application URL was captured for this listing.")
