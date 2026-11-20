"""Settings: privacy, backups, data export and runtime configuration."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from config import get_settings
from core.database import (
    backup_database, delete_all_user_data, export_all_data_json,
)
from services.job_service import count_jobs
from ui import components as c
from ui.nav import go

ENV_REFERENCE = [
    ("GEMINI_API_KEY", "Gemini API key for extraction, planning and CV drafting"),
    ("GEMINI_MODEL", "Model name, default gemini-2.5-flash"),
    ("LLM_ENABLED", "Set 0 for a fully offline run"),
    ("DATABASE_URL", "SQLAlchemy URL; defaults to the SQLite file in data/"),
    ("ADZUNA_APP_ID / ADZUNA_APP_KEY", "Adzuna aggregator credentials"),
    ("JOOBLE_API_KEY", "Jooble aggregator key"),
    ("SEARCH_PROVIDER / SEARCH_API_KEY", "brave, serper or tavily for web discovery"),
    ("GREENHOUSE_BOARDS, LEVER_COMPANIES, ASHBY_BOARDS, …", "Default ATS board seeds"),
    ("WORKDAY_TENANTS, TEAMTAILOR_SITES", "Additional ATS seed formats"),
    ("HTTP_TIMEOUT_SECONDS, MAX_CONCURRENCY", "Networking limits"),
]


def render() -> None:
    c.page_header("Settings", "Configuration, privacy and your data — you stay in control.")
    settings = get_settings()

    st.subheader("Appearance")
    dark = st.toggle("Dark mode", value=bool(st.session_state.get("dark_mode")), key="settings_dark")
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

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    st.subheader("Runtime configuration")
    col1, col2, col3 = st.columns(3)
    col1.markdown(c.kv("Gemini", "Configured" if settings.llm_available else "Not configured")
                  + c.kv("Model", settings.gemini_model), unsafe_allow_html=True)
    col2.markdown(c.kv("Database", Path(settings.database_url.split("sqlite:///")[-1]).name)
                  + c.kv("Data directory", str(settings.data_dir)), unsafe_allow_html=True)
    col3.markdown(c.kv("HTTP timeout", f"{settings.http_timeout_seconds}s")
                  + c.kv("Max concurrency", str(settings.max_concurrency)), unsafe_allow_html=True)
    with st.expander("Environment variables"):
        st.dataframe([{"Variable": k, "Purpose": v} for k, v in ENV_REFERENCE],
                     hide_index=True, use_container_width=True)
        st.caption("Secrets are read from the environment only. They are never stored in the database, "
                   "written to logs, or displayed in the UI.")

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    st.subheader("Backup & export")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Create database backup", use_container_width=True):
            path = backup_database()
            if path and path.exists():
                st.session_state.backup_bytes = path.read_bytes()
                st.session_state.backup_name = path.name
                st.success(f"Backup created: {path.name}")
            else:
                st.error("Backup is only available for SQLite databases.")
        if st.session_state.get("backup_bytes"):
            st.download_button("Download latest backup", st.session_state.backup_bytes,
                               file_name=st.session_state.get("backup_name", "backup.db"),
                               use_container_width=True)
    with col_b:
        if st.button("Export all data as JSON", use_container_width=True):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = settings.exports_dir / f"consul-export-{stamp}.json"
            path = export_all_data_json(target)
            st.session_state.export_bytes = path.read_bytes()
            st.session_state.export_name = path.name
            st.success(f"Exported {path.name}")
        if st.session_state.get("export_bytes"):
            st.download_button("Download JSON export", st.session_state.export_bytes,
                               file_name=st.session_state.get("export_name", "export.json"),
                               mime="application/json", use_container_width=True)

    st.caption("The backup contains your profile, jobs, matches, CVs and tracker data. Keep it private.")

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    st.subheader("Privacy")
    st.markdown(
        "- **Local by default.** Data lives in a local SQLite file; there is no account or cloud sync.\n"
        "- **EU/Germany defaults.** Data minimisation, purpose limitation and deletion are built in; "
        "only the CV text you upload is sent to Gemini, and only when you trigger extraction or an LLM action.\n"
        "- **No hidden requests.** Every outbound job-board request appears in Search Diagnostics.\n"
        "- **No secrets in exports.** API keys live only in the environment.\n"
        "- **Application evidence.** Rejected evidence is kept as history but never used in generated CVs."
    )
    log_file = settings.data_dir / "consul.log"
    logs_exist = log_file.exists()
    st.caption(f"Application log: {log_file} " + ("(personal data redacted)" if logs_exist else "(not created yet)"))

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    st.subheader("Delete data")
    with st.container():
        st.warning(
            "Deleting removes your profile, evidence, versions, jobs, matches, saved jobs, CVs and "
            "applications from this database. Exported files on disk are not touched."
        )
        confirm = st.text_input("Type DELETE to confirm", key="delete_confirm")
        if st.button("Delete all career data", disabled=confirm.strip() != "DELETE"):
            delete_all_user_data()
            for key in ("gt_draft", "gt_raw", "search_plan", "gt_status"):
                st.session_state.pop(key, None)
            st.success("All career data was deleted from the database.")
            st.rerun()
        if st.button("Delete generated CV files and uploads"):
            settings.ensure_dirs()
            removed = 0
            for folder in (settings.exports_dir, settings.uploads_dir, settings.backups_dir):
                for path in folder.glob("*"):
                    if path.is_file():
                        path.unlink(missing_ok=True)
                        removed += 1
            st.success(f"Removed {removed} file(s).")

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        from core.database import session_scope

        with session_scope() as session:
            jobs = count_jobs(session)
        st.markdown(c.kv("Jobs in database", str(jobs))
                    + c.kv("App version", "1.0.0")
                    + c.kv("Stack", "Streamlit · SQLite · Gemini"), unsafe_allow_html=True)
    with col2:
        if st.button("Open Search Diagnostics", use_container_width=True):
            go("diagnostics")
        st.caption("consul never applies to jobs for you. You remain the applicant of record.")
