"""Visibility / privacy tests (F14, Section 6, acceptance A8)."""
from datetime import datetime, timezone

from tests.conftest import auth, register, login


def _mkreport(client, report_type="LOST", private="My locker number is 42.",
              category="KEYS", title="Lost keys", custody=None):
    payload = {
        "report_type": report_type, "category": category,
        "title": title,
        "description": "Description text that is long enough for validation.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
        "private_details": private}
    if custody:
        payload["custody"] = custody
    r = client.post("/api/v1/reports", data=payload,
        content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["data"]


def test_private_details_hidden_from_public(client, db):
    auth(client, "a@test.com", "A")
    report = _mkreport(client)
    report_id = report["id"]

    client.post("/api/v1/auth/logout")
    auth(client, "b@test.com", "B")
    r = client.get(f"/api/v1/reports/{report_id}")
    # B has no relationship with A's report -> hidden entirely (404)
    assert r.status_code == 404


def test_private_details_visible_to_owner(client, db):
    auth(client, "a@test.com", "A")
    report = _mkreport(client, private="secret-note-xyz")
    r = client.get(f"/api/v1/reports/{report['id']}")
    assert r.status_code == 200
    assert "secret-note-xyz" in r.get_data(as_text=True)


def test_browse_never_contains_private_details(client, db):
    auth(client, "a@test.com", "A")
    _mkreport(client, report_type="FOUND", private="highly-secret", custody="WITH_FINDER")
    client.post("/api/v1/auth/logout")
    auth(client, "b@test.com", "B")
    r = client.get("/api/v1/reports/browse")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "highly-secret" not in body


def test_image_authorisation(client, db):
    auth(client, "a@test.com", "A")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "BAGS",
        "title": "Lost bag", "description": "A brown leather bag lost in the cafeteria.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img()},
        content_type="multipart/form-data")
    report = r.get_json()["data"]
    image_url = report["image_urls"][0]

    # stranger gets 404
    client.post("/api/v1/auth/logout")
    auth(client, "b@test.com", "B")
    r = client.get(image_url)
    assert r.status_code == 404


def _img():
    from werkzeug.datastructures import FileStorage
    import io
    buf = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (200, 150), (5, 5, 200)).save(buf, format="PNG")
    buf.seek(0)
    return FileStorage(stream=buf, filename="p.png", content_type="image/png")


def test_horizontal_privilege_protection(client, db):
    """User A cannot read/modify user B's reports, claims or messages."""
    auth(client, "a@test.com", "A")
    report = _mkreport(client)
    rid = report["id"]
    client.post("/api/v1/auth/logout")

    auth(client, "b@test.com", "B")
    assert client.get(f"/api/v1/reports/{rid}").status_code == 404
    assert client.patch(f"/api/v1/reports/{rid}", json={"title": "nope"}).status_code == 404
    assert client.post(f"/api/v1/reports/{rid}/close").status_code == 404
    assert client.get(f"/api/v1/reports/{rid}/matches").status_code == 404


def test_staff_scope_limited_to_own_institution(client, db):
    from tests.conftest import make_institution, make_staff
    inst1 = make_institution(db, name="Inst One")
    inst2 = make_institution(db, name="Inst Two")
    make_staff(db, "s1@x.com", inst1.id)
    make_staff(db, "s2@x.com", inst2.id)

    # user A creates a report at institution 1
    auth(client, "a@test.com", "A")
    r = client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "BAGS", "title": "Found bag",
        "description": "A bag found somewhere on the premises of inst one.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
        "institution_id": str(inst1.id), "custody": "AT_INSTITUTION"},
        content_type="multipart/form-data")
    rid = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    # staff of institution 2 must not see it
    login(client, "s2@x.com")
    assert client.get(f"/api/v1/reports/{rid}").status_code == 404
    client.post("/api/v1/auth/logout")

    # staff of institution 1 can see it (full view)
    login(client, "s1@x.com")
    r = client.get(f"/api/v1/reports/{rid}")
    assert r.status_code == 200
    assert r.get_json()["data"]["institution_id"] == inst1.id
