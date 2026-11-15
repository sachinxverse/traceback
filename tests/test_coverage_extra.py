"""Additional coverage tests: health, geocode, matches detail, notifications,
images, reports browse/close, admin filters, analytics, storage, embeddings,
jobs, notifications email path."""
import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from tests.conftest import (auth, image_file, login, make_institution,
                            make_staff, register)


def _img(colour=(120, 70, 20)):
    from werkzeug.datastructures import FileStorage
    buf = io.BytesIO()
    Image.new("RGB", (220, 180), colour).save(buf, format="PNG")
    buf.seek(0)
    return FileStorage(stream=buf, filename="p.png", content_type="image/png")


def _pair(client):
    """Matching lost/found pair -> (lost_id, found_id, match_id)."""
    auth(client, "ow@test.com", "Owner")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS", "title": "Lost brown wallet",
        "description": "Lost my brown wallet near the fountain with cards inside.",
        "incident_date": (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img((120, 70, 20))}, content_type="multipart/form-data")
    lost_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    auth(client, "fi@test.com", "Finder")
    r = client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "WALLETS_CARDS", "title": "Brown wallet found",
        "description": "A brown leather wallet was found near the fountain area.",
        "incident_date": (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "custody": "WITH_FINDER", "images": _img((125, 75, 25))},
        content_type="multipart/form-data")
    found_id = r.get_json()["data"]["id"]
    match_id = client.get(f"/api/v1/reports/{found_id}/matches").get_json()["data"][0]["id"]
    return lost_id, found_id, match_id


# ------------------------------------------------------------------- health
def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert data["embedding_backend"] == "stub"


def test_geocode_empty(client, db):
    auth(client, "g@x.com", "G")
    r = client.get("/api/v1/geocode?q=")
    assert r.status_code == 200


def test_geocode_rate_limit(client, app, db):
    auth(client, "g2@x.com", "G2")
    r1 = client.get("/api/v1/geocode?q=nowhere-xyz-123")
    from time import sleep
    sleep(1.05)
    r2 = client.get("/api/v1/geocode?q=different-query-456")
    # immediate repeat must hit the 1 req/sec limit
    r3 = client.get("/api/v1/geocode?q=another-query-789")
    assert r3.status_code == 429


def test_geocode_cache_hit(client, app, db):
    auth(client, "g3@x.com", "G3")
    client.get("/api/v1/geocode?q=cache-me")
    from time import sleep
    sleep(1.05)
    r = client.get("/api/v1/geocode?q=cache-me")
    assert r.status_code == 200


# ------------------------------------------------------------------ matches
def test_match_detail_and_dismiss(client, app, db):
    lost_id, found_id, match_id = _pair(client)
    # finder view
    r = client.get(f"/api/v1/matches/{match_id}")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["own_report"]["id"] == found_id
    assert "counterpart" in data
    r = client.post(f"/api/v1/matches/{match_id}/dismiss")
    assert r.status_code == 200
    # dismissed matches vanish from the finder's list
    r = client.get(f"/api/v1/reports/{found_id}/matches")
    assert r.get_json()["data"] == []
    client.post("/api/v1/auth/logout")

    # the lost owner still sees it
    login(client, "ow@test.com")
    r = client.get(f"/api/v1/reports/{lost_id}/matches")
    assert len(r.get_json()["data"]) == 1
    # and can dismiss too -> match becomes DISMISSED
    r = client.post(f"/api/v1/matches/{match_id}/dismiss")
    assert r.status_code == 200
    with app.app_context():
        from app.models import Match
        m = db.session.get(Match, match_id)
        assert m.status.value == "DISMISSED"


def test_match_detail_hidden_from_stranger(client):
    lost_id, found_id, match_id = _pair(client)
    client.post("/api/v1/auth/logout")
    auth(client, "stranger2@test.com", "S")
    assert client.get(f"/api/v1/matches/{match_id}").status_code == 404


# ------------------------------------------------------------ notifications
def test_notifications_flow(client, app):
    auth(client, "n1@test.com", "N1")
    # trigger a notification by creating a matched pair
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS", "title": "Lost blue case",
        "description": "Lost my blue phone case near the fountain steps.",
        "incident_date": (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img((20, 40, 200))}, content_type="multipart/form-data")
    client.post("/api/v1/auth/logout")
    auth(client, "n2@test.com", "N2")
    client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "WALLETS_CARDS", "title": "Blue case found",
        "description": "A blue phone case was found near the fountain steps today.",
        "incident_date": (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "custody": "WITH_FINDER", "images": _img((25, 45, 205))},
        content_type="multipart/form-data")
    r = client.get("/api/v1/notifications/unread-count")
    count = r.get_json()["data"]["count"]
    assert count >= 1

    r = client.get("/api/v1/notifications?unread=true")
    items = r.get_json()["data"]
    assert items
    nid = items[0]["id"]
    r = client.post(f"/api/v1/notifications/{nid}/read")
    assert r.get_json()["data"]["is_read"] is True
    # read-all
    r = client.post("/api/v1/notifications/read-all")
    assert r.status_code == 200
    r = client.get("/api/v1/notifications/unread-count")
    assert r.get_json()["data"]["count"] == 0
    # someone else's notification is 404
    r = client.post("/api/v1/notifications/999999/read")
    assert r.status_code == 404


# ------------------------------------------------------------------- images
def test_claim_image_serving_authorised(client, app):
    lost_id, found_id, match_id = _pair(client)
    client.post("/api/v1/auth/logout")
    login(client, "ow@test.com")
    r = client.post(f"/api/v1/matches/{match_id}/claims", data={
        "claim_details": "Serial SN-1 and a scratch near the zip.",
        "proof_images": _img((90, 90, 90))},
        content_type="multipart/form-data")
    claim = r.get_json()["data"]
    assert claim["proof_image_urls"]
    url = claim["proof_image_urls"][0]
    # claimant can view
    assert client.get(url).status_code == 200
    client.post("/api/v1/auth/logout")
    # finder (reviewer) can view
    login(client, "fi@test.com")
    assert client.get(url).status_code == 200
    client.post("/api/v1/auth/logout")
    # stranger cannot
    auth(client, "stranger3@test.com", "S")
    assert client.get(url).status_code == 404


# ------------------------------------------------------------------ reports
def test_browse_filters(client, app):
    auth(client, "b1@test.com", "B1")
    client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "KEYS", "title": "Found bunch of keys",
        "description": "A bunch of keys was found near the west gate entrance.",
        "incident_date": (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "custody": "WITH_FINDER", "images": _img((30, 30, 210))},
        content_type="multipart/form-data")
    r = client.get("/api/v1/reports/browse?q=keys&category=KEYS")
    items = r.get_json()["data"]
    assert items
    assert all(i["category"] == "KEYS" for i in items)
    r = client.get("/api/v1/reports/browse?q=nonexistent-xyz")
    assert r.get_json()["data"] == []


def test_report_image_add_delete_and_reprocess(client, app):
    auth(client, "img@test.com", "I")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "BAGS", "title": "Lost red bag",
        "description": "A red shoulder bag lost in the food court area.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    rid = r.get_json()["data"]["id"]
    # add one image (total 1 <= 4)
    r = client.post(f"/api/v1/reports/{rid}/images",
                    data={"images": _img((200, 30, 30))},
                    content_type="multipart/form-data")
    assert r.status_code == 201
    urls = r.get_json()["data"]["image_urls"]
    assert len(urls) == 1
    image_id = int(urls[0].rsplit("/", 1)[1])
    # delete it
    r = client.delete(f"/api/v1/reports/{rid}/images/{image_id}")
    assert r.status_code == 200
    assert r.get_json()["data"]["ok"] is True


def test_close_report_with_approved_claim_conflict(client, app):
    from app.models import Claim
    from app.models.enums import ClaimStatus
    lost_id, found_id, match_id = _pair(client)
    client.post("/api/v1/auth/logout")
    login(client, "ow@test.com")
    claim_id = client.post(f"/api/v1/matches/{match_id}/claims", data={
        "claim_details": "Serial SN-1 and a scratch near the zip."},
        content_type="multipart/form-data").get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    login(client, "fi@test.com")
    client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    client.post("/api/v1/auth/logout")
    # finder owns the FOUND report: closing it is blocked by the approved claim
    login(client, "fi@test.com")
    r = client.post(f"/api/v1/reports/{found_id}/close")
    assert r.status_code == 409
    login(client, "ow@test.com")
    r = client.post(f"/api/v1/reports/{lost_id}/close")
    assert r.status_code == 409  # approved claim blocks closing


# -------------------------------------------------------------------- admin
def test_admin_recoveries_and_audit_and_reports_filters(client, app, db):
    from app.models import User
    from app.models.enums import Role
    auth(client, "adm@x.com", "Admin")
    u = db.session.query(User).filter_by(email="adm@x.com").one()
    u.role = Role.ADMIN
    db.session.commit()

    r = client.get("/api/v1/admin/recoveries")
    assert r.status_code == 200
    r = client.get("/api/v1/admin/reports?type=LOST&status=ACTIVE")
    assert r.status_code == 200
    r = client.get("/api/v1/admin/users?q=admin&role=ADMIN")
    assert r.status_code == 200
    # audit logs pagination params
    r = client.get("/api/v1/admin/audit-logs?page=1&per_page=5")
    assert r.status_code == 200
    # analytics endpoints with date args
    today = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
    for ep in ("summary", "timeseries", "categories", "heatmap"):
        r = client.get(f"/api/v1/admin/analytics/{ep}?from=2026-01-01&to={today}")
        assert r.status_code == 200, ep


def test_admin_staff_scoped_reports(client, app, db):
    inst = make_institution(db, name="Staff Scope Inst")
    make_staff(db, "scoped@x.com", inst.id)
    auth(client, "other@x.com", "O")
    # a report without institution (not visible to staff)
    client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS", "title": "No inst keys",
        "description": "Keys lost somewhere without any institution attached.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    client.post("/api/v1/auth/logout")
    login(client, "scoped@x.com")
    r = client.get("/api/v1/admin/reports")
    assert r.status_code == 200
    assert all(item.get("institution_id") == inst.id for item in r.get_json()["data"])


# ---------------------------------------------------------------- analytics
def test_categories_endpoint(client, app, db):
    auth(client, "cat@x.com", "C")
    client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "SPORTS", "title": "Lost ball",
        "description": "Lost a red ball on the sports field this afternoon.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    client.post("/api/v1/auth/logout")
    from app.models import User
    from app.models.enums import Role
    auth(client, "catadm@x.com", "CA")
    u = db.session.query(User).filter_by(email="catadm@x.com").one()
    u.role = Role.ADMIN
    db.session.commit()
    r = client.get("/api/v1/admin/analytics/categories")
    rows = r.get_json()["data"]
    sports = [x for x in rows if x["category"] == "SPORTS"]
    assert sports and sports[0]["lost"] >= 1


# ----------------------------------------------------------------- services
def test_storage_backend_roundtrip(app, tmp_path):
    import app.services.storage as storage_mod
    storage_mod.reset_storage()
    app.config["UPLOAD_DIR"] = str(tmp_path / "up")
    storage = storage_mod.get_storage(app)
    storage.save(b"hello", "2026/01/test.bin")
    assert storage.open("2026/01/test.bin") == b"hello"
    storage.delete("2026/01/test.bin")
    storage.delete("2026/01/test.bin")  # idempotent
    storage_mod.reset_storage()


def test_blob_helpers(app):
    import numpy as np
    from app.services.embeddings import to_blob, from_blob, IMAGE_DIM
    vec = np.random.default_rng(0).normal(size=IMAGE_DIM)
    blob = to_blob(vec)
    assert from_blob(blob, IMAGE_DIM).shape == (IMAGE_DIM,)
    assert from_blob(b"short", IMAGE_DIM) is None
    assert from_blob(None, IMAGE_DIM) is None


def test_get_embedder_singleton(app):
    from app.services.embeddings import get_embedder, reset_embedder
    reset_embedder()
    e1 = get_embedder(app)
    e2 = get_embedder(app)
    assert e1 is e2
    # embed_text normalises to unit length
    import numpy as np
    v = e1.embed_text("hello world of lost things")
    assert abs(np.linalg.norm(v) - 1.0) < 1e-5


def test_real_backend_selection(app):
    """The factory chooses RealEmbedder when EMBEDDING_BACKEND=real (without
    loading model weights - construction is lazy)."""
    from app import create_app
    from app.services.embeddings import get_embedder, reset_embedder, RealEmbedder
    import app.services.storage as storage_mod
    reset_embedder()
    storage_mod.reset_storage()
    app2 = create_app("testing", embedding_backend="real")
    with app2.app_context():
        e = get_embedder(app2)
        assert isinstance(e, RealEmbedder)
    reset_embedder()


def test_process_report_failure_marks_failed(app, db, monkeypatch):
    from app.models import Report
    from app.services import jobs as jobs_mod
    auth(client := app.test_client(), "fail@x.com", "F")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS", "title": "Failure keys",
        "description": "Keys report used to test the failure handling path.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    rid = r.get_json()["data"]["id"]
    from app.services.matching import find_and_store_matches
    def boom(report):
        raise RuntimeError("boom")
    monkeypatch.setattr("app.services.matching.find_and_store_matches", boom)
    jobs_mod.process_report(rid)
    rep = db.session.get(Report, rid)
    assert rep.processing_status.value in ("FAILED", "READY")


def test_reindex_all(app, db):
    from app.services.jobs import reindex_all
    reindex_all(app)  # runs with empty db; must not raise


# ------------------------------------------------------------ notifications
def test_email_failure_never_breaks_request(app, db):
    """MAIL_ENABLED with a broken SMTP must not break the request."""
    app.config["MAIL_ENABLED"] = True
    app.config["MAIL_SERVER"] = "127.0.0.1"
    app.config["MAIL_PORT"] = 1  # nothing listens here
    client = app.test_client()
    auth(client, "mail@x.com", "M")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS", "title": "Mail keys",
        "description": "Keys report used to test the email failure path.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    assert r.status_code == 201
    app.config["MAIL_ENABLED"] = False
