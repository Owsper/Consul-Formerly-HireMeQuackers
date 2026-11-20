"""Ground Truth CV: upload, structure, review the evidence ledger, then approve."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import get_settings
from core.database import session_scope
from core.exceptions import LLMOverloadedError, consulError
from core.schemas import (
    CandidateProfileData, Certification, EducationEntry, EmploymentEntry, EvidenceItem,
    EvidenceStatus, LanguageEntry, ProjectEntry, SkillCategory,
)
from core.text import normalize_string_list, skill_group_status
from services.cv_extraction import extract_document, heuristic_hints, structured_extraction
from services.profile_service import (
    get_active_profile, list_profiles, merge_profiles, restore_version, save_profile,
    synthesize_evidence,
)
from ui import components as c

STATUS_OPTIONS = ["needs_review", "user_verified", "rejected", "unverified"]


# ---------------------------------------------------------------------------
# Draft state helpers
# ---------------------------------------------------------------------------
def _epoch() -> int:
    return int(st.session_state.get("gt_epoch", 0))


def _start_draft(data: CandidateProfileData, *, document: str, raw: str, message: str) -> None:
    st.session_state.gt_epoch = _epoch() + 1
    st.session_state.gt_draft = data.model_dump(mode="json")
    st.session_state.gt_document = document
    st.session_state.gt_raw = raw
    st.session_state.gt_status = {}
    st.session_state.gt_message = message


def _draft() -> CandidateProfileData:
    return CandidateProfileData.model_validate(st.session_state.get("gt_draft") or {})


def _save_draft(data: CandidateProfileData) -> None:
    st.session_state.gt_draft = data.model_dump(mode="json")


def _lines(value: str) -> list[str]:
    return [line.strip(" -•\t") for line in str(value or "").replace(";", "\n").splitlines()
            if line.strip(" -•\t")]


def _csv(value: object) -> list[str]:
    return normalize_string_list(value)


def _editor_rows(items: list[dict], columns: dict[str, str]) -> pd.DataFrame:
    rows = []
    for item in items:
        row = {}
        for field, kind in columns.items():
            value = item.get(field, "")
            if kind == "list":
                row[field] = "\n".join(value or []) if isinstance(value, list) else str(value or "")
            elif kind == "csv":
                row[field] = ", ".join(normalize_string_list(value))
            elif kind == "bool":
                row[field] = bool(value)
            else:
                row[field] = str(value or "")
        row["_id"] = item.get("id", "")
        rows.append(row)
    return pd.DataFrame(rows, columns=[*columns, "_id"])


def _rebuild(data: CandidateProfileData, frame: pd.DataFrame, columns: dict[str, str]) -> list[dict]:
    out: list[dict] = []
    if frame is None:
        return out
    for record in frame.to_dict("records"):
        item: dict = {}
        empty = True
        for field, kind in columns.items():
            value = record.get(field, "")
            if kind == "list":
                parsed = _lines(value)
                item[field] = parsed
                if parsed:
                    empty = False
            elif kind == "bool":
                item[field] = bool(value) if value is not None else False
            elif kind == "csv":
                parsed = _csv(value)
                item[field] = parsed
                if parsed:
                    empty = False
            else:
                text = str(value).strip() if value is not None else ""
                item[field] = "" if text.lower() == "nan" else text
                if item[field]:
                    empty = False
        if record.get("_id"):
            item["id"] = str(record["_id"])
        if not empty:
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# Upload / start
# ---------------------------------------------------------------------------
def _render_start() -> None:
    st.subheader("Build your Ground Truth")
    st.caption(
        "This profile is the only source of facts for matching and for every generated CV. "
        "Nothing is activated until you explicitly approve it."
    )
    upload_tab, manual_tab = st.tabs(["Upload a CV", "Enter manually"])

    with upload_tab:
        settings = get_settings()
        uploaded = st.file_uploader("CV as PDF or DOCX", type=["pdf", "docx"],
                                    accept_multiple_files=False,
                                    help=f"Max {settings.max_upload_mb} MB. Scanned PDFs use OCR when available.")
        if uploaded is not None:
            col_extract, col_manual = st.columns([1, 1])
            if col_extract.button("Extract text & profile", type="primary", use_container_width=True):
                _extract_upload(uploaded.getvalue(), uploaded.name)
            if col_manual.button("Just show me the extracted text", use_container_width=True):
                _extract_text_only(uploaded.getvalue(), uploaded.name)

        if st.session_state.get("gt_raw"):
            with st.expander("Extracted document text", expanded=False):
                st.text(st.session_state.gt_raw[:20000])
            if st.button("Start manual entry from scratch"):
                _start_draft(CandidateProfileData(), document=st.session_state.get("gt_document", "manual"),
                             raw=st.session_state.get("gt_raw", ""),
                             message="Started a manual profile. The document text is kept for reference.")

        if not get_settings().llm_available:
            st.info(
                "Structured extraction needs an LLM key (GEMINI_API_KEY, or LLM_PROVIDER + "
                "LLM_API_KEY). Without one, upload extracts the raw text and you can enter the "
                "structured profile manually — no data is invented."
            )

    with manual_tab:
        st.write("Enter what you can prove. You can refine everything before approval.")
        if st.button("Start a blank profile", type="primary"):
            _start_draft(CandidateProfileData(), document="manual", raw="",
                         message="Blank profile started.")
            st.rerun()


def _extract_text_only(data: bytes, filename: str) -> None:
    try:
        result = extract_document(filename, data)
    except consulError as exc:
        st.error(exc.message)
        return
    st.session_state.gt_raw = result.text
    st.session_state.gt_document = filename
    st.session_state.gt_message = f"Extracted {result.char_count:,} characters from {filename}."
    if result.warnings:
        for warning in result.warnings:
            st.warning(warning)
    st.rerun()


def _extract_upload(data: bytes, filename: str) -> None:
    try:
        result = extract_document(filename, data)
    except consulError as exc:
        st.error(exc.message)
        return
    st.session_state.gt_raw = result.text
    st.session_state.gt_document = filename
    if not result.text.strip():
        st.error("No text could be extracted. Try a text-based PDF or a DOCX file.")
        return
    if not get_settings().llm_available:
        hints = heuristic_hints(result.text)
        draft = CandidateProfileData()
        draft.personal.email = hints.get("email", "")
        draft.personal.phone = hints.get("phone", "")
        draft.personal.linkedin = hints.get("linkedin", "")
        draft.personal.github = hints.get("github", "")
        _start_draft(draft, document=filename, raw=result.text,
                     message="Text extracted. The LLM is not configured, so the structured fields are blank "
                             "except contact details found verbatim in the document.")
        st.rerun()
    with st.spinner("Structuring the document with the LLM…"):
        try:
            data, evidence = structured_extraction(result.text, filename)
        except LLMOverloadedError as exc:
            st.warning(
                f"{exc.message}"
                "\n\nThe extracted text is kept below, so nothing is lost. Wait a moment "
                "and press the button again, or start the profile from the text."
            )
            return
        except consulError as exc:
            st.error(f"{exc.message} You can still enter the profile manually.")
            return
        except Exception as exc:  # pragma: no cover - provider failures
            st.error(f"Extraction failed ({type(exc).__name__}). You can enter the profile manually.")
            return
    _start_draft(data, document=filename, raw=result.text,
                 message=f"Extracted a draft profile with {len(evidence)} candidate evidence items. "
                         "Review every field before approving.")
    st.rerun()


# ---------------------------------------------------------------------------
# Editors
# ---------------------------------------------------------------------------
def _render_profile_editor(data: CandidateProfileData) -> None:
    epoch = _epoch()
    personal = data.personal
    st.markdown("##### Personal details")
    col1, col2 = st.columns(2)
    with col1:
        personal.full_name = st.text_input("Full name", personal.full_name, key=f"p_name_{epoch}")
        personal.email = st.text_input("Email", personal.email, key=f"p_email_{epoch}")
        personal.phone = st.text_input("Phone", personal.phone, key=f"p_phone_{epoch}")
        personal.city = st.text_input("City", personal.city, key=f"p_city_{epoch}")
    with col2:
        personal.professional_title = st.text_input("Professional title", personal.professional_title,
                                                    key=f"p_title_{epoch}")
        personal.country = st.text_input("Country", personal.country, key=f"p_country_{epoch}")
        personal.linkedin = st.text_input("LinkedIn URL", personal.linkedin, key=f"p_li_{epoch}")
        personal.github = st.text_input("GitHub URL", personal.github, key=f"p_gh_{epoch}")
    personal.portfolio = st.text_input("Portfolio / website", personal.portfolio, key=f"p_port_{epoch}")

    st.markdown("##### Work authorization")
    auth = data.work_authorization
    a1, a2, a3 = st.columns(3)
    auth.residence_country = a1.text_input("Country of residence", auth.residence_country,
                                           key=f"w_country_{epoch}")
    authorized = a2.selectbox(
        "Authorized to work there?",
        ["Not stated", "Yes", "No"],
        index=0 if auth.authorized_to_work is None else (1 if auth.authorized_to_work else 2),
        key=f"w_auth_{epoch}",
    )
    auth.authorized_to_work = None if authorized == "Not stated" else authorized == "Yes"
    sponsorship = a3.selectbox(
        "Sponsorship required?",
        ["Not stated", "Yes", "No"],
        index=0 if auth.sponsorship_required is None else (1 if auth.sponsorship_required else 2),
        key=f"w_sponsor_{epoch}",
    )
    auth.sponsorship_required = None if sponsorship == "Not stated" else sponsorship == "Yes"
    b1, b2 = st.columns(2)
    auth.visa_status = b1.text_input("Visa / residence status", auth.visa_status, key=f"w_visa_{epoch}")
    auth.relocation_preference = b2.text_input("Relocation preference", auth.relocation_preference,
                                               key=f"w_reloc_{epoch}")

    st.markdown("##### Professional experience")
    st.caption("One bullet per line. Only add what you actually did — these bullets become CV evidence.")
    emp_columns = {
        "title": "text", "employer": "text", "location": "text", "start_date": "text",
        "end_date": "text", "current": "bool", "responsibilities": "list",
        "achievements": "list", "technologies": "csv", "quantified_results": "list",
    }
    emp_frame = st.data_editor(
        _editor_rows([e.model_dump(mode="json") for e in data.employment], emp_columns),
        num_rows="dynamic", use_container_width=True, key=f"emp_{epoch}",
        column_config={
            "title": st.column_config.TextColumn("Job title"),
            "employer": st.column_config.TextColumn("Employer"),
            "start_date": st.column_config.TextColumn("Start"),
            "end_date": st.column_config.TextColumn("End"),
            "current": st.column_config.CheckboxColumn("Current"),
            "responsibilities": st.column_config.TextColumn("Responsibilities (one per line)", width="large"),
            "achievements": st.column_config.TextColumn("Achievements (one per line)", width="large"),
            "technologies": st.column_config.TextColumn("Technologies (comma separated)", width="medium"),
            "quantified_results": st.column_config.TextColumn("Measured results (one per line)", width="medium"),
            "_id": None,
        },
    )
    data.employment = [EmploymentEntry.model_validate(x)
                       for x in _rebuild(data, emp_frame, emp_columns)]

    st.markdown("##### Education")
    edu_columns = {
        "institution": "text", "qualification": "text", "subject": "text",
        "start_date": "text", "end_date": "text", "status": "text",
        "coursework": "list", "achievements": "list",
    }
    edu_frame = st.data_editor(
        _editor_rows([e.model_dump(mode="json") for e in data.education], edu_columns),
        num_rows="dynamic", use_container_width=True, key=f"edu_{epoch}",
        column_config={
            "institution": st.column_config.TextColumn("Institution"),
            "qualification": st.column_config.TextColumn("Qualification"),
            "subject": st.column_config.TextColumn("Subject"),
            "start_date": st.column_config.TextColumn("Start"),
            "end_date": st.column_config.TextColumn("End"),
            "status": st.column_config.TextColumn("Status (e.g. completed)"),
            "coursework": st.column_config.TextColumn("Relevant coursework (one per line)", width="medium"),
            "achievements": st.column_config.TextColumn("Achievements (one per line)", width="medium"),
            "_id": None,
        },
    )
    data.education = [EducationEntry.model_validate(x) for x in _rebuild(data, edu_frame, edu_columns)]

    st.markdown("##### Projects")
    st.caption("Academic and personal projects are labelled as projects — never presented as employment.")
    proj_columns = {
        "name": "text", "role": "text", "label": "text", "description": "text",
        "technologies": "csv", "implementation": "text", "measurable_results": "text",
        "start_date": "text", "end_date": "text", "github_url": "text",
    }
    proj_frame = st.data_editor(
        _editor_rows([p.model_dump(mode="json") for p in data.projects], proj_columns),
        num_rows="dynamic", use_container_width=True, key=f"proj_{epoch}",
        column_config={
            "name": st.column_config.TextColumn("Project"),
            "role": st.column_config.TextColumn("Your role"),
            "label": st.column_config.SelectboxColumn("Type", options=["project", "academic_project"]),
            "description": st.column_config.TextColumn("Description", width="large"),
            "technologies": st.column_config.TextColumn("Technologies"),
            "implementation": st.column_config.TextColumn("Implementation detail", width="medium"),
            "measurable_results": st.column_config.TextColumn("Measured results", width="medium"),
            "github_url": st.column_config.LinkColumn("Repository"),
            "_id": None,
        },
    )
    data.projects = [ProjectEntry.model_validate(x) for x in _rebuild(data, proj_frame, proj_columns)]

    st.markdown("##### Skills")
    st.caption("Mark a group as **learning** or **interest** so it broadens discovery without "
               "being scored or written as demonstrated experience.")
    skill_columns = {"name": "text", "proficiency": "text", "skills": "csv"}
    skill_rows = []
    for group in data.skills:
        row = group.model_dump(mode="json")
        row["proficiency"] = row.get("proficiency") or skill_group_status(group.name)
        skill_rows.append(row)
    skill_frame = st.data_editor(
        _editor_rows(skill_rows, skill_columns),
        num_rows="dynamic", use_container_width=True, key=f"skills_{epoch}",
        column_config={
            "name": st.column_config.TextColumn("Group"),
            "proficiency": st.column_config.SelectboxColumn(
                "Status", options=["demonstrated", "learning", "interest"], width="small"),
            "skills": st.column_config.TextColumn("Skills (comma separated)", width="large"),
            "_id": None,
        },
    )
    data.skills = [SkillCategory.model_validate(x) for x in _rebuild(data, skill_frame, skill_columns)]

    st.markdown("##### Languages & certifications")
    lang_columns = {"language": "text", "proficiency": "text"}
    lang_frame = st.data_editor(
        _editor_rows([l.model_dump(mode="json") for l in data.additional.languages], lang_columns),
        num_rows="dynamic", use_container_width=True, key=f"lang_{epoch}",
        column_config={
            "language": st.column_config.TextColumn("Language"),
            "proficiency": st.column_config.TextColumn("Proficiency (e.g. C1, native)"),
            "_id": None,
        },
    )
    data.additional.languages = [LanguageEntry.model_validate(x)
                                 for x in _rebuild(data, lang_frame, lang_columns)]

    cert_columns = {"name": "text", "issuer": "text", "date": "text"}
    cert_frame = st.data_editor(
        _editor_rows([x.model_dump(mode="json") for x in data.additional.certifications], cert_columns),
        num_rows="dynamic", use_container_width=True, key=f"cert_{epoch}",
        column_config={"name": st.column_config.TextColumn("Certification"),
                       "issuer": st.column_config.TextColumn("Issuer"),
                       "date": st.column_config.TextColumn("Date"),
                       "_id": None},
    )
    data.additional.certifications = [Certification.model_validate(x)
                                      for x in _rebuild(data, cert_frame, cert_columns)]

    _save_draft(data)


# ---------------------------------------------------------------------------
# Evidence ledger
# ---------------------------------------------------------------------------
def _render_evidence(data: CandidateProfileData) -> list[EvidenceItem]:
    document = st.session_state.get("gt_document", "manual")
    evidence = synthesize_evidence(data, source_document=document,
                                   status=EvidenceStatus.NEEDS_REVIEW)
    status_map: dict[str, str] = st.session_state.get("gt_status", {})
    for item in evidence:
        if item.evidence_id in status_map:
            item.status = EvidenceStatus(status_map[item.evidence_id])

    st.caption(
        "Every CV bullet must cite an id from this ledger. Reject anything you cannot stand behind; "
        "rejected evidence is never used in a CV."
    )
    if not evidence:
        c.empty_state("No evidence yet", "Add at least one experience, project or skill.", mark="02")
        return evidence

    frame = pd.DataFrame([
        {"Include": item.status != EvidenceStatus.REJECTED, "id": item.evidence_id,
         "Category": item.category, "Evidence": item.value[:400], "Source": item.source_document,
         "Status": item.status.value}
        for item in evidence
    ])
    edited = st.data_editor(
        frame, hide_index=True, use_container_width=True, key=f"ev_{_epoch()}",
        column_config={
            "Include": st.column_config.CheckboxColumn("Use", width="small"),
            "id": st.column_config.TextColumn("ID", width="small"),
            "Category": st.column_config.TextColumn("Category", width="small"),
            "Evidence": st.column_config.TextColumn("Evidence", width="large"),
            "Source": st.column_config.TextColumn("Source", width="small"),
            "Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, width="small"),
        },
        disabled=["id", "Category", "Evidence", "Source"],
    )
    updated: dict[str, str] = {}
    by_id = {item.evidence_id: item for item in evidence}
    for row in edited.to_dict("records"):
        evidence_id = row.get("id")
        if evidence_id not in by_id:
            continue
        status = "rejected" if not row.get("Include", True) else str(row.get("Status") or "needs_review")
        if status not in STATUS_OPTIONS:
            status = "needs_review"
        updated[evidence_id] = status
        by_id[evidence_id].status = EvidenceStatus(status)
    st.session_state.gt_status = updated
    counts = {s: sum(1 for e in evidence if e.status.value == s) for s in STATUS_OPTIONS}
    st.markdown(
        " ".join(c.badge(f"{k.replace('_', ' ').title()}: {v}", "neutral")
                 for k, v in counts.items() if v),
        unsafe_allow_html=True,
    )
    return evidence


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def _evidence_summary(data: CandidateProfileData) -> list[EvidenceItem]:
    document = st.session_state.get("gt_document", "manual")
    evidence = synthesize_evidence(data, source_document=document,
                                   status=EvidenceStatus.NEEDS_REVIEW)
    status_map: dict[str, str] = st.session_state.get("gt_status", {})
    for item in evidence:
        if item.evidence_id in status_map:
            item.status = EvidenceStatus(status_map[item.evidence_id])
    usable = [e for e in evidence if e.status != EvidenceStatus.REJECTED]
    st.markdown(
        c.badge(f"{len(usable)} usable", "success")
        + " " + c.badge(f"{len(evidence) - len(usable)} rejected", "neutral"),
        unsafe_allow_html=True,
    )
    st.dataframe(
        [{"ID": e.evidence_id, "Evidence": e.value[:300], "Status": e.status.value.replace("_", " ")}
         for e in evidence],
        hide_index=True, use_container_width=True,
    )
    return evidence


def _render_history() -> None:
    with session_scope() as session:
        profiles = list_profiles(session)
        active = get_active_profile(session)
        active_id = active[0].id if active else None
        rows = []
        for profile in profiles:
            versions = sorted(profile.versions, key=lambda v: v.version, reverse=True)
            rows.append({
                "id": profile.id, "name": profile.name, "active": profile.is_active,
                "approved": profile.approved_at, "versions": len(versions),
                "updated": profile.updated_at,
            })
        version_rows = []
        for profile in profiles:
            for version in sorted(profile.versions, key=lambda v: v.version, reverse=True):
                version_rows.append({"profile_id": profile.id, "version": version.version,
                                     "note": version.note, "created": version.created_at})

    st.subheader("Profile versions")
    if not rows:
        c.empty_state("No saved profiles", "Your approved profile and every version will appear here.", mark="03")
        return
    st.dataframe(
        [{"Profile": r["name"], "Active": "Yes" if r["active"] else "No",
          "Approved": c.human_date(r["approved"]), "Versions": r["versions"],
          "Updated": c.human_date(r["updated"])} for r in rows],
        hide_index=True, use_container_width=True,
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        selected = st.selectbox("Profile", [r["id"] for r in rows],
                                format_func=lambda pid: next(r["name"] for r in rows if r["id"] == pid))
    with col2:
        versions = [v for v in version_rows if v["profile_id"] == selected]
        chosen = st.selectbox("Version", [v["version"] for v in versions] or [0],
                              format_func=lambda n: f"v{n}")
    with col3:
        st.write("")
        st.write("")
        if st.button("Restore this version", use_container_width=True):
            try:
                with session_scope() as session:
                    restore_version(session, selected, int(chosen))
                st.success("Version restored as a new draft version. Review it, then approve.")
                st.rerun()
            except consulError as exc:
                st.error(exc.message)

    if version_rows:
        with st.expander("All versions"):
            st.dataframe(
                [{"Profile": v["profile_id"], "Version": v["version"], "Note": v["note"],
                  "Created": c.human_date(v["created"])} for v in version_rows],
                hide_index=True, use_container_width=True,
            )

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    st.subheader("Danger zone")
    confirm = st.checkbox("I understand this permanently deletes the selected profile and its history.")
    if st.button("Delete selected profile", disabled=not confirm):
        try:
            from services.profile_service import delete_profile

            with session_scope() as session:
                delete_profile(session, int(selected))
            st.success("Profile deleted.")
            st.rerun()
        except consulError as exc:
            st.error(exc.message)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def render() -> None:
    c.page_header("Ground Truth CV", "Your verified, application-independent source of truth.")
    with session_scope() as session:
        active = get_active_profile(session)
        active_data = active[1] if active else None
        active_profile = active[0] if active else None
        active_name = active_profile.name if active_profile else ""

    if active_data is not None:
        st.markdown(
            c.badge("Active profile", "success")
            + f" {c.esc(active_name)} · {len(active_data.evidence)} evidence items · "
            + c.badge("Approved", "brand"),
            unsafe_allow_html=True,
        )
        st.write("")

    if st.session_state.get("gt_message"):
        st.info(st.session_state.gt_message)

    if not st.session_state.get("gt_draft"):
        _render_start()
        st.write("")
        st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
        _render_history()
        return

    data = _draft()
    st.caption(f"Draft source: {st.session_state.get('gt_document', 'manual')} · "
               "nothing here is active until you approve it.")
    if st.button("Discard draft", key="gt_discard"):
        for key in ("gt_draft", "gt_raw", "gt_document", "gt_status", "gt_message"):
            st.session_state.pop(key, None)
        st.session_state.gt_epoch = _epoch() + 1
        st.rerun()

    profile_tab, evidence_tab, review_tab = st.tabs(
        ["1 · Profile details", "2 · Evidence ledger", "3 · Review & approve"]
    )
    with profile_tab:
        _render_profile_editor(data)
        _render_merge()
    with evidence_tab:
        _render_evidence(_draft())
    with review_tab:
        evidence = _evidence_summary(_draft())
        st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
        data = _draft()
        problems = []
        if not data.personal.full_name:
            problems.append("Full name is missing.")
        if not data.personal.email and not data.personal.phone:
            problems.append("No contact details (email or phone).")
        if not data.employment and not data.projects and not data.skills:
            problems.append("Add at least one experience, project or skill.")
        for problem in problems:
            st.warning(problem)
        st.markdown(
            "**Approval is explicit.** Activating this profile makes it the source for job matching "
            "and every generated CV. You can keep editing later and create a new version.",
            unsafe_allow_html=False,
        )
        confirmed = st.checkbox(
            "I have reviewed the profile and the evidence ledger and confirm these facts are accurate.",
            key=f"gt_confirm_{_epoch()}",
        )
        col_a, col_b = st.columns([1, 2])
        if col_a.button("Save without activating", use_container_width=True):
            _save_profile(evidence, approve=False)
        if col_b.button("Approve and activate profile", type="primary",
                        use_container_width=True, disabled=not confirmed or bool(problems)):
            _save_profile(evidence, approve=True)

    st.write("")
    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    _render_history()


def _render_merge() -> None:
    st.markdown("##### Add another document")
    st.caption("Merge a second CV or certificate into this draft. Existing facts are kept; new facts are added.")
    uploaded = st.file_uploader("Additional PDF/DOCX", type=["pdf", "docx"], key="gt_merge_file")
    if uploaded is not None and st.button("Extract and merge"):
        if not get_settings().llm_available:
            st.warning("Merging needs an LLM. Configure GEMINI_API_KEY (or LLM_PROVIDER + "
                       "LLM_API_KEY), or paste the facts manually.")
            return
        with st.spinner("Extracting and merging…"):
            try:
                result = extract_document(uploaded.name, uploaded.getvalue())
                incoming, _ = structured_extraction(result.text, uploaded.name)
                current = _draft()
                merged = merge_profiles(current, incoming)
                merged.personal = current.personal  # never overwrite verified contact details
                merged.work_authorization = current.work_authorization
                _start_draft(merged, document=st.session_state.get("gt_document", "manual"),
                             raw=st.session_state.get("gt_raw", ""),
                             message=f"Merged {uploaded.name}. Review the new entries and evidence.")
                st.rerun()
            except LLMOverloadedError as exc:
                st.warning(f"{exc.message} Nothing was merged; try again shortly.")
            except consulError as exc:
                st.error(exc.message)
            except Exception as exc:  # pragma: no cover
                st.error(f"Merge failed: {type(exc).__name__}")


def _save_profile(evidence: list[EvidenceItem], *, approve: bool) -> None:
    data = _draft()
    if not data.personal.full_name:
        st.error("A full name is required before saving.")
        return
    try:
        with session_scope() as session:
            save_profile(
                session, data, evidence,
                name=data.personal.full_name,
                note="Approved from the Ground Truth page" if approve else "Saved draft",
                approve=approve,
            )
    except Exception as exc:  # pragma: no cover
        st.error(f"Could not save the profile: {exc}")
        return
    if approve:
        for key in ("gt_draft", "gt_raw", "gt_document", "gt_status", "gt_message"):
            st.session_state.pop(key, None)
        st.session_state.gt_epoch = _epoch() + 1
        st.success("Profile approved and activated.")
        st.rerun()
    st.success("Draft saved. It is not active until you approve it.")
