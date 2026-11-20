"""Application Tracker: kanban, table and per-application detail."""

from __future__ import annotations

import streamlit as st

from core.database import session_scope
from core.exceptions import consulError
from core.models import Application, Job
from core.schemas import WorkMode
from services.application_service import (
    activities_for, add_manual_job, clear_dates, create_application, ensure_application,
    kanban, list_applications, list_statuses, set_status, tracker_stats, upcoming,
    update_application,
)
from services.cv_service import list_versions
from services.job_service import list_jobs
from ui import components as c

BOARD_DEFAULT = ["Shortlisted", "Applied", "Interview", "Offer received"]


def _job_label(job: Job) -> str:
    return f"{job.title} — {job.company or 'Unknown company'}"


def _render_board() -> None:
    with session_scope() as session:
        statuses = list_statuses(session)
        board = kanban(session)
        preview = {
            status: [
                {"id": a.id, "job_id": a.job_id, "status": a.status,
                 "title": a.job.title, "company": a.job.company,
                 "follow_up": a.follow_up_date, "interview": a.interview_date}
                for a in rows
            ]
            for status, rows in board.items()
        }
    chosen = st.multiselect("Columns", statuses, default=[s for s in BOARD_DEFAULT if s in statuses],
                            key="board_columns")
    if not chosen:
        c.empty_state("Pick at least one column", "Select the pipeline stages you want to see.", mark="▤")
        return
    columns = st.columns(max(1, min(4, len(chosen))))
    for column, status in zip(columns, chosen):
        with column:
            items = preview.get(status, [])
            st.markdown(f"**{status}** " + c.badge(str(len(items)), "neutral"), unsafe_allow_html=True)
            if not items:
                st.caption("Empty")
            for item in items[:12]:
                st.markdown(
                    f"<div class='consul-card' style='padding:.6rem .7rem;'>"
                    f"<div style='font-weight:600;font-size:.86rem;'>{c.esc(item['title'])}</div>"
                    f"<div class='consul-muted' style='font-size:.76rem;'>{c.esc(item['company'] or '')}</div>"
                    f"<div class='consul-muted' style='font-size:.72rem;'>#{item['id']}"
                    + (f" · follow-up {item['follow_up']}" if item["follow_up"] else "")
                    + (f" · interview {item['interview']}" if item["interview"] else "")
                    + "</div></div>",
                    unsafe_allow_html=True,
                )
            if len(items) > 12:
                st.caption(f"+{len(items) - 12} more in the table view")
    st.caption("Move an application by opening it below and changing its status.")


def _render_upcoming() -> None:
    with session_scope() as session:
        data = upcoming(session, days=21)
        rows = [{"id": a.id, "job": a.job.title, "status": a.status,
                 "follow_up": a.follow_up_date, "interview": a.interview_date}
                for a in data["follow_ups"] + data["interviews"]]
        overdue = len(data["overdue"])
    if overdue:
        st.warning(f"{overdue} follow-up(s) are overdue.")
    if rows:
        st.dataframe(
            [{"Application": r["id"], "Role": r["job"], "Status": r["status"],
              "Follow-up": r["follow_up"], "Interview": r["interview"]} for r in rows],
            hide_index=True, use_container_width=True,
        )


def _render_detail(applications: list[dict]) -> None:
    if not applications:
        return
    st.subheader("Application detail")
    ids = [a["id"] for a in applications]
    chosen = st.selectbox(
        "Application", ids,
        format_func=lambda aid: next(f"#{aid} · {a['title']} — {a['company'] or 'Unknown'}"
                                     for a in applications if a["id"] == aid),
        key="tracker_detail_select",
    )
    with session_scope() as session:
        row = session.get(Application, chosen)
        if row is None:
            return
        job = row.job
        statuses = list_statuses(session)
        cvs = [{"id": cv.id, "version": cv.version} for cv in list_versions(session, row.job_id)]
        activities = [{"kind": a.kind, "message": a.message, "created": a.created_at}
                      for a in activities_for(session, chosen)]
        current = {
            "status": row.status, "notes": row.notes, "contact": row.contact_person,
            "follow_up": row.follow_up_date, "interview": row.interview_date,
            "salary": row.salary_notes, "outcome": row.outcome_notes,
            "cover": row.cover_letter, "cv": row.tailored_cv_id, "applied": row.applied_at,
            "job_title": job.title, "company": job.company, "url": job.application_url,
        }

    with st.form(f"detail_form_{chosen}"):
        col1, col2, col3 = st.columns(3)
        status = col1.selectbox("Status", statuses,
                                index=statuses.index(current["status"]) if current["status"] in statuses else 0)
        contact = col2.text_input("Contact person", current["contact"])
        salary = col3.text_input("Salary notes", current["salary"])
        col4, col5, col6 = st.columns(3)
        follow_up = col4.date_input("Follow-up date", value=current["follow_up"],
                                    key=f"follow_{chosen}")
        interview = col5.date_input("Interview date", value=current["interview"],
                                    key=f"interview_{chosen}")
        applied = col6.date_input("Applied on", value=current["applied"],
                                  key=f"applied_{chosen}")
        cv_ids = [None, *[cv["id"] for cv in cvs]]
        cv_index = cv_ids.index(current["cv"]) if current["cv"] in cv_ids else 0
        attached = st.selectbox(
            "Attached CV version", cv_ids, index=cv_index,
            format_func=lambda cid: "None" if cid is None else next(
                f"v{cv['version']}" for cv in cvs if cv["id"] == cid),
        )
        notes = st.text_area("Notes", current["notes"], height=110)
        outcome = st.text_area("Outcome notes", current["outcome"], height=70)
        cover = st.text_area("Cover letter / message used", current["cover"], height=90)
        clear_schedule = st.checkbox("Clear follow-up and interview dates")
        if st.form_submit_button("Update application", type="primary"):
            try:
                with session_scope() as session:
                    update_application(
                        session, chosen, status=status, notes=notes, contact_person=contact,
                        salary_notes=salary, outcome_notes=outcome, cover_letter=cover,
                        tailored_cv_id=attached, applied_at=applied,
                        follow_up_date=follow_up,
                        interview_date=interview,
                    )
                    if clear_schedule:
                        clear_dates(session, chosen)
                st.success("Application updated.")
                st.rerun()
            except consulError as exc:
                st.error(exc.message)

    st.caption(f"{current['job_title']} · {current['company'] or 'Unknown company'}")
    if current["url"]:
        st.link_button("Open application page ↗", current["url"])
    with st.expander("Activity history"):
        for activity in activities:
            st.markdown(f"**{activity['kind'].title()}** · {c.human_date(activity['created'])} — "
                        f"{c.esc(activity['message'])}", unsafe_allow_html=True)


def _render_table() -> None:
    with session_scope() as session:
        applications = list_applications(session, limit=1000)
        rows = []
        for row in applications:
            rows.append({
                "id": row.id, "title": row.job.title, "company": row.job.company,
                "status": row.status, "applied": row.applied_at,
                "follow_up": row.follow_up_date, "interview": row.interview_date,
                "updated": row.updated_at, "notes": row.notes[:120],
            })
        statuses = list_statuses(session)
    if not rows:
        c.empty_state("No applications yet",
                      "Create one from a discovered job, a saved job, or add a manual job below.",
                      mark="04")
        return
    st.dataframe(
        [{"#": r["id"], "Role": r["title"], "Company": r["company"], "Status": r["status"],
          "Applied": r["applied"], "Follow-up": r["follow_up"], "Interview": r["interview"],
          "Updated": r["updated"], "Notes": r["notes"]} for r in rows],
        hide_index=True, use_container_width=True,
    )
    st.caption(f"{len(rows)} application(s). Duplicate prevention: one application per job.")
    chosen = st.selectbox("Quick status change", [r["id"] for r in rows],
                          format_func=lambda i: next(f"#{i} · {r['title']}" for r in rows if r["id"] == i),
                          key="quick_status_id")
    quick = st.selectbox("New status", statuses, key="quick_status_value")
    if st.button("Apply status change"):
        with session_scope() as session:
            set_status(session, chosen, quick)
        st.success("Status updated.")
        st.rerun()


def _render_add() -> None:
    st.subheader("Add an application")
    with session_scope() as session:
        jobs = list_jobs(session, limit=200)
        options = {job.id: _job_label(job) for job in jobs}
    tab_existing, tab_manual = st.tabs(["From a discovered job", "Manual job"])
    with tab_existing:
        if not options:
            st.info("No jobs discovered yet. Use the manual tab.")
        else:
            job_id = st.selectbox("Job", list(options), format_func=lambda jid: options[jid])
            status = st.selectbox("Initial status", list_statuses_direct(), key="add_status")
            if st.button("Create application", type="primary"):
                try:
                    with session_scope() as session:
                        create_application(session, job_id, status=status)
                    st.success("Application created.")
                    st.rerun()
                except consulError as exc:
                    st.error(exc.message)
    with tab_manual:
        st.caption("Track something you found outside the app. A job record is created as unverified.")
        with st.form("manual_job_form"):
            title = st.text_input("Job title")
            company = st.text_input("Company")
            location = st.text_input("Location")
            country = st.text_input("Country")
            url = st.text_input("Application URL")
            description = st.text_area("Description", height=120)
            mode = st.selectbox("Work mode", ["unknown", "remote", "hybrid", "onsite"])
            if st.form_submit_button("Add job & application", type="primary"):
                if not title.strip():
                    st.error("A job title is required.")
                else:
                    try:
                        with session_scope() as session:
                            row, created = add_manual_job(
                                session, title=title, company=company, location=location,
                                country=country, url=url, description=description,
                                work_mode=WorkMode(mode),
                            )
                            ensure_application(session, row.id, status="Shortlisted")
                        st.success("Job and application added." if created else
                                   "Existing job reused; application added.")
                        st.rerun()
                    except consulError as exc:
                        st.error(exc.message)


def list_statuses_direct() -> list[str]:
    with session_scope() as session:
        return list_statuses(session)


def render() -> None:
    c.page_header("Application Tracker", "One row per real job. Notes, contacts, dates and outcomes in one place.")
    with session_scope() as session:
        stats = tracker_stats(session)
        applications = list_applications(session, limit=500)
        rows = [{"id": a.id, "title": a.job.title, "company": a.job.company,
                 "status": a.status} for a in applications]

    cols = st.columns(5)
    for col, (label, value) in zip(cols, [
        ("Total", stats["total"]), ("Active", stats["active"]),
        ("Interviews", stats["interviews"]), ("Offers", stats["offers"]),
        ("Rejected", stats["rejected"]),
    ]):
        col.metric(label, value)

    _render_upcoming()
    tab_board, tab_table, tab_add = st.tabs(["Board", "Table", "Add"])
    with tab_board:
        _render_board()
        _render_detail(rows)
    with tab_table:
        _render_table()
    with tab_add:
        _render_add()
