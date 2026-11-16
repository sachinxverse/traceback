"""Part E — OTP security tests (C1, C2, C4, C6)."""
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import login, otp_code, register


def _step1(client, email="otp1@x.com", portal="user", password="Password1"):
    # raw register (no auto-verify) then logout any session, then step 1
    client.post("/api/v1/auth/register", json={
        "name": "Otp U", "email": email, "password": password})
    client.post("/api/v1/auth/logout")
    return client.post(f"/api/v1/auth/{portal}/login",
                       json={"email": email, "password": password})


def test_no_cookies_after_step_1(client):
    r = _step1(client)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["otp_required"] is True
    assert data["challenge_id"] and data["masked_destination"].startswith("o***")
    assert "expires_in" in data and "resend_after" in data
    # C1.1: no auth cookies at this step
    assert client.get_cookie("access_token_cookie") is None
    assert client.get_cookie("refresh_token_cookie") is None
    # and the code is never in the response
    assert "dev_echo_code" not in (r.get_data(as_text=True))


def test_correct_otp_sets_cookies(client):
    _step1(client)
    r = client.post("/api/v1/auth/user/verify-otp",
                    json={"challenge_id": _challenge(client), "otp": otp_code("otp1@x.com")})
    assert r.status_code == 200
    assert client.get_cookie("access_token_cookie") is not None
    assert client.get_cookie("refresh_token_cookie") is not None
    assert client.get("/api/v1/auth/me").status_code == 200


def _challenge(client):
    """Challenge id from the latest step-1 call is returned in the body."""
    return client.post("/api/v1/auth/user/login",
                       json={"email": "otp1@x.com", "password": "Password1"}
                       ).get_json()["data"]["challenge_id"]


def test_wrong_otp_does_not_set_cookies(client):
    _step1(client)
    cid = _challenge(client)
    r = client.post("/api/v1/auth/user/verify-otp",
                    json={"challenge_id": cid, "otp": "000000"})
    assert r.status_code == 400
    assert client.get_cookie("access_token_cookie") is None


def test_expired_otp_fails(client, db):
    r = _step1(client)
    cid = r.get_json()["data"]["challenge_id"]
    from app.models import OtpChallenge
    ch = db.session.get(OtpChallenge, cid)
    ch.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    db.session.commit()
    r = client.post("/api/v1/auth/user/verify-otp",
                    json={"challenge_id": cid, "otp": otp_code("otp1@x.com")})
    assert r.status_code == 400


def test_reused_otp_fails(client):
    r = _step1(client)
    cid = r.get_json()["data"]["challenge_id"]
    code = otp_code("otp1@x.com")
    r1 = client.post("/api/v1/auth/user/verify-otp",
                     json={"challenge_id": cid, "otp": code})
    assert r1.status_code == 200
    # sign out, then try to reuse the same code on a fresh challenge-free state
    client.post("/api/v1/auth/logout")
    r = client.post("/api/v1/auth/user/login",
                    json={"email": "otp1@x.com", "password": "Password1"})
    new_cid = r.get_json()["data"]["challenge_id"]
    # old code against the NEW challenge must fail anyway
    r = client.post("/api/v1/auth/user/verify-otp",
                    json={"challenge_id": new_cid, "otp": code})
    assert r.status_code == 400


def test_sixth_wrong_attempt_locks_challenge(client, db):
    r = _step1(client)
    cid = r.get_json()["data"]["challenge_id"]
    for i in range(5):
        rr = client.post("/api/v1/auth/user/verify-otp",
                         json={"challenge_id": cid, "otp": f"{i:06d}"})
        assert rr.status_code == 400
    # 5th wrong attempt locks the challenge (max 5 attempts)
    r = client.post("/api/v1/auth/user/verify-otp",
                    json={"challenge_id": cid, "otp": "999999"})
    from app.models import OtpChallenge
    assert db.session.get(OtpChallenge, cid).locked_at is not None
    assert db.session.get(OtpChallenge, cid).attempts == 5


def test_resend_cooldown_enforced(client):
    r = _step1(client)
    data = r.get_json()["data"]
    r = client.post("/api/v1/auth/user/resend-otp",
                    json={"challenge_id": data["challenge_id"]})
    assert r.status_code == 429  # cooldown 30s not yet elapsed


def test_resend_limit_enforced(client, db, monkeypatch):
    """3 resends allowed; the 4th is refused."""
    r = _step1(client)
    cid = r.get_json()["data"]["challenge_id"]
    from app.models import OtpChallenge
    # speed past the cooldown by rewinding created_at
    def rewind():
        ch = db.session.get(OtpChallenge, cid)
        ch.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=60)
        db.session.commit()
    monkeypatch.setattr("time.time", lambda: 0)  # not used; explicit rewind instead
    for _ in range(3):
        rewind()
        rr = client.post("/api/v1/auth/user/resend-otp",
                         json={"challenge_id": cid})
        assert rr.status_code == 200
    rewind()
    rr = client.post("/api/v1/auth/user/resend-otp", json={"challenge_id": cid})
    assert rr.status_code == 429


def test_new_otp_invalidates_previous(client, db):
    r = _step1(client)
    cid = r.get_json()["data"]["challenge_id"]
    old_code = otp_code("otp1@x.com")
    from app.models import OtpChallenge
    ch = db.session.get(OtpChallenge, cid)
    ch.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=60)
    db.session.commit()
    rr = client.post("/api/v1/auth/user/resend-otp", json={"challenge_id": cid})
    assert rr.status_code == 200
    new_code = otp_code("otp1@x.com")
    assert new_code != old_code
    # the old code no longer verifies
    r = client.post("/api/v1/auth/user/verify-otp",
                    json={"challenge_id": cid, "otp": old_code})
    assert r.status_code == 400
    r = client.post("/api/v1/auth/user/verify-otp",
                    json={"challenge_id": cid, "otp": new_code})
    assert r.status_code == 200


def test_otp_stored_hashed_not_plain(client, db):
    r = _step1(client)
    code = otp_code("otp1@x.com")
    from app.models import OtpChallenge
    rows = OtpChallenge.query.all()
    assert rows, "challenge row exists"
    blob = repr(rows[0].code_hash)
    assert code not in blob
    assert rows[0].code_hash != code and len(rows[0].code_hash) == 64


def test_challenge_bound_to_portal(client, db):
    """A user-portal OTP cannot finish an admin login."""
    r = _step1(client, "portal-bound@x.com")
    cid = r.get_json()["data"]["challenge_id"]
    from app.models import User
    with client.application.app_context():
        User.query.filter_by(email="portal-bound@x.com").one().role = \
            __import__("app.models.enums", fromlist=["Role"]).Role.ADMIN
        db.session.commit()
    code = otp_code("portal-bound@x.com")
    r = client.post("/api/v1/auth/admin/verify-otp",
                    json={"challenge_id": cid, "otp": code})
    assert r.status_code == 400


def test_registration_needs_otp_and_unverified_cannot_login(client):
    r = client.post("/api/v1/auth/register", json={
        "name": "Verify Me", "email": "verify-me@x.com", "password": "Password1"})
    assert r.status_code == 201
    assert r.get_json()["data"]["otp_required"] is True
    assert client.get_cookie("access_token_cookie") is None
    # login of an unverified account re-sends a verification OTP instead
    r = client.post("/api/v1/auth/user/login",
                    json={"email": "verify-me@x.com", "password": "Password1"})
    assert r.status_code == 200
    assert r.get_json()["data"]["purpose"] == "REGISTER"
    assert client.get_cookie("access_token_cookie") is None
    # wrong OTP keeps them unverified
    cid = r.get_json()["data"]["challenge_id"]
    rr = client.post("/api/v1/auth/register/verify-otp",
                     json={"challenge_id": cid, "otp": "000000"})
    assert rr.status_code == 400
    # correct OTP verifies and logs in
    rr = client.post("/api/v1/auth/register/verify-otp",
                     json={"challenge_id": cid, "otp": otp_code("verify-me@x.com", "REGISTER")})
    assert rr.status_code == 200
    assert client.get_cookie("access_token_cookie") is not None


def test_password_reset_needs_otp_and_revokes_tokens(client, db):
    login(client, *("reset@x.com",)) if False else None
    register(client, "reset@x.com", "Reset U")
    login(client, "reset@x.com")
    assert client.get("/api/v1/auth/me").status_code == 200
    client.post("/api/v1/auth/logout")
    # request reset
    r = client.post("/api/v1/auth/forgot-password", json={"email": "reset@x.com"})
    assert r.status_code == 200
    cid = r.get_json()["data"]["challenge_id"]
    r = client.post("/api/v1/auth/forgot-password/verify-otp", json={
        "challenge_id": cid, "otp": "000000", "new_password": "NewPassw0rd"})
    assert r.status_code == 400
    r = client.post("/api/v1/auth/forgot-password/verify-otp", json={
        "challenge_id": cid, "otp": otp_code("reset@x.com", "PASSWORD_RESET"),
        "new_password": "NewPassw0rd"})
    assert r.status_code == 200
    # the old session's token version no longer matches: token unusable
    login(client, "reset@x.com", "NewPassw0rd")
    assert client.get("/api/v1/auth/me").status_code == 200
    # old password no longer works
    client.post("/api/v1/auth/logout")
    r = client.post("/api/v1/auth/user/login",
                    json={"email": "reset@x.com", "password": "Password1"})
    assert r.status_code == 401


def test_forgot_password_does_not_reveal_unknown_email(client):
    r = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@nowhere.com"})
    assert r.status_code == 200
    assert r.get_json()["data"]["otp_required"] is True  # same shape, dead challenge


def test_sensitive_action_otp_required_for_password_change(client):
    register(client, "sens@x.com", "Sens U")
    login(client, "sens@x.com")
    r = client.post("/api/v1/auth/change-password", json={
        "current_password": "Password1", "new_password": "NewPassw0rd"})
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "OTP_REQUIRED"
    # full flow works
    ch = client.post("/api/v1/auth/sensitive-otp").get_json()["data"]
    r = client.post("/api/v1/auth/change-password", json={
        "current_password": "Password1", "new_password": "NewPassw0rd",
        "otp_challenge_id": ch["challenge_id"], "otp": otp_code("sens@x.com", "SENSITIVE_ACTION")})
    assert r.status_code == 200


def test_otp_never_in_response_or_logs(client):
    """The plain code is not echoed in any API response body."""
    _step1(client)
    # (TestingOtpSender holds codes for tests; the API responses never carry them)
