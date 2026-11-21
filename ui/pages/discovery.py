"""Job Discovery: plan queries, scan sources, inspect evidence-based matches."""

from __future__ import annotations

import asyncio
import json

import httpx
import pandas as pd
import streamlit as st

from config import get_settings
from core.database import session_scope
from core.exceptions import consulError
from core.models import Job
from core.schemas import (
    JobRecord, ListingStatus, MatchResult, PlannedQuery, ScanSummary, SearchPlan,
    SearchPreferences,
)
from services.application_service import ensure_application
from services.cv_service import generate_cv_for_job
from services.job_enrichment import fetch_job_from_url, verify_listing
from services.job_scoring import score_record, scoring_weights
from services.job_service import (
    get_match, is_saved, list_jobs, row_to_record, save_job, save_match, unsave_job,
)
from core.job_taxonomy import (
    ANY_IT, category_label, category_options, specialisations_for, titles_for,
)
from services.profile_service import get_active_profile
from services.query_planner import plan_search
from services.search_profile_service import active_profile as active_search_profile
from services.search_orchestrator import (
    ScanRequest, get_enabled_sources, last_scan, run_scan, source_catalog,
)
from services.settings_service import load_preferences
from ui import components as c
from ui.nav import go


def _plan_from_state() -> SearchPlan | None:
    raw = st.session_state.get("search_plan")
    if not raw:
        return None
    try:
        return SearchPlan.model_validate(raw)
    except Exception:
        return None


def _save_plan(plan: SearchPlan) -> None:
    st.session_state.search_plan = plan.model_dump(mode="json")


def _render_search_focus(prefs: SearchPreferences) -> SearchPreferences:
    """Category, specialisation and a free-form title, without saving a profile."""
    st.markdown("##### Search focus")
    options = category_options()
    keys = [key for key, _ in options]
    index = keys.index(prefs.it_category) if prefs.it_category in keys else 0
    col1, col2, col3 = st.columns([2, 2, 3])
    category = col1.selectbox(
        "IT category", options, index=index, format_func=lambda item: item[1],
        key="disc_category",
        help="'Any IT Category' searches across every discipline. A category only seeds "
             "related titles; a custom title always takes precedence.",
    )
    category_key = category if isinstance(category, str) else category[0]
    specs = specialisations_for(category_key)
    spec = col2.selectbox(
        "Specialisation", ["", *specs],
        index=(["", *specs].index(prefs.specialisation) if prefs.specialisation in specs else 0),
        key=f"disc_spec_{category_key}",
        help="Optional focus inside the category.",
    )
    default_title = prefs.target_titles[0] if len(prefs.target_titles) == 1 else ""
    custom = col3.text_input(
        "Custom job title (optional)", default_title,
        placeholder="e.g. Unreal Engine Developer, SOC Analyst, PLC Programmer",
        key=f"disc_custom_{category_key}_{spec}",
        help="Enter any title. It becomes the primary target and is never replaced by category seeds.",
    )
    if category_key:
        suggestions = titles_for(category_key, spec, limit=5)
        if suggestions:
            st.caption("Category examples · " + ", ".join(suggestions))
    update: dict = {"it_category": category_key, "specialisation": spec}
    if custom.strip():
        update["target_titles"] = [custom.strip()]
    return prefs.model_copy(update=update)


def _render_plan(profile, prefs: SearchPreferences) -> None:
    plan = _plan_from_state()
    with st.expander("Search plan & queries", expanded=plan is None):
        st.caption(
            "Planned with local recruiting terminology for each target country — not a literal "
            "translation. Edit or delete any query before scanning; duplicates are removed."
        )
        col1, col2 = st.columns([1, 3])
        if col1.button("Generate search plan", type="primary", use_container_width=True):
            with st.spinner("Planning multilingual queries…"):
                generated = plan_search(profile, prefs)
            _save_plan(generated)
            st.rerun()
        if plan is not None:
            col2.markdown(
                c.badge("LLM plan" if plan.source == "llm" else "Rule-based plan",
                        "brand" if plan.source == "llm" else "neutral")
                + f" · {len(plan.queries)} queries",
                unsafe_allow_html=True,
            )
            if plan.warnings:
                for warning in plan.warnings:
                    st.warning(warning)
            st.caption(
                f"Category: {category_label(plan.it_category)}"
                + (f" · Specialisation: {plan.specialisation}" if plan.specialisation else "")
            )
            if plan.candidate_summary:
                st.caption(plan.candidate_summary)
            frame = pd.DataFrame([q.model_dump(mode="json") for q in plan.queries])
            edited = st.data_editor(
                frame, num_rows="dynamic", use_container_width=True, key="plan_editor",
                column_config={
                    "query": st.column_config.TextColumn("Query", width="large"),
                    "language": st.column_config.TextColumn("Lang", width="small"),
                    "target": st.column_config.SelectboxColumn(
                        "Target", options=["ats", "search", "careers", "any"], width="small"),
                    "priority": st.column_config.NumberColumn("Priority", min_value=1, max_value=5),
                    "rationale": st.column_config.TextColumn("Rationale", width="medium"),
                },
            )
            queries = []
            seen: set[str] = set()
            for row in edited.to_dict("records"):
                query = str(row.get("query") or "").strip()
                key = query.lower()
                if not query or key in seen:
                    continue
                seen.add(key)
                queries.append({"query": query, "language": str(row.get("language") or "en"),
                                "target": str(row.get("target") or "any"),
                                "priority": int(row.get("priority") or 3),
                                "rationale": str(row.get("rationale") or "")})
            if queries:
                updated = plan.model_copy(update={"queries": [
                    PlannedQuery.model_validate(q) for q in queries
                ]})
                _save_plan(updated)
            if plan.local_titles:
                st.markdown("**Local titles considered** · " + "; ".join(
                    f"{lang}: {', '.join(titles)}" for lang, titles in plan.local_titles.items()
                ))
            if plan.keywords:
                st.caption("Keywords: " + ", ".join(plan.keywords))


def _run_scan_ui(prefs: SearchPreferences, only: list[str]) -> None:
    plan = _plan_from_state()
    if plan is None:
        with session_scope() as session:
            active = get_active_profile(session)
            if active is None:
                st.error("Approve a Ground Truth profile first.")
                return
            plan = plan_search(active[1].data, prefs)
        _save_plan(plan)

    with session_scope() as session:
        active = get_active_profile(session)
        if active is None:
            st.error("Approve a Ground Truth profile first.")
            return
        profile_row, payload = active
        request = ScanRequest(
            preferences=prefs, plan=plan, profile_data=payload.data,
            evidence=payload.evidence, profile_id=profile_row.id, only=only or None,
        )
        bar = st.progress(0.0)
        status = st.empty()
        log = st.empty()

        def progress(info: dict) -> None:
            done, total = info.get("done", 0), info.get("total", 1) or 1
            bar.progress(min(1.0, done / total))
            status.markdown(f"**{info.get('stage', '').title()}** · {info.get('message', '')}")
            if info.get("source"):
                log.caption(f"Completed {done}/{total}: {info['source']}")

        try:
            summary = run_scan(session, request, progress=progress)
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            st.error(f"Scan failed: {type(exc).__name__}: {exc}")
            return
        st.session_state.last_scan_summary = summary.model_dump(mode="json")
    bar.progress(1.0)
    status.success(f"Scan complete — {summary.jobs_new} new job(s), {summary.jobs_unique} unique this run.")
    _render_scan_summary(summary)


def _render_scan_summary(summary: ScanSummary) -> None:
    with st.expander("Last scan report", expanded=True):
        if summary.notes:
            for note in summary.notes:
                st.info(note)
        cols = st.columns(4)
        cols[0].metric("Jobs seen", summary.jobs_retrieved)
        cols[1].metric("New", summary.jobs_new)
        cols[2].metric("Unique this scan", summary.jobs_unique)
        cols[3].metric("Snippets", summary.snippets)
        c.source_health_table([s.model_dump(mode="json") for s in summary.sources])
        failed = [s for s in summary.sources
                  if s.status.value in {"unavailable", "rate_limited", "restricted", "partially_working"}]
        if failed and st.button(f"Retry {len(failed)} failed source(s) now", key="retry_failed"):
            with session_scope() as session:
                prefs = load_preferences(session)
            _run_scan_ui(prefs, [s.connector for s in failed])


def _job_detail(job: Job, match: MatchResult | None, saved: bool, key: str) -> None:
    c.job_row(job, match)
    if match is not None:
        st.caption(f"Recommended action: {match.recommended_action}")
        if match.role_family:
            st.caption(f"Role family: {match.role_family}")
        if match.transferable_skills:
            st.info(
                "Transferable evidence (partial credit, not equivalence): "
                + "; ".join(match.transferable_skills)
            )
        with st.expander("Why this score"):
            c.score_breakdown(match)
            if match.transferability_notes:
                st.caption(" ".join(dict.fromkeys(match.transferability_notes)))
    st.markdown(
        " ".join(filter(None, [
            c.badge(job.listing_status.replace("_", " ").title(),
                    "success" if job.listing_status == "active" else "warn"),
            c.badge(job.work_mode.replace("_", " ").title(), "neutral") if job.work_mode != "unknown" else "",
            c.badge(f"{job.salary_currency} {job.salary_min:,.0f}–{job.salary_max:,.0f}",
                    "brand") if job.salary_min and job.salary_max else "",
            c.badge("Visa sponsorship stated", "success") if job.visa_sponsorship else "",
            c.badge("Snippet — verify before applying", "warn") if job.is_snippet else "",
        ])),
        unsafe_allow_html=True,
    )

    with st.expander("Job description & evidence"):
        if job.required_skills_json and job.required_skills_json != "[]":
            st.markdown("**Extracted requirements** · " + ", ".join(json.loads(job.required_skills_json)))
        if job.languages_json and job.languages_json != "[]":
            st.markdown("**Language requirements** · " + ", ".join(json.loads(job.languages_json)))
        st.text((job.description or "No description was retrieved for this listing.")[:12000])
        st.caption("Provenance")
        st.dataframe(
            [{"Source": s.connector, "Source job id": s.source_job_id, "URL": s.url}
             for s in job.sources],
            hide_index=True, use_container_width=True,
        )

    actions = st.columns([1, 1, 1, 1])
    if actions[0].button("Unsave" if saved else "Save", key=f"save_{key}", use_container_width=True):
        with session_scope() as session:
            if saved:
                unsave_job(session, job.id)
            else:
                save_job(session, job.id)
        st.rerun()
    if actions[1].button("Track application", key=f"track_{key}", use_container_width=True):
        try:
            with session_scope() as session:
                _, created = ensure_application(session, job.id)
            st.success("Application created in the tracker." if created else "Already in the tracker.")
        except consulError as exc:
            st.error(exc.message)
    if actions[2].button("Generate tailored CV", key=f"cv_{key}", use_container_width=True):
        try:
            with st.spinner("Building and validating the CV…"):
                with session_scope() as session:
                    row, cv, report = generate_cv_for_job(session, job.id)
            st.success(f"CV v{row.version} generated." + ("" if report.passed else " Review validation warnings."))
            st.session_state.cv_focus_job = job.id
            go("cv_studio")
        except consulError as exc:
            st.error(exc.message)
    if job.application_url:
        actions[3].link_button("Official apply page ↗", job.application_url,
                               use_container_width=True)

    if st.button("Re-check listing", key=f"verify_{key}", use_container_width=True):
        _verify_listing(job.id)


def _verify_listing(job_id: str) -> None:
    with session_scope() as session:
        row = session.get(Job, job_id)
        if row is None:
            return
        record = row_to_record(row)
        settings = get_settings()

        async def _check(rec: JobRecord):
            async with httpx.AsyncClient(timeout=settings.http_timeout_seconds,
                                         headers={"User-Agent": settings.user_agent},
                                         follow_redirects=True) as client:
                from connectors.base import HttpSession

                return await verify_listing(rec, HttpSession(client, settings))

        try:
            updated = asyncio.run(_check(record))
        except Exception as exc:
            st.error(f"Could not verify the listing: {type(exc).__name__}")
            return
        row.listing_status = updated.status.value
        row.last_verified = updated.last_verified
    st.success("Listing re-checked. Unreachable listings are kept and marked unverified.")


def _render_filters(session, prefs: SearchPreferences) -> dict:
    st.markdown("##### Filters")
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    search = col1.text_input("Search title, company or location", key="disc_search",
                             placeholder="e.g. Game Developer, SOC Analyst, Data Engineer")
    min_score = col2.slider("Min score", 0, 100, 0, key="disc_score")
    eligibility = col3.selectbox("Eligibility", ["Any", "eligible", "likely_eligible", "unclear", "ineligible"],
                                 key="disc_elig")
    work_mode = col4.selectbox("Work mode", ["Any", "remote", "hybrid", "onsite", "unknown"],
                               key="disc_mode")
    row2 = st.columns([1, 1, 1, 1])
    countries = [v for v in _distinct(session, Job.country) if v]
    country = row2[0].selectbox("Country", ["Any", *countries], key="disc_country")
    include_expired = row2[1].checkbox("Include expired", value=False, key="disc_expired")
    saved_only = row2[2].checkbox("Saved only", value=False, key="disc_saved")
    sort = row2[3].selectbox("Sort", ["Best match", "Newest", "Highest salary"], key="disc_sort")
    return {
        "search": search, "min_score": min_score if min_score > 0 else None,
        "eligibility": "" if eligibility == "Any" else eligibility,
        "work_mode": "" if work_mode == "Any" else work_mode,
        "country": "" if country == "Any" else country,
        "include_expired": include_expired, "saved_only": saved_only, "sort": sort,
    }


def _distinct(session, column) -> list[str]:
    from sqlalchemy import select

    return list(session.scalars(select(column).distinct().order_by(column)).all())


def _render_results(prefs: SearchPreferences) -> None:
    st.markdown("##### Results")
    with session_scope() as session:
        filters = _render_filters(session, prefs)
        limit = int(st.session_state.get("disc_limit", 25))
        jobs = list_jobs(
            session, limit=limit + 1, search=filters["search"], country=filters["country"],
            work_mode=filters["work_mode"], min_score=filters["min_score"],
            eligibility=filters["eligibility"], saved_only=filters["saved_only"],
            include_expired=filters["include_expired"],
        )
        has_more = len(jobs) > limit
        jobs = jobs[:limit]
        if filters["sort"] == "Newest":
            jobs.sort(key=lambda j: j.first_seen, reverse=True)
        elif filters["sort"] == "Highest salary":
            jobs.sort(key=lambda j: j.salary_max or j.salary_min or 0, reverse=True)
        items = [(job, get_match(session, job.id), is_saved(session, job.id)) for job in jobs]
        total = len(list_jobs(session, limit=10000, include_expired=filters["include_expired"]))

    if not items:
        c.empty_state(
            "No matching jobs yet",
            "Run a scan or loosen the filters. Nothing is shown unless a source actually returned it.",
            mark="⌕",
        )
        return

    st.caption(f"Showing {len(items)} of {total} discovered jobs, best evidence match first.")
    for index, (job, match, saved) in enumerate(items):
        label = f"{job.title} · {job.company or 'Unknown company'}"
        if match is not None:
            label += f"  —  {match.total_score:.0f}/100"
        if saved:
            label = "★ " + label
        with st.expander(label, expanded=False):
            _job_detail(job, match, saved, f"{job.id}_{index}")

    if has_more:
        if st.button("Load more jobs", use_container_width=True):
            st.session_state.disc_limit = limit + 25
            st.rerun()


def _render_manual_import() -> None:
    with st.expander("Add a job manually"):
        tab_url, tab_fields = st.tabs(["From a URL", "Enter details"])
        with tab_url:
            url = st.text_input("Public job posting URL", key="manual_url",
                                placeholder="https://company.com/jobs/123")
            if st.button("Fetch and parse", key="manual_fetch") and url:
                settings = get_settings()

                async def _fetch():
                    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds,
                                                 headers={"User-Agent": settings.user_agent},
                                                 follow_redirects=True) as client:
                        from connectors.base import HttpSession

                        return await fetch_job_from_url(url, HttpSession(client, settings))

                try:
                    record = asyncio.run(_fetch())
                except Exception as exc:
                    message = f"Could not fetch that page: {type(exc).__name__}: {exc}"
                    if "403" in str(exc) or "401" in str(exc):
                        message += ('\n\nThis site blocks automated access (login or bot protection). '
                                    'Open the posting in your browser and use the "Enter details" '
                                    'tab instead; the app does not bypass site protections.')
                    st.error(message)
                    return
                if not record.title:
                    st.error("No job title was found on that page; enter the details manually instead.")
                    return
                _persist_manual(record, url)
        with tab_fields:
            title = st.text_input("Job title", key="manual_title")
            company = st.text_input("Company", key="manual_company")
            location = st.text_input("Location", key="manual_location")
            link = st.text_input("Application URL", key="manual_link")
            description = st.text_area("Description", key="manual_desc", height=160)
            if st.button("Add job", key="manual_add", type="primary"):
                if not title.strip():
                    st.error("A job title is required.")
                    return
                record = JobRecord(source="manual", title=title, company=company,
                                   location=location, application_url=link, original_url=link,
                                   description=description, status=ListingStatus.UNVERIFIED)
                _persist_manual(record, link)


def _persist_manual(record: JobRecord, url: str) -> None:
    from services.deduplication import persist_job

    with session_scope() as session:
        active = get_active_profile(session)
        row, created = persist_job(session, record)
        if active is not None:
            prefs = load_preferences(session)
            match = score_record(record, active[1].data, active[1].evidence, prefs,
                                 job_id=row.id, weights=scoring_weights(session))
            save_match(session, row.id, match, profile_id=active[0].id)
    st.success("Job added." if created else "That job was already known; its record was merged.")
    st.rerun()


def render() -> None:
    c.page_header("Job Discovery", "Plan multilingual queries, scan real sources, and read the evidence behind every match.")
    with session_scope() as session:
        active = get_active_profile(session)
        if active is None:
            c.empty_state("Approve your Ground Truth first",
                          "Matching is only as honest as its source. Build and approve a profile before scanning.",
                          mark="01")
            if st.button("Open Ground Truth CV", type="primary"):
                go("profile")
            return
        prefs = load_preferences(session)
        search_profile = active_search_profile(session)
        profile = active[1].data
        catalog = source_catalog(session)
        enabled = set(get_enabled_sources(session))
        prior = last_scan(session)

    st.caption(
        (f"Active search profile: **{search_profile.name}**" if search_profile
         else "No active search profile — pick one in Search Configuration or plan from your "
              "professional title below.")
        + "  ·  Ground Truth is never changed by search settings."
    )
    if search_profile is None:
        st.warning("No active search profile. Activate or create one to keep searches reusable.")
        if st.button("Open Search Configuration"):
            go("configuration")

    prefs = _render_search_focus(prefs)
    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)

    usable = [s for s in catalog if s["configured"] and s["enabled"]]
    missing = [s for s in catalog if not s["configured"]]
    st.markdown(
        c.badge(f"{len(usable)} source(s) ready", "success" if usable else "warn")
        + (" " + c.badge(f"{len(missing)} need configuration", "neutral") if missing else ""),
        unsafe_allow_html=True,
    )
    if not usable:
        st.info(
            "No live source is configured yet, so a scan would have nothing to request. "
            "Add ATS boards or API keys in Search Configuration — or use Manual Search Assistance."
        )
        if st.button("Configure sources"):
            go("configuration")

    _render_plan(profile, prefs)

    st.markdown("##### Run a scan")
    choices = {s["key"]: s["name"] for s in catalog}
    selected = st.multiselect(
        "Sources", options=list(choices), default=[s["key"] for s in catalog if s["key"] in enabled],
        format_func=lambda k: choices.get(k, k), key="disc_sources",
    )
    scan_col, note_col = st.columns([1, 3])
    if scan_col.button("Start scan", type="primary", use_container_width=True, disabled=not usable):
        _run_scan_ui(prefs, selected)
    if not get_settings().llm_available:
        note_col.caption("LLM is off: planning uses the deterministic multilingual planner and jobs are scored by rules.")
    if prior is not None:
        with st.expander("Previous scan", expanded=False):
            _render_scan_summary(prior)

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    _render_results(prefs)
    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    _render_manual_import()
