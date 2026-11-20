"""consul — evidence-based job discovery, CV tailoring and application tracking."""

from __future__ import annotations

import streamlit as st

from config import get_settings
from core.database import healthcheck, init_db, session_scope
from core.logging_config import configure_logging, get_logger

logger = get_logger("app")

st.set_page_config(
    page_title="consul — career workspace",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _bootstrap() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    configure_logging()
    init_db()
    if "dark_mode" not in st.session_state:
        try:
            from services.settings_service import load_ui_settings

            with session_scope() as session:
                st.session_state.dark_mode = bool(load_ui_settings(session).get("dark_mode", True))
        except Exception:
            st.session_state.dark_mode = True
    if "page" not in st.session_state:
        st.session_state.page = "dashboard"


@st.cache_resource(show_spinner=False)
def _database_ready() -> bool:
    return healthcheck()


def main() -> None:
    _bootstrap()
    from ui import theme
    from ui.nav import render_sidebar

    theme.inject_css()
    page = render_sidebar()

    if not _database_ready():
        st.error("The database could not be opened. Check DATA_DIR permissions and reload.")
        return

    try:
        if page == "dashboard":
            from ui.pages import dashboard as view
        elif page == "profile":
            from ui.pages import profile as view
        elif page == "discovery":
            from ui.pages import discovery as view
        elif page == "configuration":
            from ui.pages import configuration as view
        elif page == "saved":
            from ui.pages import saved as view
        elif page == "cv_studio":
            from ui.pages import cv_studio as view
        elif page == "tracker":
            from ui.pages import tracker as view
        elif page == "diagnostics":
            from ui.pages import diagnostics as view
        else:
            from ui.pages import settings as view
        view.render()
    except Exception as exc:  # pragma: no cover - top-level UI boundary
        logger.exception("Page '%s' crashed", page)
        st.error(
            f"Something went wrong while rendering this page ({type(exc).__name__}). "
            "Your data is safe. Check the log for details, or switch pages and retry."
        )
        with st.expander("Technical detail"):
            st.code(f"{type(exc).__name__}: {exc}")

    st.markdown(
        '<div class="consul-app-footer">consul · local-first · every match is explainable · '
        'you are the applicant</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
