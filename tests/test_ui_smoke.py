"""Every page must render on a fresh database without an exception."""

from pathlib import Path

import pytest

from ui.nav import PAGES

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.mark.parametrize("page", [key for key, _, _ in PAGES])
def test_page_renders(page):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.session_state["page"] = page
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    # The app-wide error boundary must not have caught anything either.
    assert not at.error, [e.value for e in at.error]


def test_tracker_renders_with_an_application(session, job_record):
    from streamlit.testing.v1 import AppTest

    from services.application_service import create_application, update_application
    from services.deduplication import persist_job
    from services.job_service import save_job

    row, _ = persist_job(session, job_record)
    save_job(session, row.id, notes="Shortlist")
    app = create_application(session, row.id, status="Shortlisted")
    update_application(session, app.id, notes="Recruiter replied")
    session.commit()

    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.session_state["page"] = "tracker"
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_discovery_and_configuration_render_role_agnostic_controls(session, approved_profile):
    from streamlit.testing.v1 import AppTest

    from services.search_profile_service import new_profile, save_profile

    save_profile(session, new_profile(name="Games", category="game_development"))
    session.commit()

    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.session_state["page"] = "discovery"
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    labels = [box.label for box in at.selectbox]
    assert "IT category" in labels
    assert "Specialisation" in labels
    assert "Custom job title (optional)" in [x.label for x in at.text_input]
    assert "Active search profile" in " ".join(x.value for x in at.caption)

    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.session_state["page"] = "configuration"
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    assert "Profile to edit" in [box.label for box in at.selectbox]
    assert "Save profile" in " ".join(b.label for b in at.form_submit_button)


def test_cv_studio_renders_preview_and_approval(session, approved_profile, profile_data,
                                                evidence, job_record):
    from streamlit.testing.v1 import AppTest

    from services.cv_service import generate_cv_for_job
    from services.deduplication import persist_job

    row, _ = persist_job(session, job_record)
    generate_cv_for_job(session, row.id, use_llm=False, formats=("docx", "pdf"))
    session.commit()

    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.session_state["page"] = "cv_studio"
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    text = " ".join(m.value for m in at.markdown)
    assert "Document preview" in text
    assert "Template fidelity" in text
    # The preview must be rendered pages, not a data: URL the browser refuses to open.
    assert at.image, "the PDF preview must render as page images"
    assert "ATS score for this posting" in text
    assert any("ATS score" in x.value for x in at.markdown)
    assert "Approve this CV" in " ".join(b.label for b in at.button)
    assert not at.download_button, "downloads must stay locked before approval"

    approve = next(b for b in at.button if b.label == "Approve this CV")
    approve.click().run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    assert any("Download DOCX" in b.label for b in at.download_button)
