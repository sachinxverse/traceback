"""Authentication endpoints (Part B + Part C).

Three separate login portals (user / staff / admin), each a two-step flow:
1. credentials  -> creates an OTP challenge (NO cookies are set here);
2. verify OTP   -> sets the JWT cookies with a `portal` claim.

Every place that sets auth cookies is below in `_finish_login` /
`_register_finish` / `refresh` (refresh of an already-OTP-verified session).
Tests in tests/test_no_bypass.py hook `set_access_cookies` to prove no other
path can set cookies.
"""
import re
from datetime import UTC, datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies,
    verify_jwt_in_request,
)

from .. import ApiError
from ..extensions import db, limiter
from ..models import OtpChallenge, TokenBlocklist, User
from ..models.enums import Role
from ..schemas import (
    ChangePasswordSchema,
    LoginSchema,
    RegisterSchema,
    UpdateProfileSchema,
    load_json,
)
from ..services import audit as audit_svc
from ..services import otp as otp_svc
from ._auth import current_user

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# B1.2: identical generic message for wrong password, unknown account and
# wrong-portal credentials — portals never reveal which accounts exist.
GENERIC_CREDENTIALS = "Invalid credentials"

PORTAL_ROLES = {"user": Role.USER, "staff": Role.STAFF, "admin": Role.ADMIN}


def _normalize_email(email):
    return (email or "").strip().lower()


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


# --------------------------------------------------------------- portal step 1
def _portal_login(portal: str):
    """Shared service behind POST /auth/{portal}/login (step 1: credentials)."""
    data = load_json(LoginSchema(), request.get_json(silent=True) or {})
    email = _normalize_email(data["email"])
    user = User.query.filter_by(email=email).first()
    if user is not None and user.locked_until and user.locked_until > _now():
        retry = int((user.locked_until - _now()).total_seconds())
        raise ApiError("RATE_LIMITED",
                       "Too many failed login attempts. Try again later.",
                       status=429, details={"retry_after_seconds": max(retry, 1)})
    wrong = (user is None or not user.check_password(data["password"]))
    if wrong:
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            limit = current_app.config.get("LOGIN_MAX_FAILURES", 5)
            if user.failed_login_count >= limit:
                user.locked_until = _now() + timedelta(
                    seconds=current_app.config.get("LOGIN_LOCKOUT_SECONDS", 900))
                audit_svc.log_action("login_locked", actor=user, target_type="user",
                                     target_id=user.id,
                                     details={"failed_login_count": user.failed_login_count})
                _email_lockout_alert(user)
            db.session.commit()
        raise ApiError("UNAUTHENTICATED", GENERIC_CREDENTIALS, status=401)
    # B1.2: valid credentials but wrong portal -> same generic message + audit.
    if user.role != PORTAL_ROLES[portal]:
        audit_svc.log_action("login_wrong_portal", actor=user, target_type="user",
                             target_id=user.id, details={"attempted_portal": portal})
        db.session.commit()
        raise ApiError("UNAUTHENTICATED", GENERIC_CREDENTIALS, status=401)
    if not user.is_active:
        raise ApiError("FORBIDDEN", "This account is deactivated", status=403)
    # C1.4: unverified accounts cannot log in — re-send a verification OTP.
    if not user.email_verified:
        payload = otp_svc.create_challenge(user, portal, "REGISTER")
        return jsonify({"data": {**payload, "purpose": "REGISTER"}}), 200
    payload = otp_svc.create_challenge(user, portal, "LOGIN")
    return jsonify({"data": payload}), 200


def _email_lockout_alert(user):
    """Best-effort email alert to the account owner after lockout (C2)."""
    if not current_app.config.get("MAIL_ENABLED"):
        return
    try:
        from flask_mail import Message
        from ..extensions import mail
        mail.send(Message(
            subject="Your TRACEBACK account was locked",
            recipients=[user.email],
            body=("There were too many failed sign-in attempts on your TRACEBACK "
                  "account, so it has been temporarily locked. If this was not "
                  "you, change your password after the lockout ends.")))
    except Exception:  # noqa: BLE001 - alerting must never break the request
        pass


# --------------------------------------------------------------- portal step 2
def _portal_verify(portal: str):
    """Shared service behind POST /auth/{portal}/verify-otp (step 2)."""
    body = request.get_json(silent=True) or {}
    challenge_id = str(body.get("challenge_id") or "")
    code = str(body.get("otp") or "")
    # only LOGIN / REGISTER challenges may complete a login (prevents using a
    # PASSWORD_RESET or SENSITIVE_ACTION challenge to sign in without a password)
    challenge = db.session.get(OtpChallenge, challenge_id or "")
    if challenge is not None and challenge.purpose not in ("LOGIN", "REGISTER"):
        raise ApiError("OTP_INVALID", "Incorrect or expired code.", status=400)
    user = otp_svc.verify(challenge_id, code, portal,
                          challenge.purpose if challenge else "LOGIN")
    if challenge and challenge.purpose == "REGISTER":
        user.email_verified = True
    return _finish_login(user, portal)[0]


def _portal_resend(portal: str):
    body = request.get_json(silent=True) or {}
    challenge = db.session.get(OtpChallenge, str(body.get("challenge_id") or ""))
    if challenge is None or challenge.portal != portal:
        raise ApiError("OTP_INVALID", "Incorrect or expired code.", status=400)
    payload = otp_svc.resend(challenge)
    return jsonify({"data": payload}), 200


# ------------------------------------------------------------------- sessions
def _revoke_incoming_session():
    """B1.4: blocklist the browser's existing token jti before a new login."""
    try:
        verify_jwt_in_request()
        payload = get_jwt()
        db.session.add(TokenBlocklist(jti=payload["jti"], token_type="access",
                                      user_id=int(payload["sub"])))
    except Exception:  # noqa: BLE001 - no incoming session is fine
        pass
    try:
        verify_jwt_in_request(refresh=True)
        payload = get_jwt()
        db.session.add(TokenBlocklist(jti=payload["jti"], token_type="refresh",
                                      user_id=int(payload["sub"])))
    except Exception:  # noqa: BLE001
        pass


def _token_claims(user: User, portal: str) -> dict:
    return {"portal": portal, "tv": user.token_version or 0}


def _finish_login(user: User, portal: str):
    """The ONLY paths that set auth cookies: OTP-verified login and register
    verify, plus /auth/refresh for an already-verified session."""
    _revoke_incoming_session()
    user.last_login_at = _now()
    user.failed_login_count = 0
    db.session.commit()
    claims = _token_claims(user, portal)
    access = create_access_token(identity=str(user.id), additional_claims=claims)
    refresh = create_refresh_token(identity=str(user.id), additional_claims=claims)
    resp = jsonify({"data": _user_payload(user)})
    resp.status_code = 200
    set_access_cookies(resp, access)
    set_refresh_cookies(resp, refresh)
    audit_svc.log_action("login", actor=user, target_type="user", target_id=user.id,
                         details={"portal": portal})
    db.session.commit()
    return resp, _user_payload(user)


# -------------------------------------------------------------------- routes
@auth_bp.post("/register")
@limiter.limit("5 per minute")
def register():
    """Creates the account unverified and sends a verification OTP; the user
    is NOT logged in (C1.4)."""
    data = load_json(RegisterSchema(), request.get_json(silent=True) or {})
    email = _normalize_email(data["email"])
    if not EMAIL_RE.match(email):
        raise ApiError("VALIDATION_ERROR", "Invalid email", details={"email": ["Invalid email address"]})
    if User.query.filter_by(email=email).first():
        raise ApiError("CONFLICT", "An account with this email already exists", status=409)
    user = User(name=data["name"].strip(), email=email,
                phone=data.get("phone"), role=Role.USER,
                email_verified=False)
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()
    payload = otp_svc.create_challenge(user, "user", "REGISTER")
    audit_svc.log_action("register", actor=user, target_type="user", target_id=user.id)
    db.session.commit()
    return jsonify({"data": {**payload, "email": user.email}}), 201


@auth_bp.post("/register/verify-otp")
@limiter.limit("10 per minute")
def register_verify():
    """Sets email_verified and logs the user in (cookies set here only)."""
    body = request.get_json(silent=True) or {}
    challenge_id = str(body.get("challenge_id") or "")
    code = str(body.get("otp") or "")
    user = otp_svc.verify(challenge_id, code, "user", "REGISTER")
    user.email_verified = True
    resp, _payload = _finish_login(user, "user")
    return resp


# ------------------------------------------------------------ user portal
@auth_bp.post("/user/login")
@limiter.limit("10 per minute")
def user_login():
    return _portal_login("user")


@auth_bp.post("/user/verify-otp")
@limiter.limit("10 per minute")
def user_verify():
    return _portal_verify("user")


@auth_bp.post("/user/resend-otp")
@limiter.limit("10 per minute")
def user_resend():
    return _portal_resend("user")


# ------------------------------------------------------------ staff portal
@auth_bp.post("/staff/login")
@limiter.limit("10 per minute")
def staff_login():
    return _portal_login("staff")


@auth_bp.post("/staff/verify-otp")
@limiter.limit("10 per minute")
def staff_verify():
    return _portal_verify("staff")


@auth_bp.post("/staff/resend-otp")
@limiter.limit("10 per minute")
def staff_resend():
    return _portal_resend("staff")


# ------------------------------------------------------------ admin portal
@auth_bp.post("/admin/login")
@limiter.limit("10 per minute")
def admin_login():
    return _portal_login("admin")


@auth_bp.post("/admin/verify-otp")
@limiter.limit("10 per minute")
def admin_verify():
    return _portal_verify("admin")


@auth_bp.post("/admin/resend-otp")
@limiter.limit("10 per minute")
def admin_resend():
    return _portal_resend("admin")


# ------------------------------------------------------------------ refresh
@auth_bp.post("/refresh")
def refresh():
    """Refresh an already-OTP-verified session (keeps the portal claim)."""
    @jwt_required(refresh=True)
    def do_refresh():
        payload = get_jwt()
        portal = payload.get("portal", "user")
        user = db.session.get(User, int(get_jwt_identity()))
        if user is None or not user.is_active:
            raise ApiError("UNAUTHENTICATED", "User not found or inactive", status=401)
        if (payload.get("tv") or 0) != (user.token_version or 0):
            raise ApiError("UNAUTHENTICATED", "Session expired; log in again", status=401)
        resp = jsonify({"data": _user_payload(user)})
        set_access_cookies(resp, create_access_token(
            identity=str(user.id), additional_claims=_token_claims(user, portal)))
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
    except Exception:  # noqa: BLE001 - token simply not revocable here
        access_ok = False
    try:
        verify_jwt_in_request(refresh=True)
        _blocklist_current("refresh")
        refresh_ok = True
    except Exception:  # noqa: BLE001
        refresh_ok = False
    if not (access_ok or refresh_ok):
        raise ApiError("UNAUTHENTICATED", "Missing authorization token", status=401)
    unset_jwt_cookies(resp)
    return resp


def _blocklist_current(token_type):
    payload = get_jwt()
    entry = TokenBlocklist(jti=payload["jti"], token_type=token_type,
                           user_id=payload.get("sub") and int(payload["sub"]))
    db.session.add(entry)
    db.session.commit()


@auth_bp.get("/me")
def me():
    user = current_user()
    return jsonify({"data": _user_payload(user)})


@auth_bp.delete("/me")
def delete_me():
    """Self-service account deletion (Issue 6): requires a fresh
    SENSITIVE_ACTION OTP. Anonymises the personal data while keeping the
    community's reports (ownership anonymised) and the audit trail.
    """
    import re
    from flask_jwt_extended import get_jwt
    user = current_user()
    data = request.get_json(silent=True) or {}
    _require_sensitive_otp(user, data)

    # anonymise: nothing that identifies the person survives in the users row
    user.name = "Deleted User"
    user.email = f"deleted-{user.id}@invalid.example"
    user.phone = None
    user.is_active = False
    user.token_version = (user.token_version or 0) + 1  # revoke every session
    audit_svc.log_action("account_deleted", actor=user, target_type="user",
                         target_id=user.id,
                         details={"mode": "self-service-anonymise"})
    jti = get_jwt().get("jti")
    if jti:
        from ..models import TokenBlocklist
        db.session.add(TokenBlocklist(jti=jti, token_type="access", user_id=user.id))
    db.session.commit()
    return jsonify({"data": {"deleted": True,
                             "note": "Personal data anonymised; reports remain without owner identity."}})


@auth_bp.patch("/me")
def update_me():
    user = current_user()
    data = load_json(UpdateProfileSchema(), request.get_json(silent=True) or {})
    # C1.5: changing phone (or name) requires a fresh SENSITIVE_ACTION OTP.
    if "phone" in data and data["phone"] != (user.phone or ""):
        _require_sensitive_otp(user, data)
    if "name" in data:
        user.name = data["name"].strip()
    if "phone" in data:
        user.phone = data["phone"]
    db.session.commit()
    return jsonify({"data": _user_payload(user)})


def _require_sensitive_otp(user, data):
    challenge_id = str(data.get("otp_challenge_id") or "")
    code = str(data.get("otp") or "")
    if not challenge_id or not code:
        raise ApiError("OTP_REQUIRED",
                       "Confirm this change with the code sent to your email.",
                       status=403,
                       details={"otp_required": True,
                                "masked_destination": otp_svc.masked_destination(user)})
    otp_svc.verify(challenge_id, code, _portal_of(user), "SENSITIVE_ACTION")


def _portal_of(user: User) -> str:
    try:
        return get_jwt().get("portal", "user")
    except Exception:  # noqa: BLE001
        return "user"


@auth_bp.post("/sensitive-otp")
@limiter.limit("5 per minute")
def sensitive_otp():
    """Send an OTP for a sensitive action (password/e-mail/phone change)."""
    user = current_user()
    payload = otp_svc.create_challenge(user, _portal_of(user), "SENSITIVE_ACTION")
    return jsonify({"data": payload}), 200


@auth_bp.post("/change-password")
@limiter.limit("5 per minute")
def change_password():
    """C1.5: requires a fresh SENSITIVE_ACTION OTP in the request body."""
    user = current_user()
    data = load_json(ChangePasswordSchema(), request.get_json(silent=True) or {})
    if not user.check_password(data["current_password"]):
        raise ApiError("UNAUTHENTICATED", "Current password is incorrect", status=401)
    _require_sensitive_otp(user, data)
    user.set_password(data["new_password"])
    user.last_password_change_at = _now()
    # C1.5: revoke all existing tokens after a password change
    user.token_version = (user.token_version or 0) + 1
    db.session.commit()
    resp = jsonify({"data": {"ok": True}})
    try:
        verify_jwt_in_request()
        _blocklist_current("access")
    except Exception:  # noqa: BLE001, S110 - best-effort revocation
        pass
    unset_jwt_cookies(resp)
    # issue a fresh session for the current device
    portal = _portal_of(user)
    resp2 = jsonify({"data": _user_payload(user)})
    set_access_cookies(resp2, create_access_token(
        identity=str(user.id), additional_claims=_token_claims(user, portal)))
    set_refresh_cookies(resp2, create_refresh_token(
        identity=str(user.id), additional_claims=_token_claims(user, portal)))
    audit_svc.log_action("password_change", actor=user, target_type="user",
                         target_id=user.id)
    db.session.commit()
    return resp2


# --------------------------------------------------------- forgot password
@auth_bp.post("/forgot-password")
@limiter.limit("5 per minute")
def forgot_password():
    """Request a PASSWORD_RESET OTP. Response is identical whether or not the
    email exists (C2: never reveal which emails exist)."""
    body = request.get_json(silent=True) or {}
    email = _normalize_email(body.get("email") or "")
    if EMAIL_RE.match(email):
        user = User.query.filter_by(email=email).first()
        if user is not None and user.is_active:
            payload = otp_svc.create_challenge(user, "user", "PASSWORD_RESET")
            audit_svc.log_action("password_reset_requested", actor=user,
                                 target_type="user", target_id=user.id)
            db.session.commit()
            return jsonify({"data": {**payload, "email": email}}), 200
    # same response shape for unknown emails
    return jsonify({"data": {
        "otp_required": True,
        "challenge_id": "00000000000000000000000000000000",
        "masked_destination": (email[:1] + "***@" + email.partition("@")[2]) if EMAIL_RE.match(email) else "***",
        "expires_in": current_app.config.get("OTP_EXPIRES_SECONDS", 300),
        "resend_after": current_app.config.get("OTP_RESEND_COOLDOWN_SECONDS", 30),
    }}), 200


@auth_bp.post("/forgot-password/verify-otp")
@limiter.limit("5 per minute")
def forgot_password_verify():
    """Verify the reset OTP and set the new password. Revokes all tokens."""
    body = request.get_json(silent=True) or {}
    challenge_id = str(body.get("challenge_id") or "")
    code = str(body.get("otp") or "")
    new_password = str(body.get("new_password") or "")
    if len(new_password) < 8 or not re.search(r"[A-Za-z]", new_password) \
            or not re.search(r"\d", new_password):
        raise ApiError("VALIDATION_ERROR", "Invalid password",
                       details={"new_password": [
                           "Password must be 8+ characters with a letter and a digit."]})
    user = otp_svc.verify(challenge_id, code, "user", "PASSWORD_RESET")
    user.set_password(new_password)
    user.last_password_change_at = _now()
    user.token_version = (user.token_version or 0) + 1  # revoke every session
    user.failed_login_count = 0
    user.locked_until = None
    db.session.commit()
    audit_svc.log_action("password_reset", actor=user, target_type="user",
                         target_id=user.id)
    db.session.commit()
    return jsonify({"data": {"ok": True}}), 200


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role.value,
        "email_verified": bool(user.email_verified),
        "institution": {"id": user.institution.id, "name": user.institution.name}
        if user.institution else None,
    }
