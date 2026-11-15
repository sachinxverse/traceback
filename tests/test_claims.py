"""Claim workflow tests (F7, F8, Section 10, acceptance A6, A7)."""
from datetime import UTC, datetime, timedelta

from tests.conftest import auth, login


def _setup_pair(client, app):
    """Create a matching LOST/FOUND pair from two users; return (lost_id, found_id, match_id)."""
    auth(client, "owner@test.com", "Owner")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS",
        "title": "Lost brown wallet",
        "description": "Lost my brown wallet near the fountain with cards inside.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "private_details": "Initials J.K., blue card holder inside",
        "images": _img((120, 70, 20))},
        content_type="multipart/form-data")
    lost_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    auth(client, "finder@test.com", "Finder")
    r = client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "WALLETS_CARDS",
        "title": "Brown wallet found",
        "description": "A brown leather wallet was found near the fountain area.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "private_details": "Brown wallet with initials inside",
        "custody": "WITH_FINDER",
        "images": _img((125, 75, 25))},
        content_type="multipart/form-data")
    found_id = r.get_json()["data"]["id"]
    r = client.get(f"/api/v1/reports/{found_id}/matches")
    match_id = r.get_json()["data"][0]["id"]
    return lost_id, found_id, match_id


def _img(colour):
    import io

    from PIL import Image
    from werkzeug.datastructures import FileStorage
    buf = io.BytesIO()
    Image.new("RGB", (220, 180), colour).save(buf, format="PNG")
    buf.seek(0)
    return FileStorage(stream=buf, filename="p.png", content_type="image/png")


def _submit_claim(client, match_id, details="Serial number SN-99123 and a deep scratch near the corner."):
    r = client.post(f"/api/v1/matches/{match_id}/claims", data={
        "claim_details": details}, content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    return r


def test_full_happy_path_to_completed(client, app, db):
    lost_id, found_id, match_id = _setup_pair(client, app)

    # claim as lost owner
    login(client, "owner@test.com")
    r = _submit_claim(client, match_id)
    assert r.status_code == 201, r.get_data(as_text=True)
    claim_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    # reviewer (finder) sees claim with private details side-by-side
    login(client, "finder@test.com")
    r = client.get(f"/api/v1/claims/{claim_id}")
    data = r.get_json()["data"]
    assert "claim_details" in data
    assert "found_private_details" in data

    r = client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    assert r.status_code == 200
    r = client.post(f"/api/v1/claims/{claim_id}/mark-handed-over")
    assert r.status_code == 200
    client.post("/api/v1/auth/logout")

    # claimant confirms
    login(client, "owner@test.com")
    r = client.post(f"/api/v1/claims/{claim_id}/confirm-received")
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "COMPLETED"

    # both reports RECOVERED, match CONFIRMED
    from app.models import Match, Report
    with app.app_context():
        assert db.session.get(Report, lost_id).status.value == "RECOVERED"
        assert db.session.get(Report, found_id).status.value == "RECOVERED"
        assert db.session.get(Match, match_id).status.value == "CONFIRMED"


def test_reject_then_dispute_then_admin_resolve(client, app, db):
    from tests.conftest import make_institution
    make_institution(db, name="Admin Test Inst")
    from app.models import User
    with app.app_context():
        admin = User(name="Admin", email="admin@x.com", role=__import__("app.models.enums", fromlist=["Role"]).Role.ADMIN)
        admin.set_password("Password1")
        db.session.add(admin)
        db.session.commit()

    lost_id, found_id, match_id = _setup_pair(client, app)
    login(client, "owner@test.com")
    r = _submit_claim(client, match_id)
    claim_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    login(client, "finder@test.com")
    r = client.post(f"/api/v1/claims/{claim_id}/reject",
                    json={"review_note": "Details did not match the wallet contents."})
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "REJECTED"
    client.post("/api/v1/auth/logout")

    # claimant disputes
    login(client, "owner@test.com")
    r = client.post(f"/api/v1/claims/{claim_id}/dispute",
                    json={"reason": "I am certain this wallet is mine."})
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "DISPUTED"
    client.post("/api/v1/auth/logout")

    # admin resolves (approve)
    login(client, "admin@x.com")
    r = client.post(f"/api/v1/admin/claims/{claim_id}/resolve",
                    json={"decision": "APPROVE", "note": "Verified with evidence."})
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "APPROVED"


def test_withdraw_claim(client, app):
    lost_id, found_id, match_id = _setup_pair(client, app)
    login(client, "owner@test.com")
    r = _submit_claim(client, match_id)
    claim_id = r.get_json()["data"]["id"]
    r = client.post(f"/api/v1/claims/{claim_id}/withdraw")
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "WITHDRAWN"


def test_duplicate_claim_conflict(client, app):
    lost_id, found_id, match_id = _setup_pair(client, app)
    login(client, "owner@test.com")
    assert _submit_claim(client, match_id).status_code == 201
    r = client.post(f"/api/v1/matches/{match_id}/claims", data={
        "claim_details": "Serial number SN-99123 and a deep scratch near the corner."},
        content_type="multipart/form-data")
    assert r.status_code == 409


def test_only_lost_owner_can_claim(client, app):
    lost_id, found_id, match_id = _setup_pair(client, app)
    client.post("/api/v1/auth/logout")
    auth(client, "random@test.com", "Random")
    r = client.post(f"/api/v1/matches/{match_id}/claims", data={
        "claim_details": "Serial number SN-99123 and a deep scratch near the corner."},
        content_type="multipart/form-data")
    assert r.status_code == 404


def test_illegal_transitions_409(client, app):
    lost_id, found_id, match_id = _setup_pair(client, app)
    login(client, "owner@test.com")
    r = _submit_claim(client, match_id)
    claim_id = r.get_json()["data"]["id"]
    # cannot confirm before handover
    r = client.post(f"/api/v1/claims/{claim_id}/confirm-received")
    assert r.status_code == 409
    client.post("/api/v1/auth/logout")
    # claimant cannot approve
    login(client, "owner@test.com")
    r = client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    assert r.status_code == 403


def test_reviewer_rule_by_custody(client, app, db):
    """AT_INSTITUTION custody: only institution staff can review, not the finder."""
    from datetime import datetime

    from tests.conftest import make_institution, make_staff
    inst = make_institution(db, name="Review Inst")
    make_staff(db, "staff@r.com", inst.id)

    auth(client, "owner2@test.com", "Owner2")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS", "title": "Lost keys",
        "description": "Lost my keys with a blue keychain near the gate.",
        "incident_date": datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img((30, 30, 220))}, content_type="multipart/form-data")
    client.post("/api/v1/auth/logout")

    auth(client, "finder2@test.com", "Finder2")
    r = client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "KEYS", "title": "Keys found",
        "description": "Found keys with a blue keychain near the main gate.",
        "incident_date": datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
        "institution_id": str(inst.id), "custody": "AT_INSTITUTION",
        "images": _img((35, 35, 225))}, content_type="multipart/form-data")
    found_id = r.get_json()["data"]["id"]
    match_id = client.get(f"/api/v1/reports/{found_id}/matches").get_json()["data"][0]["id"]
    client.post("/api/v1/auth/logout")

    login(client, "owner2@test.com")
    r = _submit_claim(client, match_id, details="Two keys, a blue heart fob, and a bike-lock key.")
    claim_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    # the finder must NOT be able to review (custody at institution)
    login(client, "finder2@test.com")
    r = client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    assert r.status_code in (403, 404)
    client.post("/api/v1/auth/logout")

    # institution staff can
    login(client, "staff@r.com")
    r = client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    assert r.status_code == 200


def test_other_claims_auto_rejected_on_completion(client, app, db):
    """A6: completing one claim auto-rejects other live claims on the same found item."""
    lost_id, found_id, match_id = _setup_pair(client, app)

    # second lost owner also gets matched? Use a second match from another user
    auth(client, "owner3@test.com", "Owner3")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS",
        "title": "Lost brown wallet today",
        "description": "I misplaced my brown wallet by the fountain this morning.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img((121, 71, 21))}, content_type="multipart/form-data")
    lost3 = r.get_json()["data"]
    r = client.get(f"/api/v1/reports/{lost3['id']}/matches")
    matches3 = r.get_json()["data"]
    assert matches3, "expected second match against the same found report"
    match3_id = matches3[0]["id"]
    client.post("/api/v1/auth/logout")

    # claim 1 by owner
    login(client, "owner@test.com")
    c1 = _submit_claim(client, match_id).get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    # claim 2 by owner3
    login(client, "owner3@test.com")
    c2 = _submit_claim(client, match3_id).get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    # approve and complete claim 1
    login(client, "finder@test.com")
    client.post(f"/api/v1/claims/{c1}/approve", json={})
    client.post(f"/api/v1/claims/{c1}/mark-handed-over")
    client.post("/api/v1/auth/logout")
    login(client, "owner@test.com")
    client.post(f"/api/v1/claims/{c1}/confirm-received")
    client.post("/api/v1/auth/logout")

    from app.models import Claim
    with app.app_context():
        claim2 = db.session.get(Claim, c2)
        assert claim2.verification_status.value == "REJECTED"


def test_notifications_created_on_claim_events(client, app, db):
    from app.models import Notification
    lost_id, found_id, match_id = _setup_pair(client, app)
    login(client, "owner@test.com")
    r = _submit_claim(client, match_id)
    claim_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    with app.app_context():
        # finder notified
        notes = Notification.query.filter_by(type="CLAIM_SUBMITTED").all()
        assert notes
    login(client, "finder@test.com")
    client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    client.post("/api/v1/auth/logout")
    with app.app_context():
        assert Notification.query.filter_by(type="CLAIM_APPROVED").count() >= 1


def test_audit_logs_written(client, app, db):
    from app.models import AuditLog
    lost_id, found_id, match_id = _setup_pair(client, app)
    login(client, "owner@test.com")
    claim_id = _submit_claim(client, match_id).get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    login(client, "finder@test.com")
    client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    client.post("/api/v1/auth/logout")
    with app.app_context():
        assert AuditLog.query.filter_by(action="claim_approve").count() == 1


def test_ai_never_auto_approves(client, app, db):
    """No code path may set a claim APPROVED or a report RECOVERED without a
    human action: processing a report/match must never change claim states."""
    from app.models import Claim
    from app.models.enums import ClaimStatus
    lost_id, found_id, match_id = _setup_pair(client, app)
    login(client, "owner@test.com")
    _submit_claim(client, match_id)
    client.post("/api/v1/auth/logout")

    from app.services.jobs import process_report
    with app.app_context():
        claim = Claim.query.first()
        assert claim.verification_status == ClaimStatus.PENDING
        process_report(lost_id)
        process_report(found_id)
        db.session.expire_all()
        claim = Claim.query.first()
        assert claim.verification_status == ClaimStatus.PENDING
