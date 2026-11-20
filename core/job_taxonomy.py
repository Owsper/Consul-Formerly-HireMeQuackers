"""Extensible job-family taxonomy.

The search planner, scorer and CV tailor consume these definitions but never
hardcode a discipline. A new industry or specialisation is added by registering
another ``JobCategory`` (or loading a JSON category file); no engine changes are
needed. IT is simply the first populated domain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from core.text import normalize_text, similarity

ANY_IT = "any_it"


@dataclass(frozen=True)
class JobCategory:
    key: str
    label: str
    domain: str = "it"
    titles: tuple[str, ...] = ()
    specialisations: dict[str, tuple[str, ...]] = field(default_factory=dict)
    core_skills: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    translations: dict[str, tuple[str, ...]] = field(default_factory=dict)
    related: tuple[str, ...] = ()

    def all_titles(self, specialisation: str = "") -> list[str]:
        titles = list(self.specialisations.get(specialisation, ()))
        if specialisation and not titles:
            titles = [t for t in self.titles if normalize_text(specialisation) in normalize_text(t)]
        return _unique([*titles, *self.titles])


CATEGORIES: dict[str, JobCategory] = {}


def register_category(category: JobCategory, *, replace: bool = True) -> JobCategory:
    """Register a job family. Engines only use the registry, never concrete keys."""
    if category.key == ANY_IT:
        raise ValueError("'any_it' is reserved for the all-categories option")
    if category.key in CATEGORIES and not replace:
        raise ValueError(f"Category already registered: {category.key}")
    CATEGORIES[category.key] = category
    return category


def category_options() -> list[tuple[str, str]]:
    return [(ANY_IT, "Any IT Category"), *[(c.key, c.label) for c in CATEGORIES.values()]]


def get_category(key: str | None) -> JobCategory | None:
    return CATEGORIES.get(key or "")


def category_label(key: str | None) -> str:
    return get_category(key).label if get_category(key) else "Any IT Category"


def specialisations_for(key: str | None) -> list[str]:
    category = get_category(key)
    return list(category.specialisations) if category else []


def titles_for(key: str | None, specialisation: str = "", limit: int = 10) -> list[str]:
    category = get_category(key)
    if not category:
        return []
    return category.all_titles(specialisation)[:limit]


def detect_categories(text: str, skills: list[str] | None = None,
                      limit: int = 2) -> list[str]:
    """Rank categories by evidence in a free-text role or a skill list."""
    blob = normalize_text(" ".join([text, *(skills or [])]))
    if not blob:
        return []
    scored: list[tuple[float, str]] = []
    for category in CATEGORIES.values():
        score = 0.0
        for title in category.titles:
            if normalize_text(title) in blob:
                score += 4.0
        for term in (*category.core_skills, *category.keywords):
            if normalize_text(term) in blob:
                score += 1.0
        for specialisation in category.specialisations:
            if normalize_text(specialisation) in blob:
                score += 3.0
        if score:
            scored.append((score, category.key))
    scored.sort(reverse=True)
    return [key for _, key in scored[:limit]]


def guess_from_title(title: str) -> str | None:
    best = (0.0, None)
    lowered = normalize_text(title)
    for category in CATEGORIES.values():
        for candidate in category.titles:
            if normalize_text(candidate) in lowered or lowered in normalize_text(candidate):
                return category.key
            score = similarity(title, candidate)
            if score > best[0]:
                best = (score, category.key)
    return best[1] if best[0] >= 0.55 else None


def title_translations(category_key: str | None, language: str) -> tuple[str, ...]:
    category = get_category(category_key)
    if not category:
        return ()
    return category.translations.get(language, ())


def related_categories(category_key: str | None) -> list[str]:
    category = get_category(category_key)
    return list(category.related) if category else []


def load_category_file(path: str | Path) -> int:
    """Merge additional categories from JSON.

    Shape: ``{"categories": [{key,label,titles,specialisations,...}]}``.
    Relative paths are resolved by the caller; this keeps deployment choices out
    of the search engines.
    """
    file = Path(path)
    if not file.exists():
        return 0
    payload = json.loads(file.read_text(encoding="utf-8"))
    count = 0
    for item in payload.get("categories", []):
        specialisations = {
            name: tuple(titles) for name, titles in (item.get("specialisations") or {}).items()
        }
        translations = {
            lang: tuple(values) for lang, values in (item.get("translations") or {}).items()
        }
        register_category(JobCategory(
            key=item["key"], label=item.get("label", item["key"]),
            domain=item.get("domain", "it"), titles=tuple(item.get("titles", ())),
            specialisations=specialisations, core_skills=tuple(item.get("core_skills", ())),
            keywords=tuple(item.get("keywords", ())), translations=translations,
            related=tuple(item.get("related", ())),
        ))
        count += 1
    return count


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        value = " ".join(str(value or "").split())
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _category(key: str, label: str, titles: tuple[str, ...],
              specialisations: dict[str, tuple[str, ...]], skills: tuple[str, ...],
              keywords: tuple[str, ...], translations: dict[str, tuple[str, ...]],
              related: tuple[str, ...] = ()) -> None:
    register_category(JobCategory(
        key=key, label=label, titles=titles, specialisations=specialisations,
        core_skills=skills, keywords=keywords, translations=translations, related=related,
    ))


# ---------------------------------------------------------------------------
# IT categories
# ---------------------------------------------------------------------------
_category(
    "software_engineering", "Software Engineering",
    ("Software Engineer", "Software Developer", "Backend Developer", "Full Stack Engineer",
     "Application Developer", "Java Developer", "Python Developer", "C# Developer"),
    {"Backend": ("Backend Engineer", "API Developer", "Server-Side Developer"),
     "Frontend": ("Frontend Engineer", "UI Developer"),
     "Full Stack": ("Full Stack Developer", "Full Stack Engineer"),
     "Application Development": ("Application Developer", "Software Developer")},
    ("Python", "Java", "C#", "JavaScript", "TypeScript", "SQL", "APIs", "Git"),
    ("software development", "application development", "backend", "full stack", "APIs"),
    {"de": ("Softwareentwickler", "Software Engineer"),
     "fr": ("ingénieur logiciel", "développeur logiciel"),
     "es": ("ingeniero de software", "desarrollador de software"),
     "nl": ("softwareontwikkelaar",), "it": ("sviluppatore software",),
     "pl": ("programista", "inżynier oprogramowania"),
     "pt": ("desenvolvedor de software",)},
    ("web_development", "cloud_devops", "qa_testing"),
)
_category(
    "web_development", "Web Development",
    ("Web Developer", "Frontend Developer", "Full Stack Developer", "JavaScript Developer",
     "React Developer", "PHP Developer", "WordPress Developer", "Web Engineer"),
    {"Frontend": ("Frontend Developer", "React Developer", "Vue Developer"),
     "Backend": ("Web Backend Developer", "PHP Developer", "Node.js Developer"),
     "CMS": ("WordPress Developer", "Drupal Developer")},
    ("JavaScript", "TypeScript", "HTML", "CSS", "React", "Node.js", "PHP", "Web APIs"),
    ("web development", "frontend", "front-end", "responsive", "web applications"),
    {"de": ("Webentwickler", "Frontend-Entwickler"),
     "fr": ("développeur web", "développeur frontend"),
     "es": ("desarrollador web", "desarrollador frontend"),
     "nl": ("webontwikkelaar",), "it": ("sviluppatore web",),
     "pl": ("programista web",), "pt": ("desenvolvedor web",)},
    ("software_engineering", "game_development"),
)
_category(
    "game_development", "Game Development",
    ("Game Developer", "Game Programmer", "Unity Developer", "Unreal Engine Developer",
     "Gameplay Programmer", "C++ Game Developer", "Game Tools Programmer", "Game Engineer"),
    {"Gameplay Programming": ("Gameplay Programmer", "Gameplay Engineer", "C++ Game Developer"),
     "Engine & Tools": ("Engine Programmer", "Tools Programmer", "Unity Developer", "Unreal Engine Developer"),
     "Graphics": ("Graphics Programmer", "Rendering Engineer", "Technical Artist"),
     "Online & Multiplayer": ("Network Programmer", "Multiplayer Engineer", "Backend Game Developer"),
     "Game Design Technology": ("Technical Game Designer", "Game Systems Designer")},
    ("C++", "C#", "Unity", "Unreal Engine", "Gameplay", "3D Maths", "Graphics", "Game Engines"),
    ("game development", "gameplay", "game engine", "unity", "unreal", "multiplayer"),
    {"de": ("Game-Entwickler", "Spieleentwickler", "Game Programmer"),
     "fr": ("développeur de jeux", "programmeur de jeux"),
     "es": ("desarrollador de videojuegos", "programador de videojuegos"),
     "nl": ("gameontwikkelaar",), "it": ("sviluppatore di videogiochi",),
     "pl": ("programista gier",), "pt": ("desenvolvedor de jogos",)},
    ("software_engineering", "robotics_automation"),
)
_category(
    "embedded_iot", "Embedded Systems, Firmware & IoT",
    ("Embedded Software Engineer", "Firmware Developer", "Embedded Systems Engineer",
     "C/C++ Embedded Developer", "IoT Software Engineer", "Embedded Linux Engineer",
     "Microcontroller Developer", "Firmware Engineer"),
    {"Firmware": ("Firmware Developer", "Firmware Engineer", "Bare-Metal Developer"),
     "Embedded Linux": ("Embedded Linux Engineer", "Linux Kernel Developer"),
     "IoT": ("IoT Software Engineer", "IoT Developer", "Connected Devices Engineer"),
     "Automotive Embedded": ("Automotive Embedded Engineer", "AUTOSAR Engineer")},
    ("C", "C++", "Embedded C", "RTOS", "Microcontrollers", "ARM", "Firmware", "IoT", "UART", "SPI", "I2C"),
    ("embedded", "firmware", "microcontroller", "iot", "real-time", "rtos", "hardware interfaces"),
    {"de": ("Embedded-Entwickler", "Firmware-Entwickler"),
     "fr": ("développeur embarqué", "ingénieur firmware"),
     "es": ("desarrollador embebido", "ingeniero de firmware"),
     "nl": ("embedded engineer",), "it": ("sviluppatore embedded",),
     "pl": ("programista embedded",), "pt": ("desenvolvedor embarcado",)},
    ("hardware_engineering", "robotics_automation", "networking_infrastructure"),
)
_category(
    "networking_infrastructure", "Networking & IT Infrastructure",
    ("Network Engineer", "Network Administrator", "Infrastructure Engineer", "NOC Engineer",
     "Network Automation Engineer", "Systems Engineer", "IT Network Specialist"),
    {"Network Operations": ("NOC Engineer", "Network Operations Engineer"),
     "Network Security": ("Network Security Engineer", "Firewall Engineer"),
     "Infrastructure": ("Infrastructure Engineer", "Data Centre Engineer")},
    ("TCP/IP", "DNS", "DHCP", "Routing", "Switching", "Firewalls", "VPN", "Linux", "Network Automation"),
    ("networking", "network infrastructure", "routing", "switching", "data centre", "lan", "wan"),
    {"de": ("Netzwerkadministrator", "Netzwerkingenieur"),
     "fr": ("administrateur réseau", "ingénieur réseau"),
     "es": ("administrador de redes", "ingeniero de redes"),
     "nl": ("netwerkbeheerder",), "it": ("amministratore di rete",),
     "pl": ("administrator sieci",), "pt": ("administrador de redes",)},
    ("cloud_devops", "cybersecurity", "it_support"),
)
_category(
    "cloud_devops", "Cloud Engineering & DevOps",
    ("Cloud Engineer", "DevOps Engineer", "Platform Engineer", "Site Reliability Engineer",
     "Cloud Infrastructure Engineer", "Kubernetes Engineer", "Infrastructure as Code Engineer"),
    {"DevOps": ("DevOps Engineer", "CI/CD Engineer", "Release Engineer"),
     "Platform": ("Platform Engineer", "Internal Developer Platform Engineer"),
     "Cloud": ("Cloud Engineer", "AWS Engineer", "Azure Engineer", "GCP Engineer"),
     "Reliability": ("Site Reliability Engineer", "SRE"),
     "Kubernetes": ("Kubernetes Engineer", "Container Platform Engineer")},
    ("AWS", "Azure", "GCP", "Kubernetes", "Docker", "Terraform", "CI/CD", "Linux", "Observability"),
    ("cloud", "devops", "platform engineering", "infrastructure as code", "containers", "reliability"),
    {"de": ("Cloud-Engineer", "DevOps-Engineer"),
     "fr": ("ingénieur cloud", "ingénieur DevOps"),
     "es": ("ingeniero de cloud", "ingeniero DevOps"),
     "nl": ("cloud engineer", "DevOps engineer"), "it": ("cloud engineer",),
     "pl": ("inżynier chmury", "inżynier DevOps"),
     "pt": ("engenheiro de nuvem", "engenheiro DevOps")},
    ("networking_infrastructure", "cybersecurity", "software_engineering"),
)
_category(
    "cybersecurity", "Cybersecurity",
    ("Cybersecurity Analyst", "Security Engineer", "SOC Analyst", "Penetration Tester",
     "Application Security Engineer", "GRC Analyst", "Information Security Specialist"),
    {"Security Operations": ("SOC Analyst", "Security Operations Analyst", "Incident Responder"),
     "Offensive Security": ("Penetration Tester", "Red Team Engineer", "Security Researcher"),
     "Application Security": ("Application Security Engineer", "Product Security Engineer"),
     "Governance & Compliance": ("GRC Analyst", "Information Security Compliance Analyst")},
    ("Security", "SIEM", "Incident Response", "Penetration Testing", "OWASP", "ISO 27001", "IAM", "Firewalls"),
    ("cybersecurity", "information security", "soc", "threat", "vulnerability", "compliance", "incident response"),
    {"de": ("Cybersecurity-Analyst", "IT-Sicherheitsingenieur"),
     "fr": ("analyste cybersécurité", "ingénieur sécurité"),
     "es": ("analista de ciberseguridad", "ingeniero de seguridad"),
     "nl": ("cybersecurity analist",), "it": ("analista di cybersecurity",),
     "pl": ("analityk cyberbezpieczeństwa",), "pt": ("analista de cibersegurança",)},
    ("networking_infrastructure", "cloud_devops", "it_support"),
)
_category(
    "ai_ml", "Artificial Intelligence & Machine Learning",
    ("AI Engineer", "Machine Learning Engineer", "MLOps Engineer", "NLP Engineer",
     "Computer Vision Engineer", "AI Solutions Engineer", "Research Engineer"),
    {"ML Engineering": ("Machine Learning Engineer", "ML Engineer", "MLOps Engineer"),
     "Generative AI": ("AI Engineer", "LLM Engineer", "Generative AI Engineer"),
     "NLP": ("NLP Engineer", "Natural Language Processing Engineer"),
     "Computer Vision": ("Computer Vision Engineer", "Perception Engineer"),
     "Research": ("AI Research Engineer", "Research Scientist")},
    ("Python", "Machine Learning", "PyTorch", "TensorFlow", "LLMs", "MLOps", "NLP", "Computer Vision"),
    ("artificial intelligence", "machine learning", "deep learning", "llm", "model deployment", "mlops"),
    {"de": ("KI-Entwickler", "Machine-Learning-Engineer"),
     "fr": ("ingénieur IA", "ingénieur machine learning"),
     "es": ("ingeniero de IA", "ingeniero de machine learning"),
     "nl": ("AI engineer",), "it": ("ingegnere IA",),
     "pl": ("inżynier AI", "inżynier uczenia maszynowego"),
     "pt": ("engenheiro de IA",)},
    ("data_science", "software_engineering", "robotics_automation"),
)
_category(
    "data_science", "Data Engineering, Science & Analytics",
    ("Data Engineer", "Data Scientist", "Data Analyst", "Analytics Engineer",
     "BI Developer", "ETL Developer", "Business Intelligence Analyst"),
    {"Data Engineering": ("Data Engineer", "ETL Developer", "Data Platform Engineer"),
     "Data Science": ("Data Scientist", "Applied Scientist"),
     "Analytics": ("Data Analyst", "Product Analyst", "BI Developer"),
     "Analytics Engineering": ("Analytics Engineer", "dbt Developer")},
    ("SQL", "Python", "pandas", "ETL", "Data Warehousing", "dbt", "Spark", "Power BI", "Tableau", "Statistics"),
    ("data engineering", "data science", "analytics", "business intelligence", "etl", "data warehouse"),
    {"de": ("Data Engineer", "Datenanalyst", "Data Scientist"),
     "fr": ("ingénieur données", "analyste données", "data scientist"),
     "es": ("ingeniero de datos", "analista de datos", "científico de datos"),
     "nl": ("data engineer", "data-analist"), "it": ("data engineer", "analista dati"),
     "pl": ("inżynier danych", "analityk danych"),
     "pt": ("engenheiro de dados", "analista de dados")},
    ("database_admin", "ai_ml", "software_engineering"),
)
_category(
    "database_admin", "Database Administration",
    ("Database Administrator", "Database Engineer", "SQL Developer", "DBA",
     "Data Platform Administrator", "Database Reliability Engineer"),
    {"Operations": ("Database Administrator", "DBA", "Database Reliability Engineer"),
     "Development": ("SQL Developer", "Database Developer", "Database Engineer"),
     "Data Platform": ("Data Platform Administrator", "Data Platform Engineer")},
    ("SQL", "PostgreSQL", "MySQL", "Oracle", "SQL Server", "MongoDB", "Backup & Recovery", "Query Tuning"),
    ("database administration", "dba", "query optimisation", "backup", "replication", "data platform"),
    {"de": ("Datenbankadministrator", "DBA"),
     "fr": ("administrateur de bases de données", "DBA"),
     "es": ("administrador de bases de datos", "DBA"),
     "nl": ("databasebeheerder",), "it": ("amministratore di database",),
     "pl": ("administrator baz danych",), "pt": ("administrador de banco de dados",)},
    ("data_science", "cloud_devops", "it_support"),
)
_category(
    "qa_testing", "QA Engineering & Software Testing",
    ("QA Engineer", "Test Automation Engineer", "Software Tester", "QA Analyst", "SDET",
     "Quality Engineer", "Test Engineer"),
    {"Automation": ("Test Automation Engineer", "SDET", "Automation QA Engineer"),
     "Manual QA": ("QA Analyst", "Software Tester", "Manual Tester"),
     "Performance": ("Performance Test Engineer", "Load Test Engineer"),
     "Quality Engineering": ("Quality Engineer", "QA Engineer")},
    ("Testing", "Test Automation", "Selenium", "Playwright", "Cypress", "pytest", "API Testing", "CI/CD"),
    ("quality assurance", "testing", "test automation", "regression", "test strategy", "defect tracking"),
    {"de": ("QA-Engineer", "Softwaretester", "Testautomatisierer"),
     "fr": ("ingénieur QA", "testeur logiciel"),
     "es": ("ingeniero de QA", "probador de software"),
     "nl": ("QA engineer", "softwaretester"), "it": ("QA engineer", "tester software"),
     "pl": ("inżynier QA", "tester oprogramowania"),
     "pt": ("engenheiro de QA", "testador de software")},
    ("software_engineering", "cloud_devops"),
)
_category(
    "robotics_automation", "Robotics & Automation",
    ("Robotics Engineer", "Automation Engineer", "Controls Engineer", "Robotics Software Engineer",
     "PLC Programmer", "Mechatronics Engineer", "Automation Software Engineer"),
    {"Robotics Software": ("Robotics Software Engineer", "Robot Programmer"),
     "Industrial Automation": ("Automation Engineer", "PLC Programmer", "Controls Engineer"),
     "Mechatronics": ("Mechatronics Engineer", "Robotics Engineer")},
    ("ROS", "C++", "Python", "PLC", "Industrial Automation", "Control Systems", "Computer Vision", "Mechatronics"),
    ("robotics", "automation", "control systems", "plc", "ros", "mechatronics", "industrial"),
    {"de": ("Robotikingenieur", "Automatisierungsingenieur"),
     "fr": ("ingénieur robotique", "ingénieur automatisation"),
     "es": ("ingeniero de robótica", "ingeniero de automatización"),
     "nl": ("robotica engineer",), "it": ("ingegnere robotico",),
     "pl": ("inżynier robotyki",), "pt": ("engenheiro de robótica",)},
    ("embedded_iot", "hardware_engineering", "ai_ml"),
)
_category(
    "it_support", "IT Support & Systems Administration",
    ("IT Support Specialist", "Systems Administrator", "IT Support Engineer",
     "Helpdesk Technician", "Desktop Support Engineer", "System Administrator"),
    {"Helpdesk": ("Helpdesk Technician", "Service Desk Analyst", "IT Support Specialist"),
     "Systems Administration": ("Systems Administrator", "System Administrator", "Linux Administrator"),
     "End User Computing": ("Desktop Support Engineer", "Endpoint Engineer")},
    ("Windows", "Linux", "Active Directory", "Troubleshooting", "Networking", "Ticketing", "Endpoint Management"),
    ("it support", "helpdesk", "service desk", "systems administration", "endpoint", "troubleshooting"),
    {"de": ("IT-Support-Spezialist", "Systemadministrator"),
     "fr": ("technicien support IT", "administrateur systèmes"),
     "es": ("especialista de soporte IT", "administrador de sistemas"),
     "nl": ("IT-supportmedewerker", "systeembeheerder"),
     "it": ("specialista supporto IT", "amministratore di sistemi"),
     "pl": ("specjalista wsparcia IT", "administrator systemów"),
     "pt": ("especialista de suporte de TI", "administrador de sistemas")},
    ("networking_infrastructure", "cybersecurity"),
)
_category(
    "hardware_engineering", "Hardware & Computer Engineering",
    ("Hardware Engineer", "Computer Engineer", "Embedded Hardware Engineer",
     "PCB Design Engineer", "Electronics Engineer", "Firmware Hardware Engineer"),
    {"PCB Design": ("PCB Design Engineer", "Hardware Design Engineer"),
     "Embedded Hardware": ("Embedded Hardware Engineer", "Firmware Hardware Engineer"),
     "Computer Engineering": ("Computer Engineer", "Hardware Engineer")},
    ("PCB Design", "Electronics", "Circuit Design", "FPGA", "Verilog", "VHDL", "Microcontrollers", "Signal Integrity"),
    ("hardware", "pcb", "electronics", "circuit", "fpga", "computer engineering", "embedded hardware"),
    {"de": ("Hardware-Entwickler", "Computer-Ingenieur"),
     "fr": ("ingénieur matériel", "ingénieur électronique"),
     "es": ("ingeniero de hardware", "ingeniero electrónico"),
     "nl": ("hardware engineer",), "it": ("ingegnere hardware",),
     "pl": ("inżynier sprzętu",), "pt": ("engenheiro de hardware",)},
    ("embedded_iot", "robotics_automation"),
)
_category(
    "it_consulting", "Technical Consulting & IT Business Analysis",
    ("IT Consultant", "Technical Consultant", "Business Analyst", "IT Business Analyst",
     "Solutions Consultant", "Systems Analyst", "Technology Consultant"),
    {"IT Consulting": ("IT Consultant", "Technology Consultant", "Solutions Consultant"),
     "Business Analysis": ("Business Analyst", "IT Business Analyst", "Systems Analyst"),
     "Solution Consulting": ("Solutions Consultant", "Pre-Sales Consultant", "Technical Consultant")},
    ("Requirements Analysis", "Stakeholder Management", "SQL", "Process Modelling", "Agile", "IT Strategy"),
    ("consulting", "business analysis", "requirements", "stakeholders", "process improvement", "solution design"),
    {"de": ("IT-Berater", "Business-Analyst"),
     "fr": ("consultant IT", "analyste métier"),
     "es": ("consultor IT", "analista de negocio"),
     "nl": ("IT-consultant", "businessanalist"),
     "it": ("consulente IT", "analista funzionale"),
     "pl": ("konsultant IT", "analityk biznesowy"),
     "pt": ("consultor de TI", "analista de negócios")},
    ("software_engineering", "data_science", "cybersecurity"),
)

GENERIC_IT_TITLES = [
    "IT Specialist", "Technology Specialist", "IT Graduate", "Technical Consultant",
    "Junior IT Specialist", "Working Student IT",
]


def all_category_titles(limit_per_category: int = 3, limit: int = 24) -> list[str]:
    out: list[str] = []
    for category in CATEGORIES.values():
        out.extend(category.titles[:limit_per_category])
    return _unique(out)[:limit]
