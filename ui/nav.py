"""Page registry and the grouped workspace navigation."""

from __future__ import annotations

import html

import streamlit as st

PAGES: list[tuple[str, str, str]] = [
    ("dashboard", "Dashboard", "Overview of your search"),
    ("profile", "Ground Truth CV", "Your verified source of truth"),
    ("discovery", "Job Discovery", "Scan and review matches"),
    ("configuration", "Search Configuration", "Profiles, sources and scoring"),
    ("saved", "Saved Jobs", "Shortlisted opportunities"),
    ("cv_studio", "CV Studio", "Tailored, evidence-checked CVs"),
    ("builder", "CV Builder", "Edit a CV directly, check as you go"),
    ("tracker", "Application Tracker", "Applications and follow-ups"),
    ("diagnostics", "Search Diagnostics", "What each source actually did"),
    ("settings", "Settings", "Privacy, data and preferences"),
]

PAGE_LABEL = {key: label for key, label, _ in PAGES}

NAV_ICONS = {
    "dashboard": ":material/space_dashboard:",
    "profile": ":material/badge:",
    "discovery": ":material/travel_explore:",
    "configuration": ":material/tune:",
    "saved": ":material/bookmark:",
    "cv_studio": ":material/edit_document:",
    "builder": ":material/design_services:",
    "tracker": ":material/view_kanban:",
    "diagnostics": ":material/monitor_heart:",
    "settings": ":material/settings:",
}

NAV_GROUPS: list[tuple[str, list[str]]] = [
    ("Workspace", ["dashboard"]),
    ("Find work", ["profile", "discovery", "configuration", "saved"]),
    ("Apply", ["cv_studio", "builder", "tracker"]),
    ("Operations", ["diagnostics", "settings"]),
]


def go(page: str) -> None:
    st.session_state.page = page
    st.rerun()


def current_page() -> str:
    page = st.session_state.get("page", "dashboard")
    return page if page in PAGE_LABEL else "dashboard"


def render_sidebar() -> str:
    from ui.theme import apply_branding

    apply_branding()
    current = current_page()

    for group, keys in NAV_GROUPS:
        st.sidebar.markdown(f'<div class="consul-nav-label">{group}</div>',
                            unsafe_allow_html=True)
        for key in keys:
            label = PAGE_LABEL[key]
            if st.sidebar.button(
                label,
                key=f"nav_{key}",
                icon=NAV_ICONS.get(key),
                use_container_width=True,
                type="primary" if key == current else "secondary",
            ):
                st.session_state.page = key
                st.rerun()

    st.sidebar.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    dark = st.sidebar.toggle("Dark mode", value=bool(st.session_state.get("dark_mode")))
    if dark != bool(st.session_state.get("dark_mode")):
        st.session_state.dark_mode = dark
        try:
            from core.database import session_scope
            from services.settings_service import save_ui_settings

            with session_scope() as session:
                save_ui_settings(session, {"dark_mode": dark})
        except Exception:
            pass
        st.rerun()

    _profile_status()
    st.sidebar.markdown(
        '<div class="consul-side-footer">Local-first · no telemetry<br>You are the applicant of record</div>',
        unsafe_allow_html=True,
    )
    return current


def _profile_status() -> None:
    try:
        from core.database import session_scope
        from core.text import initials
        from services.profile_service import get_active_profile

        with session_scope() as session:
            active = get_active_profile(session)
            if active is None:
                st.sidebar.markdown(
                    '<div class="consul-side-profile">'
                    '<div class="consul-avatar">—</div>'
                    '<div><div class="consul-side-name">No profile</div>'
                    '<div class="consul-side-muted">Approve Ground Truth</div></div></div>',
                    unsafe_allow_html=True,
                )
                return
            profile, payload = active
            name = payload.data.personal.full_name or "Unnamed candidate"
            safe_name = html.escape(name)
            st.sidebar.markdown(
                '<div class="consul-side-profile">'
                f'<div class="consul-avatar">{initials(name)}</div>'
                f'<div><div class="consul-side-name">{safe_name}</div>'
                f'<div class="consul-side-muted">v{profile.version} · '
                f'<span class="consul-stamp">{len(payload.evidence)} evidenced</span></div></div></div>',
                unsafe_allow_html=True,
            )
    except Exception:
        return
