"""Job normalisation and requirement extraction.

Rules run in Python and only use what the advert says. The LLM is used only as
an optional fallback for pages where the rules find nothing, and its output is
validated before use. Missing salary/language/visa values stay ``None``/unknown.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.logging_config import get_logger
from core.schemas import JobRecord, ListingStatus, WorkMode
from core.text import normalize_text, normalize_whitespace, strip_listing_boilerplate

logger = get_logger("enrichment")

SKILL_VOCAB: dict[str, str] = {}
for canonical, aliases in {
    "Python": ["python"],
    "JavaScript": ["javascript", "js "],
    "TypeScript": ["typescript"],
    "Java": ["java "],
    "C++": ["c++", "cpp", "c plus plus"],
    "C#": ["c#", ".net"],
    "Go": ["golang", " go "],
    "Rust": ["rust"],
    "PHP": ["php"],
    "Ruby": ["ruby"],
    "Swift": ["swift"],
    "Kotlin": ["kotlin"],
    "SQL": ["sql"],
    "HTML": ["html"],
    "CSS": ["css"],
    "React": ["react"],
    "Angular": ["angular"],
    "Vue.js": ["vue.js", "vuejs", " vue "],
    "Next.js": ["next.js", "nextjs"],
    "Node.js": ["node.js", "nodejs", "node "],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Spring Boot": ["spring boot", "springboot"],
    ".NET": [".net", "asp.net"],
    "Express": ["express.js", "expressjs"],
    "Laravel": ["laravel"],
    "TensorFlow": ["tensorflow"],
    "PyTorch": ["pytorch"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "pandas": ["pandas"],
    "NumPy": ["numpy"],
    "LangChain": ["langchain"],
    "Hugging Face": ["hugging face", "huggingface", "transformers"],
    "Gemini": ["gemini", "google genai"],
    "OpenAI API": ["openai"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure"],
    "GCP": ["gcp", "google cloud"],
    "Git": ["git", "github", "gitlab"],
    "GitHub Actions": ["github actions"],
    "CI/CD": ["ci/cd", "continuous integration"],
    "Linux": ["linux", "unix"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "SQLite": ["sqlite"],
    "Elasticsearch": ["elasticsearch", "opensearch"],
    "Kafka": ["kafka"],
    "RabbitMQ": ["rabbitmq"],
    "GraphQL": ["graphql"],
    "REST APIs": ["rest api", "restful", "rest apis", "http api"],
    "gRPC": ["grpc"],
    "Microservices": ["microservice", "microservices"],
    "Agile": ["agile", "scrum", "kanban"],
    "Jira": ["jira"],
    "pytest": ["pytest"],
    "Jest": ["jest"],
    "Selenium": ["selenium"],
    "Playwright": ["playwright"],
    "Figma": ["figma"],
    "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"],
    "Spark": ["apache spark", "pyspark", " spark "],
    "Airflow": ["airflow"],
    "dbt": ["dbt"],
    "Snowflake": ["snowflake"],
    "Databricks": ["databricks"],
    "SAP": ["sap"],
    "Software Architecture": ["software architecture", "system design"],
    "RTOS": ["rtos", "freertos", "zephyr", "real-time operating system",
             "real time operating system"],
    "Microcontrollers": ["microcontroller", "microcontrollers", "mcu", "stm32", "esp32",
                         "arduino", "raspberry pi pico"],
    "Firmware": ["firmware", "bare metal", "bare-metal"],
    "Embedded Systems": ["embedded systems", "embedded system", "embedded software",
                         "embedded c", "embedded"],
    "ARM": ["arm cortex", "arm"],
    "UART": ["uart"],
    "SPI": ["spi"],
    "I2C": ["i2c", "i²c"],
    "PLC": ["plc", "siemens tia portal", "tia portal"],
    "CAN bus": ["can bus", "can-bus", "canopen"],
    "Salesforce": ["salesforce"],
    "Excel": ["excel"],
    "Machine Learning": ["machine learning", "ml "],
    "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"],
    "Computer Vision": ["computer vision", "opencv"],
    "LLMs": ["llm", "large language model", "generative ai", "genai"],
    "MLOps": ["mlops", "mlflow"],
    "Streamlit": ["streamlit"],
    "Vercel": ["vercel"],
    "Supabase": ["supabase"],
    "Firebase": ["firebase"],
    "WordPress": ["wordpress"],
    "Selenium WebDriver": ["webdriver"],
}.items():
    for alias in aliases:
        SKILL_VOCAB[alias.strip().lower()] = canonical

LANGUAGE_NAMES = {
    "english": "English", "englisch": "English", "anglais": "English", "inglés": "English",
    "german": "German", "deutsch": "German", "allemand": "German", "alemán": "German",
    "french": "French", "französisch": "French", "français": "French", "francés": "French",
    "spanish": "Spanish", "spanisch": "Spanish", "espagnol": "Spanish", "español": "Spanish",
    "dutch": "Dutch", "niederländisch": "Dutch", "nederlands": "Dutch", "neerlandés": "Dutch",
    "italian": "Italian", "italienisch": "Italian", "italiano": "Italian",
    "polish": "Polish", "polnisch": "Polish", "portuguese": "Portuguese", "português": "Portuguese",
    "chinese": "Chinese", "mandarin": "Chinese", "japanese": "Japanese",
}

COUNTRY_HINTS = {
    "germany": "Germany", "deutschland": "Germany", "berlin": "Germany", "munich": "Germany",
    "münchen": "Germany", "hamburg": "Germany", "frankfurt": "Germany", "cologne": "Germany",
    "köln": "Germany", "stuttgart": "Germany", "düsseldorf": "Germany", "leipzig": "Germany",
    "austria": "Austria", "wien": "Austria", "vienna": "Austria",
    "switzerland": "Switzerland", "zürich": "Switzerland", "zurich": "Switzerland",
    "france": "France", "paris": "France", "lyon": "France", "toulouse": "France",
    "spain": "Spain", "madrid": "Spain", "barcelona": "Spain", "españa": "Spain",
    "netherlands": "Netherlands", "amsterdam": "Netherlands", "rotterdam": "Netherlands",
    "utrecht": "Netherlands", "eindhoven": "Netherlands",
    "italy": "Italy", "milano": "Italy", "rome": "Italy", "roma": "Italy",
    "poland": "Poland", "warsaw": "Poland", "kraków": "Poland", "krakow": "Poland",
    "portugal": "Portugal", "lisbon": "Portugal", "lisboa": "Portugal",
    "united kingdom": "United Kingdom", "london": "United Kingdom", "uk": "United Kingdom",
    "ireland": "Ireland", "dublin": "Ireland", "united states": "United States",
    "usa": "United States", "new york": "United States", "san francisco": "United States",
    "canada": "Canada", "toronto": "Canada", "australia": "Australia", "sydney": "Australia",
    "india": "India", "bangalore": "India", "singapore": "Singapore",
}

REQUIREMENT_HEADERS = re.compile(
    r"^(requirements?|qualifications?|your profile|what you bring|must[- ]have|skills|"
    r"ihr profil|dein profil|anforderungen|was sie mitbringen|voraussetzungen|"
    r"profil recherché|ce que nous attendons|requisitos|perfil|"
    r"vereisten|wat wij vragen|requisiti|wymagania|requisitos)$", re.I,
)
RESPONSIBILITY_HEADERS = re.compile(
    r"^(responsibilities|tasks|your tasks|what you(?:'| wi)ll do|the role|role|"
    r"aufgaben|deine aufgaben|ihre aufgaben|tätigkeiten|"
    r"missions|vos missions|responsabilidades|funciones|taken|verantwoordelijkheden)$", re.I,
)
NICE_TO_HAVE = re.compile(r"(nice[- ]to[- ]have|preferred|bonus|plus|advantage|von vorteil|"
                          r"wünschenswert|souhaitable|deseable|pluspunt)", re.I)

BULLET_RE = re.compile(r"^\s*(?:[-•*·–]|\d+[.)])\s+")

# A bare C token is a real language requirement but must not match the letter
# inside ordinary words, "C++" or "C#".
C_LANGUAGE_RE = re.compile(r"(?<![a-z0-9+#])c(?![a-z0-9+#])", re.I)


def _alias_pattern(alias: str) -> re.Pattern:
    """Token-aware alias match, so "go" no longer fires inside "Google"."""
    if alias.strip().lower() == "go":
        # The Go language is written as a bare word, which collides with the
        # English verb ("go to", "go back"). Those phrases are never a skill.
        return re.compile(
            r"(?<![a-z0-9])go(?![a-z0-9])(?!\s+(?:to|back|through|live|up|down|"
            r"ahead|beyond|with|for|into|out|over|around|off|on|under|by)\b)",
            re.I,
        )
    return re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", re.I)


_SKILL_PATTERNS: dict[str, list[re.Pattern]] = {}
for _alias, _canonical in SKILL_VOCAB.items():
    _SKILL_PATTERNS.setdefault(_canonical, []).append(_alias_pattern(_alias))


def detect_language(text: str) -> str:
    blob = normalize_text(text)[:4000]
    if not blob:
        return ""
    markers = {
        "de": [" und ", " mit ", " wir ", " für ", " der ", " die ", " das ", " sie ", " ihre ",
               " einen ", " eine ", " einen ", " nicht ", " gern ", " kenntnisse ", " aufgaben "],
        "fr": [" avec ", " nous ", " vous ", " pour ", " des ", " une ", " dans ", "vos "],
        "es": [" con ", " para ", " nuestro", " una ", " los ", " las ", " tus "],
        "nl": [" wij ", " met ", " voor ", " het ", " een ", " jouw ", " je "],
    }
    scores = {lang: sum(blob.count(m) for m in needles) for lang, needles in markers.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "en"


def _section_lines(description: str) -> tuple[list[str], list[str]]:
    lines = [l.strip() for l in strip_listing_boilerplate(description).splitlines()]
    requirement_lines: list[str] = []
    responsibility_lines: list[str] = []
    current = None
    for line in lines:
        is_bullet = bool(BULLET_RE.match(line))
        cleaned = re.sub(r"^[#*\-\s]+", "", line).strip(" :").strip()
        if cleaned and len(cleaned) <= 60:
            if REQUIREMENT_HEADERS.match(cleaned):
                current = "requirements"
                continue
            if RESPONSIBILITY_HEADERS.match(cleaned):
                current = "responsibilities"
                continue
            # An all-caps bullet ("C", "SQL", "RTOS") is content, not a new
            # section header. Resetting here used to drop every requirement
            # after the first uppercase skill.
            if cleaned.isupper() and len(cleaned.split()) <= 4 and not is_bullet:
                current = None
        if current == "requirements" and line:
            requirement_lines.append(line)
        elif current == "responsibilities" and line:
            responsibility_lines.append(line)
    return requirement_lines, responsibility_lines


def extract_skills(description: str, requirement_text: str = "") -> tuple[list[str], list[str]]:
    blob = " " + normalize_text(description) + " "
    required_blob = " " + normalize_text(requirement_text) + " "
    found: dict[str, int] = {}
    for canonical, patterns in _SKILL_PATTERNS.items():
        hits = sum(len(pattern.findall(blob)) for pattern in patterns)
        if hits:
            found[canonical] = found.get(canonical, 0) + hits
    if C_LANGUAGE_RE.search(blob):
        found["C"] = found.get("C", 0) + len(C_LANGUAGE_RE.findall(blob))
    ordered = sorted(found, key=lambda k: (-found[k], k))
    required: list[str] = []
    preferred: list[str] = []
    for skill in ordered:
        if skill == "C":
            in_requirements = bool(C_LANGUAGE_RE.search(required_blob))
        else:
            in_requirements = any(pattern.search(required_blob)
                                  for pattern in _SKILL_PATTERNS.get(skill, []))
        (required if in_requirements else preferred).append(skill)
    return required[:20], preferred[:20]


# A qualifier written before the language ("sehr gute Deutschkenntnisse") is a
# requirement level, not decoration. Values are existing PROFICIENCY_RANK tokens.
_QUALIFIER_LEVELS: tuple[tuple[str, str], ...] = (
    ("verhandlungssicher", "c1"), ("sehr gut", "b2"), ("fließend", "c1"),
    ("fliessend", "c1"), ("muttersprachlich", "native"), ("grundkenntnis", "a2"),
    ("grundlegend", "a2"), ("very good", "b2"), ("business fluent", "c1"),
    ("conversational", "b1"), ("fluent", "c1"), ("native", "native"),
    ("business", "c1"), ("professional", "c1"), ("advanced", "b2"),
    ("intermediate", "b1"), ("basic", "a1"), ("good", "b1"), ("gut", "b1"),
)
_QUALIFIER_RE = (
    r"(?:verhandlungssicher\w*|sehr gut\w*|gut\w*|fließend\w*|fliessend\w*|"
    r"muttersprachlich\w*|grundlegend\w*|grundkenntnisse|very good|good|business fluent|"
    r"conversational|fluent|native|business|professional|basic|intermediate|advanced)"
)


def _qualifier_level(qualifier: str) -> str:
    blob = normalize_text(qualifier)
    for prefix, level in _QUALIFIER_LEVELS:
        if blob.startswith(prefix):
            return level
    return ""


def extract_languages(description: str) -> list[str]:
    text = normalize_text(description)
    found: list[str] = []
    pattern = re.compile(
        r"(" + _QUALIFIER_RE + r"\s+)?"
        r"(" + "|".join(re.escape(k) for k in LANGUAGE_NAMES) + r")"
        r"\s*(?:language|kenntnisse|knowledge|skills)?\s*(?:auf\s+)?[\(\-–:]?\s*"
        r"(fluent|native|business|professional|basic|intermediate|advanced|b2|c1|c2|a2|b1|mother tongue|muttersprache)?",
        re.I,
    )
    for match in pattern.finditer(text):
        language = LANGUAGE_NAMES.get(match.group(2).lower())
        if not language:
            continue
        level = (match.group(3) or "").strip()
        if not level:
            level = _qualifier_level(match.group(1) or "")
        entry = f"{language} ({level})" if level and level.lower() not in {"language"} else language
        if entry not in found:
            found.append(entry)
    return found[:5]


def extract_sponsorship(description: str) -> bool | None:
    text = normalize_text(description)
    negative = [
        r"(no|not|unable to|cannot|can't|do not|kein(e|en|erlei)?|nicht|ohne)[^.\n]{0,60}"
        r"(visa|visum|sponsor)",
        r"(visa|visum|sponsorship)[^.\n]{0,40}(not (available|offered|provided)|nicht möglich|"
        r"kein(e|en|erlei)?|nicht)",
        r"(must|need to) (have|hold)[^.\n]{0,40}(right to work|work permit|arbeitserlaubnis)",
    ]
    positive = [
        r"(we|company)[^.\n]{0,40}(sponsor|visa support|relocation support)",
        r"(visa|sponsorship)[^.\n]{0,30}(available|provided|offered|supported|möglich)",
    ]
    if any(re.search(p, text) for p in negative):
        return False
    if any(re.search(p, text) for p in positive):
        return True
    return None


def extract_education(description: str) -> list[str]:
    text = description or ""
    found: list[str] = []
    for match in re.finditer(
        r"^[^\n]{0,120}\b(bachelor|master|b\.?sc|m\.?sc|degree|diploma|phd|doctorate|studium|"
        r"abschluss|bac\+?\d?|licence|máster|grado)\b[^\n]{0,120}$",
        text, re.I | re.M,
    ):
        line = normalize_whitespace(match.group(0))
        if 10 < len(line) < 250 and line not in found:
            found.append(line)
    return found[:5]


def extract_experience_requirements(description: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(
        r"^[^\n]{0,100}\b(\d{1,2})\s*\+?\s*(?:-|to|–)?\s*(\d{1,2})?\s*(?:years?|jahre[n]?|ans|años|jaar)\b[^\n]{0,100}$",
        description or "", re.I | re.M,
    ):
        line = normalize_whitespace(match.group(0))
        if len(line) < 250 and line not in found:
            found.append(line)
    return found[:5]


def extract_responsibilities(description: str, responsibility_lines: list[str]) -> list[str]:
    candidates = [normalize_whitespace(BULLET_RE.sub("", l)) for l in responsibility_lines if l.strip()]
    candidates = [c for c in candidates if len(c) > 8]
    if not candidates:
        candidates = [
            normalize_whitespace(BULLET_RE.sub("", line))
            for line in (description or "").splitlines()
            if BULLET_RE.match(line) and len(line.strip()) > 10
        ]
    seen: set[str] = set()
    out: list[str] = []
    for item in candidates:
        key = item.lower()
        if key not in seen and len(item) < 400:
            seen.add(key)
            out.append(item)
    return out[:15]


def canonical_country(*values: str) -> str:
    blob = normalize_text(" ".join(v for v in values if v))
    # Prefer explicit country names over city hints.
    for key in sorted(COUNTRY_HINTS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", blob):
            return COUNTRY_HINTS[key]
    return ""


def enrich_job(record: JobRecord, *, infer_country: bool = True) -> JobRecord:
    """Fill missing structured fields from the advert text, without inventing."""
    description = strip_listing_boilerplate(record.description or "")
    requirement_lines, responsibility_lines = _section_lines(description)
    requirement_text = "\n".join(requirement_lines)
    nice_start = NICE_TO_HAVE.search(requirement_text)
    if nice_start:
        required_text = requirement_text[:nice_start.start()]
        preferred_text = requirement_text[nice_start.start():]
    else:
        required_text, preferred_text = requirement_text, ""

    if requirement_text:
        skills_required, skills_preferred = extract_skills(description, required_text)
        if preferred_text:
            pref_only, _ = extract_skills(preferred_text, preferred_text)
            for skill in pref_only:
                if skill not in skills_required and skill not in skills_preferred:
                    skills_preferred.append(skill)
    else:
        # No recognisable requirements section: the whole advert is the evidence
        # base, so matched skills are treated as wanted (flagged as heuristic).
        skills_required, skills_preferred = extract_skills(description, description)

    updates: dict[str, Any] = {}
    if not record.required_skills:
        updates["required_skills"] = skills_required
    if not record.preferred_skills:
        updates["preferred_skills"] = skills_preferred[:15]
    if not record.responsibilities:
        updates["responsibilities"] = extract_responsibilities(description, responsibility_lines)
    if not record.education_requirements:
        updates["education_requirements"] = extract_education(description)
    if not record.experience_requirements:
        updates["experience_requirements"] = extract_experience_requirements(description)
    if not record.languages:
        updates["languages"] = extract_languages(description)
    if record.visa_sponsorship is None:
        updates["visa_sponsorship"] = extract_sponsorship(description)
    if not record.language:
        updates["language"] = detect_language(description)
    if infer_country and not record.country:
        updates["country"] = canonical_country(record.location, description[:2000])
    if record.work_mode == WorkMode.UNKNOWN:
        blob = normalize_text(f"{record.title} {record.location} {description}")
        if re.search(r"\b(fully remote|remote|home ?office|télétravail|teletrabajo|thuiswerk)\b", blob):
            updates["work_mode"] = WorkMode.REMOTE
        elif re.search(r"\bhybrid|hybride|híbrido\b", blob):
            updates["work_mode"] = WorkMode.HYBRID
        elif re.search(r"\b(on-?site|vor ort|presencial)\b", blob):
            updates["work_mode"] = WorkMode.ONSITE

    enriched = record.model_copy(update=updates) if updates else record
    if not enriched.description.strip():
        logger.debug("Job %s has no description yet; it will need verification", enriched.title)
    return enriched


async def llm_extract_requirements(record: JobRecord) -> JobRecord:
    """Optional LLM fallback when the rules found no required skills."""
    from services.llm_service import get_llm_service

    service = get_llm_service()
    if not service.available or record.required_skills or len(record.description) < 200:
        return record

    from pydantic import BaseModel, Field

    class Extraction(BaseModel):
        required_skills: list[str] = Field(default_factory=list)
        preferred_skills: list[str] = Field(default_factory=list)
        responsibilities: list[str] = Field(default_factory=list)
        language_requirements: list[str] = Field(default_factory=list)

    try:
        result = service.prompt_json(
            "job_analysis",
            Extraction,
            job_json=record.model_dump_json(indent=2)[:20000],
        )
        record = record.model_copy(update={
            "required_skills": result.required_skills or record.required_skills,
            "preferred_skills": result.preferred_skills or record.preferred_skills,
            "responsibilities": result.responsibilities or record.responsibilities,
            "languages": result.language_requirements or record.languages,
        })
    except Exception as exc:
        logger.info("LLM requirement extraction skipped: %s", exc)
    return record


async def verify_listing(record: JobRecord, http) -> JobRecord:
    """Re-check a listing URL. Returns an updated status, never deletes data."""
    url = record.application_url or record.original_url
    if not url:
        return record.model_copy(update={"status": ListingStatus.UNVERIFIED})
    try:
        response = await http._request("GET", url, attempts=1)
    except Exception:
        return record.model_copy(update={"status": ListingStatus.UNVERIFIED})
    status_code = response.status_code
    if status_code in {404, 410}:
        return record.model_copy(update={"status": ListingStatus.EXPIRED,
                                         "last_verified": datetime.now(timezone.utc)})
    if status_code >= 400:
        return record.model_copy(update={"status": ListingStatus.UNVERIFIED})
    text = normalize_text(response.text[:5000])
    if any(phrase in text for phrase in ("no longer available", "position has been filled",
                                          "stelle ist nicht mehr", "offre n'est plus disponible",
                                          "job not found", "vacancy closed")):
        return record.model_copy(update={"status": ListingStatus.EXPIRED,
                                         "last_verified": datetime.now(timezone.utc)})
    return record.model_copy(update={"status": ListingStatus.ACTIVE,
                                     "last_verified": datetime.now(timezone.utc)})


async def fetch_job_from_url(url: str, http, *, company: str = "") -> JobRecord:
    """Manually import a job from a pasted URL."""
    from connectors.company_careers import parse_job_page

    html = await http.get_text(url)
    fields = parse_job_page(html, url)
    record = JobRecord(
        source="manual",
        source_job_id=url[:280],
        title=fields.get("title") or "Untitled listing",
        company=fields.get("company") or company,
        location=fields.get("location", ""),
        country=fields.get("country", ""),
        description=fields.get("description", ""),
        employment_type=fields.get("employment_type", ""),
        work_mode=fields.get("work_mode", WorkMode.UNKNOWN),
        posted_at=fields.get("posted_at"),
        salary_min=fields.get("salary_min"),
        salary_max=fields.get("salary_max"),
        salary_currency=fields.get("salary_currency", ""),
        application_url=url,
        original_url=url,
        status=ListingStatus.UNVERIFIED,
    )
    return enrich_job(record)
