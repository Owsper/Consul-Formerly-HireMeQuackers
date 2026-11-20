"""SQLAlchemy engine/session management with SQLite pragmas and backups."""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config import get_settings
from core.logging_config import get_logger
from core.models import Base

logger = get_logger("database")

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _apply_sqlite_pragmas(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def build_engine(database_url: str | None = None) -> Engine:
    settings = get_settings()
    url = database_url or settings.database_url
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        if ":memory:" in url or url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            path = url.split("sqlite:///", 1)[-1]
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        engine = create_engine(url, **kwargs)
        _apply_sqlite_pragmas(engine)
    else:
        engine = create_engine(url, pool_pre_ping=True, **kwargs)
    return engine


def configure_database(database_url: str | None = None) -> Engine:
    """(Re)create the global engine; used at startup and by tests."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = build_engine(database_url)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        get_settings().ensure_dirs()
        _engine = configure_database(None)
    return _engine


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Database initialised at %s", engine.url.render_as_string(hide_password=True))


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session: commit on success, rollback on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI-style dependency for completeness / future API surface."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def healthcheck() -> bool:
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover
        logger.exception("Database healthcheck failed")
        return False


def backup_database(destination_dir: Path | None = None) -> Path | None:
    """Create a consistent SQLite backup. Returns the backup path."""
    settings = get_settings()
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        logger.info("Backup skipped: not a SQLite database")
        return None
    target_dir = destination_dir or settings.backups_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(engine.url.database or "")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target_path = target_dir / f"consul-{stamp}.db"
    if source_path.exists():
        with engine.connect() as conn:
            raw = conn.connection.dbapi_connection  # type: ignore[attr-defined]
            import sqlite3

            dest = sqlite3.connect(target_path)
            try:
                raw.backup(dest)
            finally:
                dest.close()
    else:  # pragma: no cover - unusual
        shutil.copyfile(source_path, target_path)
    logger.info("Database backup written to %s", target_path)
    return target_path


def export_all_data() -> dict:
    """Export user-owned data as JSON (no secrets are stored in the DB)."""
    with session_scope() as session:
        from core.models import (
            Application, ApplicationActivity, CandidateProfile, Job, JobMatchRow, JobSourceRef,
            ProfileEvidence, ProfileVersion, SavedJob, TailoredCVRow,
        )

        def rows(model):  # noqa: ANN001
            return [
                {c.name: (getattr(r, c.name).isoformat() if hasattr(getattr(r, c.name), "isoformat") and getattr(r, c.name) else getattr(r, c.name))
                 for c in model.__table__.columns}
                for r in session.query(model).all()
            ]

        return {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "profiles": rows(CandidateProfile),
            "evidence": rows(ProfileEvidence),
            "profile_versions": rows(ProfileVersion),
            "jobs": rows(Job),
            "job_sources": rows(JobSourceRef),
            "matches": rows(JobMatchRow),
            "saved_jobs": rows(SavedJob),
            "tailored_cvs": rows(TailoredCVRow),
            "applications": rows(Application),
            "application_activity": rows(ApplicationActivity),
        }


def export_all_data_json(path: Path) -> Path:
    data = export_all_data()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def delete_all_user_data() -> None:
    """Privacy: wipe all career data, keeping the schema."""
    with session_scope() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
    logger.warning("All user data deleted")
