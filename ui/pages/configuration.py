"""Search Configuration: preferences, sources, boards and scoring weights."""

from __future__ import annotations

import json

import streamlit as st

from config import get_settings, reload_settings
from core.database import session_scope
from core.exceptions import consulError
from core.models import Company, UserSetting
from core.job_taxonomy import category_options, specialisations_for, titles_for
from core.schemas import SearchPreferences
from services.application_service import add_custom_status, list_statuses, remove_custom_status
from services.company_service import add_company, list_companies, seed_company_registry
from services.job_scoring import DEFAULT_WEIGHTS, scoring_weights
from services.search_profile_service import (
    activate_profile, active_profile, deactivate_profile, duplicate_profile, list_profiles,
    new_profile, save_profile,
)
from services.search_orchestrator import (
    get_enabled_sources, set_enabled_sources, source_catalog,
)
from services.settings_service import load_preferences, save_preferences, set_setting
from ui import components as c

WORK_MODES = ["remote", "hybrid", "onsite"]
EMPLOYMENT_TYPES = ["full_time", "part_time", "contract", "internship", "working_student",
                    "graduate", "freelance"]


def _join(values: list[str]) -> str:
    return "\n".join(values or [])


def _split(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").replace(",", "\n").splitlines() if line.strip()]


def render() -> None:
    c.page_header("Search Configuration", "Preferences, sources, company boards and transparent scoring.")
    settings = get_settings()

    with session_scope() as session:
        prefs = load_preferences(session)
        profiles = list_profiles(session)
        current = active_profile(session)
        catalog = source_catalog(session)
        enabled = set(get_enabled_sources(session))
        companies = list_companies(session)
        statuses = list_statuses(session)
        weights = scoring_weights(session)

    tab_prefs, tab_sources, tab_scoring = st.tabs(
        ["Search preferences", "Sources & companies", "Scoring & statuses"]
    )

    with tab_prefs:
        st.markdown("##### Search profiles")
        st.caption(
            "A profile is a reusable search brief, not a filter that hides roles. Activate one "
            "profile at a time; duplicate it to explore another discipline without losing settings."
        )
        profile_ids = [p.profile_id for p in profiles]
        selected_id = st.selectbox(
            "Profile to edit", profile_ids or [""],
            index=profile_ids.index(current.profile_id) if current and current.profile_id in profile_ids else 0,
            format_func=lambda pid: next(
                (f"{p.name}{'  · active' if p.active else ''}" for p in profiles if p.profile_id == pid),
                "No profile yet"),
            key="profile_select",
        )
        editing = next((p for p in profiles if p.profile_id == selected_id), prefs)
        action_cols = st.columns([1, 1, 1, 1])
        if action_cols[0].button("New profile", use_container_width=True):
            with session_scope() as session:
                save_profile(session, new_profile())
            st.rerun()
        if action_cols[1].button("Duplicate", use_container_width=True, disabled=not selected_id):
            with session_scope() as session:
                duplicate_profile(session, selected_id)
            st.success("Profile duplicated (inactive). Activate it when ready.")
            st.rerun()
        if action_cols[2].button("Activate", use_container_width=True, disabled=not selected_id):
            with session_scope() as session:
                activate_profile(session, selected_id)
            st.rerun()
        if action_cols[3].button("Deactivate", use_container_width=True, disabled=not selected_id):
            with session_scope() as session:
                deactivate_profile(session, selected_id)
            st.warning("Profile deactivated. Activate another profile before planning a search.")
            st.rerun()

        category_choices = category_options()
        category_keys = [key for key, _ in category_choices]
        category_index = category_keys.index(editing.it_category) if editing.it_category in category_keys else 0
        st.markdown("##### Profile identity & discipline")
        cat_col, spec_col = st.columns(2)
        it_category = cat_col.selectbox(
            "IT category", category_choices, index=category_index,
            format_func=lambda item: item[1], key=f"pref_cat_{editing.profile_id or 'new'}",
            help="'Any IT Category' searches broadly. A category only seeds related titles; "
                 "your custom titles take precedence.",
        )
        category_key = it_category if isinstance(it_category, str) else it_category[0]
        spec_options = specialisations_for(category_key)
        specialisation = spec_col.selectbox(
            "Specialisation", ["", *spec_options],
            index=(["", *spec_options].index(editing.specialisation)
                   if editing.specialisation in spec_options else 0),
            key=f"pref_spec_{editing.profile_id or 'new'}_{category_key}",
            help="Optional focus inside the category, e.g. Gameplay Programming or Firmware.",
        )
        suggestions = titles_for(category_key, specialisation, limit=8)
        if suggestions:
            st.caption("Example titles for this category · " + ", ".join(suggestions))

        with st.form("preferences_form"):
            profile_name = st.text_input("Profile name", editing.name)
            st.markdown("##### Target roles & skills")
            col3, col4 = st.columns(2)
            target_titles = col3.text_area(
                "Custom target job titles (one per line)", _join(editing.target_titles), height=120,
                help="Highest priority. Enter any title, e.g. 'Unreal Engine Developer' or "
                     "'Working Student Embedded Systems'. Leave blank to use category titles.",
            )
            alternatives = col4.text_area(
                "Alternative titles (one per line)", _join(editing.alternative_titles), height=120,
                help="Adjacent roles you would accept.",
            )
            col5, col6, col7 = st.columns(3)
            required_skills = col5.text_area(
                "Required skills for this search", _join(editing.required_skills), height=90,
                help="Used for query keywords and match explanations. Does not alter Ground Truth.",
            )
            preferred_skills = col6.text_area(
                "Preferred skills", _join(editing.preferred_skills), height=90,
            )
            technologies = col7.text_area(
                "Technologies, tools & languages", _join(editing.technologies), height=90,
            )
            col8, col9, col10 = st.columns(3)
            seniority = col8.selectbox(
                "Seniority / experience level",
                ["", "internship", "working_student", "graduate", "junior", "mid", "senior", "lead"],
                index=(["", "internship", "working_student", "graduate", "junior", "mid",
                        "senior", "lead"].index(editing.seniority)
                       if editing.seniority in {"", "internship", "working_student", "graduate",
                                               "junior", "mid", "senior", "lead"} else 0),
            )
            types = col9.multiselect("Employment types", EMPLOYMENT_TYPES,
                                     default=[t for t in editing.employment_types if t in EMPLOYMENT_TYPES])
            modes = col10.multiselect("Work modes", WORK_MODES,
                                      default=[m for m in editing.work_modes if m in WORK_MODES])

            st.markdown("##### Locations, languages & constraints")
            col11, col12 = st.columns(2)
            countries = col11.text_input("Countries (comma separated)", ", ".join(editing.countries),
                                         placeholder="Germany, Netherlands")
            cities = col12.text_input("Cities (comma separated)", ", ".join(editing.cities))
            col13, col14, col15 = st.columns(3)
            languages = col13.text_input("Working languages (comma separated)",
                                         ", ".join(editing.languages))
            salary_min = col14.number_input("Minimum salary (annual, optional)",
                                            min_value=0.0, value=float(editing.salary_min or 0.0),
                                            step=1000.0)
            currency = col15.text_input("Currency", editing.salary_currency or "EUR")
            col16, col17 = st.columns(2)
            max_age = col16.number_input("Maximum posting age (days)", min_value=1, max_value=365,
                                         value=int(editing.max_posting_age_days or 60))
            relocate = col17.checkbox("Willing to relocate", value=bool(editing.willing_to_relocate))
            min_experience = st.number_input(
                "Minimum years of experience (optional)", min_value=0, max_value=50,
                value=int(editing.min_experience_years or 0), step=1,
            )
            auth_constraints = st.text_area(
                "Work authorisation constraints for this search",
                editing.work_authorization_constraints, height=70,
                placeholder="e.g. Part-time during term, full-time internship, German student visa",
            )
            excluded = st.text_area("Excluded companies (one per line)",
                                    _join(editing.exclude_companies), height=70)
            notes = st.text_area("Notes for the planner (optional)", editing.notes, height=70)
            activate = st.checkbox("Use this profile for discovery", value=True)
            submitted = st.form_submit_button("Save profile", type="primary")
        if submitted:
            updated = SearchPreferences(
                profile_id=editing.profile_id,
                active=activate,
                name=profile_name or "Untitled search",
                it_category=category_key,
                specialisation=specialisation,
                target_titles=_split(target_titles),
                alternative_titles=_split(alternatives),
                required_skills=_split(required_skills),
                preferred_skills=_split(preferred_skills),
                technologies=_split(technologies),
                seniority=seniority,
                countries=[x.strip() for x in countries.split(",") if x.strip()],
                cities=[x.strip() for x in cities.split(",") if x.strip()],
                work_modes=modes or WORK_MODES,
                employment_types=types or ["full_time"],
                languages=[x.strip() for x in languages.split(",") if x.strip()],
                salary_min=salary_min or None, salary_currency=currency or "EUR",
                max_posting_age_days=int(max_age), willing_to_relocate=relocate,
                min_experience_years=min_experience or None,
                work_authorization_constraints=auth_constraints,
                exclude_companies=_split(excluded), notes=notes,
            )
            with session_scope() as session:
                save_profile(session, updated, activate=activate)
            st.success("Search profile saved. Regenerate the plan in Job Discovery to use it.")
            st.rerun()

        st.caption(
            "Profiles guide discovery; they never hide an eligibility problem. Missing languages, "
            "work authorization and sponsorship are always surfaced in the match."
        )

    with tab_sources:
        st.markdown("##### Source status")
        rows = []
        for item in catalog:
            rows.append({
                "Enabled": item["enabled"],
                "Source": item["name"],
                "Kind": item["kind"],
                "Status": c.STATUS_LABEL.get(item["status"], item["status"]),
                "Configuration": "Ready" if item["configured"] else "Missing: " + ", ".join(item["missing"]),
            })
        edited = st.data_editor(
            rows, hide_index=True, use_container_width=True, key="source_editor",
            column_config={
                "Enabled": st.column_config.CheckboxColumn("Enabled", width="small"),
                "Source": st.column_config.TextColumn("Source", width="medium"),
                "Kind": st.column_config.TextColumn("Kind", width="small"),
                "Status": st.column_config.TextColumn("Last status", width="medium"),
                "Configuration": st.column_config.TextColumn("Configuration", width="large"),
            },
            disabled=["Source", "Kind", "Status", "Configuration"],
        )
        if st.button("Save enabled sources", type="primary"):
            chosen = [row["Source"] for row in edited.to_dict("records") if row.get("Enabled")]
            names = {item["name"]: item["key"] for item in catalog}
            with session_scope() as session:
                set_enabled_sources(session, [names[n] for n in chosen if n in names])
            st.success("Enabled sources updated.")
            st.rerun()

        missing = [item for item in catalog if not item["configured"]]
        if missing:
            with st.expander("How to configure missing integrations", expanded=False):
                st.markdown(
                    "Credentials and board ids live in `.env` only — never in the database or logs."
                )
                for item in missing:
                    st.markdown(f"**{item['name']}** — set `{', '.join(item['missing'])}` in `.env`. "
                                f"{item['description']}")
                if st.button("Reload .env"):
                    reload_settings()
                    st.success("Environment reloaded.")
                    st.rerun()

        st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
        st.markdown("##### Company boards & career pages")
        st.caption(
            "Register companies directly. If the URL points at a known ATS, the board is detected "
            "automatically; otherwise the career page itself is parsed."
        )
        if companies:
            st.dataframe(
                [{"Company": row.name, "Provider": row.ats_provider or "—",
                  "Identifier": row.ats_identifier or "—",
                  "Country": row.country or "—", "Jobs seen": row.jobs_seen,
                  "Health": c.STATUS_LABEL.get(row.health, row.health),
                  "Career page": row.career_url} for row in companies],
                hide_index=True, use_container_width=True,
            )
        with st.form("add_company_form"):
            col1, col2, col3 = st.columns([2, 4, 1])
            name = col1.text_input("Company name")
            url = col2.text_input("Career page or ATS board URL",
                                  placeholder="https://boards.greenhouse.io/acme")
            country = col3.text_input("Country")
            if st.form_submit_button("Add company", type="primary"):
                if not name.strip():
                    st.error("A company name is required.")
                else:
                    detected = add_company_checked(name, url, country)
                    if detected:
                        st.success(f"{name} added ({detected}).")
                        st.rerun()
        if st.button("Seed boards from .env"):
            with session_scope() as session:
                count = seed_company_registry(session)
            st.success(f"Registered {count} board entries from configuration.")
            st.rerun()

        st.caption(
            "No CAPTCHA, login or access-control bypass is implemented. Sources that require "
            "authentication are reported as unavailable, and Manual Search Assistance is offered instead."
        )

    with tab_scoring:
        st.markdown("##### Scoring weights")
        st.caption(
            "Weights are normalised to 100. The score is deterministic; every dimension shows its "
            "rationale in the job detail, and eligibility is reported separately from suitability."
        )
        with st.form("weights_form"):
            cols = st.columns(4)
            values: dict[str, float] = {}
            for index, (key, default) in enumerate(DEFAULT_WEIGHTS.items()):
                values[key] = cols[index % 4].number_input(
                    key.replace("_", " ").title(), min_value=0.0, max_value=100.0,
                    value=float(weights.get(key, default)), step=1.0,
                    key=f"weight_{key}",
                )
            if st.form_submit_button("Save weights", type="primary"):
                total = sum(values.values()) or 1
                normalized = {k: round(v / total * 100, 2) for k, v in values.items()}
                with session_scope() as session:
                    set_setting(session, "scoring_weights", normalized)
                st.success("Scoring weights updated. Existing matches keep their recorded score until re-scanned.")
                st.rerun()
        current_total = sum(values.values()) or 1
        st.dataframe(
            [{"Dimension": k.replace("_", " ").title(), "Weight": f"{v:.0f}",
              "Normalised": f"{v / current_total * 100:.1f}"} for k, v in values.items()],
            hide_index=True, use_container_width=True,
        )

        st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
        st.markdown("##### Application statuses")
        st.caption("The default pipeline is fixed; custom statuses appear in the tracker as extra columns.")
        st.write(", ".join(statuses))
        col1, col2 = st.columns([2, 1])
        new_status = col1.text_input("Add a custom status", placeholder="e.g. Take-home review")
        if col2.button("Add status", use_container_width=True) and new_status.strip():
            with session_scope() as session:
                add_custom_status(session, new_status)
            st.rerun()
        custom_only = [s for s in statuses if s not in
                       ["Discovered", "Shortlisted", "Reviewing", "CV generated", "Ready to apply",
                        "Applied", "Assessment", "Interview", "Technical interview",
                        "Final interview", "Offer received", "Rejected", "Withdrawn", "Archived"]]
        if custom_only:
            remove = st.selectbox("Remove a custom status", custom_only)
            if st.button("Remove status"):
                with session_scope() as session:
                    remove_custom_status(session, remove)
                st.rerun()

        st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
        st.markdown("##### LLM configuration")
        st.markdown(
            c.kv("LLM configured", "Yes" if settings.llm_available else "No")
            + c.kv("Provider", settings.llm_provider)
            + c.kv("Model", settings.active_model or "—")
            + c.kv("API key source", "GEMINI_API_KEY" if settings.llm_provider == "gemini"
                   else "LLM_API_KEY"),
            unsafe_allow_html=True,
        )
        if not settings.llm_available:
            st.info("Set GEMINI_API_KEY (or choose LLM_PROVIDER and set LLM_API_KEY) in .env to "
                    "enable LLM planning, extraction and CV drafting. Everything else works "
                    "offline with deterministic fallbacks.")


def add_company_checked(name: str, url: str, country: str) -> str:
    try:
        with session_scope() as session:
            row = add_company(session, name.strip(), url.strip(), country.strip())
            return row.ats_provider or "company_careers"
    except consulError as exc:
        st.error(exc.message)
        return ""
    except Exception as exc:  # pragma: no cover - defensive
        st.error(f"Could not add the company: {exc}")
        return ""
