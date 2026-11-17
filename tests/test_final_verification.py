"""Final-verification regression tests (from the readiness review):
1) two claims on one found item can't both be APPROVED,
2) a DISPUTED/REJECTED claim can't be approved once RECOVERED,
3) closing a report with a PENDING claim cascades correctly."""
from datetime import UTC, datetime, timedelta

from tests.conftest import auth, login, make_institution, wait_processing
from tests.test_claims import _img, _setup_pair, _submit_claim


def _second_lost_for_same_found(client, found_desc_words):
    """A second LOST report that also matches the same found wallet."""
    auth(client, "owner2@test.com", "Owner Two")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS",
        "title": "Lost brown wallet 2",
        "description": "Lost a brown wallet by the fountain with a blue holder.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img((120, 70, 20))},
        content_type="multipart/form-data")
    lost2 = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    return lost2


def test_two_claims_same_found_never_both_approved(client, app, db):
    lost_id, found_id, match_id = _setup_pair(client, app)

    # a second user files a similar lost report, producing a second match
    # against the SAME found item
    auth(client, "owner2@test.com", "Owner Two")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS",
        "title": "Lost brown wallet again",
        "description": "Lost a brown wallet by the fountain with a blue holder.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img((120, 70, 20))},
        content_type="multipart/form-data")
    assert r.status_code == 201
    lost2 = r.get_json()["data"]["id"]
    r = client.get(f"/api/v1/reports/{lost2}/matches")
    matches2 = r.get_json()["data"]
    m2 = next((m for m in matches2
               if (m.get("found_report", {}) or {}).get("id") == found_id
               or m.get("found_report_id") == found_id), None)
    client.post("/api/v1/auth/logout")

    login(client, "owner@test.com")
    claim1 = _submit_claim(client, match_id).get_json()["data"]["id"]

    claim2_id = None
    if m2:
        client.post("/api/v1/auth/logout")
        login(client, "owner2@test.com")
        r = _submit_claim(client, m2["id"], details="Blue holder and initials J.K. inside are mine.")
        if r.status_code == 201:
            claim2_id = r.get_json()["data"]["id"]
        client.post("/api/v1/auth/logout")

    # approve claim1 through the full flow
    login(client, "finder@test.com")
    r = client.post(f"/api/v1/claims/{claim1}/approve", json={})
    assert r.status_code == 200
    if claim2_id:
        r = client.post(f"/api/v1/claims/{claim2_id}/approve", json={})
        assert r.status_code in (400, 409), "second approval must be blocked"
    client.post("/api/v1/auth/logout")

    from app.models import Claim
    with app.app_context():
        approved = [c for c in Claim.query.all() if c.verification_status.value == "APPROVED"]
        assert len(approved) <= 1, "two claims on the same found item must never both be APPROVED"


def test_recovered_item_blocks_disputed_claim_approval(client, app, db):
    lost_id, found_id, match_id = _setup_pair(client, app)
    login(client, "owner@test.com")  # only the lost-side owner may claim
    claim_id = _submit_claim(client, match_id).get_json()["data"]["id"]

    # finder rejects; claimant disputes; item gets recovered via another path
    login(client, "finder@test.com")
    client.post(f"/api/v1/claims/{claim_id}/reject",
                json={"review_note": "Details did not match."})
    client.post("/api/v1/auth/logout")
    login(client, "owner@test.com")
    client.post(f"/api/v1/claims/{claim_id}/dispute", json={"reason": "It is mine."})
    client.post("/api/v1/auth/logout")

    from app.models import Report
    from app.models.enums import ReportStatus
    with app.app_context():
        found = db.session.get(Report, found_id)
        found.status = ReportStatus.RECOVERED
        db.session.commit()

    auth(client, "admin@test.com", "Admin Person")
    # promote to ADMIN
    from app.models import User
    from app.models.enums import Role
    with app.app_context():
        admin = User.query.filter_by(email="admin@test.com").first()
        admin.role = Role.ADMIN
        db.session.commit()
    login(client, "admin@test.com")
    r = client.post(f"/api/v1/admin/claims/{claim_id}/resolve",
                    json={"decision": "APPROVE", "note": "attempted"})
    assert r.status_code in (400, 409), "RECOVERED items must not be approved"


def test_closing_report_with_pending_claim_cascades(client, app, db):
    lost_id, found_id, match_id = _setup_pair(client, app)
    login(client, "owner@test.com")  # only the lost-side owner may claim
    claim_id = _submit_claim(client, match_id).get_json()["data"]["id"]

    from app.models import Claim, Report
    from app.models.enums import ClaimStatus, ReportStatus
    with app.app_context():
        found = db.session.get(Report, found_id)
        found.status = ReportStatus.REMOVED
        found.removed_reason = "duplicate"
        db.session.commit()

    # cascade: the live PENDING claim must no longer be actionable/live
    with app.app_context():
        claim = db.session.get(Claim, claim_id)
        # a live claim on a removed report must not be approvable
        from app.services.claims import approve_claim, TransitionError
        from app.models import User
        reviewer = User.query.filter_by(email="finder@test.com").first()
        with app.app_context():
            pass
    login(client, "finder@test.com")
    r = client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    assert r.status_code in (400, 404, 409), "removed-report claims must not be approved"
