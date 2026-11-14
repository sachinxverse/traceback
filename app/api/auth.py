"""Authentication endpoints (Section 7.3): JWT in HttpOnly cookies with CSRF."""
import re

from flask import Blueprint, after_this_request, current_app, jsonify, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                decode_token, get_jwt, get_jwt_identity, set_access_cookies,
                                set_refresh_cookies, unset_jwt_cookies)
from werkzeug.security import generate_password_hash

from .. import ApiError
from ..extensions import db, limiter
from ..models import TokenBlocklist, User
from ..schemas import (ChangePasswordSchema, LoginSchema, RegisterSchema,
                       UpdateProfileSchema, load_json)
from ._auth import current_user
from ..models.enums import Role
from datetime import datetime

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    user = User.query.filter_by(email=email).first()
    if user is None or not user.check_password(data["password"]):
        # generic failure message (never reveal which part failed)
        raise ApiError("UNAUTHENTICATED", "Invalid email or password", status=401)
    if not user.is_active:
        raise ApiError("FORBIDDEN", "This account is deactivated", status=403)
    user.last_login_at = datetime.utcnow()
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
    from flask_jwt_extended import get_jwt_identity, jwt_required

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
    except Exception:
        access_ok = False
    try:
        verify_jwt_in_request(refresh=True)
        _blocklist_current("refresh")
        refresh_ok = True
    except Exception:
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
    except Exception:
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
