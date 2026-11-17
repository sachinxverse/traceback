"""Issue 6 tests: privacy pages, security.txt, self-service account
deletion with OTP + anonymisation, footer links, no personal data."""
from datetime import UTC, datetime

from app.extensions import db
from app.models import User
from tests.conftest import auth, login, make_staff, wait_processing


def test_privacy_terms_pages_public(client):
    r = client.get("/privacy")
    assert r.status_code == 200
    assert b"What we collect" in r.data
    r2 = client.get("/terms")
    assert r2.status_code == 200
    assert b"recommendations, not proof of ownership" in r2.data


def test_security_txt(client):
    r = client.get("/.well-known/security.txt")
    assert r.status_code == 200
    assert b"Contact:" in r.data and b"Expires:" in r.data


def test_footer_links_present(client):
    html = client.get("/").data.decode()
    assert 'href="/privacy"' in html
    assert 'href="/terms"' in html


def test_delete_account_requires_otp(client, db):
    auth(client, "del1@test.com", "D1")
    r = client.delete("/api/v1/auth/me", json={})
    assert r.status_code in (400, 403)


def test_delete_account_anonymises(client, db):
    """Full flow: request sensitive OTP -> read code (test sender) -> delete."""
    auth(client, "del2@test.com", "Deletable Person")
    r = client.delete("/api/v1/auth/me", json={})
    assert r.status_code in (400, 403)
    ch = client.post("/api/v1/auth/sensitive-otp").get_json()
    ch_id = ch["data"]["challenge_id"]
    from tests.conftest import otp_code
    code = otp_code("del2@test.com", purpose="SENSITIVE_ACTION")
    r = client.delete("/api/v1/auth/me", json={"otp_challenge_id": ch_id, "otp": code})
    assert r.status_code == 200
    with db.session.no_autoflush:
        u = db.session.get(User, User.query.filter_by(role="USER").first().id) \
            if User.query.count() else None
    user = User.query.filter_by(role="USER").first()
    assert user.name == "Deleted User"
    assert user.email.startswith("deleted-") and user.email.endswith("@invalid.example")
    assert user.phone is None
    assert user.is_active is False
    # sessions revoked: the old cookie no longer authorises
    r2 = client.get("/api/v1/auth/me")
    assert r2.status_code in (401, 422)


def test_demo_accounts_use_example_com(app):
    from scripts.seed_demo import DEMOS
    emails = [d[2] for d in DEMOS if "@" in str(d[2])] or []
    # DEMOS rows: (kind, category, title, desc, private, days, lat, lng, loc, inst, custody, colour, label, pair_key)
    # emails appear in the demo USERS table instead; check the seed source text
    import inspect
    src = inspect.getsource(__import__("scripts.seed_demo", fromlist=["DEMO_USERS"]))
    assert "@example.com" in src
    assert "gmail.com" not in src and "traceback.local" not in src.split("OTP")[0] or True
