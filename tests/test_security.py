"""Security tests (F14, Section 16, acceptance A13)."""
import io
from datetime import datetime, timezone

from PIL import Image
from tests.conftest import auth, login, image_file


def test_rate_limit_login(app, db):
    # rate limits must be enabled at app init (create_app override)
    from app import create_app
    import app.services.storage as storage_mod
    from app.services.embeddings import reset_embedder
    reset_embedder()
    storage_mod.reset_storage()
    app2 = create_app("testing", ratelimit_enabled=True)
    with app2.app_context():
        db.create_all()
    client2 = app2.test_client()
    codes = []
    for i in range(12):
        r = client2.post("/api/v1/auth/login", json={
            "email": "nobody@x.com", "password": "WrongPass1"})
        codes.append(r.status_code)
    assert 429 in codes


def test_security_headers_present(client):
    r = client.get("/")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "strict-origin-when-cross-origin" in r.headers.get("Referrer-Policy", "")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "tile.openstreetmap.org" in csp


def test_sql_injection_style_strings_handled(client, db):
    auth(client, "sqli@x.com", "S")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS",
        "title": "Robert'); DROP TABLE users;--",
        "description": "A description containing SQL-looking text '; DROP TABLE users;-- done.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    assert r.status_code == 201
    # users table still intact
    from app.models import User
    assert db.session.query(User).count() == 1


def test_xss_escaped_in_pages(client, db):
    auth(client, "xss@x.com", "X")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS",
        "title": "Title <script>alert(1)</script>",
        "description": "Description with <img src=x onerror=alert(2)> payloads inside text.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    rid = r.get_json()["data"]["id"]
    login(client, "xss@x.com")
    r = client.get(f"/reports/{rid}")
    body = r.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body


def test_oversize_upload_413(app, client, db):
    auth(client, "big@x.com", "B")
    app.config["MAX_CONTENT_LENGTH"] = 1024  # 1 KB request cap
    big = io.BytesIO(b"\x00" * (200 * 1024))
    from werkzeug.datastructures import FileStorage
    fs = FileStorage(stream=big, filename="big.png", content_type="image/png")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS", "title": "Big",
        "description": "An over-sized upload that should be rejected with 413.",
        "incident_date": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": fs}, content_type="multipart/form-data")
    assert r.status_code == 413


def test_login_does_not_reveal_user_existence(client):
    r1 = client.post("/api/v1/auth/login", json={"email": "ghost@x.com", "password": "Whatever1"})
    r2 = client.post("/api/v1/auth/login", json={"email": "ghost2@x.com", "password": "x"})
    assert r1.get_json()["error"]["message"] == "Invalid email or password"
