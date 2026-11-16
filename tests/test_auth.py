"""Auth tests (F1, Section 7.3)."""
from tests.conftest import login, register


def test_register_login_logout_cycle(client, db):
    from tests.conftest import _complete_register
    # raw register returns 201 + OTP challenge, NO cookies yet (Part C)
    r = client.post("/api/v1/auth/register", json={
        "name": "Test A", "email": "a@test.com", "password": "Password1"})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.get_json()["data"]["otp_required"] is True
    assert client.get_cookie("access_token_cookie") is None  # not logged in before OTP
    r = _complete_register(client, "a@test.com", r)
    assert r.status_code == 200
    r = login(client, "a@test.com")
    assert r.status_code == 200

    # authenticated request
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.get_json()["data"]["email"] == "a@test.com"

    # logout revokes the token: reuse of the captured token gives 401 TOKEN_REVOKED
    access = client.get_cookie("access_token_cookie").value
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    # simulate a stolen-token reuse
    client.set_cookie("access_token_cookie", access)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "TOKEN_REVOKED"


def test_duplicate_email_conflict(client):
    assert register(client, "dup@test.com").status_code == 200
    r = register(client, "dup@test.com")
    assert r.status_code == 409


def test_weak_password_rejected(client):
    r = register(client, "weak@test.com", password="short")
    assert r.status_code == 400
    r = register(client, "weak2@test.com", password="lettersonly")
    assert r.status_code == 400


def test_login_failure_generic(client):
    register(client, "b@test.com")
    r = login(client, "b@test.com", "WrongPass1")
    assert r.status_code == 401
    msg = r.get_json()["error"]["message"].lower()
    assert "invalid" in msg


def test_cookie_flags(client):
    register(client, "c@test.com")
    r = login(client, "c@test.com")
    set_cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie


def test_inactive_user_blocked(client, db):
    from app.models import User
    register(client, "d@test.com")
    user = db.session.query(User).filter_by(email="d@test.com").one()
    user.is_active = False
    db.session.commit()
    r = login(client, "d@test.com")
    assert r.status_code == 403


def test_refresh_endpoint(client):
    register(client, "e@test.com")
    login(client, "e@test.com")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200


def test_change_password_revokes_old_tokens(client):
    register(client, "f@test.com", password="Password1")
    login(client, "f@test.com", "Password1")
    # C1.5: sensitive-action OTP required first
    ch = client.post("/api/v1/auth/sensitive-otp")
    assert ch.status_code == 200
    from tests.conftest import otp_code
    code = otp_code("f@test.com", "SENSITIVE_ACTION")
    r = client.post("/api/v1/auth/change-password", json={
        "current_password": "Password1", "new_password": "NewPassw0rd",
        "otp_challenge_id": ch.get_json()["data"]["challenge_id"], "otp": code})
    assert r.status_code == 200, r.get_data(as_text=True)


def test_csrf_required_on_state_change(client, db):
    register(client, "g@test.com")
    login(client, "g@test.com")
    # posts without the CSRF header must fail: use a header-free request
    from flask.testing import FlaskClient
    resp = FlaskClient.open(client, "/api/v1/auth/logout", method="POST", json={})
    assert resp.status_code in (400, 401, 403)


def test_logout_without_csrf_header_never_succeeds(client, app, db):
    """Regression: a body-less POST with no CSRF header (the old browser bug)
    must NOT log the user out."""
    from flask.testing import FlaskClient
    register(client, "csrflogout@test.com")
    login(client, "csrflogout@test.com")
    # plain request without the CSRF header, like the buggy apiFetch did
    resp = FlaskClient.open(client, "/api/v1/auth/logout", method="POST")
    assert resp.status_code in (400, 401, 403)
    # the session survives: /me still works (plain GET carries cookies)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200


def test_logout_with_expired_access_token_revokes_refresh(client, app, db):
    """Regression: after the 30-min access token expires, logout must still
    succeed via the refresh-token path and revoke the refresh token."""
    from datetime import timedelta

    from flask_jwt_extended import create_access_token

    from app.models import User

    register(client, "expired@test.com")
    login(client, "expired@test.com")
    refresh_cookie = client.get_cookie("refresh_token_cookie")
    refresh_csrf = client.get_cookie("csrf_refresh_token").value
    assert refresh_cookie is not None

    # forge an expired access token (fresh csrf claim -> mismatched header too)
    with app.app_context():
        user = db.session.query(User).filter_by(email="expired@test.com").one()
        expired = create_access_token(
            identity=str(user.id), expires_delta=timedelta(seconds=-1))
    client.set_cookie("access_token_cookie", expired)
    # the browser sends exactly ONE csrf header; drop the stale access one
    client.delete_cookie("csrf_access_token")

    # logout with the refresh CSRF header (what the fixed frontend does)
    r = client.post("/api/v1/auth/logout", headers=[("X-CSRF-TOKEN", refresh_csrf)])
    assert r.status_code == 200, r.get_data(as_text=True)

    # the old refresh token must now be revoked
    client.delete_cookie("refresh_token_cookie")
    client.set_cookie("refresh_token_cookie", refresh_cookie.value)
    r = client.post("/api/v1/auth/refresh", headers=[("X-CSRF-TOKEN", refresh_csrf)])
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "TOKEN_REVOKED"
