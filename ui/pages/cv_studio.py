"""CV Studio: evidence-cited, job-specific CVs with validation and export."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import streamlit as st

from config import get_settings
from core.database import session_scope
from core.exceptions import ProfileNotFoundError, consulError
from core.models import Job
from services.application_documents import (
    cover_letter_filename, email_filename, generate_cover_letter, generate_recruiter_email,
    load_cover_letter, load_recruiter_email, save_cover_letter, save_recruiter_email,
)
from services.application_service import ensure_application, update_application
from services.cv_service import (
    approve_cv, ensure_document_audit, generate_cv_for_job, get_version, is_cv_approved,
    list_versions, load_cv, reexport, revoke_cv_approval,
)
from services.cv_tailoring import audit_cv_with_llm
from services.document_export import export_cover_letter_docx, pdf_render_source
from services.job_service import get_match, list_jobs, row_to_record
from services.master_template import MASTER_FILENAME
from services.profile_service import get_active_profile
from ui import components as c
from ui.nav import go
from ui.pdf_preview import show_pdf_preview

LANGUAGES = {"en": "English", "de": "Deutsch", "fr": "Français", "es": "Español", "nl": "Nederlands"}


def _job_options() -> list[dict]:
    with session_scope() as session:
        jobs = list_jobs(session, limit=300)
        return [
            {
                "id": job.id, "title": job.title, "company": job.company,
                "location": job.location, "language": job.language,
                "score": job.match.total_score if job.match else None,
                "application_url": job.application_url,
                "match": get_match(session, job.id),
            }
            for job in jobs
        ]


def _select_job(options: list[dict]) -> dict | None:
    if not options:
        return None
    focus = st.session_state.get("cv_focus_job")
    ids = [o["id"] for o in options]
    index = ids.index(focus) if focus in ids else 0

    def label(job_id: str) -> str:
        item = next(o for o in options if o["id"] == job_id)
        score = f"{item['score']:.0f}/100 · " if item["score"] is not None else ""
        return f"{score}{item['title']} — {item['company'] or 'Unknown company'}"

    chosen = st.selectbox("Target job", ids, index=index, format_func=label, key="cv_job_select")
    st.session_state.cv_focus_job = chosen
    return next(o for o in options if o["id"] == chosen)


def render() -> None:
    c.page_header("CV Studio", "Every bullet cites your evidence. Nothing is invented, ever.")
    with session_scope() as session:
        active = get_active_profile(session)
        if active is None:
            c.empty_state("Approve a Ground Truth profile first",
                          "A tailored CV can only rephrase and select verified facts. Build the profile first.",
                          mark="01")
            if st.button("Open Ground Truth CV", type="primary"):
                go("profile")
            return

    options = _job_options()
    if not options:
        c.empty_state("No jobs to tailor for",
                      "Discover or add a job first, then come back to build a targeted CV.",
                      mark="02")
        if st.button("Go to Job Discovery", type="primary"):
            go("discovery")
        return

    job = _select_job(options)
    if job is None:
        return

    tab_cv, tab_letter, tab_email = st.tabs(
        ["Tailored CV", "Cover letter", "Recruiter email"]
    )
    with tab_cv:
        _render_cv_tab(job)
    with tab_letter:
        _render_cover_letter_tab(job)
    with tab_email:
        _render_email_tab(job)


def _generation_context(job_id: str):
    """Ground Truth plus the target job, detached from the session."""
    with session_scope() as session:
        active = get_active_profile(session)
        if active is None:
            raise ProfileNotFoundError(
                "Approve a Ground Truth profile before drafting application documents."
            )
        _, payload = active
        job_row = session.get(Job, job_id)
        if job_row is None:
            raise consulError("That job no longer exists.")
        return payload.data, payload.evidence, row_to_record(job_row), get_match(session, job_id)


def _language_index(job: dict) -> int:
    return list(LANGUAGES).index(job["language"]) if job["language"] in LANGUAGES else 0


def _render_cv_tab(job: dict) -> None:
    left, right = st.columns([1.15, 1])
    with left:
        st.markdown(
            f"<div class='consul-card'><div class='consul-job-title'>{c.esc(job['title'])}</div>"
            f"<div class='consul-job-meta'>{c.esc(job['company'] or 'Unknown company')} · "
            f"{c.esc(job['location'] or 'Location not stated')}</div></div>",
            unsafe_allow_html=True,
        )
        if job["match"] is not None:
            st.markdown(
                " ".join([
                    c.score_badge(job["match"].total_score, job["match"].classification.value),
                    c.badge(job["match"].eligibility.status.value.replace("_", " ").title(),
                            "success" if job["match"].eligibility.status.value in {"eligible", "likely_eligible"}
                            else "warn" if job["match"].eligibility.status.value == "unclear" else "danger"),
                ]),
                unsafe_allow_html=True,
            )
            if job["match"].missing_required_skills:
                st.caption("Not evidenced, so it will not be claimed: "
                           + ", ".join(job["match"].missing_required_skills[:8]))
    with right:
        settings = get_settings()
        language = st.selectbox(
            "CV language", list(LANGUAGES), index=list(LANGUAGES).index(job["language"])
            if job["language"] in LANGUAGES else 0,
            format_func=lambda code: LANGUAGES[code], key="cv_language",
        )
        use_llm = st.checkbox("Use Gemini drafting", value=settings.llm_available,
                              disabled=not settings.llm_available, key="cv_use_llm",
                              help="Without an LLM, the deterministic evidence-only builder is used.")
        formats = st.multiselect("Export formats", ["docx", "pdf", "txt"], default=["docx", "pdf"],
                                 key="cv_formats")
        st.caption(f"Master template: **{MASTER_FILENAME}** — reconstructed from "
                   "Rohan_Thomas_Vinu_CV.pdf. Typography, margins and section rules are fixed.")

    if st.button("Generate tailored CV", type="primary"):
        with st.spinner("Selecting evidence, drafting, validating and exporting…"):
            try:
                with session_scope() as session:
                    row, _, report = generate_cv_for_job(
                        session, job["id"], use_llm=use_llm, language=language,
                        formats=tuple(formats or ["docx", "pdf"]),
                    )
            except consulError as exc:
                st.error(exc.message)
                return
            except Exception as exc:  # pragma: no cover
                st.error(f"CV generation failed: {type(exc).__name__}: {exc}")
                return
        if report.passed:
            st.success(f"CV v{row.version} generated and passed validation.")
        else:
            st.warning(f"CV v{row.version} generated, but validation found blocking issues. "
                       "Review the report before exporting.")
        st.rerun()

    st.markdown('<div class="consul-divider"></div>', unsafe_allow_html=True)
    _render_versions(job["id"])


def _render_versions(job_id: str) -> None:
    with session_scope() as session:
        versions = list_versions(session, job_id)
        data = [
            {"id": v.id, "version": v.version, "generator": v.generator,
             "created": v.created_at, "docx": v.docx_path, "pdf": v.pdf_path,
             "template": v.template_name}
            for v in versions
        ]
    if not data:
        c.empty_state("No CV for this job yet",
                      "Generate one above. Each generation creates a new, separately downloadable version.",
                      mark="03")
        return

    st.subheader("Versions")
    ids = [v["id"] for v in data]
    chosen = st.selectbox(
        "Version", ids, format_func=lambda vid: next(
            f"v{v['version']} · {v['generator']} · {c.human_date(v['created'])}"
            for v in data if v["id"] == vid),
        key="cv_version_select",
    )
    with session_scope() as session:
        row = get_version(session, chosen)
        if row is None:
            return
        cv, report = load_cv(row)
        paths = {"docx": row.docx_path, "pdf": row.pdf_path, "version": row.version}
        validation = report
        template_name = row.template_name
        approved = is_cv_approved(session, chosen)

    st.markdown("##### Document preview")
    pdf_path = Path(paths["pdf"]) if paths["pdf"] else None
    previewed = False
    if pdf_path and pdf_path.exists():
        source = pdf_render_source(pdf_path)
        previewed = show_pdf_preview(
            pdf_path,
            caption=(
                "Rendered from the DOCX with LibreOffice. This is the file you download."
                if source == "docx_conversion"
                else "Rendered with the built-in measured renderer (LibreOffice is not "
                     "installed); geometry matches the master template."
            ),
        )
    if not previewed:
        st.info("The PDF pages could not be rendered for preview. The editable DOCX is intact, "
                "and the document below is the same content in reading order.")
        st.markdown(c.render_cv_html(cv), unsafe_allow_html=True)

    with session_scope() as session:
        version_row = get_version(session, chosen)
        audit = ensure_document_audit(session, version_row) if version_row is not None else {}
    if audit:
        _render_ats_audit(audit)

    ats = validation.ats_report or {}
    if ats:
        st.markdown("##### Parse risk detail")
        risk = str(ats.get("parse_risk") or "unknown")
        risk_tone = {"low": "success", "medium": "warn", "high": "danger"}.get(risk, "neutral")
        must = (ats.get("keyword_coverage") or {}).get("must_have") or {}
        quant = ats.get("quantified_bullets") or {}
        covered = len(must.get("covered") or [])
        available = int(must.get("available") or 0)
        st.markdown(
            c.badge(f"Parse risk: {risk.title()}", risk_tone)
            + " " + c.badge(f"Must-have keywords: {covered}/{available} evidenced", "brand")
            + " " + c.badge(f"Quantified bullets: {quant.get('with_metrics', 0)}/"
                            f"{quant.get('total', 0)}", "neutral"),
            unsafe_allow_html=True,
        )
        for reason in ats.get("parse_risk_reasons") or []:
            st.caption(reason)
        with st.expander("ATS details and recommended fixes"):
            if must:
                if must.get("covered"):
                    st.write("**Evidenced and used:** " + ", ".join(must["covered"][:12]))
                if must.get("missing_evidenced"):
                    st.write("**Evidenced but not used here:** "
                             + ", ".join(must["missing_evidenced"][:12]))
                if must.get("unevidenced"):
                    st.caption("Not evidenced, so never claimed: "
                               + ", ".join(must["unevidenced"][:12]))
            vague = (ats.get("content_quality") or {}).get("vague_responsibility_count")
            if vague:
                st.caption(f"Vague duty-style bullets without a result: {vague}.")
            for tip in ats.get("recommendations") or []:
                st.write(f"- {tip}")
            st.caption(f"Rules version {ats.get('version', 'unknown')} · "
                       "deterministic checks, no model judgement")
        if ats.get("knockout_note"):
            st.info(ats["knockout_note"])


    layout = validation.layout or {}
    st.markdown("##### Template fidelity")
    if layout.get("checks"):
        checks = layout["checks"]
        st.markdown(
            c.badge("Layout matches reference" if layout.get("passed") else "Layout needs attention",
                    "success" if layout.get("passed") else "warn")
            + " " + c.badge(f"Renderer: {layout.get('source', 'unknown').replace('_', ' ')}", "neutral"),
            unsafe_allow_html=True,
        )
        for check in checks:
            st.markdown(
                c.badge("Pass" if check.get("passed") else "Check",
                        "success" if check.get("passed") else "warn")
                + f" **{c.esc(check.get('name', '').replace('_', ' ').title())}** — "
                + c.esc(check.get("detail", "")),
                unsafe_allow_html=True,
            )
    else:
        st.caption("No layout report is stored for this version. Re-export to verify it.")

    st.write("")
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("##### Validation report")
        st.markdown(
            c.badge("Passed" if validation.passed else "Needs attention",
                    "success" if validation.passed else "danger")
            + " " + c.badge(f"Evidence coverage {validation.evidence_coverage:.0%}", "brand"),
            unsafe_allow_html=True,
        )
        for issue in validation.issues:
            tone = "error" if issue.severity == "error" else ""
            st.markdown(f'<div class="consul-flag {tone}"><b>{c.esc(issue.code)}</b> — '
                        f'{c.esc(issue.message)}</div>', unsafe_allow_html=True)
        if validation.removed_content:
            with st.expander(f"Removed unsupported content ({len(validation.removed_content)})"):
                for text in validation.removed_content:
                    st.write(f"- {text}")
        if validation.unmet_requirements:
            st.caption("Requirements intentionally not claimed: "
                       + ", ".join(validation.unmet_requirements))
    with col2:
        st.markdown("##### Review & download")
        can_approve = validation.passed and layout.get("passed", True)
        if not approved:
            st.info("Preview the document above. Download is enabled only after you approve "
                    "this exact version.")
            if st.button("Approve this CV", key=f"approve_{chosen}", type="primary",
                         use_container_width=True, disabled=not can_approve):
                with session_scope() as session:
                    approve_cv(session, chosen)
                st.success("CV approved. Downloads are now enabled.")
                st.rerun()
            if not can_approve:
                st.caption("Approval is blocked while validation or layout checks report errors.")
        else:
            st.success("Approved for download.")
            for fmt, path in (("docx", paths["docx"]), ("pdf", paths["pdf"])):
                if path and Path(path).exists():
                    st.download_button(
                        f"Download {fmt.upper()}", Path(path).read_bytes(),
                        file_name=Path(path).name, key=f"dl_{fmt}_{chosen}",
                        use_container_width=True,
                    )
                else:
                    st.caption(f"{fmt.upper()} not available for this version.")
            if st.button("Revoke approval", key=f"revoke_{chosen}", use_container_width=True):
                with session_scope() as session:
                    revoke_cv_approval(session, chosen)
                st.rerun()
        if st.button("Re-export files", key=f"reexport_{chosen}", use_container_width=True):
            try:
                with session_scope() as session:
                    files = reexport(session, chosen, formats=("docx", "pdf", "txt"))
                    revoke_cv_approval(session, chosen)
                st.success("Re-exported: " + ", ".join(files)
                           + ". Re-approve after reviewing the new preview.")
                st.rerun()
            except consulError as exc:
                st.error(exc.message)
        if st.button("Run second-pass LLM audit", key=f"audit_{chosen}",
                     use_container_width=True, disabled=not get_settings().llm_available):
            with session_scope() as session:
                active = get_active_profile(session)
                if active is None:
                    return
                try:
                    issues = asyncio.run(audit_cv_with_llm(cv, active[1].data, active[1].evidence,
                                                           _record_for(session, job_id)))
                except Exception as exc:
                    st.error(f"Audit failed: {type(exc).__name__}")
                    return
            if not issues:
                st.success("The auditor found no unsupported claims.")
            for issue in issues:
                st.warning(f"{issue.code}: {issue.message}")
        st.caption(f"Template: {template_name or 'builtin'} · "
                   "Ground Truth is never modified by CV generation.")

    with st.expander("Evidence map"):
        for bullet in cv.all_bullets():
            st.markdown(f"- {c.esc(bullet.text)} " +
                        " ".join(c.badge(i, "neutral") for i in bullet.evidence_ids),
                        unsafe_allow_html=True)


def _render_cover_letter_tab(job: dict) -> None:
    settings = get_settings()
    st.caption(
        "A one-page cover letter that connects your verified evidence to this posting. "
        "The recipient, greeting and sign-off are never guessed, and no fact about the "
        "company is assumed beyond this job's own data."
    )
    col1, col2, col3 = st.columns(3)
    language = col1.selectbox("Letter language", list(LANGUAGES), index=_language_index(job),
                              format_func=lambda code: LANGUAGES[code], key="cl_language")
    recipient_name = col2.text_input(
        "Recipient name (optional)", key="cl_recipient_name",
        help="Leave blank to address the hiring manager generically. A name is never invented.",
    )
    recipient_title = col3.text_input(
        "Recipient role (optional)", key="cl_recipient_title",
        placeholder="e.g. Talent Acquisition Manager",
    )
    use_llm = st.checkbox(
        "Use Gemini drafting", value=settings.llm_available,
        disabled=not settings.llm_available, key="cl_use_llm",
        help="Without an LLM, the deterministic evidence-only letter is used.",
    )

    if st.button("Generate cover letter", type="primary", key="cl_generate"):
        with st.spinner("Selecting evidence, drafting and validating the letter…"):
            try:
                data, evidence, record, match = _generation_context(job["id"])
                draft, report = generate_cover_letter(
                    data, evidence, record, match, use_llm=use_llm, language=language,
                    recipient_name=recipient_name, recipient_title=recipient_title,
                )
                with session_scope() as session:
                    save_cover_letter(session, job["id"], draft, report)
            except consulError as exc:
                st.error(exc.message)
                return
            except Exception as exc:  # pragma: no cover
                st.error(f"Cover letter generation failed: {type(exc).__name__}: {exc}")
                return
        st.rerun()

    with session_scope() as session:
        stored = load_cover_letter(session, job["id"])
    if stored is None:
        st.caption("No cover letter yet for this job. Generate one above.")
        return
    draft, report = stored

    st.markdown(
        c.badge("Passed" if report.passed else "Needs attention",
                "success" if report.passed else "danger")
        + " " + c.badge(f"{draft.word_count()} words", "brand")
        + " " + c.badge(f"Evidence coverage {report.evidence_coverage:.0%}", "neutral")
        + " " + c.badge(draft.generator.replace("_", " ").title(), "neutral"),
        unsafe_allow_html=True,
    )
    st.code(draft.to_text(), language="text")

    col_txt, col_docx, col_save = st.columns(3)
    col_txt.download_button(
        "Download .txt", draft.to_text().encode("utf-8"),
        file_name=cover_letter_filename(draft, "txt"), mime="text/plain",
        key=f"cl_txt_{job['id']}", use_container_width=True,
    )
    with tempfile.TemporaryDirectory(prefix="consul-letter-") as tmp:
        docx_path = export_cover_letter_docx(
            draft, Path(tmp) / cover_letter_filename(draft, "docx")
        )
        docx_bytes = Path(docx_path).read_bytes()
    col_docx.download_button(
        "Download .docx", docx_bytes,
        file_name=cover_letter_filename(draft, "docx"),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key=f"cl_docx_{job['id']}", use_container_width=True,
    )
    if col_save.button("Save to application tracker", key=f"cl_save_{job['id']}",
                       use_container_width=True):
        with session_scope() as session:
            application, created = ensure_application(session, job["id"], status="Shortlisted")
            update_application(session, application.id, cover_letter=draft.to_text())
        st.success("Cover letter saved to the tracker." if not created
                   else "Application added as Shortlisted with this cover letter.")

    _render_letter_report(report)
    _render_evidence_used(draft, "Cover letter evidence")
    st.caption("The Ground Truth profile was not modified. Regenerating replaces this draft.")


def _render_email_tab(job: dict) -> None:
    settings = get_settings()
    st.caption(
        "A short, direct email for contacting a recruiter or hiring manager about this role. "
        "The subject, greeting and sign-off are built from your profile and this posting — "
        "no recruiter name, company culture or opening is invented."
    )
    col1, col2, col3 = st.columns(3)
    language = col1.selectbox("Email language", list(LANGUAGES), index=_language_index(job),
                              format_func=lambda code: LANGUAGES[code], key="em_language")
    recipient_name = col2.text_input(
        "Recipient name (optional)", key="em_recipient_name",
        help="Leave blank to address the hiring manager generically. A name is never invented.",
    )
    recipient_title = col3.text_input(
        "Recipient role (optional)", key="em_recipient_title",
        placeholder="e.g. Talent Acquisition Manager",
    )
    use_llm = st.checkbox(
        "Use Gemini drafting", value=settings.llm_available,
        disabled=not settings.llm_available, key="em_use_llm",
        help="Without an LLM, the deterministic evidence-only email is used.",
    )

    if st.button("Generate email draft", type="primary", key="em_generate"):
        with st.spinner("Selecting evidence, drafting and validating the email…"):
            try:
                data, evidence, record, match = _generation_context(job["id"])
                draft, report = generate_recruiter_email(
                    data, evidence, record, match, use_llm=use_llm, language=language,
                    recipient_name=recipient_name, recipient_title=recipient_title,
                )
                with session_scope() as session:
                    save_recruiter_email(session, job["id"], draft, report)
            except consulError as exc:
                st.error(exc.message)
                return
            except Exception as exc:  # pragma: no cover
                st.error(f"Email generation failed: {type(exc).__name__}: {exc}")
                return
        st.rerun()

    with session_scope() as session:
        stored = load_recruiter_email(session, job["id"])
    if stored is None:
        st.caption("No email draft yet for this job. Generate one above.")
        return
    draft, report = stored

    st.markdown(
        c.badge("Passed" if report.passed else "Needs attention",
                "success" if report.passed else "danger")
        + " " + c.badge(f"Subject: {draft.subject}", "brand")
        + " " + c.badge(f"{draft.word_count()} words", "neutral")
        + " " + c.badge(draft.generator.replace("_", " ").title(), "neutral"),
        unsafe_allow_html=True,
    )
    st.code(draft.to_text(), language="text")
    st.download_button(
        "Download .txt", draft.to_text().encode("utf-8"),
        file_name=email_filename(draft, "txt"), mime="text/plain",
        key=f"em_txt_{job['id']}", use_container_width=True,
    )

    _render_letter_report(report)
    _render_evidence_used(draft, "Email evidence")
    if job.get("application_url"):
        st.link_button("Open application page ↗", job["application_url"])
    st.caption("If the posting asks you to apply through its portal, do that as well; "
               "this email is for reaching the right person, not bypassing the process.")


def _render_letter_report(report) -> None:
    for issue in report.issues:
        tone = "error" if issue.severity == "error" else ""
        st.markdown(f'<div class="consul-flag {tone}"><b>{c.esc(issue.code)}</b> — '
                    f'{c.esc(issue.message)}</div>', unsafe_allow_html=True)
    if report.unsupported_claims:
        with st.expander(f"Unsupported content ({len(report.unsupported_claims)})"):
            for text in report.unsupported_claims:
                st.write(f"- {text}")


def _render_evidence_used(draft, title: str) -> None:
    ids = draft.evidence_ids()
    if not ids:
        return
    with session_scope() as session:
        active = get_active_profile(session)
        values = ({item.evidence_id: item.value for item in active[1].evidence}
                  if active is not None else {})
    with st.expander(f"{title} ({len(ids)} citations)"):
        for evidence_id in ids[:24]:
            st.markdown(
                f"- {c.badge(evidence_id, 'neutral')} {c.esc(values.get(evidence_id, ''))}",
                unsafe_allow_html=True,
            )


def _render_ats_audit(audit: dict) -> None:
    """Score measured on the exported file, with every point traceable."""
    score = int(audit.get("score") or 0)
    status = str(audit.get("status") or "attention")
    tone = {"pass": "success", "attention": "warn", "blocked": "danger"}.get(status, "neutral")
    verdict = {
        "pass": "All hard gates pass",
        "attention": "Fixable gaps",
        "blocked": "Hard gate failed",
    }.get(status, status.title())

    st.markdown("##### ATS score for this posting")
    st.markdown(
        c.badge(f"{score}/100", tone)
        + " " + c.badge(verdict, tone)
        + " " + c.badge(f"Engine {audit.get('engine', 'consul-ats-sim')} "
                        f"{audit.get('version', '')}".strip(), "neutral"),
        unsafe_allow_html=True,
    )
    st.progress(min(1.0, max(0.0, score / 100)))
    if audit.get("blockers"):
        st.error("A real ATS could struggle to read this document: "
                 + ", ".join(audit["blockers"]) + ".")

    rows = [
        {
            "Criterion": item.get("label", ""),
            "Score": f"{item.get('points', 0):g}/{item.get('weight', 0)}",
            "Result": {"pass": "Pass", "partial": "Partial", "fail": "Fail"}.get(
                item.get("status", ""), item.get("status", "")),
            "Measured": item.get("detail", ""),
        }
        for item in audit.get("criteria") or []
    ]
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)

    if audit.get("fixes"):
        st.markdown("**What would raise the score**")
        for fix in audit["fixes"]:
            st.write(f"- {fix}")

    parsed = audit.get("parsed") or {}
    coverage = audit.get("keyword_coverage") or {}
    must = coverage.get("must_have") or {}
    with st.expander("What was measured, and on which file"):
        st.caption(
            f"Read from the {parsed.get('source', 'exported').upper()} "
            f"({parsed.get('pages', 0)} page(s), {parsed.get('characters', 0)} characters, "
            f"{parsed.get('file_kb', 0)} KB). Tokens recovered from the document model: "
            f"{float(parsed.get('recovery') or 0):.0%}. Tables: {parsed.get('tables', 0)}. "
            f"Text boxes: {parsed.get('text_boxes', 0)}. Images: {parsed.get('images', 0)}."
        )
        if parsed.get("fonts"):
            st.caption("Fonts a parser sees: " + ", ".join(parsed["fonts"]))
        if must.get("covered"):
            st.write("**Posting terms present in the parsed text:** "
                     + ", ".join(must["covered"][:14]))
        if must.get("missing_evidenced"):
            st.write("**Evidenced but absent from this document:** "
                     + ", ".join(must["missing_evidenced"][:14]))
        if must.get("unevidenced"):
            st.caption("Not evidenced, so never claimed: "
                       + ", ".join(must["unevidenced"][:14]))
        st.caption(audit.get("disclaimer", ""))
        st.caption(
            "Weights: text layer and extraction 12, contact fields 10, section recognition 12, "
            "reading order 8, job-specific keywords 30, title alignment 8, format safety 12, "
            "dates and recency 8."
        )
        for note in audit.get("notes") or []:
            st.caption(note)

    with st.expander("What the parser actually extracted"):
        st.caption("Verbatim text layer of the exported file. If something is missing here, "
                   "it is missing for the employer's system too.")
        st.code(audit.get("extracted_text") or "", language="text")


def _record_for(session, job_id: str):
    from services.job_service import row_to_record

    row = session.get(Job, job_id)
    return row_to_record(row)
