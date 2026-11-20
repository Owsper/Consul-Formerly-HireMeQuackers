from datetime import date, timedelta

import pytest

from core.exceptions import DuplicateApplicationError, InvalidStatusError, JobNotFoundError
from services.application_service import (
    activities_for, add_custom_status, add_manual_job, canonical_status, create_application,
    ensure_application, kanban, list_applications, list_statuses, tracker_stats, upcoming,
    update_application,
)
from services.deduplication import persist_job


@pytest.fixture
def job(session, job_record):
    row, _ = persist_job(session, job_record)
    return row


def test_duplicate_application_prevented(session, job):
    first = create_application(session, job.id)
    assert first.status == "Discovered"
    with pytest.raises(DuplicateApplicationError):
        create_application(session, job.id)
    existing, created = ensure_application(session, job.id)
    assert created is False and existing.id == first.id


def test_unknown_job_rejected(session):
    with pytest.raises(JobNotFoundError):
        create_application(session, "does-not-exist")


def test_status_change_is_validated_and_logged(session, job):
    app = create_application(session, job.id)
    update_application(session, app.id, status="Applied")
    assert app.status == "Applied"
    assert app.applied_at == date.today()
    with pytest.raises(InvalidStatusError):
        update_application(session, app.id, status="Teleported")
    kinds = [a.kind for a in activities_for(session, app.id)]
    assert "status" in kinds


def test_custom_statuses(session, job):
    add_custom_status(session, "Take-home task")
    assert "Take-home task" in list_statuses(session)
    assert canonical_status(session, "take-home TASK") == "Take-home task"
    app = create_application(session, job.id, status="Take-home task")
    assert app.status == "Take-home task"


def test_follow_ups_and_interviews(session, job):
    app = create_application(session, job.id, status="Applied")
    soon = date.today() + timedelta(days=2)
    update_application(session, app.id, follow_up_date=soon, interview_date=soon)
    agenda = upcoming(session, days=14)
    assert [a.id for a in agenda["follow_ups"]] == [app.id]
    assert [a.id for a in agenda["interviews"]] == [app.id]


def test_kanban_and_stats(session, job):
    app = create_application(session, job.id, status="Applied")
    board = kanban(session)
    assert app.id in [a.id for a in board["Applied"]]
    stats = tracker_stats(session)
    assert stats["total"] == 1 and stats["active"] == 1


def test_search_and_filter_applications(session, job):
    create_application(session, job.id)
    assert len(list_applications(session, search="acme")) == 1
    assert len(list_applications(session, status="Discovered")) == 1
    assert len(list_applications(session, status="Rejected")) == 0


def test_manual_job_entry_can_open_tracker_entry(session):
    row, created = add_manual_job(session, title="Platform Engineer", company="Initech",
                                  url="https://example.com/jobs/42", create_tracker_entry=True)
    assert created is True
    from services.job_service import sources_for_job

    assert sources_for_job(row)[0]["connector"] == "manual"
    apps = list_applications(session)
    assert len(apps) == 1 and apps[0].job_id == row.id
    with pytest.raises(ValueError):
        add_manual_job(session, title="  ", company="Nobody")
