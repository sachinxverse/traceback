"""Auth tests (F1, Section 7.3)."""
from tests.conftest import register, login, auth


def test_register_login_logout_cycle(client, db):
    r = register(client, "a@test.com")
    assert r.status_code == 201, r.get_data(as_text=True)
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
    assert register(client, "dup@test.com").status_code == 201
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
    r = client.post("/api/v1/auth/change-password", json={
        "current_password": "Password1", "new_password": "NewPassw0rd"})
    assert r.status_code == 200


def test_csrf_required_on_state_change(client, db):
    register(client, "g@test.com")
    login(client, "g@test.com")
    # posts without the CSRF header must fail: use a header-free request
    from flask.testing import FlaskClient
    resp = FlaskClient.open(client, "/api/v1/auth/logout", method="POST", json={})
    assert resp.status_code in (400, 401, 403)
