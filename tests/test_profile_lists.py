"""Regression coverage for profile CSV fields that hold lists."""

from __future__ import annotations

from core.schemas import CandidateProfileData
from core.text import normalize_string_list
from services.profile_service import synthesize_evidence
from ui.pages.profile import _editor_rows, _rebuild


def _legacy_csv(value: object) -> list[str]:
    """The old editor splitter, kept here to reproduce saved legacy data."""
    return [part.strip() for part in str(value or "").replace(";", ",").split(",") if part.strip()]


def test_normalizer_heals_repeated_editor_round_trips():
    expected = ["Python", "PySide6", "C#", ".NET", "CI/CD", "JavaScript/TypeScript"]
    value: object = expected
    for _ in range(5):
        assert normalize_string_list(value) == expected
        value = _legacy_csv(value)


def test_normalizer_handles_direct_serialized_lists():
    assert normalize_string_list("['Python', 'SQL']") == ["Python", "SQL"]
    assert normalize_string_list('["Python", "SQL"]') == ["Python", "SQL"]
    assert normalize_string_list([["Python"], ["SQL"]]) == ["Python", "SQL"]
    assert normalize_string_list(["React (hooks)", "(ISC)²"]) == ["React (hooks)", "(ISC)²"]


def test_profile_editor_round_trip_is_stable():
    expected = ["Python", "PySide6", "C#", "CI/CD"]
    data = CandidateProfileData.model_validate({
        "skills": [{"name": "Languages", "skills": expected}],
    })
    columns = {"name": "text", "skills": "csv"}

    for _ in range(3):
        frame = _editor_rows([group.model_dump(mode="json") for group in data.skills], columns)
        assert frame.loc[0, "skills"] == "Python, PySide6, C#, CI/CD"
        data.skills = [
            type(data.skills[0]).model_validate(item)
            for item in _rebuild(data, frame, columns)
        ]
        assert data.skills[0].skills == expected


def test_schema_normalizes_legacy_skills_and_technologies():
    data = CandidateProfileData.model_validate({
        "employment": [{"technologies": "['Python', 'FastAPI']"}],
        "projects": [{"technologies": ["['Python'", "'SQLite']"]}],
        "skills": [{"name": "Languages", "skills": "['Python', 'SQL']"}],
    })

    assert data.employment[0].technologies == ["Python", "FastAPI"]
    assert data.projects[0].technologies == ["Python", "SQLite"]
    assert data.skills[0].skills == ["Python", "SQL"]

    evidence = synthesize_evidence(data)
    skill_evidence = next(item for item in evidence if item.category == "skill")
    assert skill_evidence.value == "Python, SQL"
    assert all("[" not in item.value and "]" not in item.value for item in evidence)
