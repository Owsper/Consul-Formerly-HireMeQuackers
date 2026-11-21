from pathlib import Path

from core.schemas import (
    CoverLetterDraft, DocumentParagraph, EmailDraft, SkillCategory,
)
from services.application_documents import (
    cover_letter_filename, email_filename, generate_cover_letter, generate_recruiter_email,
    load_cover_letter, load_recruiter_email, save_cover_letter, save_recruiter_email,
    validate_cover_letter,
)
from services.document_export import export_cover_letter_docx


def _valid_ids(evidence) -> set[str]:
    return {e.evidence_id for e in evidence if e.status.value != "rejected"}


def test_rule_based_cover_letter_is_evidence_grounded(profile_data, evidence, job_record):
    draft, report = generate_cover_letter(
        profile_data, evidence, job_record, use_llm=False, language="en"
    )
    assert draft.generator == "rule_based"
    assert draft.greeting == "Dear Hiring Manager,"
    assert draft.signature == "Ada Lovelace"
    assert draft.paragraphs, "the letter must contain evidence-backed paragraphs"
    assert report.passed, [i.message for i in report.issues if i.severity == "error"]
    assert report.evidence_coverage == 1.0
    for paragraph in draft.paragraphs:
        assert paragraph.evidence_ids
        assert set(paragraph.evidence_ids) <= _valid_ids(evidence)
    assert "Senior Backend Engineer" in draft.to_text()
    assert "Ada Lovelace" in draft.to_text()


def test_rule_based_email_is_short_and_names_the_role(profile_data, evidence, job_record):
    draft, report = generate_recruiter_email(
        profile_data, evidence, job_record, use_llm=False, language="en"
    )
    assert draft.subject == "Application: Senior Backend Engineer at Acme — Ada Lovelace"
    assert report.passed, [i.message for i in report.issues if i.severity == "error"]
    assert draft.word_count() <= 180
    assert draft.paragraphs
    for paragraph in draft.paragraphs:
        assert set(paragraph.evidence_ids) <= _valid_ids(evidence)


def test_recipient_is_used_but_never_invented(profile_data, evidence, job_record):
    unnamed, _ = generate_cover_letter(
        profile_data, evidence, job_record, use_llm=False
    )
    assert unnamed.greeting == "Dear Hiring Manager,"

    named, report = generate_cover_letter(
        profile_data, evidence, job_record, use_llm=False,
        recipient_name="Jordan Lee", recipient_title="Talent Acquisition Lead",
    )
    assert named.greeting == "Dear Jordan Lee,"
    assert report.passed
    assert "Jordan Lee" in named.to_text()


def test_letter_generator_falls_back_offline(profile_data, evidence, job_record):
    draft, _ = generate_cover_letter(profile_data, evidence, job_record, use_llm=True)
    assert draft.generator == "rule_based"
    email, _ = generate_recruiter_email(profile_data, evidence, job_record, use_llm=True)
    assert email.generator == "rule_based"


def test_validator_rejects_uncited_claims_and_invented_metrics(profile_data, evidence,
                                                               job_record):
    good_id = evidence[0].evidence_id
    draft = CoverLetterDraft(
        greeting="Dear Hiring Manager,",
        signature="Ada Lovelace",
        paragraphs=[
            DocumentParagraph(text="Built Python APIs with FastAPI.", evidence_ids=[good_id]),
            DocumentParagraph(text="I admire your award-winning culture.", evidence_ids=[]),
            DocumentParagraph(text="Increased revenue by 987%.", evidence_ids=[good_id]),
            DocumentParagraph(text="Used a fake reference.", evidence_ids=["ev-does-not-exist"]),
        ],
        closing="Thank you.",
    )
    report = validate_cover_letter(draft, profile_data, evidence, job_record)
    assert report.passed is False
    assert report.unsupported_claims
    assert any(i.code == "uncited_claims" for i in report.issues)


def test_validator_rejects_learning_skills(profile_data, evidence, job_record):
    profile_data.skills.append(SkillCategory(name="Currently learning", skills=["Kubernetes"]))
    draft = CoverLetterDraft(
        greeting="Dear Hiring Manager,",
        signature="Ada Lovelace",
        paragraphs=[DocumentParagraph(
            text="I have strong Kubernetes experience with Python.",
            evidence_ids=[evidence[0].evidence_id],
        )],
        closing="Thank you.",
    )
    report = validate_cover_letter(draft, profile_data, evidence, job_record)
    assert report.passed is False
    assert any(i.code == "unsupported_skill_claim" for i in report.issues)


def test_validator_rejects_invented_recipient(profile_data, evidence, job_record):
    draft = CoverLetterDraft(
        greeting="Dear Sarah Miller,",
        signature="Ada Lovelace",
        paragraphs=[DocumentParagraph(
            text="I am a backend engineer with Python experience.",
            evidence_ids=[evidence[0].evidence_id],
        )],
        closing="Thank you.",
    )
    report = validate_cover_letter(draft, profile_data, evidence, job_record)
    assert report.passed is False
    assert any(i.code == "invented_recipient" for i in report.issues)


def test_drafts_persist_per_job(session, profile_data, evidence, job_record):
    letter, report = generate_cover_letter(profile_data, evidence, job_record, use_llm=False)
    email, email_report = generate_recruiter_email(
        profile_data, evidence, job_record, use_llm=False
    )
    save_cover_letter(session, "job-1", letter, report)
    save_recruiter_email(session, "job-1", email, email_report)
    session.commit()

    loaded_letter = load_cover_letter(session, "job-1")
    loaded_email = load_recruiter_email(session, "job-1")
    assert loaded_letter is not None and loaded_email is not None
    assert loaded_letter[0].to_text() == letter.to_text()
    assert loaded_email[0].subject == email.subject
    assert load_cover_letter(session, "other-job") is None


def test_cover_letter_docx_export(profile_data, evidence, job_record, tmp_path):
    from docx import Document

    draft, _ = generate_cover_letter(profile_data, evidence, job_record, use_llm=False)
    path = export_cover_letter_docx(draft, tmp_path / cover_letter_filename(draft, "docx"))
    assert Path(path).exists() and Path(path).stat().st_size > 500
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "Ada Lovelace" in text
    assert "Dear Hiring Manager" in text
    assert "Senior Backend Engineer" in text


def test_cv_studio_cover_letter_and_email_tabs(session, approved_profile, job_record):
    from streamlit.testing.v1 import AppTest

    from services.deduplication import persist_job

    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    persist_job(session, job_record)
    session.commit()

    at = AppTest.from_file(app_path, default_timeout=90)
    at.session_state["page"] = "cv_studio"
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    labels = [button.label for button in at.button]
    assert "Generate cover letter" in labels
    assert "Generate email draft" in labels

    next(b for b in at.button if b.label == "Generate cover letter").click().run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert any("Cover letter evidence" in item.label for item in at.expander)
    assert any("Download .docx" in b.label for b in at.download_button)

    next(b for b in at.button if b.label == "Generate email draft").click().run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert any("Email evidence" in item.label for item in at.expander)
    assert any("Download .txt" in b.label for b in at.download_button)


def test_non_english_draft_uses_localised_skeleton(profile_data, evidence, job_record):
    letter, report = generate_cover_letter(
        profile_data, evidence, job_record, use_llm=False, language="de"
    )
    email, _ = generate_recruiter_email(
        profile_data, evidence, job_record, use_llm=False, language="de"
    )
    assert letter.greeting.startswith("Sehr geehrte")
    assert email.subject.startswith("Bewerbung:")
    assert report.passed, [i.message for i in report.issues if i.severity == "error"]
    assert email_filename(email).startswith("consul_Email")
