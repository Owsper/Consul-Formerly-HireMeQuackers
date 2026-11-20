"""Multiple reusable search profiles.

Profiles live in ``UserSetting`` as JSON so existing databases keep working.
Nothing here knows about job titles or disciplines: a profile is just a set of
search constraints consumed by the planner, scorer and UI.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from core.schemas import SearchPreferences
from services.settings_service import get_setting, set_setting

PROFILES_KEY = "search_profiles"
ACTIVE_PROFILE_KEY = "active_search_profile_id"
LEGACY_KEY = "search_preferences"

SENIORITY_OPTIONS = [
    "", "internship", "working_student", "graduate", "junior", "mid", "senior", "lead",
]


def _new_id() -> str:
    return "sp-" + uuid.uuid4().hex[:10]


def _as_preferences(raw: object) -> SearchPreferences | None:
    try:
        return SearchPreferences.model_validate(raw or {})
    except Exception:
        return None


def _stored(session: Session) -> list[SearchPreferences]:
    raw = get_setting(session, PROFILES_KEY, None)
    if raw is None:
        legacy = _as_preferences(get_setting(session, LEGACY_KEY, {}))
        if legacy and (legacy.target_titles or legacy.alternative_titles or legacy.countries):
            legacy.profile_id = legacy.profile_id or "default"
            legacy.active = True
            set_setting(session, PROFILES_KEY, [legacy.model_dump(mode="json")])
            set_setting(session, ACTIVE_PROFILE_KEY, legacy.profile_id)
            return [legacy]
        return []
    profiles: list[SearchPreferences] = []
    for item in raw or []:
        profile = _as_preferences(item)
        if profile is not None:
            if not profile.profile_id:
                profile.profile_id = _new_id()
            profiles.append(profile)
    return profiles


def _write(session: Session, profiles: list[SearchPreferences],
           active_id: str | None = None) -> None:
    set_setting(session, PROFILES_KEY, [p.model_dump(mode="json") for p in profiles])
    if active_id is None:
        active = next((p.profile_id for p in profiles if p.active), "")
        active_id = active
    set_setting(session, ACTIVE_PROFILE_KEY, active_id or "")


def list_profiles(session: Session) -> list[SearchPreferences]:
    return _stored(session)


def get_profile(session: Session, profile_id: str) -> SearchPreferences | None:
    return next((p for p in _stored(session) if p.profile_id == profile_id), None)


def active_profile(session: Session) -> SearchPreferences | None:
    stored = _stored(session)
    active_id = str(get_setting(session, ACTIVE_PROFILE_KEY, "") or "")
    profile = next((p for p in stored if p.profile_id == active_id), None)
    if profile is None:
        profile = next((p for p in stored if p.active), None)
    return profile


def new_profile(*, name: str = "New search", category: str = "any_it") -> SearchPreferences:
    return SearchPreferences(name=name or "New search", it_category=category,
                             profile_id=_new_id(), active=True)


def save_profile(session: Session, profile: SearchPreferences,
                 *, activate: bool = True) -> SearchPreferences:
    """Create or update a profile. Activation is explicit and exclusive."""
    stored = _stored(session)
    profile.profile_id = profile.profile_id or _new_id()
    index = next((i for i, p in enumerate(stored) if p.profile_id == profile.profile_id), None)
    if activate:
        for other in stored:
            other.active = other.profile_id == profile.profile_id
        profile.active = True
    elif index is None:
        profile.active = False
    elif stored[index].active:
        profile.active = True
    if index is None:
        stored.append(profile)
    else:
        stored[index] = profile
    active_id = profile.profile_id if profile.active else None
    _write(session, stored, active_id)
    return profile


def duplicate_profile(session: Session, profile_id: str,
                      *, name: str | None = None) -> SearchPreferences | None:
    source = get_profile(session, profile_id)
    if source is None:
        return None
    copy = source.model_copy(deep=True)
    copy.profile_id = _new_id()
    copy.name = name or f"{source.name} (copy)"
    copy.active = False
    return save_profile(session, copy, activate=False)


def activate_profile(session: Session, profile_id: str) -> SearchPreferences | None:
    stored = _stored(session)
    found = next((p for p in stored if p.profile_id == profile_id), None)
    if found is None:
        return None
    for profile in stored:
        profile.active = profile.profile_id == profile_id
    _write(session, stored, profile_id)
    found.active = True
    return found


def deactivate_profile(session: Session, profile_id: str) -> bool:
    stored = _stored(session)
    found = next((p for p in stored if p.profile_id == profile_id), None)
    if found is None:
        return False
    found.active = False
    _write(session, stored, "")
    return True


def load_active_preferences(session: Session) -> SearchPreferences:
    profile = active_profile(session)
    return profile or SearchPreferences()


def save_active_preferences(session: Session, prefs: SearchPreferences) -> SearchPreferences:
    return save_profile(session, prefs, activate=True)
