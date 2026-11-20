from core.models import CandidateProfile, ProfileVersion
from core.schemas import CandidateProfileData, EvidenceStatus
from services.profile_service import (
    get_active_profile, get_versions, merge_profiles, restore_version, save_profile,
)


def test_unapproved_profile_is_not_active(session, profile_data, evidence):
    profile = save_profile(session, profile_data, evidence, approve=False)
    assert profile.is_active is False
    assert get_active_profile(session) is None


def test_approval_activates_and_keeps_evidence_statuses(session, profile_data, evidence):
    evidence[2].status = EvidenceStatus.NEEDS_REVIEW
    profile = save_profile(session, profile_data, evidence, approve=True)
    session.expire_all()
    stored = session.get(CandidateProfile, profile.id)
    assert stored.is_active is True
    statuses = {row.evidence_id: row.status for row in stored.evidence}
    assert statuses  # every claim is traceable
    assert statuses[evidence[2].evidence_id] == "needs_review"


def test_rejected_evidence_is_retained_and_flagged(session, profile_data, evidence):
    evidence[0].status = EvidenceStatus.REJECTED
    profile = save_profile(session, profile_data, evidence, approve=True)
    session.expire_all()
    stored = session.get(CandidateProfile, profile.id)
    rejected = [row for row in stored.evidence if row.status == "rejected"]
    assert len(rejected) == 1


def test_each_save_creates_a_version(session, profile_data, evidence):
    profile = save_profile(session, profile_data, evidence, approve=False)
    updated = profile_data.model_copy(deep=True)
    updated.personal.professional_title = "Platform Engineer"
    save_profile(session, updated, evidence, approve=True, profile_id=profile.id,
                 note="Changed title")
    versions = get_versions(session, profile.id)
    # History is returned newest-first for the UI timeline.
    assert [v.version for v in versions] == [2, 1]
    assert "Platform Engineer" in versions[0].data_json


def test_restore_version(session, profile_data, evidence):
    profile = save_profile(session, profile_data, evidence, approve=False)
    updated = profile_data.model_copy(deep=True)
    updated.personal.full_name = "Ada Byron"
    save_profile(session, updated, evidence, approve=True, profile_id=profile.id)
    restore_version(session, profile.id, 1)
    restored = CandidateProfileData.model_validate_json(
        session.get(CandidateProfile, profile.id).data_json
    )
    assert restored.personal.full_name == "Ada Lovelace"


def test_merge_profiles_adds_without_duplicating(profile_data):
    incoming = CandidateProfileData.model_validate({
        "employment": [{
            "employer": "Shop GmbH", "title": "Software Engineer",
            "responsibilities": ["Built Python APIs with FastAPI and PostgreSQL"],
        }],
        "skills": [{"name": "Languages", "skills": ["Python", "Go"]}],
        "additional": {"languages": [{"language": "German", "proficiency": "C1"}]},
    })
    merged = merge_profiles(profile_data, incoming)
    assert len(merged.employment) == 1
    assert len(merged.employment[0].responsibilities) == 2
    assert "Go" in merged.all_skills()
    assert len(merged.additional.languages) == 1
