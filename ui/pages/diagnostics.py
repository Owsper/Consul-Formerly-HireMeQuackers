"""Search Diagnostics: source-by-source truth, scan history and manual assistance."""

from __future__ import annotations

import urllib.parse

import streamlit as st

from core.database import session_scope
from services.company_service import list_companies
from services.profile_service import get_active_profile
from services.query_planner import build_rule_based_plan
from services.search_orchestrator import (
    ScanRequest, last_scan, run_scan, scan_history, source_catalog,
)
from services.settings_service import load_preferences
from ui import components as c


def _search_links(query: str, location: str) -> list[tuple[str, str]]:
    q = urllib.parse.quote_plus(query)
    loc = urllib.parse.quote_plus(location)
    links = [
        ("LinkedIn Jobs", f"https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}"),
        ("Indeed", f"https://www.indeed.com/jobs?q={q}&l={loc}"),
        ("Google Jobs", f"https://www.google.com/search?q={q}+jobs+{loc}&ibp=htl;jobs"),
        ("StepStone", f"https://www.stepstone.de/jobs/{q}?where={loc}"),
        ("Welcome to the Jungle", f"https://www.welcometothejungle.com/en/jobs?query={q}"),
    ]
    return links


def _render_manual_assistance(plan) -> None:
    st.markdown("##### Manual Search Assistance")
    st.caption(
        "For sources that block automated access (CAPTCHA, login, bot protection), the app does not "
        "try to bypass anything. Instead, open the search yourself and paste a job URL under "
        "Job Discovery → Add a job manually."
    )
    if plan is None:
        st.info("Generate a search plan in Job Discovery to see prepared searches here.")
        return
    queries = plan.queries[:6]
    if not queries:
        return
    location = ", ".join(plan.queries[0].query.split()[-1:]) if plan.queries else ""
    for query in queries:
        with st.expander(f"{query.query}  ·  {query.language.upper()} · priority {query.priority}"):
            st.code(query.query, language=None)
            for name, url in _search_links(query.query, location):
                st.link_button(name, url, use_container_width=False)


def _render_catalog() -> None:
    with session_scope() as session:
        catalog = source_catalog(session)
        companies = list_companies(session)
    st.subheader("Source configuration")
    st.dataframe(
        [{"Source": item["name"], "Kind": item["kind"],
          "Enabled": "Yes" if item["enabled"] else "No",
          "Configured": "Yes" if item["configured"] else "No",
          "Last status": c.STATUS_LABEL.get(item["status"], item["status"]),
          "Requires": ", ".join(item["requires"]) or "—",
          "Missing": ", ".join(item["missing"]) or "—"} for item in catalog],
        hide_index=True, use_container_width=True,
    )
    with st.expander("Connector capabilities"):
        for item in catalog:
            st.markdown(f"**{item['name']}** — {item['description'] or 'No description.'}")
    st.caption(f"{len(companies)} company/board entries in the registry. "
               "A source is never reported healthy unless a request actually succeeded.")


def render() -> None:
    c.page_header("Search Diagnostics", "What was requested, what succeeded, and what failed — with no invented results.")
    with session_scope() as session:
        latest = last_scan(session)
        history = scan_history(session, limit=10)
        active = get_active_profile(session)
        prefs = load_preferences(session)
        plan = build_rule_based_plan(active[1].data, prefs) if active else None

    if st.session_state.get("search_plan"):
        from core.schemas import SearchPlan

        try:
            plan = SearchPlan.model_validate(st.session_state.search_plan)
        except Exception:
            pass

    if latest is None:
        c.empty_state("No scan yet",
                      "Run a scan from Job Discovery. This page will then show every request outcome, "
                      "including sources that were missing configuration.",
                      mark="⌁")
        _render_catalog()
        st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
        _render_manual_assistance(plan)
        return

    failed = [s for s in latest.sources
              if s.status.value in {"unavailable", "rate_limited", "restricted", "partially_working"}]
    cols = st.columns(4)
    cols[0].metric("Jobs retrieved", latest.jobs_retrieved)
    cols[1].metric("New this scan", latest.jobs_new)
    cols[2].metric("Sources attempted", len(latest.sources))
    cols[3].metric("Failed/partial", len(failed))

    st.subheader("Last scan")
    st.caption(f"Started {latest.started_at:%d %b %Y %H:%M} · "
               f"finished {latest.finished_at:%H:%M}" if latest.finished_at else "Scan unfinished.")
    if latest.notes:
        for note in latest.notes:
            st.info(note)
    c.source_health_table([s.model_dump(mode="json") for s in latest.sources])
    with st.expander("Per-source detail"):
        for source in latest.sources:
            st.markdown(f"**{source.display_name or source.connector}** — "
                        f"{c.status_badge(source.status.value)}", unsafe_allow_html=True)
            st.caption(f"Queries: {source.queries_executed} · requests "
                       f"{source.requests_ok}/{source.requests_made} OK · "
                       f"{source.jobs_found} found, {source.jobs_accepted} accepted · "
                       f"{source.duration_seconds:.1f}s")
            if source.error:
                st.code(source.error)
            if source.detail:
                st.caption(source.detail)

    if failed:
        if st.button(f"Retry {len(failed)} failed source(s)", type="primary"):
            with session_scope() as session:
                active = get_active_profile(session)
                if active is None:
                    st.error("No approved profile.")
                    return
                request = ScanRequest(
                    preferences=load_preferences(session), plan=plan,
                    profile_data=active[1].data, evidence=active[1].evidence,
                    profile_id=active[0].id,
                    only=[s.connector for s in failed],
                )
                with st.spinner("Retrying…"):
                    summary = run_scan(session, request)
            st.success(f"Retry finished: {summary.jobs_new} new job(s).")
            st.rerun()
    if latest.not_scanned:
        st.caption("Not scanned (disabled): " + ", ".join(latest.not_scanned))

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    st.subheader("Scan history")
    st.dataframe(
        [{"Scan": row.id[:8], "Started": row.started_at, "Status": row.status,
          "Sources": len(row.sources)} for row in history],
        hide_index=True, use_container_width=True,
    )

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    _render_catalog()
    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    _render_manual_assistance(plan)
