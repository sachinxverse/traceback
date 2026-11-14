"""Admin + analytics tests (F12, F13, Section 14, acceptance A11)."""
from datetime import datetime, timedelta

from tests.conftest import auth, login, make_institution, make_staff


def make_admin(db, email="adm@test.com"):
    from app.models import User
    from app.models.enums import Role
    u = db.session.query(User).filter_by(email=email).first()
    if u is None:
        u = User(name="Admin", email=email)
        u.set_password("Password1")
        db.session.add(u)
    u.role = Role.ADMIN
    db.session.commit()
    return u


def test_admin_requires_role(client, db):
    auth(client, "pl@x.com", "Plain")
    r = client.get("/api/v1/admin/users")
    assert r.status_code in (403, 404)


def test_admin_cannot_demote_self(client, db):
    auth(client, "selfadmin@x.com", "Self")
    admin = make_admin(db, "selfadmin@x.com")
    my_id = admin.id
    r = client.patch(f"/api/v1/admin/users/{my_id}", json={"role": "USER"})
    assert r.status_code == 409


def test_admin_user_patch_audited(client, db):
    from app.models import AuditLog
    auth(client, "a1@x.com", "A1")
    auth(client, "target@x.com", "Target")
    admin = make_admin(db, "a1@x.com")
    from app.models import User
    target = db.session.query(User).filter_by(email="target@x.com").one()
    client.post("/api/v1/auth/logout")
    login(client, "a1@x.com")
    r = client.patch(f"/api/v1/admin/users/{target.id}", json={"role": "STAFF"})
    assert r.status_code == 200
    assert AuditLog.query.filter_by(action="user_update").count() == 1


def test_summary_on_seeded_like_data(client, app, db):
    make_admin(db, "sum@x.com")
    inst = make_institution(db, name="Sum Inst")
    auth(client, "u@x.com", "U")
    for i in range(3):
        client.post("/api/v1/reports", data={
            "report_type": "LOST" if i % 2 == 0 else "FOUND",
            "category": "KEYS", "title": f"Keys report {i}",
            "description": f"Description of keys report number {i} for testing.",
            "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "institution_id": str(inst.id),
            **({"custody": "AT_INSTITUTION"} if i % 2 else {})},
            content_type="multipart/form-data")
    login(client, "sum@x.com")
    r = client.get("/api/v1/admin/analytics/summary")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["total_reports"] >= 3
    assert data["lost_reports"] >= 1
    assert data["found_reports"] >= 1
    assert "potential_match_rate" in data


def test_timeseries_range(client, db):
    make_admin(db, "ts@x.com")
    login(client, "ts@x.com")
    r = client.get("/api/v1/admin/analytics/timeseries?from=2026-01-01&to=2026-01-07")
    data = r.get_json()["data"]
    assert data["interval"] == "day"
    assert len(data["points"]) == 7  # each day in the range
    assert all("lost" in p and "found" in p for p in data["points"])


def test_heatmap_privacy_threshold(client, app, db):
    make_admin(db, "hm@x.com")
    auth(client, "h@x.com", "H")
    # one report at a unique location -> must be hidden
    client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS", "title": "Lonely keys",
        "description": "One single report at a unique location for privacy.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "latitude": "55.5", "longitude": "55.5"},
        content_type="multipart/form-data")
    login(client, "hm@x.com")
    r = client.get("/api/v1/admin/analytics/heatmap")
    cells = r.get_json()["data"]
    assert all(c["count"] >= 2 for c in cells)


def test_report_moderation_remove_restore(client, app, db):
    make_admin(db, "mod@x.com")
    auth(client, "victim@x.com", "V")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS", "title": "To remove",
        "description": "This report will be removed by the moderator soon.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    rid = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    login(client, "mod@x.com")
    r = client.post(f"/api/v1/admin/reports/{rid}/remove", json={"reason": "Spam content"})
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "REMOVED"
    r = client.post(f"/api/v1/admin/reports/{rid}/restore")
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "ACTIVE"


def test_audit_log_filters(client, app, db):
    make_admin(db, "aud@x.com")
    auth(client, "actor@x.com", "Actor")
    admin = make_admin(db, "aud@x.com")
    from app.models import User
    from app.services.audit import log_action
    actor = db.session.query(User).filter_by(email="actor@x.com").one()
    log_action("test_action", actor=actor, target_type="user", target_id=actor.id)
    db.session.commit()
    client.post("/api/v1/auth/logout")
    login(client, "aud@x.com")
    r = client.get("/api/v1/admin/audit-logs?action=test_action")
    assert r.status_code == 200
    assert r.get_json()["data"]
    r = client.get("/api/v1/admin/audit-logs?action=nonexistent_action")
    assert r.get_json()["data"] == []
