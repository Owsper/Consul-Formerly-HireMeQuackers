"""Conservative transferable-skill reasoning across IT disciplines.

A transfer is evidence of adjacency, never proof of equivalence. Callers keep the
requirement in the missing list and award only partial credit.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.text import canonical_skill, normalize_text


@dataclass(frozen=True)
class Relationship:
    source: str
    targets: tuple[str, ...]
    categories: tuple[str, ...]
    note: str


RELATIONSHIPS: tuple[Relationship, ...] = (
    Relationship("python", ("automation", "scripting", "data engineering", "etl",
                            "machine learning", "backend", "api"),
                 ("data_science", "ai_ml", "cloud_devops", "software_engineering", "qa_testing"),
                 "Python is adjacent to automation, data and backend work; hands-on domain evidence is still required."),
    Relationship("c", ("embedded", "firmware", "microcontroller", "rtos", "iot"),
                 ("embedded_iot", "hardware_engineering", "robotics_automation"),
                 "C is a foundation for embedded/firmware work but does not replace device or RTOS evidence."),
    Relationship("c++", ("embedded", "firmware", "game", "unity", "unreal", "robotics",
                         "real-time", "graphics", "c#"),
                 ("embedded_iot", "game_development", "robotics_automation", "hardware_engineering"),
                 "C++ transfers into game, embedded and robotics codebases at a foundational level."),
    Relationship("c#", ("unity", "game", "gameplay", ".net", "backend"),
                 ("game_development", "software_engineering"),
                 "C# is the primary Unity language; engine-specific experience still has to be shown."),
    Relationship("sql", ("database", "data analysis", "etl", "postgresql", "mysql", "oracle",
                         "data engineering", "bi"),
                 ("database_admin", "data_science", "software_engineering"),
                 "SQL transfers across database, analytics and backend roles, with dialect depth unproven."),
    Relationship("javascript", ("typescript", "web", "frontend", "react", "node.js", "full stack"),
                 ("web_development", "software_engineering", "game_development"),
                 "JavaScript transfers to adjacent web stacks; framework-specific evidence is separate."),
    Relationship("typescript", ("javascript", "web", "frontend", "react", "node.js", "full stack"),
                 ("web_development", "software_engineering"),
                 "TypeScript transfers across modern web stacks; framework-specific evidence is separate."),
    Relationship("linux", ("networking", "devops", "infrastructure", "systems administration",
                           "embedded linux", "cloud", "bash"),
                 ("networking_infrastructure", "cloud_devops", "it_support", "embedded_iot"),
                 "Linux administration transfers into infrastructure, support and embedded Linux work."),
    Relationship("networking", ("tcp/ip", "dns", "routing", "switching", "firewall", "vpn",
                                "network", "infrastructure"),
                 ("networking_infrastructure", "cybersecurity", "cloud_devops", "it_support"),
                 "Networking fundamentals transfer to infrastructure and security roles, not to hands-on SOC work by themselves."),
    Relationship("docker", ("kubernetes", "devops", "containers", "cloud", "ci/cd"),
                 ("cloud_devops", "software_engineering", "networking_infrastructure"),
                 "Container experience transfers toward platform/DevOps work; orchestration depth is separate."),
    Relationship("kubernetes", ("docker", "devops", "containers", "cloud", "platform"),
                 ("cloud_devops", "networking_infrastructure"),
                 "Kubernetes experience transfers across platform and cloud operations."),
    Relationship("aws", ("azure", "gcp", "cloud", "devops", "terraform"),
                 ("cloud_devops", "networking_infrastructure", "data_science"),
                 "One cloud provider transfers conceptually to another; provider-specific certification is not implied."),
    Relationship("azure", ("aws", "gcp", "cloud", "devops", "terraform"),
                 ("cloud_devops", "networking_infrastructure", "data_science"),
                 "One cloud provider transfers conceptually to another; provider-specific certification is not implied."),
    Relationship("gcp", ("aws", "azure", "cloud", "devops", "terraform"),
                 ("cloud_devops", "networking_infrastructure", "data_science"),
                 "One cloud provider transfers conceptually to another; provider-specific certification is not implied."),
    Relationship("pytorch", ("tensorflow", "machine learning", "deep learning", "mlops"),
                 ("ai_ml", "data_science", "robotics_automation"),
                 "PyTorch transfers to adjacent ML stacks; production MLOps evidence is separate."),
    Relationship("tensorflow", ("pytorch", "machine learning", "deep learning", "mlops"),
                 ("ai_ml", "data_science", "robotics_automation"),
                 "TensorFlow transfers to adjacent ML stacks; production MLOps evidence is separate."),
    Relationship("selenium", ("playwright", "cypress", "test automation", "qa"),
                 ("qa_testing", "software_engineering"),
                 "One browser automation framework transfers to another with some ramp-up."),
    Relationship("playwright", ("selenium", "cypress", "test automation", "qa"),
                 ("qa_testing", "software_engineering"),
                 "One browser automation framework transfers to another with some ramp-up."),
    Relationship("api", ("rest apis", "integration", "backend", "microservices", "networking",
                         "tcp/ip", "infrastructure"),
                 ("software_engineering", "cloud_devops", "data_science", "networking_infrastructure"),
                 "API integration experience transfers to backend, data and infrastructure automation."),
    Relationship("git", ("ci/cd", "version control", "devops"),
                 ("software_engineering", "cloud_devops", "qa_testing"),
                 "Version-control workflow transfers into CI/CD and team engineering practice."),
)

SIBLING_GROUPS: tuple[tuple[str, ...], ...] = (
    ("javascript", "typescript"),
    ("react", "vue", "angular"),
    ("aws", "azure", "gcp"),
    ("postgresql", "mysql", "sql server", "oracle", "sqlite"),
    ("pytorch", "tensorflow"),
    ("selenium", "playwright", "cypress"),
    ("docker", "podman"),
    ("jenkins", "github actions", "gitlab ci"),
    ("unity", "unreal engine", "godot"),
    ("plc", "siemens tia portal", "rockwell"),
)


def _overlaps(requirement: str, target: str) -> bool:
    req, tgt = normalize_text(requirement), normalize_text(target)
    if not req or not tgt:
        return False
    if min(len(req), len(tgt)) <= 2:
        return req == tgt
    return req == tgt or req in tgt or tgt in req


def find_transferable(required: list[str], candidate_skills: list[str],
                      category: str | None = None) -> list[tuple[str, str, str]]:
    """Return ``(missing_requirement, candidate_skill, note)`` tuples."""
    owned = {canonical_skill(s): s for s in candidate_skills if canonical_skill(s)}
    exact = {canonical_skill(s) for s in required}
    missing = [s for s in required if canonical_skill(s) not in owned]
    results: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    for relationship in RELATIONSHIPS:
        source = canonical_skill(relationship.source)
        if source not in owned:
            continue
        if category and relationship.categories and category not in relationship.categories:
            continue
        for target in relationship.targets:
            for requirement in missing:
                if not _overlaps(requirement, target):
                    continue
                key = (canonical_skill(requirement), source)
                if key in seen:
                    continue
                seen.add(key)
                results.append((requirement, owned[source], relationship.note))

    # Same-family tools (cloud providers, SQL engines, test frameworks) are
    # adjacent but still not the exact requirement.
    for group in SIBLING_GROUPS:
        for requirement in missing:
            req = canonical_skill(requirement)
            if req not in group:
                continue
            for sibling in group:
                if sibling != req and sibling in owned:
                    key = (req, sibling)
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append((
                        requirement, owned[sibling],
                        f"{owned[sibling]} is in the same tool family as {requirement}; "
                        "the exact tool is not evidenced.",
                    ))
    return results[:4]


def transfer_summary(transfers: list[tuple[str, str, str]]) -> list[str]:
    return [f"{source} → {requirement} (transferable, not equivalent)" 
            for requirement, source, _ in transfers]
