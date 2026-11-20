from core.schemas import SearchPreferences
from services.settings_service import (
    get_setting, load_preferences, load_ui_settings, save_preferences, save_ui_settings,
    set_setting,
)
from services.job_scoring import scoring_weights


def test_preferences_roundtrip(session):
    prefs = SearchPreferences(target_titles=["Data Engineer"], countries=["Netherlands"],
                              work_modes=["remote"], languages=["English"])
    save_preferences(session, prefs)
    loaded = load_preferences(session)
    assert loaded.target_titles == ["Data Engineer"]
    assert loaded.countries == ["Netherlands"]


def test_defaults_when_unset(session):
    assert load_preferences(session).target_titles == []
    assert load_ui_settings(session) == {}


def test_scalar_settings_and_ui_merge(session):
    set_setting(session, "theme", "dark")
    assert get_setting(session, "theme") == "dark"
    assert get_setting(session, "missing", "fallback") == "fallback"
    save_ui_settings(session, {"theme": "light"})
    save_ui_settings(session, {"compact": True})
    assert load_ui_settings(session) == {"theme": "light", "compact": True}


def test_scoring_weights_are_normalised(session):
    set_setting(session, "scoring_weights", {"technical": 60, "role": 40, "location": 999})
    weights = scoring_weights(session)
    assert abs(sum(weights.values()) - 100.0) < 0.01
    defaults = scoring_weights()
    assert abs(sum(defaults.values()) - 100.0) < 0.01
