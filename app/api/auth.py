"""Authentication endpoints (Section 7.3): JWT in HttpOnly cookies with CSRF."""
import re
from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies,
)

from .. import ApiError
from ..extensions import db, limiter
from ..models import TokenBlocklist, User
from ..models.enums import Role
from ..schemas import (
    ChangePasswordSchema,
    LoginSchema,
    RegisterSchema,
    UpdateProfileSchema,
    load_json,
)
from ._auth import current_user

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# C4: progressive lockout after repeated failed logins (in-memory, per-app).
# 5 failures within 15 minutes lock the (email, ip) key for 15 minutes.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_LOCKOUT_SECONDS = 15 * 60


def _login_attempts():
    return current_app.extensions.setdefault("login_attempts", {})


def _login_gate_key(email):
    return f"{email}|{request.remote_addr or 'local'}"


def _check_login_lockout(email):
    entry = _login_attempts().get(_login_gate_key(email))
    if not entry:
        return
    failures, last_fail = entry
    now = datetime.now(UTC).replace(tzinfo=None).timestamp()
    if now - last_fail > LOGIN_WINDOW_SECONDS:
        _login_attempts().pop(_login_gate_key(email), None)
        return
    if failures >= LOGIN_MAX_FAILURES:
        retry_after = int(LOGIN_LOCKOUT_SECONDS - (now - last_fail))
        raise ApiError("RATE_LIMITED",
                       "Too many failed login attempts. Try again later.",
                       status=429,
                       details={"retry_after_seconds": max(retry_after, 1)})


def _record_login_failure(email):
    key = _login_gate_key(email)
    attempts = _login_attempts()
    failures, last_fail = attempts.get(key, (0, 0.0))
    now = datetime.now(UTC).replace(tzinfo=None).timestamp()
    if now - last_fail > LOGIN_WINDOW_SECONDS:
        failures = 0
    attempts[key] = (failures + 1, now)


def _record_login_success(email):
    _login_attempts().pop(_login_gate_key(email), None)


def _normalize_email(email):
    return (email or "").strip().lower()


@auth_bp.post("/register")
@limiter.limit("5 per minute")
def register():
    data = load_json(RegisterSchema(), request.get_json(silent=True) or {})
    email = _normalize_email(data["email"])
    if not EMAIL_RE.match(email):
        raise ApiError("VALIDATION_ERROR", "Invalid email", details={"email": ["Invalid email address"]})
    if User.query.filter_by(email=email).first():
        raise ApiError("CONFLICT", "An account with this email already exists", status=409)
    user = User(name=data["name"].strip(), email=email,
                phone=data.get("phone"), role=Role.USER)
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    resp = jsonify({"data": _user_payload(user)})
    _set_auth_cookies(resp, user)
    return resp, 201


@auth_bp.post("/login")
@limiter.limit("10 per minute")
def login():
    data = load_json(LoginSchema(), request.get_json(silent=True) or {})
    email = _normalize_email(data["email"])
    _check_login_lockout(email)
    user = User.query.filter_by(email=email).first()
    if user is None or not user.check_password(data["password"]):
        # generic failure message (never reveal which part failed)
        _record_login_failure(email)
        raise ApiError("UNAUTHENTICATED", "Invalid email or password", status=401)
    _record_login_success(email)
    if not user.is_active:
        raise ApiError("FORBIDDEN", "This account is deactivated", status=403)
    user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.commit()
    resp = jsonify({"data": _user_payload(user)})
    _set_auth_cookies(resp, user)
    return resp


def _set_auth_cookies(resp, user):
    access = create_access_token(identity=str(user.id))
    refresh = create_refresh_token(identity=str(user.id))
    set_access_cookies(resp, access)
    set_refresh_cookies(resp, refresh)


@auth_bp.post("/refresh")
def refresh():
    from flask_jwt_extended import jwt_required

    @jwt_required(refresh=True)
    def do_refresh():
        user = db.session.get(User, int(get_jwt_identity()))
        if user is None or not user.is_active:
            raise ApiError("UNAUTHENTICATED", "User not found or inactive", status=401)
        resp = jsonify({"data": _user_payload(user)})
        set_access_cookies(resp, create_access_token(identity=str(user.id)))
        return resp
    return do_refresh()


@auth_bp.post("/logout")
def logout():
    """Revoke current access and refresh tokens; clear cookies. Requires a
    valid (access or refresh) token; CSRF double-submit applies."""
    resp = jsonify({"data": {"ok": True}})
    access_ok = refresh_ok = False
    try:
        verify_jwt_in_request()
        _blocklist_current("access")
        access_ok = True
    except ApiError:
        access_ok = False
    except Exception:  # noqa: BLE001 - token simply not revocable here
        access_ok = False
    try:
        verify_jwt_in_request(refresh=True)
        _blocklist_current("refresh")
        refresh_ok = True
    except Exception:  # noqa: BLE001 - token simply not revocable here
        refresh_ok = False
    if not (access_ok or refresh_ok):
        raise ApiError("UNAUTHENTICATED", "Missing authorization token", status=401)
    unset_jwt_cookies(resp)
    return resp


def verify_jwt_in_request(*args, **kwargs):
    from flask_jwt_extended import verify_jwt_in_request as _v
    return _v(*args, **kwargs)


def _blocklist_current(token_type):
    from flask_jwt_extended import get_jwt as _gj
    payload = _gj()
    entry = TokenBlocklist(jti=payload["jti"], token_type=token_type,
                           user_id=payload.get("sub") and int(payload["sub"]))
    db.session.add(entry)
    db.session.commit()


@auth_bp.get("/me")
def me():
    user = current_user()
    return jsonify({"data": _user_payload(user)})


@auth_bp.patch("/me")
def update_me():
    user = current_user()
    data = load_json(UpdateProfileSchema(), request.get_json(silent=True) or {})
    if "name" in data:
        user.name = data["name"].strip()
    if "phone" in data:
        user.phone = data["phone"]
    db.session.commit()
    return jsonify({"data": _user_payload(user)})


@auth_bp.post("/change-password")
@limiter.limit("5 per minute")
def change_password():
    user = current_user()
    data = load_json(ChangePasswordSchema(), request.get_json(silent=True) or {})
    if not user.check_password(data["current_password"]):
        raise ApiError("UNAUTHENTICATED", "Current password is incorrect", status=401)
    user.set_password(data["new_password"])
    db.session.commit()
    resp = jsonify({"data": {"ok": True}})
    # revoke existing tokens
    try:
        verify_jwt_in_request()
        _blocklist_current("access")
    except Exception:  # noqa: BLE001, S110 - best-effort revocation
        pass
    unset_jwt_cookies(resp)
    # issue a fresh session
    _set_auth_cookies(resp, user)
    return resp


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role.value,
        "institution": {"id": user.institution.id, "name": user.institution.name}
        if user.institution else None,
    }
