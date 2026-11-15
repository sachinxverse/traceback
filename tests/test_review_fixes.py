"""Regression tests for the independent review findings (sections A..C).

Each test fails before the corresponding fix and passes after.
"""
from datetime import datetime, timedelta, timezone

import pytest
from tests.conftest import auth, login

from app.extensions import db
from app.models import Claim, Match, Notification, Report, User
from app.models.enums import ClaimStatus, MatchStatus, ReportStatus, Role


def make_admin(db, email="admin@traceback.local"):
    u = db.session.query(User).filter_by(email=email).first()
    if u is None:
        u = User(name="Admin", email=email)
        u.set_password("Password1")
        db.session.add(u)
    u.role = Role.ADMIN
    db.session.commit()
    return u


def _ensure_match(db, lost_id, found_id):
    """Deterministically create the SUGGESTED match between the two reports."""
    m = db.session.query(Match).filter_by(lost_report_id=lost_id,
                                          found_report_id=found_id).first()
    if m is None:
        m = Match(lost_report_id=lost_id, found_report_id=found_id,
                  total_score=0.9, status=MatchStatus.SUGGESTED)
        db.session.add(m)
        db.session.commit()
    return m


def _img(colour=(120, 70, 20)):
    import io
    from PIL import Image
    from werkzeug.datastructures import FileStorage
    buf = io.BytesIO()
    Image.new("RGB", (220, 180), colour).save(buf, format="PNG")
    buf.seek(0)
    return FileStorage(stream=buf, filename="p.png", content_type="image/png")


def _pair(client, lost_email="owner@test.com", found_email="finder@test.com",
          desc=None):
    """Matching LOST/FOUND pair; returns (lost_id, found_id, match_id)."""
    desc = desc or "Lost my brown wallet near the fountain with cards inside."
    auth(client, lost_email, "Owner")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS",
        "title": "Lost brown wallet",
        "description": desc,
        "incident_date": (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "private_details": "Initials J.K.",
        "images": _img()}, content_type="multipart/form-data")
    lost_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    auth(client, found_email, "Finder")
    r = client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "WALLETS_CARDS",
        "title": "Brown wallet found",
        "description": "A brown leather wallet was found near the fountain area.",
        "incident_date": (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "custody": "WITH_FINDER",
        "images": _img()}, content_type="multipart/form-data")
    found_id = r.get_json()["data"]["id"]
    match_id = client.get(f"/api/v1/reports/{found_id}/matches").get_json()["data"][0]["id"]
    return lost_id, found_id, match_id


def _lost_report(client, email, name, title, desc, days_ago=3):
    auth(client, email, name)
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS",
        "title": title, "description": desc,
        "incident_date": (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img()}, content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    lost_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    return lost_id


def _claim(client, match_id, details="Serial number SN-99123 and a deep scratch."):
    r = client.post(f"/api/v1/matches/{match_id}/claims", data={
        "claim_details": details}, content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["data"]["id"]


# ----------------------------------------------------------------- A1
def test_a1_only_one_approved_claim_per_found_report(client, app, db):
    make_admin(db)
    lost_id, found_id, match_id = _pair(client)
    carol_lost_id = _lost_report(client, "carol@test.com", "Carol",
                                 "Lost wallet",
                                 "I lost my brown wallet with cards near the fountain.")
    with app.app_context():
        carol_match_id = _ensure_match(db, carol_lost_id, found_id).id

    login(client, "owner@test.com")
    claim1 = _claim(client, match_id)
    client.post("/api/v1/auth/logout")
    login(client, "carol@test.com")
    claim2 = _claim(client, carol_match_id, details="Mine, has a blue card.")
    client.post("/api/v1/auth/logout")

    login(client, "finder@test.com")
    r = client.post(f"/api/v1/claims/{claim1}/approve", json={})
    assert r.status_code == 200
    r = client.post(f"/api/v1/claims/{claim2}/approve", json={})
    assert r.status_code == 409, r.get_data(as_text=True)
    assert "already approved" in r.get_json()["error"]["message"]

    # after claim 1 is withdrawn, claim 2 can be approved
    client.post("/api/v1/auth/logout")
    login(client, "owner@test.com")
    r = client.post(f"/api/v1/claims/{claim1}/withdraw", json={})
    assert r.status_code == 200
    client.post("/api/v1/auth/logout")
    login(client, "finder@test.com")
    r = client.post(f"/api/v1/claims/{claim2}/approve", json={})
    assert r.status_code == 200, r.get_data(as_text=True)


def test_a1_race_two_approvals_cannot_both_succeed(client, app, db):
    lost_id, found_id, match_id = _pair(client)
    carol_lost_id = _lost_report(client, "carol@test.com", "Carol",
                                 "Lost wallet 2",
                                 "Brown wallet lost with cards near the fountain.")
    with app.app_context():
        carol_match_id = _ensure_match(db, carol_lost_id, found_id).id

    login(client, "carol@test.com")
    claim2 = _claim(client, carol_match_id)
    client.post("/api/v1/auth/logout")
    login(client, "owner@test.com")
    claim1 = _claim(client, match_id)
    client.post("/api/v1/auth/logout")

    # simulate interleaved service-level approvals against the same session
    with app.app_context():
        from app.services import claims as cs
        finder = db.session.query(User).filter_by(email="finder@test.com").one()
        c1 = db.session.get(Claim, claim1)
        cs.approve_claim(c1, finder)
        c2 = db.session.get(Claim, claim2)
        with pytest.raises(cs.TransitionError):
            cs.approve_claim(c2, finder)
        c2 = db.session.get(Claim, claim2)
        assert c2.verification_status == ClaimStatus.PENDING


# ----------------------------------------------------------------- A2
def _completed_item_with_second_claim(client, app, db):
    """Claim 1 completes; a second claim is auto-rejected; its claimant
    tries to dispute it. Returns (claim1_id, claim2_id, found_id, dispute_resp)."""
    lost_id, found_id, match_id = _pair(client, "owner2@test.com", "finder2@test.com")
    login(client, "owner2@test.com")
    claim1 = _claim(client, match_id)
    client.post("/api/v1/auth/logout")

    carol_lost_id = _lost_report(client, "carol2@test.com", "Carol",
                                 "Another lost wallet",
                                 "My brown wallet with cards went missing by the fountain.",
                                 days_ago=2)
    with app.app_context():
        carol_match_id = _ensure_match(db, carol_lost_id, found_id).id
    login(client, "carol2@test.com")
    claim2 = _claim(client, carol_match_id, details="Blue card holder inside mine.")
    client.post("/api/v1/auth/logout")

    login(client, "finder2@test.com")
    client.post(f"/api/v1/claims/{claim1}/approve", json={})
    client.post(f"/api/v1/claims/{claim1}/mark-handed-over", json={})
    client.post("/api/v1/auth/logout")
    login(client, "owner2@test.com")
    r = client.post(f"/api/v1/claims/{claim1}/confirm-received", json={})
    assert r.status_code == 200
    client.post("/api/v1/auth/logout")

    # claim 2 was auto-rejected; carol disputes it
    login(client, "carol2@test.com")
    r = client.post(f"/api/v1/claims/{claim2}/dispute",
                    json={"reason": "It is mine, not theirs"})
    return claim1, claim2, found_id, r


def test_a2_dispute_on_recovered_item_returns_409(client, app, db):
    claim1, claim2, found_id, r = _completed_item_with_second_claim(client, app, db)
    assert r.status_code == 409, r.get_data(as_text=True)
    assert "recovered" in r.get_json()["error"]["message"].lower()
    with app.app_context():
        assert db.session.get(Claim, claim2).verification_status == ClaimStatus.REJECTED


def test_a2_admin_approve_on_recovered_item_returns_409(client, app, db):
    make_admin(db)
    claim1, claim2, found_id, r = _completed_item_with_second_claim(client, app, db)
    login(client, "admin@traceback.local")
    r = client.post(f"/api/v1/admin/claims/{claim2}/resolve",
                    json={"decision": "APPROVE"})
    assert r.status_code == 409, r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Claim, claim2).verification_status == ClaimStatus.REJECTED
        assert db.session.get(Report, found_id).status == ReportStatus.RECOVERED


def test_a2_dispute_then_admin_approve_restores_lock(client, app, db):
    """Dispute on a still-ACTIVE item, then admin approve: found and lost
    reports go back to CLAIM_PENDING and the match to CLAIMED."""
    make_admin(db)
    lost_id, found_id, match_id = _pair(client, "owner3@test.com", "finder3@test.com")
    login(client, "owner3@test.com")
    claim = _claim(client, match_id)
    client.post("/api/v1/auth/logout")
    login(client, "finder3@test.com")
    client.post(f"/api/v1/claims/{claim}/reject",
                json={"review_note": "Proof insufficient"})
    client.post("/api/v1/auth/logout")
    login(client, "owner3@test.com")
    r = client.post(f"/api/v1/claims/{claim}/dispute",
                    json={"reason": "The proof was valid"})
    assert r.status_code == 200, r.get_data(as_text=True)
    # while disputed the item is locked (A5)
    with app.app_context():
        assert db.session.get(Report, found_id).status == ReportStatus.CLAIM_PENDING
        assert db.session.get(Match, match_id).status == MatchStatus.CLAIMED
    client.post("/api/v1/auth/logout")
    login(client, "admin@traceback.local")
    r = client.post(f"/api/v1/admin/claims/{claim}/resolve",
                    json={"decision": "APPROVE", "note": "Claim is valid"})
    assert r.status_code == 200, r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Claim, claim).verification_status == ClaimStatus.APPROVED
        assert db.session.get(Report, found_id).status == ReportStatus.CLAIM_PENDING
        assert db.session.get(Report, lost_id).status == ReportStatus.CLAIM_PENDING
        assert db.session.get(Match, match_id).status == MatchStatus.CLAIMED


# ----------------------------------------------------------------- A3
def test_a3_close_with_pending_claim_rejects_and_notifies(client, app, db):
    lost_id, found_id, match_id = _pair(client)
    login(client, "owner@test.com")
    claim = _claim(client, match_id)
    client.post("/api/v1/auth/logout")
    login(client, "finder@test.com")
    r = client.post(f"/api/v1/reports/{found_id}/close", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    with app.app_context():
        c = db.session.get(Claim, claim)
        assert c.verification_status == ClaimStatus.REJECTED
        assert "closed" in (c.review_note or "").lower()
        assert db.session.get(Report, lost_id).status == ReportStatus.ACTIVE
        assert db.session.get(Match, match_id).status == MatchStatus.EXPIRED
        notes = Notification.query.filter_by(user_id=c.claimant_id).all()
        assert any("closed" in (n.message or "").lower() for n in notes)


def test_a3_admin_remove_with_pending_claim_rejects_and_notifies(client, app, db):
    make_admin(db)
    lost_id, found_id, match_id = _pair(client)
    login(client, "owner@test.com")
    claim = _claim(client, match_id)
    client.post("/api/v1/auth/logout")
    login(client, "admin@traceback.local")
    r = client.post(f"/api/v1/admin/reports/{found_id}/remove",
                    json={"reason": "Prohibited item"})
    assert r.status_code == 200, r.get_data(as_text=True)
    with app.app_context():
        c = db.session.get(Claim, claim)
        assert c.verification_status == ClaimStatus.REJECTED
        assert db.session.get(Report, lost_id).status == ReportStatus.ACTIVE


def test_a3_dispute_after_close_is_blocked(client, app, db):
    lost_id, found_id, match_id = _pair(client)
    login(client, "owner@test.com")
    claim = _claim(client, match_id)
    client.post("/api/v1/auth/logout")
    login(client, "finder@test.com")
    client.post(f"/api/v1/reports/{found_id}/close", json={})
    client.post("/api/v1/auth/logout")
    login(client, "owner@test.com")
    r = client.post(f"/api/v1/claims/{claim}/dispute",
                    json={"reason": "It really is mine"})
    assert r.status_code == 409, r.get_data(as_text=True)


# ----------------------------------------------------------------- A4
def test_a4_rejection_notification_uses_match_id(client, app, db):
    lost_id, found_id, match_id = _pair(client)
    login(client, "owner@test.com")
    claim = _claim(client, match_id)
    client.post("/api/v1/auth/logout")
    login(client, "finder@test.com")
    client.post(f"/api/v1/claims/{claim}/reject",
                json={"review_note": "Proof insufficient"})
    with app.app_context():
        c = db.session.get(Claim, claim)
        notes = Notification.query.filter_by(related_claim_id=claim).all()
        assert notes, "claimant should be notified"
        assert all(n.related_match_id == c.match_id for n in notes)


def test_a4_audit_logs_record_from_and_to(client, app, db):
    from app.models import AuditLog
    make_admin(db)
    lost_id, found_id, match_id = _pair(client)
    login(client, "owner@test.com")
    claim = _claim(client, match_id)
    client.post("/api/v1/auth/logout")
    login(client, "finder@test.com")
    client.post(f"/api/v1/claims/{claim}/approve", json={})
    client.post(f"/api/v1/claims/{claim}/mark-handed-over", json={})
    client.post("/api/v1/auth/logout")
    login(client, "owner@test.com")
    r = client.post(f"/api/v1/claims/{claim}/confirm-received", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    with app.app_context():
        logs = AuditLog.query.filter_by(target_type="claim",
                                        target_id=claim).order_by(AuditLog.id).all()
        by_action = {l.action: l for l in logs}
        assert by_action["claim_approve"].details["from"] == "PENDING"
        assert by_action["claim_approve"].details["to"] == "APPROVED"
        assert by_action["recovery_completed"].details["from"] == "APPROVED"
        assert by_action["recovery_completed"].details["to"] == "COMPLETED"
        for log in by_action.values():
            assert "from" in (log.details or {}), log.action
            assert "to" in (log.details or {}), log.action


# ----------------------------------------------------------------- A5
def test_a5_dispute_locks_item_against_competing_claims(client, app, db):
    make_admin(db)
    lost_id, found_id, match_id = _pair(client, "owner4@test.com", "finder4@test.com")
    login(client, "owner4@test.com")
    claim = _claim(client, match_id)
    client.post("/api/v1/auth/logout")
    login(client, "finder4@test.com")
    client.post(f"/api/v1/claims/{claim}/reject",
                json={"review_note": "Proof insufficient"})
    client.post("/api/v1/auth/logout")
    login(client, "owner4@test.com")
    r = client.post(f"/api/v1/claims/{claim}/dispute",
                    json={"reason": "The proof was valid"})
    assert r.status_code == 200
    client.post("/api/v1/auth/logout")

    # a third user must NOT be able to claim while the dispute is open
    eve_lost_id = _lost_report(client, "eve4@test.com", "Eve",
                               "Eve lost wallet",
                               "Brown wallet lost by the fountain with cards inside.",
                               days_ago=4)
    with app.app_context():
        eve_match_id = _ensure_match(db, eve_lost_id, found_id).id
    login(client, "eve4@test.com")
    r = client.post(f"/api/v1/matches/{eve_match_id}/claims", data={
        "claim_details": "Also mine"}, content_type="multipart/form-data")
    # the submit is blocked while the dispute holds the item
    assert r.status_code in (404, 409), r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Report, found_id).status == ReportStatus.CLAIM_PENDING
        assert db.session.get(Match, match_id).status == MatchStatus.CLAIMED

    # admin rejects the dispute -> item is released again
    login(client, "admin@traceback.local")
    r = client.post(f"/api/v1/admin/claims/{claim}/resolve",
                    json={"decision": "REJECT", "note": "Dispute not upheld"})
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Report, found_id).status == ReportStatus.ACTIVE
        assert db.session.get(Match, match_id).status == MatchStatus.SUGGESTED


# ----------------------------------------------------------------- B2
def test_b2_production_validate_rejects_placeholders_and_short_keys():
    import os
    from config import ProductionConfig, get_config

    env = {
        "SECRET_KEY": "please-change-this-secret",
        "JWT_SECRET_KEY": "x" * 40,
        "DATABASE_URL": "postgresql+psycopg2://u:p@localhost/db",
    }
    old = {k: os.environ.get(k) for k in env}
    try:
        os.environ.update(env)
        with pytest.raises(RuntimeError, match="weak/placeholder"):
            ProductionConfig.validate()

        os.environ["SECRET_KEY"] = "a" * 40
        os.environ["JWT_SECRET_KEY"] = "short"
        with pytest.raises(RuntimeError, match="weak/placeholder"):
            ProductionConfig.validate()

        os.environ["JWT_SECRET_KEY"] = "b" * 40
        ProductionConfig.validate()  # strong keys -> passes

        # strong keys but missing from env entirely -> still required
        os.environ.pop("SECRET_KEY")
        with pytest.raises(RuntimeError, match="Missing required"):
            ProductionConfig.validate()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_b2_compose_has_no_insecure_defaults():
    import re
    text = open("docker-compose.yml", encoding="utf-8").read()
    assert "${SECRET_KEY:?set" in text
    assert "${JWT_SECRET_KEY:?set" in text
    assert "${POSTGRES_PASSWORD:?set" in text
    assert ":-please-change" not in text
    assert "POSTGRES_PASSWORD: traceback" not in text
    assert 'COOKIE_SECURE: "false"' not in text
    # db service must not publish ports
    db_block = text.split("\n  db:\n")[1]
    assert not re.search(r"^\s+ports:", db_block, re.M)


def test_b2_dockerfile_separates_torch_index():
    text = open("Dockerfile", encoding="utf-8").read()
    assert "-r requirements.txt \\" in text  # first command without torch index
    assert "ARG INSTALL_AI=true" in text
    # the torch index line applies only to torch, never to requirements.txt
    torch_line = [l for l in text.splitlines() if "download.pytorch.org" in l][0]
    assert "requirements.txt" not in torch_line
    assert "|| echo" in text


# ----------------------------------------------------------------- B3
def test_b3_migration_upgrade_and_check(tmp_path, monkeypatch):
    """A fresh empty database can be migrated with `flask db upgrade` and
    `flask db check` reports no differences."""
    import subprocess
    import sys
    import os
    py = sys.executable
    dbfile = tmp_path / "mig.db"
    env = dict(os.environ)
    env["FLASK_APP"] = "wsgi.py"
    env["DATABASE_URL"] = f"sqlite:///{dbfile.as_posix()}"
    up = subprocess.run([py, "-m", "flask", "db", "upgrade"], env=env,
                        capture_output=True, text=True, timeout=180,
                        cwd=os.path.abspath(os.path.dirname(__file__) + "/.."))
    assert up.returncode == 0, up.stdout + up.stderr
    assert "Running upgrade" in (up.stdout + up.stderr)
    assert "initial schema" in (up.stdout + up.stderr)
    chk = subprocess.run([py, "-m", "flask", "db", "check"], env=env,
                         capture_output=True, text=True, timeout=180,
                         cwd=os.path.abspath(os.path.dirname(__file__) + "/.."))
    assert chk.returncode == 0, chk.stdout + chk.stderr
    assert "No new upgrade operations detected" in chk.stdout


def test_b3_no_leftover_debug_files():
    import glob
    leftovers = [p for p in glob.glob("tests/test_zdebug*")]
    assert leftovers == []


# ----------------------------------------------------------------- C1
def _seed_claims(db, n=120):
    """Create n claims for one claimant without going through the API."""
    from app.models import Match, Report, User
    claimant = db.session.query(User).filter_by(email="pager@test.com").first()
    if claimant is None:
        claimant = User(name="Pager", email="pager@test.com")
        claimant.set_password("Password1")
        db.session.add(claimant)
        finder = db.session.query(User).filter_by(email="pagerf@test.com").first()
        if finder is None:
            finder = User(name="PagerF", email="pagerf@test.com")
            finder.set_password("Password1")
            db.session.add(finder)
        db.session.commit()
    finder = db.session.query(User).filter_by(email="pagerf@test.com").one()
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    lost = Report(user_id=claimant.id, report_type="LOST", category="WALLETS_CARDS",
                  title="Lost wallet", description="desc", status="ACTIVE",
                  incident_date=now - timedelta(days=2))
    found = Report(user_id=finder.id, report_type="FOUND", category="WALLETS_CARDS",
                   title="Found wallet", description="desc", status="ACTIVE",
                   custody="WITH_FINDER", incident_date=now - timedelta(days=1))
    db.session.add_all([lost, found])
    db.session.commit()
    match = Match(lost_report_id=lost.id, found_report_id=found.id,
                  total_score=0.9, status="SUGGESTED")
    db.session.add(match)
    db.session.commit()
    claims = [Claim(match_id=match.id, claimant_id=claimant.id, report_id=found.id,
                    claim_details=f"claim {i}", verification_status="PENDING")
              for i in range(n)]
    db.session.add_all(claims)
    db.session.commit()
    return claimant.id, n


def test_c1_claims_mine_paginates_and_caps(client, app, db):
    _seed_claims(db)
    login(client, "pager@test.com")
    r = client.get("/api/v1/claims/mine?per_page=50&page=2")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["data"]) == 50
    assert body["meta"]["page"] == 2
    assert body["meta"]["total"] == 120
    assert body["meta"]["pages"] == 3
    # per_page is capped at 100
    r = client.get("/api/v1/claims/mine?per_page=500")
    assert r.get_json()["meta"]["per_page"] == 100


def test_c1_query_count_constant_across_pages(client, app, db):
    """N+1 check: page 1 and page 3 execute the same number of SQL queries."""
    from sqlalchemy import event
    from app.extensions import db as _db
    _seed_claims(db)
    login(client, "pager@test.com")
    counts = {}
    for page in (1, 3):
        n = [0]

        def _count(*a, **k):
            n[0] += 1
        with app.test_request_context():
            pass
        ev = event.listen(_db.engine, "before_cursor_execute", _count)
        try:
            r = client.get(f"/api/v1/claims/mine?per_page=10&page={page}")
            assert r.status_code == 200
        finally:
            event.remove(_db.engine, "before_cursor_execute", _count)
        counts[page] = n[0]
    assert counts[1] == counts[3], counts


def test_c1_incoming_and_admin_lists_paginate(client, app, db):
    from tests.test_review_fixes import make_admin
    make_admin(db)
    _seed_claims(db)
    login(client, "pagerf@test.com")
    r = client.get("/api/v1/claims/incoming?per_page=25")
    body = r.get_json()
    assert r.status_code == 200
    assert len(body["data"]) == 25
    assert body["meta"]["total"] == 120
    login(client, "admin@traceback.local")
    r = client.get("/api/v1/admin/claims?status=PENDING&per_page=30")
    body = r.get_json()
    assert r.status_code == 200
    assert len(body["data"]) == 30
    assert body["meta"]["total"] == 120
    r = client.get("/api/v1/admin/audit-logs?per_page=5&page=2")
    assert r.status_code == 200 and r.get_json()["meta"]["page"] == 2


# ----------------------------------------------------------------- C2
def test_c2_labels_contain_positives_and_negatives():
    """The seeded labels must include negatives (review C2: FPR was
    meaningless with 0 negatives) and hard same-category distractors."""
    import csv
    rows = list(csv.DictReader(open("scripts/labels.csv", encoding="utf-8")))
    pos = [r for r in rows if r["is_same_item"].strip() == "1"]
    neg = [r for r in rows if r["is_same_item"].strip() == "0"]
    assert len(pos) >= 5
    assert len(neg) >= 8
    # hard negatives: same lost id as a positive (same-category distractor)
    pos_lost = {r["lost_id"] for r in pos}
    hard = [r for r in neg if r["lost_id"] in pos_lost]
    assert hard, "no hard same-category distractors in labels.csv"


def test_c2_stub_embedder_separates_different_colours():
    """Regression: the white label box used to dominate the stub image cosine
    so different-coloured items scored ~0.98. Identical images must still
    score 1.0; different border colours must fall below the image band."""
    import io
    import numpy as np
    from PIL import Image
    from app.services.embeddings import StubEmbedder

    def img(colour):
        im = Image.new("RGB", (320, 320), colour)
        from PIL import ImageDraw
        d = ImageDraw.Draw(im)
        d.rectangle([64, 128, 256, 192], fill="white")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()

    e = StubEmbedder()
    v1 = e.embed_image(img((25, 25, 112)))   # midnightblue
    v2 = e.embed_image(img((25, 25, 112)))   # identical
    v3 = e.embed_image(img((192, 192, 192)))  # silver
    cos_same = float(np.dot(v1, v2))
    cos_diff = float(np.dot(v1, v3))
    assert cos_same > 0.999, cos_same
    assert cos_diff < 0.55, cos_diff


def test_c2_evaluation_reports_both_labels(tmp_path, monkeypatch):
    """The evaluation harness handles positive AND negative pairs."""
    import csv
    import subprocess
    import sys
    import os
    labels = tmp_path / "labels.csv"
    with open(labels, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lost_id", "found_id", "is_same_item"])
        w.writerow([999991, 999992, 0])  # nonexistent ids are skipped safely
    env = dict(os.environ, APP_CONFIG="testing", EMBEDDING_BACKEND="stub")
    r = subprocess.run([sys.executable, "scripts/evaluate_matching.py",
                        str(labels)], env=env, capture_output=True, text=True,
                       timeout=180, cwd=os.path.abspath(os.path.dirname(__file__) + "/.."))
    assert r.returncode == 0, r.stderr
    assert "negative: 0" in r.stdout  # missing reports are skipped
