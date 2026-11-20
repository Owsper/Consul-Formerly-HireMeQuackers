"""User preferences and app settings persisted in SQLite (never secrets)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from core.models import UserSetting
from core.schemas import SearchPreferences

PREFERENCES_KEY = "search_preferences"
UI_KEY = "ui_settings"


def get_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(UserSetting, key)
    if row is None or not row.value:
        return default
    try:
        return json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return default


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(UserSetting, key)
    payload = json.dumps(value, ensure_ascii=False, default=str)
    if row is None:
        session.add(UserSetting(key=key, value=payload))
    else:
        row.value = payload
    session.flush()


def load_preferences(session: Session) -> SearchPreferences:
    """Return the active search profile (legacy single-preference keys migrate)."""
    from services.search_profile_service import load_active_preferences

    return load_active_preferences(session)


def save_preferences(session: Session, prefs: SearchPreferences) -> SearchPreferences:
    """Save and activate a profile under the multi-profile store."""
    from services.search_profile_service import save_active_preferences

    return save_active_preferences(session, prefs)


def load_ui_settings(session: Session) -> dict:
    return get_setting(session, UI_KEY, {}) or {}


def save_ui_settings(session: Session, values: dict) -> None:
    existing = load_ui_settings(session)
    existing.update(values)
    set_setting(session, UI_KEY, existing)
