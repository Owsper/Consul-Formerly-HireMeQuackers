# CONSUL

**A local-first job discovery, candidate intelligence, CV tailoring and application tracking
workspace where every claim is traceable to evidence.**

CONSUL is a Streamlit application backed by a small set of Python services and a SQLite
database. It runs entirely on your machine: no account, no hosted database, no telemetry, no
background sync. You upload your CV, review what the app understood, approve it as your
**Ground Truth**, and from then on every match score and every generated CV bullet points back
to a specific item in that approved evidence ledger.

The central rule is simple:

> **The Ground Truth CV is the only source of truth.** If a fact cannot be traced to a document
> you uploaded or a fact you entered yourself, CONSUL will drop it rather than invent it.

---

## Table of contents

- [At a glance](#at-a-glance)
- [What it does](#what-it-does)
- [System architecture](#system-architecture)
- [Core concepts](#core-concepts)
- [End-to-end workflow](#end-to-end-workflow)
- [The nine pages](#the-nine-pages)
- [Job sources and connectors](#job-sources-and-connectors)
- [Search planning and the job taxonomy](#search-planning-and-the-job-taxonomy)
- [Matching and scoring](#matching-and-scoring)
- [CV Studio and document generation](#cv-studio-and-document-generation)
- [Application tracker](#application-tracker)
- [Diagnostics and source health](#diagnostics-and-source-health)
- [Data model and storage](#data-model-and-storage)
- [Installation and setup](#installation-and-setup)
- [Configuration reference](#configuration-reference)
- [First-run walkthrough](#first-run-walkthrough)
- [Running offline](#running-offline)
- [Extending CONSUL](#extending-consul)
- [Tests](#tests)
- [Privacy and security](#privacy-and-security)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

---

## At a glance

| | |
| --- | --- |
| **Interface** | Streamlit, nine pages, dark by default with a warm-paper light theme |
| **Runtime** | Python 3.11+ (verified on 3.11.9) |
| **Storage** | SQLite by default (`data/consul.db`); any SQLAlchemy URL is accepted |
| **AI** | Google Gemini by default; any OpenAI-compatible provider, or a local Ollama |
| **Offline** | Fully usable without an LLM: deterministic planning, scoring and CV generation |
| **Sources** | 13 connectors: nine ATS platforms, two aggregators, web search, generic career pages |
| **Documents** | ATS-safe DOCX, PDF and TXT generated from a fixed master template |
| **Privacy** | Local data only, redacting logs, SSRF protection, export/backup/delete controls |
| **Tests** | 109 tests, all HTTP mocked; suite runs in about 40–50 seconds |

### Design principles

1. **Truthfulness over polish.** Extraction stores a verbatim `source_text` for each fact. A
   generated bullet without a valid evidence id is removed before export. Numbers that do not
   appear in the ledger are treated as unsupported.
2. **Explicit approval.** Saving a profile does not silently verify it. Approval is a separate
   action that records a new profile version and activates it.
3. **Honest reporting.** A connector only counts as scanned when it made a successful request.
   Failures are reported with their real status; an empty successful response is
   `partially_working`, never `healthy`.
4. **No bypassing.** There is no CAPTCHA, login or anti-bot circumvention. Sites that block
   automated access are reported as restricted and can be added manually.
5. **You are the applicant.** CONSUL prepares documents and tracks applications. It never
   submits an application on your behalf.

---

## What it does

| Area | Capability |
| --- | --- |
| **Ground Truth CV** | PDF/DOCX upload, text extraction with OCR fallback, LLM structured extraction, editable profile, evidence review, explicit approval, manual entry and multi-document merge. |
| **Evidence ledger** | Granular, stable evidence ids with category, field path, source document, verbatim source text, confidence, inferred flag and review status. Rejected evidence stays in history but is excluded from CVs. |
| **Search profiles** | Multiple reusable profiles with target and alternative titles, IT category, specialisation, required/preferred skills, technologies, seniority, industries, locations, work modes, employment types, languages, salary floor, posting age, work-authorisation constraints and planner notes. |
| **Search planning** | LLM planning with a deterministic multilingual fallback; inspectable and editable query table; category catalogue; local-language titles; company registry. |
| **Discovery** | Parallel scans across enabled sources, preference filtering, exact/fuzzy deduplication, structured enrichment, 100-point scoring, saved shortlist, manual import from a URL or by hand. |
| **CV Studio** | Per-job, evidence-only tailoring; mandatory master template; DOCX/PDF/TXT export; in-app PDF preview; explicit approval gate; layout-fidelity report; optional second-pass LLM audit; descriptive filenames and versions. |
| **Tracker** | Kanban board, table view, 14 default statuses plus custom ones, notes, contacts, follow-up and interview dates, salary notes, outcome notes, activity log and duplicate-application prevention. |
| **Diagnostics** | Per-source health, configured/enabled state, request counts, errors, duration, scan history and one-click retry of failed sources. |
| **Privacy controls** | SQLite backup, full JSON export, delete all career data, delete generated files, redacted logs. |

---

## System architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            Streamlit UI (app.py)                        │
│  dashboard · profile · discovery · configuration · saved · cv_studio    │
│  tracker · diagnostics · settings                                       │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ session_scope() — one transactional SQLAlchemy session per action
┌───────────────▼──────────────────────────────────────────────────────────┐
│                                services/                                 │
│  cv_extraction   profile_service   query_planner   search_orchestrator   │
│  search_profile_service   company_service   deduplication                │
│  job_enrichment  job_scoring  job_service  cv_tailoring  cv_service      │
│  document_export  master_template  layout_verification  application_service│
│  settings_service  llm_service                                           │
└───────┬───────────────────────────┬───────────────────────────┬──────────┘
        │                           │                           │
┌───────▼─────────┐   ┌─────────────▼───────────┐   ┌───────────▼──────────┐
│   connectors/   │   │          core/          │   │       prompts/       │
│ 13 sources,     │   │ schemas, ORM models,    │   │ versioned $template  │
│ shared HTTP,    │   │ database, security,     │   │ prompt files         │
│ retries, limits │   │ text, taxonomy, skills  │   │                      │
└───────┬─────────┘   └─────────────┬───────────┘   └──────────────────────┘
        │                           │
        │                  ┌────────▼─────────┐        ┌──────────────────┐
        └─────────────────►│  SQLite database │        │ data/uploads      │
          outbound HTTP    │  data/consul.db  │        │ data/exports      │
          (job boards)     └──────────────────┘        │ data/backups      │
                                                       └──────────────────┘
```

### Layer responsibilities

| Layer | Responsibility |
| --- | --- |
| `app.py` | Page config, startup bootstrap (directories, logging, database), CSS injection, sidebar navigation, page dispatch and a top-level error boundary. |
| `ui/` | Theme (one design system), reusable components, navigation and nine page modules. Pages call services; they do not contain matching or extraction logic. |
| `services/` | Business logic: extraction, profile lifecycle, planning, orchestration, deduplication, enrichment, scoring, CV generation, export, verification, tracker operations. |
| `connectors/` | One module per source. All share `BaseConnector`, `HttpSession`, `RateLimiter` and normalisation helpers. Every connector is independently configurable and independently reported. |
| `core/` | Pydantic v2 contracts, SQLAlchemy 2.0 models, engine/session management, security helpers, text normalisation, the job-family taxonomy and transferable-skill rules. |
| `prompts/` | Plain-text prompt templates using `string.Template` placeholders, loaded by `llm_service.render_prompt()`. |
| `templates/` | The authoritative master CV template and the reference PDF used for layout comparison. |
| `tests/` | Pytest suite with a disposable database per test and all HTTP mocked by `respx`. |

### Request and data flow

1. **Ingest.** A PDF/DOCX is validated (type, size), text is extracted, and an optional LLM
   converts it into `CandidateProfileData` plus evidence items. Manual entry and merging are
   first-class alternatives.
2. **Approve.** The profile and evidence ledger are saved as a version. Only an approved,
   active profile can power discovery or CV generation.
3. **Plan.** The planner produces a `SearchPlan` of `PlannedQuery` objects, either from the LLM
   or deterministically from the profile, selected category and multilingual title tables.
4. **Scan.** The orchestrator runs enabled connectors concurrently, enforces per-source timeouts,
   builds a relevance context, then persists, enriches, deduplicates and scores results.
5. **Review.** Jobs are browsed with their provenance, listing status, score breakdown,
   eligibility, missing requirements and transferable skills.
6. **Tailor.** CV Studio selects only relevant, non-rejected evidence, drafts bullets, sanitises
   them, validates citations and numeric claims, exports the master template and measures the PDF.
7. **Approve and track.** The exact rendered version must be approved before download. Tracking
   an application creates one tracker row per job and logs every change.

---

## Core concepts

### Ground Truth profile

`CandidateProfileData` is the application-independent record of the candidate:

- **personal** — name, professional title, email, phone, city, country, LinkedIn, GitHub,
  portfolio, website
- **work authorization** — residence country, visa status, authorization flag, hour
  restrictions, sponsorship requirement, relocation preference, geographic limitations
- **education** — institution, qualification, degree, subject, dates, status, coursework,
  academic projects, achievements
- **employment** — employer, title, location, dates, current flag, responsibilities,
  achievements, technologies, quantified results
- **projects** — name, description, team type, role, technologies, implementation, measurable
  results, dates, GitHub URL, verified achievements, and a `project`/`academic_project` label
- **skills** — named skill groups
- **additional** — certifications, awards, publications, volunteering, languages, professional
  interests and free-form extras

List entries receive stable ids (`edu-1`, `emp-2`, `prj-1`, `cert-1`, …) so evidence can point at
them across edits.

### Evidence ledger

Every fact becomes a `ProfileEvidence` row with:

| Field | Meaning |
| --- | --- |
| `evidence_id` | Stable identifier used by CV bullets and match rationales |
| `category` | `personal`, `employment`, `project`, `skill`, `language`, … |
| `field_path` | Location in the profile, e.g. `employment[0].responsibilities[2]` |
| `label`, `value` | Human-readable fact |
| `source_document` | Uploaded filename or `manual` |
| `source_text` | Verbatim text the fact came from |
| `confidence` | 0.0–1.0 |
| `inferred` | True when the fact was inferred rather than quoted |
| `status` | `unverified`, `needs_review`, `user_verified` or `rejected` |

Rejecting an item removes it from CV generation and scoring evidence while preserving it in the
audit trail. Approval of the profile does **not** automatically upgrade individual evidence
statuses.

### Versions and approvals

- **Profile versions.** Every save creates a `ProfileVersion` containing the profile and evidence
  snapshots. Older versions can be restored from the Ground Truth page.
- **Search profiles.** Multiple named search profiles live as JSON in `UserSetting`, so adding or
  editing them requires no database migration. They can be created, edited, duplicated, activated
  and deactivated.
- **CV versions.** Every generation for a job creates a new `TailoredCVRow` with its content,
  evidence map, validation report, layout report, generator and file paths. Approval is recorded
  per CV id in `UserSetting` as `cv_approved_<id>`; re-exporting revokes it so the new render must
  be reviewed.
- **Tracker activity.** Status changes and notable edits append `ApplicationActivity` entries.

---

## End-to-end workflow

```
Upload CV ──► extract text ──► structured draft ──► review evidence ──► approve profile
                                                                           │
                                       ┌───────────────────────────────────┘
                                       ▼
                          create/activate search profile
                                       │
                                       ▼
                     plan queries (LLM or deterministic)
                                       │
                                       ▼
             scan enabled sources ──► normalise ──► deduplicate ──► enrich
                                       │
                                       ▼
                          score every job against evidence
                                       │
                    ┌──────────────────┼───────────────────┐
                    ▼                  ▼                   ▼
                 save job          tailor CV          track application
                                       │
                                       ▼
                         DOCX + PDF + TXT from master template
                                       │
                                       ▼
                          validate ──► preview ──► approve ──► download
```

A scan is allowed to be incomplete, but it is never allowed to be dishonest: sources that failed
stay failed in the report, expired listings keep their status, snippets stay marked unverified,
and jobs are stored unscored if no profile is approved.

---

## The nine pages

### 1. Dashboard (`ui/pages/dashboard.py`)

A truthful overview: jobs discovered, strong matches, saved jobs, applications and interviews,
a pipeline strip, a five-step onboarding checklist, recently discovered jobs with scores, upcoming
follow-ups and interviews, search-health summary, and direct navigation buttons. Empty states
explain what is missing instead of showing placeholder data.

### 2. Ground Truth CV (`ui/pages/profile.py`)

Three tabs guide the profile through review:

1. **Profile details** — the full editor for personal details, work authorization, education,
   employment, projects, skills and additional sections.
2. **Evidence ledger** — every item with source, confidence and status; items can be accepted or
   rejected.
3. **Review & approve** — validation warnings (missing name, missing contact details, no
   experience/projects/skills), an explicit confirmation checkbox, then either **Save without
   activating** or **Approve and activate profile**.

Also available:

- upload a PDF or DOCX and extract with AI (or start manual entry)
- merge a second document into the current draft; verified contact details and work authorization
  are never overwritten by a merge
- browse profile versions and restore an earlier one
- delete a selected profile and its history after an explicit confirmation

### 3. Job Discovery (`ui/pages/discovery.py`)

- Shows the active search profile and whether a Ground Truth profile is approved.
- Lets you adjust the search focus, generate a plan and **edit the query table** (query, language,
  target, priority, rationale). The edited plan is what gets executed.
- Displays configured versus missing sources before a scan.
- Runs a scan over selected, enabled sources with a live progress bar and per-source completion log.
- Shows the scan report, source health table and a retry button for failed sources.
- Filters results by text, score, work mode, listing status, saved state and source.
- Expands each job into its description, extracted requirements, provenance and score breakdown.
- Supports re-checking a listing and adding jobs manually:
  - **From a URL** — fetch and parse a career page
  - **Enter details** — create a job by hand when a source blocks automation

### 4. Search Configuration (`ui/pages/configuration.py`)

Three tabs:

- **Preferences** — edit the full search profile schema, including category, specialisation,
  titles, skills, seniority, locations, work modes, employment types, languages, salary,
  posting age, exclusions and planner notes. Profiles can be saved, activated, duplicated and
  deleted.
- **Sources** — enable or disable each connector, see what configuration it needs, reload `.env`,
  seed boards from environment variables, and manage the company registry (add a company by name
  and career URL; known ATS URLs are detected automatically).
- **Scoring** — edit the eight scoring weights. Weights are normalised to 100. Existing matches
  keep their recorded score until rescanned.

### 5. Saved Jobs (`ui/pages/saved.py`)

The shortlist between discovery and applying. Each saved job shows its score breakdown, a free
notes field, and actions to remove it, add it to the tracker as `Shortlisted`, or generate a CV.

### 6. CV Studio (`ui/pages/cv_studio.py`)

- Choose a job, CV language (English, German, French, Spanish, Dutch) and export formats.
- Toggle LLM drafting; without an LLM the deterministic evidence-only builder is used.
- Generate a version, then review:
  - in-app PDF preview rendered from the DOCX
  - validation report: passed/failed, evidence coverage, unsupported claims, removed content,
    matched and unmet requirements, ATS checks
  - template-fidelity panel from the layout comparison
- **Approve this CV** unlocks downloads for that exact version. Approval is blocked while
  validation or layout checks report errors.
- Revoke approval, re-export files (which requires re-approval), or run a second-pass LLM audit.
- Browse all versions for the job.

### 7. Application Tracker (`ui/pages/tracker.py`)

Three views:

- **Board** — Kanban columns for every status, including custom ones.
- **Table** — sortable/filterable table of all applications.
- **Add** — create an application from a discovered job or from a manually entered job.

The detail panel manages status, tailored CV link, cover letter, notes, contact person, applied
date, follow-up date, interview date, salary notes and outcome notes. Each change is logged. One
application per job is enforced; creating a second is rejected as a duplicate.

Default statuses:

```
Discovered → Shortlisted → Reviewing → CV generated → Ready to apply → Applied
→ Assessment → Interview → Technical interview → Final interview → Offer received
→ Rejected / Withdrawn / Archived
```

Custom statuses can be added and removed in Search Configuration.

### 8. Search Diagnostics (`ui/pages/diagnostics.py`)

Answers "what actually happened?":

- source catalogue with kind, description, required variables, configured state, enabled state
  and last known health
- last-scan summary: jobs seen, new, unique, snippets, and a per-source table
- requests made / succeeded / failed, queries executed, duration, error text and last success
- scan history
- retry only the failed sources

Console timestamps and the `data/consul.log` file hold the same events, with secrets redacted.

### 9. Settings (`ui/pages/settings.py`)

- Appearance (dark/light, persisted per profile)
- Read-only runtime configuration: provider, model, database file, data directory, HTTP timeout,
  concurrency, environment-variable reference
- Create and download a consistent SQLite backup
- Export all user-owned data as JSON
- Privacy notes and log location
- **Delete all career data** (typed `DELETE` confirmation) and delete generated files, uploads
  and backups
- App version, stack and database job count

---

## Job sources and connectors

All connectors live in `connectors/` and share retry/backoff, `Retry-After` handling, per-source
pacing, SSRF-validated URLs and request statistics. None of them bypasses authentication or
anti-bot protection.

| Connector | Key | Kind | Configuration | Behaviour |
| --- | --- | --- | --- | --- |
| Greenhouse | `greenhouse` | ATS | `GREENHOUSE_BOARDS` | Public board API `/v1/boards/{token}/jobs` plus job detail |
| Lever | `lever` | ATS | `LEVER_COMPANIES` | Public postings API, including EU-hosted instances |
| Ashby | `ashby` | ATS | `ASHBY_BOARDS` | Public job-board posting API |
| SmartRecruiters | `smartrecruiters` | ATS | `SMARTRECRUITERS_COMPANIES` | Company postings list plus detail |
| Workable | `workable` | ATS | `WORKABLE_ACCOUNTS` | Public account widget API |
| Recruitee | `recruitee` | ATS | `RECRUITEE_COMPANIES` | Public offers API |
| Personio | `personio` | ATS | `PERSONIO_COMPANIES` | Public XML career feeds |
| Workday | `workday` | ATS | `WORKDAY_TENANTS` | Public CXS job search; tenants configured as `tenant/site@host` |
| TeamTailor | `teamtailor` | ATS | `TEAMTAILOR_SITES` | Public job index plus `JobPosting` JSON-LD; `Company:subdomain` or a full careers URL |
| Adzuna | `adzuna` | Aggregator | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ADZUNA_COUNTRY` | Free developer tier; aggregates many boards |
| Jooble | `jooble` | Aggregator | `JOOBLE_API_KEY` | Free key on request; POST search API |
| Web search discovery | `search_engine` | Search | `SEARCH_PROVIDER`, `SEARCH_API_KEY` | Brave, Serper or Tavily; results are snippets and stay marked unverified |
| Company career pages | `company_careers` | Careers | Company registry entries | Fetches career pages directly and extracts `JobPosting` JSON-LD |

### Board seed syntax

Seed boards can be supplied in `.env` or managed in **Search Configuration → Companies**:

```text
GREENHOUSE_BOARDS=Acme:acme,Other Co:otherco
LEVER_COMPANIES=Acme:acme
ASHBY_BOARDS=Acme:acme
SMARTRECRUITERS_COMPANIES=Acme:acme
WORKABLE_ACCOUNTS=Acme:acme
RECRUITEE_COMPANIES=Acme:acme
PERSONIO_COMPANIES=Acme:acme
WORKDAY_TENANTS=Acme/External@acme.wd1.myworkdayjobs.com
TEAMTAILOR_SITES=Acme:acme
```

A bare identifier is also accepted and used as the display name. A company added through the UI
with a recognised ATS URL is converted into the matching provider and identifier; otherwise it
becomes a `company_careers` entry.

### What counts as a scanned source

| Observed outcome | Status |
| --- | --- |
| At least one successful request and at least one job | `healthy` |
| Successful requests but zero jobs | `partially_working` |
| HTTP 429 after retries | `rate_limited` |
| HTTP 401/403 | `restricted` |
| Required credentials or board ids missing | `configuration_missing` |
| Transport failure, timeout, crash or empty failure | `unavailable` |

A source that is disabled or not selected is listed as not scanned, not as healthy.

---

## Search planning and the job taxonomy

`services/query_planner.py` builds a `SearchPlan` containing:

- candidate summary
- selected IT category and specialisation
- role families
- English titles
- local-language titles per language
- keywords and exclude terms
- up to 40 deduplicated `PlannedQuery` entries (`query`, `language`, `target`, `priority`,
  `rationale`)
- source (`llm` or `rule_based`) and warnings

**With an LLM**, Gemini or the configured OpenAI-compatible provider receives the verified
profile, category context, category catalogue and skills. **Without one**, the rule-based planner
uses the same taxonomy, country-to-language mapping, local recruitment terms and role
translations. Explicit target titles always lead; category seeds only add alternatives.

### Category registry

`core/job_taxonomy.py` is the extensible registry. It ships with 15 IT families plus the
**Any IT Category** option:

software engineering · web development · game development · embedded systems, firmware & IoT ·
networking & IT infrastructure · cloud engineering & DevOps · cybersecurity · AI & machine
learning · data engineering, science & analytics · database administration · QA engineering &
software testing · robotics & automation · IT support & systems administration · hardware &
computer engineering · technical consulting & IT business analysis

Each category defines titles, specialisations, core skills, keywords, translations (German,
French, Spanish, Dutch, Italian, Polish, Portuguese) and related categories.

### Adding a job family

Option A — register in code:

```python
from core.job_taxonomy import JobCategory, register_category

register_category(JobCategory(
    key="quantum_engineering",
    label="Quantum Engineering",
    titles=("Quantum Software Engineer",),
    specialisations={"Quantum Software": ("Quantum Algorithm Developer",)},
    core_skills=("Qiskit", "Quantum Computing"),
    translations={"de": ("Quantenentwickler",)},
))
```

Option B — create `config/job_categories.json` (loaded automatically at import time):

```json
{
  "categories": [
    {
      "key": "quantum_engineering",
      "label": "Quantum Engineering",
      "titles": ["Quantum Software Engineer"],
      "specialisations": {"Quantum Software": ["Quantum Algorithm Developer"]},
      "core_skills": ["Qiskit", "Quantum Computing"],
      "translations": {"de": ["Quantenentwickler"]}
    }
  ]
}
```

Restart the app after editing. The planner, scorer, connectors and CV tailor all read the
registry, so no engine changes are needed. Custom titles always override category seeds.

---

## Matching and scoring

Scoring is deterministic and inspectable. The LLM is not asked "is this a good match"; every
dimension has a weight, a score and a rationale. Eligibility is reported separately from
suitability.

### Dimensions and default weights

| Dimension | Default weight | What it measures |
| --- | ---: | --- |
| `technical_skills` | 30 | Required skills evidenced directly, with partial credit for adjacent skills |
| `experience_evidence` | 20 | Relevant employment and project evidence |
| `role_responsibilities` | 15 | Overlap between the advert's responsibilities and the candidate's history |
| `education` | 10 | Advertised education level versus the highest evidenced qualification |
| `seniority` | 10 | Seniority inferred from titles and years of listed employment |
| `location_preferences` | 5 | Country, work mode and on-site compatibility |
| `languages` | 5 | Stated language requirements versus evidenced proficiency |
| `work_authorization` | 5 | Country of residence, authorization flag and sponsorship statements |

Weights are normalised to 100 and editable in **Search Configuration → Scoring**. Existing matches
keep their recorded score until the job is rescored.

### The result

A `MatchResult` includes:

- total score (0–100) and separate suitability score
- eight `DimensionScore` entries with rationale and evidence ids
- `classification`: `excellent`, `strong`, `potential`, `weak` or `not_recommended`
- `eligibility`: `eligible`, `likely_eligible`, `unclear` or `ineligible`, with concerns
- matching skills, missing required skills, preferred skills held
- transferable skills summary and explanations
- relevant projects and experience
- education alignment, language compatibility and work-authorization notes
- red flags, a plain-language explanation and a recommended action

### Transferable skills

`core/skill_transfer.py` recognises adjacency such as C++ → games/embedded/robotics,
Python → automation/data, SQL → databases/analytics, Docker → Kubernetes, AWS → Azure/GCP, and
sibling tool families such as PyTorch/TensorFlow or Selenium/Playwright/Cypress.

Transfers earn **only partial credit**, remain in the missing-requirements list, and are labelled
"transferable, not equivalent". They never silently qualify the candidate.

### Hard constraints and red flags

Eligibility can become `ineligible` when the profile explicitly denies work authorization, when
the advert offers no sponsorship while the profile requires it, or when a language requirement is
unmet. Red flags also cover large seniority gaps and several missing required skills. Employment
type mismatches appear as concerns.

---

## CV Studio and document generation

### The master template is mandatory

`templates/master_cv.docx` reconstructs the bundled reference design
(`templates/master_reference.pdf`) as a real DOCX with named styles. It is generated on demand
from `services/master_template.py` if missing. Generated CVs load this template, clear its sample
body and populate the named styles. They never build a fresh generic layout and cannot be
overridden by uploading another reference.

Measured geometry:

| Property | Value |
| --- | --- |
| Page | A4, 595.28 × 841.89 pt |
| Side margins | 57.7 pt left, 57.65 pt right |
| Top / bottom margins | 44.5 pt / 57.7 pt |
| Font | Times New Roman (Liberation Serif metric substitute) |
| Name / body / meta / section sizes | 16 / 10 / 9.5 / 10.5 pt |
| Date and label column | 111.6 pt |
| Bullet hanging indent | 12.9 pt |
| Section rules | 0.5 pt, full content width (480 pt) |
| Named styles | `Consul Name`, `Consul Contact`, `Consul Detail`, `Consul Section`, `Consul Entry`, `Consul Meta`, `Consul Bullet`, `Consul Row`, `Consul Body` |

### Two generators, one guarantee

- **LLM generator** — recruiter-style rewriting using only permitted facts. It receives the
  Ground Truth profile, the evidence ledger and the target job.
- **Deterministic generator** — used offline or when LLM output fails validation. It selects,
  orders and lightly edits existing facts; it never writes new claims.

Both outputs pass through the same deterministic pipeline:

1. **Sanitiser** — removes bullets with missing or unknown evidence ids, fixes unsupported
   formatting, and records every removal.
2. **Validator** — checks evidence coverage, verifies every bullet id exists and is not rejected,
   verifies every number appears in the evidence corpus, checks contact details, standard headings,
   absence of emoji/icons/skill bars, chronological order, estimated length, requirement coverage
   and that academic projects are not presented as employment.
3. **Fallback** — if an LLM draft still fails, the deterministic CV replaces it.

The resulting `ValidationReport` stores `passed`, issues by severity, evidence coverage,
unsupported claims, matched and unmet requirements, removed content, ATS checks and the layout
report.

### Export

- **DOCX** — populated into the master template and editable in Word or LibreOffice.
- **PDF** — converted from that DOCX with LibreOffice when available. Without a converter, a
  measured renderer draws the same geometry directly, and the UI labels which path was used.
- **TXT** — plain-text ATS-safe rendering.

Filenames are descriptive and versioned:

```text
consul_CV_<Candidate>_<Company>_<JobTitle>_v<version>.docx
```

### Preview, approval and review

Every version is previewed as a PDF inside CV Studio. Approval is per version and is blocked when
validation or layout checks report errors. Download buttons exist only for an approved version.
**Re-exporting revokes approval** so the new render must be reviewed again. The optional
second-pass LLM audit asks the model to find unsupported claims in the generated CV.

### Layout verification

After export, `services/layout_verification.py` measures the PDF with PyMuPDF and compares it with
`templates/master_reference.pdf`:

- page size and margins
- main column and date column alignment
- bullet indentation
- font family and name/body sizes
- section rules and their width
- text overflow on the right and bottom
- page count

Tolerances are about 2.5 pt to allow metric-compatible font substitution. Results appear in the
version's template-fidelity panel and are stored in the validation report. Layout verification
never blocks an export; failures are reported honestly.

### CV language

The deterministic builder supports English, German, French, Spanish and Dutch headings, summary
templates and date formatting. Section content stays in the language of the evidence.

---

## Application tracker

Each `Application` is linked to exactly one job and carries:

`status`, `tailored_cv_id`, `cover_letter`, `notes`, `contact_person`, `follow_up_date`,
`interview_date`, `applied_at`, `salary_notes`, `outcome_notes` and `sort_order`.

- 14 default statuses plus unlimited custom statuses
- closed statuses: `Rejected`, `Withdrawn`, `Archived`
- duplicate prevention: one application per job id
- activity log for status and detail changes
- `upcoming()` powers the dashboard's 14-day follow-up and interview panel
- manual jobs are supported for sources that cannot be scanned

---

## Diagnostics and source health

Every scan creates a `ScanSession` with per-source `ScanSourceReport` rows and, when a plan was
used, `ScanQuery` rows. Reports include:

- connector key and display name
- status and error text
- queries executed
- requests made, succeeded and failed
- jobs found and accepted
- duration
- last success timestamp

Retrying a failed source creates a new scan restricted to those connectors. Scan history is capped
for display but retained in the database. Nothing in the UI fabricates success: if the network is
down, the report says so.

---

## Data model and storage

### Tables

| Table | Purpose |
| --- | --- |
| `candidate_profiles` | Profile JSON, name, active flag, approval timestamp |
| `profile_evidence` | Evidence ledger rows, unique per `(profile_id, evidence_id)` |
| `profile_versions` | Profile and evidence snapshots, unique per `(profile_id, version)` |
| `companies` | Company/ATS registry, health, last scan, jobs seen |
| `jobs` | Canonical normalised job rows with source-independent fields |
| `job_sources` | Provenance per connector and source job id, unique per pair |
| `job_matches` | One match result per job, including score, eligibility and full payload |
| `saved_jobs` | Shortlist notes, one per job |
| `tailored_cvs` | CV content, evidence map, validation, layout, file paths, generator |
| `applications` | Tracker rows, one per job |
| `application_activities` | Append-only tracker history |
| `scan_sessions`, `scan_source_reports`, `scan_queries` | Scan diagnostics |
| `search_preferences` | Legacy compatibility table; active profiles live in `user_settings` |
| `user_settings` | JSON settings: search profiles, UI settings, scoring weights, approvals, custom statuses |

### Files

```
data/
├── consul.db          # SQLite database (WAL mode, foreign keys on)
├── consul.log         # redacted application log
├── uploads/           # created at startup; cleared by the Settings delete-files action
├── exports/           # generated DOCX/PDF/TXT and JSON exports
└── backups/           # consistent SQLite backups
```

`DATABASE_URL` can point at another SQLite file or a PostgreSQL instance. SQLite pragmas
(`foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`) are applied automatically. Backups
use SQLite's online backup API, so they are consistent while the app is running.

---

## Installation and setup

### Prerequisites

| Requirement | Needed for | Notes |
| --- | --- | --- |
| Python 3.11+ | Everything | 3.11.9 is the verified version |
| pip and venv | Installation | Bundled with Python |
| An LLM API key | AI extraction, planning, drafting | Optional; the app is fully usable offline |
| Tesseract + `pytesseract` | OCR for scanned PDFs | Optional and not bundled |
| LibreOffice | DOCX → PDF conversion | Optional; a measured renderer is the fallback |

### Quick start (Linux / macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional; edit to add an LLM key
streamlit run app.py
```

Open <http://localhost:8501>.

### Quick start (Windows, Git Bash / PowerShell)

```bash
python -m venv .venv
source .venv/Scripts/activate       # Git Bash
# .venv\Scripts\activate            # PowerShell or cmd
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

`app.py` creates `data/`, `data/uploads/`, `data/exports/` and `data/backups/`, configures logging,
initialises the schema and seeds UI defaults on first launch. No migration step is required.

### Optional: OCR for scanned PDFs

```bash
# Windows (winget)
winget install --id UB-Mannheim.TesseractOCR
pip install pytesseract

# macOS
brew install tesseract
pip install pytesseract

# Debian / Ubuntu
sudo apt install tesseract-ocr
pip install pytesseract
```

Without Tesseract, CONSUL detects that a PDF is image-only and offers manual entry instead of
pretending extraction succeeded.

### Optional: LibreOffice for PDF fidelity

CONSUL looks for a converter in this order:

1. `CONSUL_SOFFICE`
2. `SOFFICE_PATH`
3. `LIBREOFFICE_PATH`
4. `soffice` or `libreoffice` on `PATH`
5. standard install paths for Windows, Linux and macOS

```bash
# macOS
brew install --cask libreoffice

# Debian / Ubuntu
sudo apt install libreoffice

# Windows: install LibreOffice, then optionally
CONSUL_SOFFICE=C:/Program Files/LibreOffice/program/soffice.exe
```

If no converter is found, the built-in measured renderer produces the PDF and the UI states that
LibreOffice was not used. The DOCX remains the editable source either way.

### Optional: local model with Ollama

```bash
ollama pull llama3.1
ollama serve
```

Then set:

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
# LLM_BASE_URL defaults to http://localhost:11434/v1
```

Ollama needs no API key.

---

## Configuration reference

All configuration is environment based. `.env` in the project root is loaded automatically with
`load_dotenv(override=False)`, so real environment variables win. Secrets are never written to
SQLite, logs or the UI.

### LLM providers

`LLM_PROVIDER` selects the backend. Gemini speaks its native API; every other provider uses the
OpenAI `/chat/completions` shape.

| `LLM_PROVIDER` | Default base URL | Default model |
| --- | --- | --- |
| `gemini` | native Google Gen AI SDK | `gemini-2.5-flash` |
| `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` |
| `groq` | `https://api.groq.com/openai/v1` | `openai/gpt-oss-20b` |
| `openrouter` | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| `mistral` | `https://api.mistral.ai/v1` | `mistral-small-latest` |
| `cerebras` | `https://api.cerebras.ai/v1` | `llama-3.3-70b` |
| `zai` | `https://api.z.ai/api/paas/v4` | `glm-4-flash` |
| `ollama` | `http://localhost:11434/v1` | `llama3.1` |
| `custom` | must set `LLM_BASE_URL` | must set `LLM_MODEL` |

`LLM_BASE_URL` and `LLM_MODEL` override the preset. `LLM_API_KEY` is accepted as an alias for
`ZAI_API_KEY`, and `LLM_BASE_URL` for `ZAI_API_BASE`.

### Environment variables

#### AI

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `gemini` | Provider selection |
| `LLM_ENABLED` | `1` | Set `0` to disable all model calls |
| `GEMINI_API_KEY` | — | Key for the Gemini provider |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model |
| `LLM_API_KEY` | — | Key for any non-Gemini provider |
| `LLM_MODEL` | provider default | Model override |
| `LLM_BASE_URL` | provider default | Endpoint override |
| `LLM_TIMEOUT_SECONDS` | `45` | Hard per-request timeout |
| `LLM_MAX_OUTPUT_TOKENS` | `8192` | Output cap |
| `LLM_REASONING_EFFORT` | empty | `low`, `medium` or `high` for reasoning models |

> **Groq note.** Groq's free tier counts `max_tokens` against an 8,000 tokens/minute budget. Use
> `LLM_MAX_OUTPUT_TOKENS=6000` and `LLM_REASONING_EFFORT=low`. If a reasoning model spends the
> whole budget on reasoning and returns no answer, CONSUL reports exactly that instead of a
> generic empty response.

#### Storage

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATA_DIR` | `./data` | Database, logs, uploads, exports and backups |
| `DATABASE_URL` | `sqlite:///<DATA_DIR>/consul.db` | SQLAlchemy connection URL |
| `MAX_UPLOAD_MB` | `10` | Upload size limit |

#### Networking and scanning

| Variable | Default | Purpose |
| --- | --- | --- |
| `HTTP_TIMEOUT_SECONDS` | `20` | Per-request HTTP timeout |
| `MAX_CONCURRENCY` | `8` | Sources scanned in parallel |
| `PER_SOURCE_CONCURRENCY` | `3` | Concurrency for connectors that fan out requests (SmartRecruiters detail fetches) |
| `USER_AGENT` | `consul/1.0 (personal job search assistant)` | Outbound User-Agent; set a contact if you like |

#### Documents

| Variable | Purpose |
| --- | --- |
| `CONSUL_SOFFICE`, `SOFFICE_PATH`, `LIBREOFFICE_PATH` | Explicit LibreOffice/soffice binary |

#### Aggregators (optional)

| Variable | Purpose |
| --- | --- |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Adzuna API credentials |
| `ADZUNA_COUNTRY` | Adzuna country code, default `de` |
| `JOOBLE_API_KEY` | Jooble API key |

#### Web search discovery (optional)

| Variable | Purpose |
| --- | --- |
| `SEARCH_PROVIDER` | `none`, `brave`, `serper` or `tavily` |
| `SEARCH_API_KEY` | Provider key |

#### ATS board seeds (optional)

`GREENHOUSE_BOARDS`, `LEVER_COMPANIES`, `ASHBY_BOARDS`, `SMARTRECRUITERS_COMPANIES`,
`WORKABLE_ACCOUNTS`, `RECRUITEE_COMPANIES`, `PERSONIO_COMPANIES`, `WORKDAY_TENANTS`,
`TEAMTAILOR_SITES`.

#### Diagnostics

| Variable | Purpose |
| --- | --- |
| `CONSUL_DEBUG` | Any non-empty value enables debug-level logging |

### Streamlit theme

`.streamlit/config.toml` sets the dark palette, the signal-orange accent, the sans-serif base and
`gatherUsageStats = false`. The light theme is CSS-driven inside `ui/theme.py`. Fonts (Dela Gothic
One, Archivo, Geist Mono) are bundled in `ui/assets/fonts` under the SIL Open Font License and
inlined, so nothing loads from the network.

---

## First-run walkthrough

1. **Start the app.**
   ```bash
   streamlit run app.py
   ```
2. **Add an LLM key (optional).** Edit `.env` and set `GEMINI_API_KEY`, or choose another
   provider. Without a key, skip straight to the next step.
3. **Build the Ground Truth.** Open **Ground Truth CV** → **Upload a CV**, choose a PDF/DOCX and
   start extraction. If extraction is unavailable or unsatisfactory, use **Enter manually**.
4. **Review the evidence ledger.** Check each fact, its source and its status. Reject anything
   that is wrong or that you do not want used. Rejected items are kept as history but excluded
   from CVs.
5. **Approve and activate.** Confirm the accuracy checkbox and click **Approve and activate
   profile**. Discovery and CV generation are now unlocked.
6. **Configure search.** Open **Search Configuration** → **Preferences**. Create a search profile
   with target titles, category, skills, locations and work modes; activate it. Then open
   **Sources** and enable the sources you can configure. Add company boards if you know them.
7. **Plan queries.** Open **Job Discovery**. Generate a plan, inspect the query table, edit
   languages, targets and priorities, and save it.
8. **Run a scan.** Select sources and start the scan. Watch the progress log. Read the report,
   including any failures.
9. **Review matches.** Filter by score and work mode. Open a job to see its description,
   provenance, score breakdown, eligibility and missing requirements. Save the ones worth pursuing.
10. **Tailor a CV.** Open **CV Studio**, choose a job and language, generate a CV, read the
    validation and layout reports, preview the PDF, then approve and download.
11. **Track the application.** Add it to the tracker from Saved Jobs or the Tracker page. Set dates,
    contacts and notes; the dashboard surfaces upcoming follow-ups and interviews.
12. **Back up.** Use **Settings → Create database backup** and **Export all data as JSON**.

---

## Running offline

Set `LLM_ENABLED=0` or simply omit every API key. In offline mode:

- CV text extraction uses deterministic parsing and heuristic contact hints; OCR is used only if
  Tesseract is installed.
- Search planning uses the rule-based multilingual planner and the category registry.
- Job requirement extraction uses Python rules only.
- CV generation uses the deterministic evidence-only builder.
- Scoring, deduplication, exports, the tracker and all privacy controls are unchanged.

AI-only conveniences are disabled and labelled as such in the UI. Nothing silently falls back to
fabricated data.

---

## Extending CONSUL

### Add a job family

See [Adding a job family](#adding-a-job-family). Either register a `JobCategory` in code or add
`config/job_categories.json`; restart afterwards.

### Add a connector

1. Create `connectors/<name>.py` with a class deriving from `BaseConnector`.
2. Set `key`, `display_name`, `provider_kind`, `requires` and `description`.
3. Implement `missing_config()` and `async def search(ctx, http, settings)`.
4. Use `http.get_json`, `http.get_text` or `http.post_json` so retries, rate limits, SSRF checks
   and request statistics are automatic.
5. Build `JobRecord` objects and finish with `self.finish(result, started, http.stats, jobs, queries)`.
6. Add the class to `CONNECTOR_CLASSES` in `services/search_orchestrator.py`.
7. Add a test with `respx` mocking the endpoints.

The diagnostics catalogue, enable/disable controls and health reporting pick the connector up
automatically.

### Add a prompt

Create `prompts/<name>.txt` using `$placeholders`, then call
`llm.prompt_json("<name>", Schema, **context)` or `llm.prompt_text("<name>", **context)`. The
service validates the response against the Pydantic schema and retries only on invalid JSON.

---

## Tests

```bash
python -m pytest -q
```

`pytest.ini` sets `asyncio_mode = auto`, `testpaths = tests`, and ignores deprecation warnings.
Each test gets a disposable SQLite database; all outbound HTTP is mocked with `respx`; no test
requires an API key, network access, LibreOffice or Tesseract.

Coverage includes:

- security helpers (SSRF validation, upload validation, HTML/text sanitising)
- text normalisation, skill aliases and matching helpers
- profile lifecycle, evidence synthesis, versioning and merge
- query planning, taxonomy, multi-profile CRUD and role-agnostic search
- transferable matching and scoring
- every connector, deduplication and enrichment
- CV tailoring, validation, master template and exports
- applications, settings and document extraction
- all nine UI pages via Streamlit `AppTest`
- a full end-to-end workflow: profile → plan → mocked scan → scoring → CV → tracker

**Last verified in this environment:** `109 passed` in 40–47 s on Python 3.11.9, Windows, with
LibreOffice installed at its standard path. OCR was not installed, so OCR-specific paths were not
exercised here.

---

## Privacy and security

- **Local first.** All user data lives in `data/consul.db` and local files. There is no account,
  cloud sync or analytics. Streamlit usage stats are disabled.
- **Data minimisation.** Only the CV text you upload is sent to the LLM, and only when you trigger
  extraction, planning, drafting or auditing. Job advert text is sent only for optional
  enrichment and tailoring.
- **Secrets stay out of storage.** API keys are read from the environment; they are never written
  to SQLite, exports or the UI.
- **Redacted logging.** A custom formatter redacts values that look like API keys, tokens, secrets
  or passwords before they reach the console or `data/consul.log`.
- **Upload validation.** Only `.pdf` and `.docx`, with a configurable size limit and an empty-file
  check.
- **SSRF protection.** Outbound URLs must be HTTP(S), must not target localhost, `.local`,
  `.internal`, metadata hosts or private/loopback/link-local IPs, and DNS resolution is checked.
- **Untrusted text handling.** HTML from job boards is stripped of scripts, tags and control
  characters before storage or display.
- **Retention control.** Rejected evidence is retained for audit but excluded from CVs. The
  Settings page can delete all career data, generated files, uploads and backups.
- **Backups and exports are your responsibility.** They contain personal data; keep them private.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| "No LLM is configured" | No key, or `LLM_ENABLED=0` | Set `GEMINI_API_KEY` or `LLM_PROVIDER` + `LLM_API_KEY`; restart or reload `.env` |
| LLM calls time out | Slow provider or large output | Lower `LLM_TIMEOUT_SECONDS`; the request already has a hard timeout |
| Provider returns an empty answer | Reasoning model consumed the output budget | Choose a non-reasoning model or raise `LLM_MAX_OUTPUT_TOKENS` |
| Groq 429 / rate limited | Free-tier token budget | Use `LLM_MAX_OUTPUT_TOKENS=6000`, `LLM_REASONING_EFFORT=low` |
| Scan finds nothing | No source configured or enabled | Add ATS boards or API keys in Search Configuration; check Diagnostics |
| All sources `configuration_missing` | Seed variables or keys are empty | Fill them in `.env`, then **Reload .env** or **Seed boards from .env** |
| A source is `restricted` | Site blocks automated access | Use Manual Search Assistance; CONSUL will not bypass it |
| PDF preview uses the built-in renderer | LibreOffice not found | Install LibreOffice or set `CONSUL_SOFFICE` |
| PDF fonts look different | Liberation Serif substitutes Times New Roman | Expected; layout comparison allows metric tolerance |
| Scanned PDF extracts nothing | OCR not installed | Install Tesseract and `pytesseract`, or enter facts manually |
| "Database could not be opened" | Permissions or invalid `DATABASE_URL` | Check `DATA_DIR` and the SQLite path |
| Port 8501 already in use | Another Streamlit instance | `streamlit run app.py --server.port 8502` |
| Merge needs an LLM | Multi-document merge uses structured extraction | Configure a provider or paste the facts manually |
| Downloads are locked | The CV version is not approved | Read the validation and layout reports, then approve that version |
| Approval is blocked | Validation or layout checks report errors | Fix the CV/report, regenerate, then approve |

---

## Known limitations

- **AI features need a provider.** Offline mode is deterministic and intentionally conservative;
  it will not infer missing facts.
- **OCR is not bundled.** It requires system Tesseract plus `pytesseract`.
- **Job-board APIs change without notice.** Health statuses surface breakage instead of hiding it,
  and each connector can be disabled independently.
- **Workday and TeamTailor** support the public career-site shapes documented in their modules;
  tenant-specific quirks may need configuration.
- **Salary, visa and language fields** are filled only when the advert states them. Missing values
  stay unknown rather than estimated.
- **DOCX → PDF conversion** needs LibreOffice for exact rendering. Without it, the measured
  renderer matches the template geometry but is not a Word rendering.
- **The master template is single-column by requirement.** Uploading another reference does not
  override it.
- **Layout comparison** allows small metric tolerances (about 2.5 pt) for font substitution.
- **Category seeds and transferable links are starting points, not claims.** Exact requirements
  stay in the missing list; verify adjacent skills before applying.
- **One user per instance.** There is no authentication or multi-user isolation; run it locally.
- **SQLite is the tested default.** PostgreSQL is supported by the ORM layer but is not covered by
  the test suite's default configuration.

---

## License and attribution

No license file is included in this repository. Bundled fonts are distributed under the SIL Open
Font License (`ui/assets/fonts/OFL.txt`). The bundled reference CV design is used solely as the
layout specification for generated documents.
