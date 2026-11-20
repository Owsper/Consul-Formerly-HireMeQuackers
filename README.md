# CONSUL (previously HireMeQuackers)

A local-first job discovery, candidate intelligence, CV tailoring and application
tracking workspace. It is a Streamlit app backed by a small set of services and a
SQLite database. Everything runs on your machine; no account, hosted database or
telemetry is involved.

The central rule is simple: **the Ground Truth CV is the only source of truth.**
Every generated CV bullet must point to an evidence item that came from a document
you uploaded or a fact you entered yourself. The app will drop a bullet rather than
invent a claim.

## What it does

| Area | Capability |
| --- | --- |
| Ground Truth CV | PDF/DOCX upload → text extraction (with OCR fallback) → LLM structured extraction → editable profile → explicit approval. Manual entry and multi-document merge are first-class fallbacks. |
| Evidence ledger | Every claim has an id, source document, status and audit trail. Rejecting an item excludes it from CVs but keeps it in history. |
| Search | Multiple search profiles across 15 IT disciplines (plus Any IT Category), custom titles, skill-driven multilingual planning, inspectable/editable queries, company registry. |
| Connectors | Greenhouse, Lever (US + EU), Ashby, SmartRecruiters, Workable, Recruitee, Personio, Workday, TeamTailor, Adzuna, Jooble, web-search discovery and generic company career pages. |
| Jobs | One normalised model, provenance per source, exact then fuzzy deduplication, honest listing statuses, 100-point scoring with configurable weights and separate eligibility. |
| CV Studio | Evidence-only tailor per job, mandatory master-template DOCX, ATS-safe PDF/TXT, document preview, explicit approval before download, layout-fidelity report, descriptive filenames and versions. |
| Tracker | Kanban + table, 14 default statuses plus custom ones, notes/contacts/interviews/follow-ups/salary, duplicate-application prevention. |
| Diagnostics | Per-source health (`healthy`, `partially_working`, `rate_limited`, `restricted`, `configuration_missing`, `unavailable`), request counts, errors, retry of failed sources. |

## Quick start

Python 3.11+ is required.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env             # optional, then edit
streamlit run app.py
```

The database and folders are created on first launch under `data/`.
The app works fully offline: without `GEMINI_API_KEY` it uses the deterministic
rule-based planner, scoring, and CV builder.

### Configuration

All configuration is environment based (`.env` is loaded automatically). Secrets
are never written to SQLite, logs or the UI.

- `GEMINI_API_KEY`, `GEMINI_MODEL` — Google Gemini (the default provider).
- `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` — use any other
  OpenAI-compatible provider (`openai`, `groq`, `openrouter`, `deepseek`,
  `mistral`, `cerebras`, `zai`, `ollama`, or `custom` with your own base URL).
- `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `LLM_REASONING_EFFORT`,
  `LLM_ENABLED` — request ceiling, output cap and optional reasoning cap;
  `LLM_ENABLED=0` runs fully offline. Groq's free tier counts `max_tokens`
  against its 8,000 tokens/minute budget: use `LLM_MAX_OUTPUT_TOKENS=6000`
  and `LLM_REASONING_EFFORT=low`.
- `DATABASE_URL`, `DATA_DIR`, `MAX_UPLOAD_MB` — storage.
- `CONSUL_SOFFICE` — optional path to a LibreOffice/soffice binary for DOCX→PDF.
- `HTTP_TIMEOUT_SECONDS`, `MAX_CONCURRENCY`, `USER_AGENT` — scanning behaviour.
- `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`, `JOOBLE_API_KEY` — optional aggregators.
- `SEARCH_PROVIDER` (`none`/`brave`/`serper`/`tavily`) + `SEARCH_API_KEY` — optional web discovery.
- `GREENHOUSE_BOARDS`, `LEVER_COMPANIES`, `ASHBY_BOARDS`, `SMARTRECRUITERS_COMPANIES`,
  `WORKABLE_ACCOUNTS`, `RECRUITEE_COMPANIES`, `PERSONIO_COMPANIES`,
  `WORKDAY_TENANTS`, `TEAMTAILOR_SITES` — seed boards, `Display Name:identifier`.
  They can also be managed in **Search Configuration → Companies**.

### OCR (optional)

Scanned PDFs fall back to OCR when Tesseract and `pytesseract` are installed.
Without them, the app tells you the PDF is image-only and offers manual entry.

## Project layout

```
app.py                  # Streamlit bootstrap: CSS, sidebar, page dispatch, error boundary
core/                   # schemas (Pydantic v2), SQLAlchemy models, DB, security, text utils
connectors/             # one module per source, shared base with retries/rate limits
services/               # extraction, profile, planning, scanning, scoring, CV, exports, tracker
prompts/                # versioned prompt templates (string.Template)
ui/                     # theme, components, navigation, 9 pages
tests/                  # pytest suite, all HTTP mocked with respx
templates/master_cv.docx      # the reusable master CV template (generated on demand)
templates/master_reference.pdf # bundled reference design (Rohan_Thomas_Vinu_CV.pdf)
data/                         # SQLite DB, uploads, exports, backups (gitignored)
```

## Interface

The workspace uses one design system (`ui/theme.py`) borrowed from our TerraTrace
mission console: warm near-black panels, a single signal-orange accent, Dela
Gothic One headlines, Archivo body text and Geist Mono for labels and numbers,
hairline borders and 4px corners. The dashboard opens on a colour-block hero.
Dark is the default; the toggle switches to a warm-paper daylight variant.
Navigation is grouped by Workspace, Find work, Apply and Operations. Cards,
badges, metrics, forms, tables, empty states and the CV preview share one
spacing and colour scale. Fonts are bundled in `ui/assets/fonts` (SIL OFL) and
inlined, so nothing loads from the network; keyboard focus is visible and
reduced-motion preferences are respected.

## Design notes

- **Truthfulness.** Extraction keeps a verbatim `source_text` for each fact.
  Deterministic evidence ids are stable across edits. The sanitizer removes bullets
  with unknown/missing evidence ids and numbers that do not appear in the ledger.
  LLM drafts that fail validation are replaced by the rule-based CV.
- **Approval.** Saving a profile does not silently mark evidence as verified.
  Approval is an explicit action, recorded as a new profile version.
- **No fabricated scans.** A connector only counts as scanned when it made a
  successful request. Failures are reported with their real status; an empty
  successful response is `partially_working`, not `healthy`.
- **No bypassing.** There is no CAPTCHA, login or anti-bot circumvention. Sites that
  block automated access are reported as restricted and can be added manually via
  Manual Search Assistance.
- **Deduplication.** Same source + source id updates the existing row. Cross-source
  matches use canonical URLs and a title/company/location fingerprint. History is
  never deleted; expired listings stay visible with their status.
- **Master template fidelity.** `templates/master_cv.docx` reconstructs the
  reference CV: A4, 57.7 pt side margins, Times/Liberation Serif 16/10.5/10/9.5 pt,
  111.6 pt date and label columns, underlined section headings with full-width
  rules, hanging bullets and two-column skill/language rows. Generated CVs load
  this template and populate named styles; they never build a generic layout.
- **Preview and approval.** Each version is previewed as a PDF in CV Studio. The
  download buttons stay locked until the exact version is approved. Re-exporting
  revokes approval so the new render must be reviewed. Ground Truth is untouched.
- **Layout verification.** After export, the PDF is measured (page size, margins,
  column alignment, bullet indentation, fonts, rules, overflow, page count) and
  compared with the bundled reference. Results appear in the version's Template
  fidelity panel and are stored with the validation report.
- **PDF rendering.** When LibreOffice/soffice is available (`CONSUL_SOFFICE`,
  `SOFFICE_PATH`, `PATH`, or a standard install) the exported DOCX is converted to
  PDF and that output is measured. Without a converter, a measured renderer draws
  the same geometry; the UI says which path was used.
- **Role-agnostic discovery.** `core/job_taxonomy.py` is the extensible registry of
  job families (software, web, games, embedded/IoT, networking, cloud/DevOps,
  security, AI/ML, data, databases, QA, robotics, support, hardware, IT consulting).
  A profile can select a category, a specialisation, Any IT Category, or a free-form
  custom title. Explicit titles always lead; category seeds only add alternatives.
- **Search profiles.** Profiles store target/alternative titles, category and
  specialisation, required/preferred skills, technologies, seniority, employment
  types, locations, work modes, languages, salary, work-authorisation constraints and
  planner notes. They can be edited, duplicated, activated and deactivated. Profiles
  live in SQLite JSON settings, so no migration is needed.
- **Skill-driven planning.** Gemini receives the profile, category context, category
  catalogue and verified candidate skills. The deterministic fallback uses the same
  taxonomy and skills, including local recruitment terms. Neither path is restricted
  to software titles.
- **Transferable matching.** `core/skill_transfer.py` recognises adjacency such as
  C++ → game/embedded or Python → automation/data. Transfers earn only partial credit,
  stay in the missing-requirements list, and are explained as "transferable, not
  equivalent" instead of silently qualifying the candidate.
- **Privacy.** Local SQLite only, redacting log formatter, upload type/size
  validation, SSRF checks on user-supplied URLs, and export/backup/delete controls
  in Settings. No analytics.

### Adding a job family

The search planner, scorer, connectors and CV tailor only read the taxonomy
registry. Add a family either in `core/job_taxonomy.py` with `register_category()`
or by creating `config/job_categories.json`:

```json
{"categories": [{
  "key": "quantum_engineering",
  "label": "Quantum Engineering",
  "titles": ["Quantum Software Engineer"],
  "specialisations": {"Quantum Software": ["Quantum Algorithm Developer"]},
  "core_skills": ["Qiskit", "Quantum Computing"],
  "translations": {"de": ["Quantenentwickler"]}
}]}
```

Restart the app after editing. No search-engine or matching code changes are
required, and custom titles always override category seeds.

## Tests

```bash
python -m pytest -q
```

The suite uses a disposable SQLite database per test and mocks all HTTP with
`respx`. It covers security/text helpers, profile lifecycle and merge, query
planning, the job taxonomy and multi-profile CRUD, transferable matching, every
connector, deduplication/enrichment, scoring, CV tailoring and exports,
applications, settings, document extraction, all nine UI pages, and a full
end-to-end workflow (profile → plan → mocked scan → scoring → CV → tracker).

Last run in this environment: **97 passed** in ~30 s (Python 3.11, Windows, LibreOffice 26.8 installed).
UI tests use Streamlit's `AppTest` and render every page against an empty database,
plus the tracker with a real application and CV Studio with a preview/approval gate.

## Known limitations

- AI extraction/planning/CV drafting needs a Gemini key; offline mode is
  deterministic and intentionally conservative.
- OCR requires system Tesseract; it is not bundled.
- Job-board APIs change without notice. Health statuses surface breakage instead of
  hiding it, and each connector can be disabled independently.
- Salary, visa and language fields are only filled when the advert states them.
- `workday` and `teamtailor` support the public career-site shapes documented in
  their modules; tenant-specific quirks may need configuration.
- DOCX→PDF conversion needs LibreOffice (or `CONSUL_SOFFICE` pointing at it).
  LibreOffice 26.8 is installed in this environment and is used automatically; on a
  machine without it the app uses the measured renderer and labels the preview
  accordingly. The DOCX remains the editable source in Word/LibreOffice.
- The reference design is single-column by requirement. Other uploaded references
  are not used to override the master layout; the master template is authoritative.
- Span-level layout comparison allows small metric tolerances (about 2–3 pt) for
  font substitution between Liberation Serif and Times New Roman.
- Category seeds and transferable-skill links are starting points, not claims about
  the candidate. Exact requirements stay in the missing list; verify adjacent skills
  before applying. Offline planning uses the deterministic taxonomy; Gemini can
  propose additional synonyms and multilingual titles when configured.
