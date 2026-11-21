"""CV Studio: evidence-cited, job-specific CVs with validation and export."""

from __future__ import annotations

import asyncio
from pathlib import Path

import streamlit as st

from config import get_settings
from core.database import session_scope
from core.exceptions import consulError
from core.models import Job
from services.cv_service import (
    approve_cv, ensure_document_audit, generate_cv_for_job, get_version, is_cv_approved,
    list_versions, load_cv, reexport, revoke_cv_approval,
)
from services.cv_tailoring import audit_cv_with_llm
from services.document_export import pdf_render_source
from services.job_service import get_match, list_jobs
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
