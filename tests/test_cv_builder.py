from pathlib import Path

from core.schemas import CVBullet, CVRow, CVSection
from services import cv_builder as builder
from services.document_export import cv_to_text


def test_master_cv_contains_the_whole_verified_profile(profile_data, evidence):
    cv = builder.build_master_cv(profile_data, evidence)
    headings = [section.heading for section in cv.sections]
    assert headings[0] == "Professional Experience"
    assert "Education" in headings
    assert "Technical Skills" in headings
    assert "Languages" in headings
    assert cv.header.name == "Ada Lovelace"
    assert "Germany" in cv.header.visa_status
    assert cv.target_job_title == ""

    experience = cv.sections[0]
    assert experience.entries[0].organization == "Shop GmbH"
    # The master keeps every verified bullet, not just the five a tailored CV takes.
    assert len(experience.entries[0].bullets) == 2

    valid = {item.evidence_id for item in evidence if item.status.value != "rejected"}
    for bullet in cv.all_bullets():
        assert bullet.id
        assert bullet.evidence_ids
        assert set(bullet.evidence_ids) <= valid
    for section in cv.sections:
        assert section.id
        for entry in section.entries:
            assert entry.id


def test_job_and_blank_drafts_are_editable(profile_data, evidence, job_record):
    job = builder.job_draft(profile_data, evidence, job_record, None, scope="job-1")
    assert job.scope == "job-1"
    assert job.source == "job"
    assert job_record.title in job.source_label
    evaluation = builder.evaluate(job.cv, profile_data, evidence, job_record)
    assert evaluation.exportable, [issue.message for issue in evaluation.report.issues]
    assert job.cv.all_bullets()

    blank = builder.blank_draft(profile_data, scope=builder.MASTER_SCOPE)
    assert blank.cv.header.name == "Ada Lovelace"
    assert [section.heading for section in blank.cv.sections] == [
        "Professional Experience", "Technical Skills"]
    assert not blank.cv.all_bullets()


def test_draft_round_trips_through_settings(session, profile_data, evidence):
    draft = builder.master_draft(profile_data, evidence)
    builder.save_draft(session, draft)
    loaded = builder.load_draft(session, builder.MASTER_SCOPE)
    assert loaded is not None
    assert loaded.source == "ground_truth"
    assert loaded.cv.header.name == "Ada Lovelace"
    assert loaded.cv.sections[0].id == draft.cv.sections[0].id
    assert loaded.cv.sections[0].entries[0].bullets[0].id == \
        draft.cv.sections[0].entries[0].bullets[0].id


def test_hide_and_restore_keep_the_section(session, profile_data, evidence):
    draft = builder.master_draft(profile_data, evidence)
    original = draft.cv.sections[1].heading
    builder.hide_section(draft, 1)
    assert original not in [section.heading for section in draft.cv.sections]
    assert [section.heading for section in draft.hidden] == [original]
    builder.restore_section(draft, 0)
    assert draft.cv.sections[-1].heading == original
    assert draft.hidden == []


def test_move_and_restore_master_order(profile_data, evidence):
    draft = builder.master_draft(profile_data, evidence)
    skills = next(index for index, section in enumerate(draft.cv.sections)
                  if section.heading == "Technical Skills")
    builder.move_section(draft.cv, skills, -2)
    assert draft.cv.sections[skills - 2].heading == "Technical Skills"
    builder.restore_master_order(draft)
    assert draft.cv.sections[0].heading == "Professional Experience"
    assert [section.heading for section in draft.cv.sections].index("Technical Skills") > \
        [section.heading for section in draft.cv.sections].index("Education")


def test_evaluation_never_mutates_the_draft(profile_data, evidence):
    draft = builder.master_draft(profile_data, evidence)
    first_id = draft.cv.sections[0].entries[0].bullets[0].id
    draft.cv.sections[0].entries[0].bullets.append(CVBullet(text="Invented a whole platform."))
    evaluation = builder.evaluate(draft.cv, profile_data, evidence)
    assert evaluation.removed
    assert draft.cv.sections[0].entries[0].bullets[-1].text == "Invented a whole platform."
    assert draft.cv.sections[0].entries[0].bullets[0].id == first_id


def test_approval_is_bound_to_the_exact_document(profile_data, evidence):
    draft = builder.master_draft(profile_data, evidence)
    evaluation = builder.evaluate(draft.cv, profile_data, evidence)
    assert evaluation.exportable, [issue.message for issue in evaluation.report.issues]

    builder.approve(draft, evaluation)
    assert builder.is_approved(draft, evaluation)

    draft.cv.header.applying_for = "Applying for: Staff Engineer"
    edited = builder.evaluate(draft.cv, profile_data, evidence)
    assert not builder.is_approved(draft, edited)


def test_export_requires_approval_then_writes_versioned_files(tmp_path, profile_data, evidence):
    draft = builder.master_draft(profile_data, evidence)
    try:
        builder.export_draft(draft, profile_data, evidence, formats=("txt",))
    except builder.BuilderError as exc:
        assert "Approve" in exc.message
    else:  # pragma: no cover - must never export unapproved content
        raise AssertionError("an unapproved CV was exported")

    evaluation = builder.evaluate(draft.cv, profile_data, evidence)
    builder.approve(draft, evaluation)
    files, _ = builder.export_draft(draft, profile_data, evidence, formats=("docx", "txt"))

    assert draft.export_version == 1
    assert set(files) == {"docx", "txt"}
    assert all(Path(path).exists() for path in files.values())
    assert "v1" in Path(files["txt"]).name
    assert "ADA LOVELACE" in Path(files["txt"]).read_text(encoding="utf-8")

    draft.approved_hash = ""
    builder.approve(draft, builder.evaluate(draft.cv, profile_data, evidence))
    files, _ = builder.export_draft(draft, profile_data, evidence, formats=("txt",))
    assert draft.export_version == 2
    assert "v2" in Path(files["txt"]).name


def test_export_honours_the_builder_section_order(profile_data, evidence):
    draft = builder.master_draft(profile_data, evidence)
    draft.cv.sections = [
        CVSection(heading="Technical Skills", kind="skills",
                  rows=[CVRow(label="Technical", text="Python, SQL")]),
        *draft.cv.sections,
    ]
    draft.cv.sections[0].skills = ["Python", "SQL"]
    evaluation = builder.evaluate(draft.cv, profile_data, evidence)
    builder.approve(draft, evaluation)
    files, _ = builder.export_draft(draft, profile_data, evidence, formats=("txt",))
    text = Path(files["txt"]).read_text(encoding="utf-8")
    assert text.index("TECHNICAL SKILLS") < text.index("PROFESSIONAL EXPERIENCE")

    # CV Studio keeps the master order: the same content is re-sorted without the flag.
    default_text = cv_to_text(draft.cv)
    assert default_text.index("PROFESSIONAL EXPERIENCE") < default_text.index("TECHNICAL SKILLS")
