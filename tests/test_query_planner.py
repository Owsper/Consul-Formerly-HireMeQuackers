from core.schemas import SearchPreferences
from services.query_planner import build_rule_based_plan, languages_for_countries, plan_search


def test_planner_produces_unique_multilingual_queries(profile_data):
    prefs = SearchPreferences(
        target_titles=["Backend Engineer"], countries=["Germany", "Netherlands"],
        languages=["English"], work_modes=["remote", "hybrid"],
    )
    plan = build_rule_based_plan(profile_data, prefs)
    assert plan.source == "rule_based"
    assert plan.queries
    queries = [q.query.strip().lower() for q in plan.queries]
    assert len(queries) == len(set(queries)), "queries must be deduplicated"
    languages = {q.language for q in plan.queries}
    assert {"en", "de", "nl"} & languages
    assert any("entwickler" in q or "engineer" in q for q in queries)


def test_planner_uses_local_terms_not_literal_translation(profile_data):
    prefs = SearchPreferences(target_titles=["Software Engineer"], countries=["Germany"],
                              languages=["English"])
    plan = build_rule_based_plan(profile_data, prefs)
    german_titles = plan.local_titles.get("de", [])
    assert german_titles
    assert any(term in " ".join(german_titles).lower()
               for term in ("entwickler", "softwareentwickler", "ingenieur"))


def test_languages_for_countries():
    assert "de" in languages_for_countries(["Germany"], ["English"])
    assert "nl" in languages_for_countries(["Netherlands"], [])
    assert languages_for_countries([], ["English"]) == ["en"]


def test_plan_search_falls_back_without_llm(profile_data):
    plan = plan_search(profile_data, SearchPreferences(target_titles=["Backend Engineer"],
                                                       countries=["Germany"]))
    assert plan.source == "rule_based"
    assert plan.warnings
    assert plan.queries
