"""CV Builder: a live document editor over the evidence contract.

The layout follows the Resume Matcher builder that inspired it — the document on
the left, the page on the right, with job-match and ATS tabs — while every rule
that decides what may appear (evidence, validation, master template, approval)
comes from Consul.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.database import session_scope
from core.exceptions import consulError
from core.models import Job
from core.schemas import BuilderDraft, CandidateProfileData, EvidenceItem, JobRecord, MatchResult
from services import cv_builder as builder
from services.cv_service import list_versions, load_cv
from services.job_service import get_match, list_jobs, row_to_record
from services.profile_service import get_active_profile
from ui import components as c
from ui.nav import go

LANGUAGES = {"en": "English", "de": "Deutsch", "fr": "Français", "es": "Español",
             "nl": "Nederlands"}
MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf", "txt": "text/plain"}


def _cache_key(scope: str) -> str:
    return f"builder_draft_{scope}"


def _clear_widget_state() -> None:
    for key in [k for k in list(st.session_state) if k.startswith("bb_")]:
        del st.session_state[key]


def _save(draft: BuilderDraft) -> None:
    with session_scope() as session:
        builder.save_draft(session, draft)
    st.session_state[_cache_key(draft.scope)] = draft


def _commit(draft: BuilderDraft) -> None:
    """Persist a structural edit and redraw from the model.

    Widget state is dropped because indices/ids may have moved; the draft is the
    single source of truth, exactly like a document model.
    """
    _clear_widget_state()
    _save(draft)
    st.rerun()


def render() -> None:
    c.page_header("CV Builder", "Edit the document directly. Consul still decides what may be claimed.")
    with session_scope() as session:
        active = get_active_profile(session)
        if active is None:
            c.empty_state("Approve a Ground Truth profile first",
                          "The builder rearranges verified facts. Without a profile there is "
                          "nothing truthful to arrange.", mark="01")
            if st.button("Open Ground Truth CV", type="primary"):
                go("profile")
            return
        profile: CandidateProfileData = active[1].data
        evidence: list[EvidenceItem] = list(active[1].evidence)
        jobs = [
            {"id": job.id, "title": job.title, "company": job.company,
             "score": job.match.total_score if job.match else None}
            for job in list_jobs(session, limit=300)
        ]

    scope = _scope_selector(jobs)
    job_record: JobRecord | None = None
    match: MatchResult | None = None
    versions: list[tuple[int, object]] = []
    if scope != builder.MASTER_SCOPE:
        with session_scope() as session:
            row = session.get(Job, scope)
            if row is None:
                st.session_state.pop("builder_scope", None)
                st.rerun()
                return
            job_record = row_to_record(row)
            match = get_match(session, scope)
            versions = [(v.version, load_cv(v)[0]) for v in list_versions(session, scope)]

    draft = _draft_for(scope, profile, evidence, job_record, match, versions)
    if draft is None:
        return

    checker = builder.skill_checker(profile, evidence)
    labels = builder.evidence_labels(evidence)

    left, right = st.columns([1.1, 1], gap="large")
    with left:
        _editor(draft, scope, checker, labels, profile, evidence)
    # The editor mutated the draft in place, so evaluate and save only after it.
    evaluation = builder.evaluate(draft.cv, profile, evidence, job_record)
    _save(draft)
    with right:
        _preview_and_checks(draft, evaluation, profile, evidence, job_record, match, scope)


# ---------------------------------------------------------------------------
# Scope and draft lifecycle
# ---------------------------------------------------------------------------
def _scope_selector(jobs: list[dict]) -> str:
    options = [builder.MASTER_SCOPE] + [job["id"] for job in jobs]
    by_id = {job["id"]: job for job in jobs}
    focus = st.session_state.get("cv_focus_job")
    if st.session_state.get("builder_scope") not in options:
        st.session_state.builder_scope = focus if focus in by_id else builder.MASTER_SCOPE

    def label(scope: str) -> str:
        if scope == builder.MASTER_SCOPE:
            return "Master CV — all verified content"
        job = by_id[scope]
        score = f"{job['score']:.0f}/100 · " if job["score"] is not None else ""
        return f"{score}{job['title']} — {job['company'] or 'Unknown company'}"

    return st.selectbox("Editing", options, format_func=label, key="builder_scope")


def _draft_for(scope: str, profile: CandidateProfileData, evidence: list[EvidenceItem],
               job_record: JobRecord | None, match: MatchResult | None,
               versions: list[tuple[int, object]]) -> BuilderDraft | None:
    cached = st.session_state.get(_cache_key(scope))
    if isinstance(cached, BuilderDraft):
        return cached
    with session_scope() as session:
        draft = builder.load_draft(session, scope)
    if draft is not None:
        st.session_state[_cache_key(scope)] = draft
        return draft
    return _starters(scope, profile, evidence, job_record, match, versions)


def _starters(scope: str, profile: CandidateProfileData, evidence: list[EvidenceItem],
              job_record: JobRecord | None, match: MatchResult | None,
              versions: list[tuple[int, object]]) -> BuilderDraft | None:
    st.markdown("#### Start a draft")
    st.caption("Nothing is uploaded: drafts are built from your approved Ground Truth profile.")
    language = st.selectbox("CV language", list(LANGUAGES), format_func=LANGUAGES.get,
                            key=f"bb_{scope}_start_language")
    columns = st.columns(3)
    created: BuilderDraft | None = None

    if columns[0].button("From Ground Truth", type="primary", use_container_width=True,
                         key=f"bb_{scope}_start_master",
                         help="Every verified fact, ready to trim."):
        created = builder.master_draft(profile, evidence, scope=scope, language=language)

    if job_record is not None:
        if columns[1].button("From this job", use_container_width=True,
                             key=f"bb_{scope}_start_job",
                             help="Starts from the newest CV Studio version, or drafts a "
                                  "deterministic evidence-only CV for this advert."):
            if versions:
                version, cv = versions[0]
                created = builder.version_draft(cv, scope=scope, language=language,
                                                label=f"CV Studio v{version}")
            else:
                created = builder.job_draft(profile, evidence, job_record, match,
                                            scope=scope, language=language)

    if columns[2].button("Blank document", use_container_width=True,
                         key=f"bb_{scope}_start_blank",
                         help="Header plus empty sections; every bullet still needs evidence."):
        created = builder.blank_draft(profile, scope=scope, language=language)

    if created is None:
        return None
    _save(created)
    return created


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------
def _editor(draft: BuilderDraft, scope: str, checker, labels: dict[str, str],
            profile: CandidateProfileData, evidence: list[EvidenceItem]) -> None:
    cv = draft.cv
    st.markdown("#### Document")
    with st.container(border=True):
        st.markdown(f"**{cv.header.name or 'Unnamed candidate'}** · {cv.header.title or '—'}")
        contacts = " · ".join(cv.header.contact_lines) or "No contact details in Ground Truth"
        st.caption(contacts)
        if cv.header.visa_status:
            st.caption(f"Visa status: {cv.header.visa_status}")
        cv.header.applying_for = st.text_input(
            "Headline for this application", value=cv.header.applying_for,
            key=f"bb_{scope}_applying",
            placeholder="e.g. Applying for: Senior Backend Engineer",
        )
        st.caption("Name, title, contact details and visa status are read from Ground Truth "
                   "and cannot be edited into the document here.")

    cv.summary = st.text_area("Professional summary", value=cv.summary, height=110,
                              key=f"bb_{scope}_summary")

    for index, section in enumerate(list(cv.sections)):
        _section_card(draft, section, index, scope, checker, labels, profile, evidence)

    _add_section(draft, scope)
    _hidden_sections(draft, scope)

    with st.expander("Document actions"):
        columns = st.columns(2)
        if columns[0].button("Restore master order", key=f"bb_{scope}_order",
                             help="Sort sections the way the master template orders them."):
            builder.restore_master_order(draft)
            _commit(draft)
        confirmed = st.checkbox("I want to discard this draft and start over",
                                key=f"bb_{scope}_discard_confirm")
        if columns[1].button("Discard draft", disabled=not confirmed, key=f"bb_{scope}_discard"):
            with session_scope() as session:
                builder.delete_draft(session, draft.scope)
            st.session_state.pop(_cache_key(draft.scope), None)
            _clear_widget_state()
            st.rerun()
        st.caption("Drafts autosave locally. A discarded draft can be recreated from Ground "
                   "Truth at any time.")


def _section_card(draft: BuilderDraft, section, index: int, scope: str, checker,
                  labels: dict[str, str], profile: CandidateProfileData,
                  evidence: list[EvidenceItem]) -> None:
    cv = draft.cv
    with st.container(border=True):
        head = st.columns([6, 1, 1, 1])
        section.heading = head[0].text_input(
            "Section heading", value=section.heading,
            key=f"bb_{scope}_{section.id}_heading", label_visibility="collapsed",
            placeholder="Section heading",
        )
        if head[1].button("↑", key=f"bb_{scope}_{section.id}_up", disabled=index == 0,
                          help="Move section up"):
            builder.move_section(cv, index, -1)
            _commit(draft)
        if head[2].button("↓", key=f"bb_{scope}_{section.id}_down",
                          disabled=index == len(cv.sections) - 1, help="Move section down"):
            builder.move_section(cv, index, 1)
            _commit(draft)
        if head[3].button("Hide", key=f"bb_{scope}_{section.id}_hide",
                          help="Hide this section without deleting it."):
            builder.hide_section(draft, index)
            _commit(draft)

        st.caption(f"{section.kind} · {len(section.entries)} entries · {len(section.lines)} lines")
        if builder.empty_section(section):
            st.caption("Empty sections are not exported.")

        if section.kind == "entries":
            _entries_editor(draft, section, scope, labels, profile, evidence)
        elif section.kind == "skills":
            _skills_editor(draft, section, scope, checker)
        elif section.kind == "lines":
            _lines_editor(draft, section, scope)


def _entries_editor(draft: BuilderDraft, section, scope: str, labels: dict[str, str],
                    profile: CandidateProfileData, evidence: list[EvidenceItem]) -> None:
    for e_index, entry in enumerate(list(section.entries)):
        with st.expander(f"{e_index + 1}. {entry.title or 'Untitled entry'}", expanded=False):
            _entry_facts(entry)
            for b_index, bullet in enumerate(list(entry.bullets)):
                columns = st.columns([9, 1])
                bullet.text = columns[0].text_area(
                    "Bullet", value=bullet.text, height=70, label_visibility="collapsed",
                    key=f"bb_{scope}_{bullet.id}_text", placeholder="One verified achievement",
                )
                if columns[1].button("✕", key=f"bb_{scope}_{bullet.id}_del", help="Remove bullet"):
                    builder.remove_at(entry.bullets, b_index)
                    _commit(draft)
                bullet.evidence_ids = st.multiselect(
                    "Evidence cited by this bullet", options=list(labels),
                    default=[i for i in bullet.evidence_ids if i in labels],
                    format_func=lambda key: labels.get(key, key),
                    key=f"bb_{scope}_{bullet.id}_ev", label_visibility="collapsed",
                    placeholder="Cite evidence — uncited bullets are removed at export",
                )
                if bullet.text.strip() and not bullet.evidence_ids:
                    st.caption("Not cited: this bullet is dropped at export until you attach evidence.")

            columns = st.columns(2)
            if columns[0].button("+ Bullet", key=f"bb_{scope}_{entry.id}_add_bullet"):
                builder.add_bullet(entry)
                _commit(draft)
            if columns[1].button("Remove entry", key=f"bb_{scope}_{entry.id}_del_entry"):
                builder.remove_at(section.entries, e_index)
                _commit(draft)

    _add_entry(draft, section, scope, profile, evidence)


def _entry_facts(entry) -> None:
    """Title, organisation, place and dates are read from the verified record."""
    st.markdown(f"**{entry.title or 'Untitled entry'}**")
    details = " · ".join(value for value in
                         (entry.organization, entry.location, entry.dates) if value)
    st.caption(details or "No organisation, location or dates recorded")
    if entry.technologies:
        st.caption("Technologies: " + ", ".join(entry.technologies))
    st.caption("Title, organisation, location, dates and technologies come from Ground "
               "Truth and cannot be retyped here. Edit the Ground Truth profile to correct "
               "them.")


def _add_entry(draft: BuilderDraft, section, scope: str,
               profile: CandidateProfileData, evidence: list[EvidenceItem]) -> None:
    options = builder.available_entries(draft, profile, evidence)
    if not options:
        st.caption("Every entry in your Ground Truth is already in this document.")
        return
    with st.expander("+ Add an entry from Ground Truth"):
        st.caption("Entries are selected from your verified profile; bullets are what you "
                   "write here, and every bullet still has to cite evidence.")
        choice = st.selectbox("Entry", [label for label, _ in options],
                              key=f"bb_{scope}_{section.id}_pick_entry")
        if st.button("Add entry", key=f"bb_{scope}_{section.id}_add_entry"):
            section.entries.append(next(item for label, item in options
                                        if label == choice))
            _commit(draft)


def _skills_editor(draft: BuilderDraft, section, scope: str, checker) -> None:
    for r_index, row in enumerate(list(section.rows)):
        columns = st.columns([2, 6, 1])
        row.label = columns[0].text_input("Label", value=row.label, label_visibility="collapsed",
                                          key=f"bb_{scope}_{row.id}_label", placeholder="Label")
        row.text = columns[1].text_input("Skills", value=row.text, label_visibility="collapsed",
                                         key=f"bb_{scope}_{row.id}_text", placeholder="Comma separated")
        if columns[2].button("✕", key=f"bb_{scope}_{row.id}_del", help="Remove row"):
            builder.remove_at(section.rows, r_index)
            _commit(draft)

    # Keep the flat list in step with the rows the export actually prints.
    section.skills = [item.strip() for row in section.rows
                      for item in row.text.split(",") if item.strip()]
    unsupported = sorted({skill for skill in section.skills if not checker(skill)})
    if unsupported:
        st.caption("Not supported by your evidence (removed at export): "
                   + ", ".join(unsupported[:10]))
    if st.button("+ Skill row", key=f"bb_{scope}_{section.id}_add_row"):
        builder.add_skill_row(section)
        _commit(draft)


def _lines_editor(draft: BuilderDraft, section, scope: str) -> None:
    for l_index, line in enumerate(list(section.lines)):
        columns = st.columns([9, 1])
        section.lines[l_index] = columns[0].text_input(
            "Line", value=line, label_visibility="collapsed",
            key=f"bb_{scope}_{section.id}_line_{l_index}", placeholder="One verified line")
        if columns[1].button("✕", key=f"bb_{scope}_{section.id}_line_{l_index}_del",
                             help="Remove line"):
            builder.remove_at(section.lines, l_index)
            _commit(draft)
    if st.button("+ Line", key=f"bb_{scope}_{section.id}_add_line"):
        section.lines.append("")
        _commit(draft)


def _add_section(draft: BuilderDraft, scope: str) -> None:
    with st.expander("Add a section"):
        names = [name for name, _ in builder.SECTION_CATALOG] + ["Custom section"]
        choice = st.selectbox("Section", names, key=f"bb_{scope}_add_section")
        if choice == "Custom section":
            heading = st.text_input("Heading", key=f"bb_{scope}_add_heading",
                                    placeholder="e.g. Professional Development")
            kind = st.selectbox("Kind", ["entries", "skills", "lines"],
                                key=f"bb_{scope}_add_kind")
        else:
            heading, kind = next(item for item in builder.SECTION_CATALOG if item[0] == choice)
        if st.button("Add section", key=f"bb_{scope}_add_confirm"):
            builder.add_section(draft, heading, kind)
            _commit(draft)


def _hidden_sections(draft: BuilderDraft, scope: str) -> None:
    if not draft.hidden:
        return
    with st.expander(f"Hidden sections ({len(draft.hidden)})"):
        for index, section in enumerate(list(draft.hidden)):
            columns = st.columns([5, 1, 1])
            columns[0].write(section.heading)
            if columns[1].button("Restore", key=f"bb_{scope}_hidden_{section.id}_restore"):
                builder.restore_section(draft, index)
                _commit(draft)
            if columns[2].button("Drop", key=f"bb_{scope}_hidden_{section.id}_drop",
                                 help="Delete this hidden section permanently."):
                builder.drop_hidden_section(draft, index)
                _commit(draft)


# ---------------------------------------------------------------------------
# Preview, match and checks
# ---------------------------------------------------------------------------
def _preview_and_checks(draft: BuilderDraft, evaluation, profile: CandidateProfileData,
                        evidence: list[EvidenceItem], job_record: JobRecord | None,
                        match: MatchResult | None, scope: str) -> None:
    tab_preview, tab_match, tab_checks = st.tabs(["Preview", "JD match", "Checks"])
    with tab_preview:
        st.caption("Live document preview. Section order is yours; the master template fixes "
                   "typography, margins and rules.")
        st.markdown(c.render_cv_html(draft.cv, preserve_order=True), unsafe_allow_html=True)
        st.caption("The exported PDF is the authoritative document; export it to check pagination.")
    with tab_match:
        _jd_match(evaluation, match, job_record)
    with tab_checks:
        _checks(draft, evaluation, profile, evidence, job_record, scope)


def _jd_match(evaluation, match: MatchResult | None, job_record: JobRecord | None) -> None:
    if job_record is None:
        st.info("This is the master document. Pick a job above to see its match and keyword "
                "coverage, then tailor this CV for it.")
        return
    st.markdown(f"**{job_record.title}** — {job_record.company or 'Unknown company'}")
    if match is not None:
        c.score_breakdown(match)
    coverage = evaluation.ats.get("keyword_coverage") or {}
    for key, label in (("must_have", "Must-have"), ("nice_to_have", "Nice-to-have")):
        data = coverage.get(key) or {}
        if not data.get("total"):
            continue
        ratio = data.get("ratio", 1.0)
        st.markdown(f"**{label} coverage** · {ratio:.0%} of the {data.get('available', 0)} "
                    f"evidenced requirements")
        if data.get("covered"):
            st.caption("Covered: " + ", ".join(data["covered"][:10]))
        if data.get("missing_evidenced"):
            st.caption("Evidenced but not in this CV yet: "
                       + ", ".join(data["missing_evidenced"][:10]))
        if data.get("unevidenced"):
            st.caption("Not evidenced, so never claimed: " + ", ".join(data["unevidenced"][:10]))
    quantified = evaluation.ats.get("quantified_bullets") or {}
    st.caption(f"Quantified bullets: {quantified.get('with_metrics', 0)}/"
               f"{quantified.get('total', 0)}")
    st.caption("A missing keyword is never inserted as a claim. Add a bullet only if the "
               "ledger already contains the fact.")


def _checks(draft: BuilderDraft, evaluation, profile: CandidateProfileData,
            evidence: list[EvidenceItem], job_record: JobRecord | None, scope: str) -> None:
    ats = evaluation.ats
    risk = str(ats.get("parse_risk") or "low")
    tone = {"low": "success", "medium": "warn", "high": "danger"}.get(risk, "neutral")
    st.markdown(" ".join([
        c.badge(f"parse risk: {risk}", tone),
        c.badge(f"{len(draft.cv.all_bullets())} bullets"),
        c.badge("complete" if evaluation.exportable else "blocked",
                "success" if evaluation.exportable else "danger"),
    ]), unsafe_allow_html=True)

    checks = ats.get("parse_checks") or {}
    if checks:
        st.dataframe(
            [{"Check": key.replace("_", " ").title(), "Pass": bool(value)}
             for key, value in checks.items()],
            hide_index=True, use_container_width=True,
        )

    report = evaluation.report
    errors = [issue for issue in report.issues if issue.severity == "error"]
    warnings = [issue for issue in report.issues if issue.severity != "error"]
    if errors:
        st.error("Blocking issues — export is withheld until these are resolved.")
        for issue in errors:
            st.markdown(f"- **{issue.code or 'error'}** · {issue.message}")
    if warnings:
        with st.expander(f"Warnings ({len(warnings)})"):
            for issue in warnings:
                st.markdown(f"- **{issue.code or 'warning'}** · {issue.message}")
    if evaluation.removed:
        with st.expander(f"Removed at export ({len(evaluation.removed)})"):
            for item in evaluation.removed:
                st.markdown(f"- {item}")
            st.caption("Only content the evidence ledger cannot support is removed.")
    if report.unsupported_claims:
        with st.expander("Unsupported claims"):
            for claim in report.unsupported_claims:
                st.markdown(f"- {claim}")
    if report.unmet_requirements:
        with st.expander("Requirements this CV does not evidence"):
            for item in report.unmet_requirements:
                st.markdown(f"- {item}")

    recommendations = ats.get("recommendations") or []
    if recommendations:
        with st.expander("Recommendations", expanded=not evaluation.exportable):
            for item in recommendations:
                st.markdown(f"- {item}")

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    _approval(draft, evaluation, profile, evidence, job_record, scope)


def _approval(draft: BuilderDraft, evaluation, profile: CandidateProfileData,
              evidence: list[EvidenceItem], job_record: JobRecord | None, scope: str) -> None:
    st.markdown("#### Approve & export")
    approved = builder.is_approved(draft, evaluation)
    if not evaluation.exportable:
        st.caption("Approve once every blocking issue above is resolved.")

    if approved:
        when = draft.approved_at.strftime("%d %b %Y, %H:%M UTC") if draft.approved_at else ""
        st.success(f"This exact CV is approved{f' ({when})' if when else ''}.")
        columns = st.columns(2)
        if columns[0].button("Revoke approval", key=f"bb_{scope}_revoke"):
            builder.revoke(draft)
            _commit(draft)
        if columns[1].button("Export DOCX + PDF + TXT", type="primary",
                             key=f"bb_{scope}_export"):
            try:
                with session_scope() as session:
                    files, _ = builder.export_draft(draft, profile, evidence, job_record)
                    builder.save_draft(session, draft)
                st.session_state[f"builder_files_{scope}"] = files
                st.rerun()
            except consulError as exc:
                st.error(exc.message)
            except Exception as exc:  # pragma: no cover - export boundary
                st.error(f"Export failed: {type(exc).__name__}: {exc}")
        _downloads(draft, scope)
    else:
        if draft.approved_hash:
            st.caption("The CV changed since it was approved, so approval was revoked. "
                       "Review it again to export.")
        reviewed = st.checkbox("I have reviewed every claim in this CV",
                               key=f"bb_{scope}_reviewed")
        if st.button("Approve this CV", type="primary",
                     disabled=not (reviewed and evaluation.exportable),
                     key=f"bb_{scope}_approve"):
            try:
                builder.approve(draft, evaluation)
            except consulError as exc:
                st.error(exc.message)
                return
            _commit(draft)

    st.caption("Approval is a hash of the exact export-ready document: any edit revokes it. "
               "Every export is a new version in DATA_DIR/exports.")


def _downloads(draft: BuilderDraft, scope: str) -> None:
    files = st.session_state.get(f"builder_files_{scope}") or draft.last_exports
    if not files:
        return
    columns = st.columns(len(files))
    for column, (fmt, path) in zip(columns, files.items()):
        target = Path(path)
        if not target.exists():
            continue
        column.download_button(
            f"Download {fmt.upper()}", data=target.read_bytes(), file_name=target.name,
            mime=MIME.get(fmt, "application/octet-stream"),
            key=f"bb_{scope}_dl_{fmt}", use_container_width=True,
        )
