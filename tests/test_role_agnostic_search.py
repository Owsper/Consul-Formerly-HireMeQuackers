"""Role-agnostic discovery: categories, custom titles, profiles and transfers."""

from core.job_taxonomy import ANY_IT, CATEGORIES, category_options, detect_categories, titles_for
from core.schemas import JobRecord, SearchPreferences, SkillCategory
from services.job_scoring import score_record
from services.query_planner import build_rule_based_plan
from services.search_profile_service import (
    activate_profile, active_profile, deactivate_profile, duplicate_profile, list_profiles,
    new_profile, save_profile,
)


def test_taxonomy_covers_broad_it_and_has_any_option():
    labels = " ".join(c.label for c in CATEGORIES.values()).lower()
    for expected in ("game", "embedded", "network", "cloud", "security", "artificial",
                     "data", "database", "qa", "robotic", "support", "hardware", "consult"):
        assert expected in labels
    options = dict(category_options())
    assert options[ANY_IT] == "Any IT Category"
    assert len(CATEGORIES) >= 15
    assert "Unity Developer" in titles_for("game_development")


def test_custom_title_is_never_replaced_by_category_seed(profile_data):
    prefs = SearchPreferences(
        it_category="game_development",
        target_titles=["Unreal Engine Developer"],
        specialisation="Gameplay Programming",
        countries=["Germany"],
        employment_types=["working_student"],
    )
    plan = build_rule_based_plan(profile_data, prefs)
    assert plan.english_titles[0] == "Unreal Engine Developer"
    assert plan.role_families[0] == "Unreal Engine Developer"
    joined = " ".join(plan.english_titles).lower()
    assert "unreal" in joined and "gameplay" in joined
    assert "working student" in joined
    assert any(q.query.startswith('"Unreal Engine Developer"') for q in plan.queries[:2])


def test_embedded_category_does_not_fall_back_to_software_titles(profile_data):
    prefs = SearchPreferences(
        it_category="embedded_iot", countries=["Germany"],
        required_skills=["C", "RTOS", "Microcontrollers"],
    )
    plan = build_rule_based_plan(profile_data, prefs)
    titles = " ".join(plan.english_titles).lower()
    assert "embedded" in titles or "firmware" in titles
    assert "python developer" not in titles
    assert "backend developer" not in titles
    assert plan.it_category == "embedded_iot"
    assert any("embedded" in q.query.lower() or "firmware" in q.query.lower()
               for q in plan.queries)


def test_any_it_with_custom_cyber_title_stays_cyber(profile_data):
    prefs = SearchPreferences(it_category=ANY_IT, target_titles=["SOC Analyst"],
                              countries=["Germany"])
    plan = build_rule_based_plan(profile_data, prefs)
    assert plan.english_titles[0] == "SOC Analyst"
    assert plan.it_category == "cybersecurity"
    assert any("soc analyst" in q.query.lower() for q in plan.queries[:2])
    assert not any("game developer" in t.lower() for t in plan.english_titles)


def test_any_it_without_titles_sweeps_every_registered_discipline(profile_data):
    plan = build_rule_based_plan(
        profile_data, SearchPreferences(it_category=ANY_IT, countries=["Germany"]))
    queries = " ".join(q.query.lower() for q in plan.queries)
    for category in CATEGORIES.values():
        if category.titles:
            assert category.titles[0].lower() in queries, category.key


def test_detect_categories_uses_skills_and_titles():
    assert detect_categories("Unity gameplay programmer", ["C#"])[0] == "game_development"
    assert detect_categories("Firmware engineer", ["C", "RTOS"])[0] == "embedded_iot"
    assert detect_categories("SOC analyst", ["SIEM"])[0] == "cybersecurity"


def test_new_category_file_can_extend_registry_without_engine_changes(tmp_path):
    import json

    from core.job_taxonomy import load_category_file

    payload = {"categories": [{
        "key": "quantum_engineering", "label": "Quantum Engineering",
        "titles": ["Quantum Software Engineer"], "core_skills": ["Qiskit"],
        "translations": {"de": ["Quantenentwickler"]},
    }]}
    path = tmp_path / "categories.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_category_file(path) == 1
    assert "Quantum Software Engineer" in titles_for("quantum_engineering")
    # Clean up so the in-process registry does not leak into other tests.
    CATEGORIES.pop("quantum_engineering", None)


def test_multiple_profiles_save_activate_duplicate_and_deactivate(session):
    game = save_profile(session, new_profile(name="Games", category="game_development"))
    data = save_profile(session, new_profile(name="Data", category="data_science"))
    assert len(list_profiles(session)) == 2
    assert active_profile(session).profile_id == data.profile_id

    duplicated = duplicate_profile(session, game.profile_id)
    assert duplicated and duplicated.active is False
    assert duplicated.name == "Games (copy)"

    activate_profile(session, game.profile_id)
    assert active_profile(session).profile_id == game.profile_id
    assert len(list_profiles(session)) == 3

    deactivate_profile(session, game.profile_id)
    assert active_profile(session) is None

    # A save with activation replaces the exclusive active profile.
    activate_profile(session, data.profile_id)
    assert active_profile(session).profile_id == data.profile_id


def _profile_with_skills(profile_data, title, skills):
    profile = profile_data.model_copy(deep=True)
    profile.personal.professional_title = title
    profile.skills = [SkillCategory(name="Skills", skills=skills)]
    return profile


def test_transferable_skill_gets_partial_credit_but_stays_missing(profile_data, evidence):
    profile = _profile_with_skills(profile_data, "Gameplay Programmer", ["C++", "C#"])
    job = JobRecord(
        source="manual", title="Unity Developer", company="Studio",
        description="Unity gameplay programming with C#.", country="Germany",
        required_skills=["Unity", "C#"], languages=["English (C1)"],
    )
    prefs = SearchPreferences(countries=["Germany"],
                              work_modes=["remote", "hybrid", "onsite"])
    match = score_record(job, profile, evidence, prefs)
    assert "Unity" in match.missing_required_skills, "adjacency must not count as exact evidence"
    assert any("C#" in item and "Unity" in item for item in match.transferable_skills)
    assert match.role_family == "Game Development"
    assert "Transferable but not equivalent" in match.explanation
    technical = next(d for d in match.dimensions if d.name == "technical_skills")
    assert "partial credit" in technical.rationale


def test_short_skill_names_do_not_create_false_transfers(profile_data, evidence):
    profile = _profile_with_skills(profile_data, "Linux Administrator", ["Linux"])
    job = JobRecord(
        source="manual", title="Embedded Software Engineer", company="Devices",
        description="Firmware in C with RTOS.", country="Germany",
        required_skills=["C", "RTOS", "Microcontrollers"],
    )
    match = score_record(job, profile, evidence, SearchPreferences())
    assert not any("→ C" in item for item in match.transferable_skills)
    assert set(match.missing_required_skills) == {"C", "RTOS", "Microcontrollers"}
