"""OTP service (Part C).

Security invariants:
- codes are generated with `secrets.randbelow` (never `random`);
- only an HMAC-SHA256 hash of the code is stored (key = app SECRET_KEY + id);
- verification uses `hmac.compare_digest`;
- a challenge is single-use, expires, locks after too many wrong attempts,
  and is bound to portal + user + purpose + ip/ua hash;
- codes are never returned in API responses, never logged, and only echoed to
  the UI when OTP_DEV_ECHO is true AND the app is not in production.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from flask import current_app, request

from ..extensions import db
from ..models import OtpChallenge, User


from .. import ApiError


class OtpError(ApiError):
    """OTP-specific ApiError: the standard JSON error handler converts it."""


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _secret() -> bytes:
    return current_app.config["SECRET_KEY"].encode()


def code_hash_for(challenge_id: str, code: str) -> str:
    """HMAC-SHA256(code; key=SECRET_KEY, msg=challenge_id:code)."""
    msg = f"{challenge_id}:{code}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def generate_code() -> str:
    """Cryptographically secure 6-digit numeric code."""
    length = int(current_app.config.get("OTP_CODE_LENGTH", 6))
    max_num = 10 ** length
    # rejection sampling keeps the distribution uniform
    while True:
        n = secrets.randbelow(max_num)
        if n >= 10 ** (length - 1) or length == 1:
            break
    return str(n).zfill(length)


def _ip_hash() -> str:
    ip = (request.remote_addr or "local") if request else "local"
    return hmac.new(_secret(), ip.encode(), hashlib.sha256).hexdigest()


def _ua_hash() -> str:
    ua = (request.user_agent.string or "")[:400] if request else ""
    return hmac.new(_secret(), ua.encode(), hashlib.sha256).hexdigest()


def masked_destination(user: User) -> str:
    """r***@gmail.com / +91******7890 — never reveals the full address."""
    if user.phone and current_app.config.get("OTP_SENDER") == "sms":
        p = user.phone
        return (p[:3] + "*" * max(len(p) - 6, 3) + p[-3:]) if len(p) > 6 else p
    email = user.email or ""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if local else "***"


def _purge_user_challenges(user_id, purpose, keep_id=None):
    """Invalidate previous unused challenges for the same user+purpose."""
    for c in OtpChallenge.query.filter_by(user_id=user_id, purpose=purpose,
                                          consumed=False).all():
        if keep_id and c.id == keep_id:
            continue
        c.consumed = True
        c.locked_at = c.locked_at or _now()


def hourly_count(email: str) -> int:
    """Challenges created for this email in the last hour (C2 hourly limit)."""
    since = _now() - timedelta(hours=1)
    q = (OtpChallenge.query
         .join(User, OtpChallenge.user_id == User.id)
         .filter(User.email == email, OtpChallenge.created_at >= since))
    return q.count()


def create_challenge(user: User, portal: str, purpose: str) -> dict:
    """Create a challenge, send the code through the configured sender.

    Returns the payload for the API response (no code inside unless
    OTP_DEV_ECHO in development).
    """
    cfg = current_app.config
    if hourly_count(user.email) >= cfg.get("OTP_HOURLY_LIMIT", 5):
        raise OtpError("RATE_LIMITED",
                       "Too many verification requests. Try again later.",
                       status=429)
    # a new challenge invalidates previous unused ones for the same purpose
    _purge_user_challenges(user.id, purpose)
    code = generate_code()
    challenge_id = uuid.uuid4().hex
    challenge = OtpChallenge(
        user_id=user.id, portal=portal, purpose=purpose,
        code_hash=code_hash_for(challenge_id, code),
        expires_at=_now() + timedelta(seconds=cfg.get("OTP_EXPIRES_SECONDS", 300)),
        ip_hash=_ip_hash(), ua_hash=_ua_hash(),
        destination=masked_destination(user),
    )
    challenge.id = challenge_id
    db.session.add(challenge)
    db.session.commit()
    try:
        get_sender().send(user, code, purpose)
    except Exception as e:  # noqa: BLE001 - delivery failure must be a clean 503
        if not current_app.config.get("TESTING"):
            current_app.logger.error("OTP delivery failed: %s", type(e).__name__)
        db.session.delete(challenge)
        db.session.commit()
        raise OtpError("DELIVERY_FAILED",
                       "Could not send the verification code. Please try again.",
                       status=503)
    payload = {
        "otp_required": True,
        "challenge_id": challenge.id,
        "masked_destination": challenge.destination,
        "expires_in": cfg.get("OTP_EXPIRES_SECONDS", 300),
        "resend_after": cfg.get("OTP_RESEND_COOLDOWN_SECONDS", 30),
    }
    if cfg.get("OTP_DEV_ECHO") and current_app.config.get("APP_CONFIG", "") != "production":
        payload["dev_echo_code"] = code
    return payload


def resend(challenge: OtpChallenge) -> dict:
    """Issue a fresh code for an existing challenge (cooldown + limit)."""
    cfg = current_app.config
    if challenge.consumed or challenge.is_locked:
        raise OtpError("CHALLENGE_LOCKED",
                       "This verification request is no longer valid. Start again.",
                       status=400)
    age = (_now() - challenge.created_at).total_seconds()
    if challenge.resend_count > 0:
        last_sent = challenge.created_at  # updated below via resend bookkeeping
    # cooldown since the code was created (or last resend)
    cooldown = cfg.get("OTP_RESEND_COOLDOWN_SECONDS", 30)
    if age < cooldown:
        raise OtpError("RATE_LIMITED", f"Please wait {int(cooldown - age)} seconds before requesting a new code.",
                       status=429, details={"retry_after_seconds": int(cooldown - age)})
    if challenge.resend_count >= cfg.get("OTP_MAX_RESENDS", 3):
        raise OtpError("RATE_LIMITED",
                       "Too many resend attempts. Start again from the login form.",
                       status=429)
    # invalidate the old code by re-hashing with a new one
    code = generate_code()
    challenge.code_hash = code_hash_for(challenge.id, code)
    challenge.resend_count += 1
    challenge.created_at = _now()
    challenge.expires_at = _now() + timedelta(seconds=cfg.get("OTP_EXPIRES_SECONDS", 300))
    challenge.attempts = 0
    db.session.commit()
    get_sender().send(db.session.get(User, challenge.user_id), code, challenge.purpose)
    payload = {
        "otp_required": True,
        "challenge_id": challenge.id,
        "masked_destination": challenge.destination,
        "expires_in": cfg.get("OTP_EXPIRES_SECONDS", 300),
        "resend_after": cooldown,
    }
    if cfg.get("OTP_DEV_ECHO"):
        payload["dev_echo_code"] = code
    return payload


def verify(challenge_id: str, code: str, portal: str, purpose: str) -> User:
    """Verify an OTP challenge; returns the user on success, raises OtpError."""
    cfg = current_app.config
    challenge = db.session.get(OtpChallenge, challenge_id or "")
    generic = OtpError("OTP_INVALID", "Incorrect or expired code.", status=400)
    if challenge is None or challenge.consumed:
        raise generic
    if challenge.portal != portal or challenge.purpose != purpose:
        # bound to portal + purpose: an OTP for one flow cannot finish another
        raise generic
    if challenge.is_expired or challenge.is_locked:
        raise OtpError("CHALLENGE_LOCKED",
                       "This code has expired or is locked. Start again from the login form.",
                       status=400)
    if challenge.ip_hash != _ip_hash() or challenge.ua_hash != _ua_hash():
        raise generic
    user = db.session.get(User, challenge.user_id)
    if user is None:
        raise generic
    if hmac.compare_digest(challenge.code_hash, code_hash_for(challenge.id, code or "")):
        challenge.consumed = True
        challenge.used_at = _now()
        db.session.commit()
        return user
    # wrong code
    challenge.attempts += 1
    if challenge.attempts >= cfg.get("OTP_MAX_ATTEMPTS", 5):
        challenge.locked_at = _now()
    db.session.commit()
    left = max(cfg.get("OTP_MAX_ATTEMPTS", 5) - challenge.attempts, 0)
    if challenge.locked_at:
        raise OtpError("OTP_LOCKED",
                       "Too many incorrect codes. Start again from the login form.",
                       status=400)
    raise OtpError("OTP_INVALID", f"Incorrect code. {left} attempts left.",
                   status=400, details={"attempts_left": left})


def purge_expired() -> int:
    """Delete expired challenges; returns how many rows were removed (CLI)."""
    n = OtpChallenge.query.filter(OtpChallenge.expires_at < _now()).delete(synchronize_session=False)
    db.session.commit()
    return n


# ----------------------------------------------------------------- senders
class OtpSender:
    """Delivery-channel interface (C3)."""

    name = "base"

    def send(self, user: User, code: str, purpose: str) -> None:
        raise NotImplementedError


class EmailOtpSender(OtpSender):
    """Email OTP via Flask-Mail using MAIL_* configuration."""

    name = "email"

    SUBJECTS = {
        "LOGIN": "Your TRACEBACK sign-in code",
        "REGISTER": "Verify your TRACEBACK account",
        "PASSWORD_RESET": "Reset your TRACEBACK password",
        "SENSITIVE_ACTION": "Confirm your TRACEBACK account change",
    }

    def _content(self, purpose):
        subject = self.SUBJECTS.get(purpose, "Your TRACEBACK verification code")
        minutes = current_app.config.get("OTP_EXPIRES_SECONDS", 300) // 60
        return subject, minutes

    def send(self, user, code, purpose):
        from flask_mail import Message
        from ..extensions import mail
        subject, minutes = self._content(purpose)
        body, html = _code_email_body(code, minutes)
        msg = Message(subject=subject, recipients=[user.email], body=body, html=html)
        mail.send(msg)


def _code_email_body(code, minutes):
    body = (f"Your TRACEBACK verification code is {code}.\n"
            f"It expires in {minutes} minutes.\n\n"
            "If you did not request this, ignore this email and change your password.")
    html = f"""<div style="font-family:Arial,sans-serif;max-width:480px">
  <h2 style="color:#0B1F3A">TRACEBACK verification</h2>
  <p>Your code is:</p>
  <p style="font-size:32px;font-weight:800;letter-spacing:8px;color:#1D4ED8">{code}</p>
  <p>This code expires in {minutes} minutes. It can be used once.</p>
  <p style="color:#64748B">If you did not request this, ignore this email and
  change your password.</p>
</div>"""
    return body, html


class EmailApiSender(OtpSender):
    """Email OTP over an HTTPS mail API instead of SMTP.

    Render (and most PaaS free tiers) block outbound SMTP ports (25/465/587);
    a plain HTTPS POST to the provider's REST API works everywhere. Currently
    supports Mailjet (MAIL_API_PROVIDER=mailjet) using the standard API-key /
    secret-key pair stored in MAIL_USERNAME / MAIL_PASSWORD.
    """

    name = "emailapi"

    def send(self, user, code, purpose):
        import requests
        provider = current_app.config.get("MAIL_API_PROVIDER", "")
        if provider != "mailjet":
            raise RuntimeError(
                "MAIL_API_PROVIDER must be 'mailjet' for OTP_SENDER=emailapi")
        subject, minutes = EmailOtpSender.SUBJECTS.get(
            purpose, "Your TRACEBACK verification code"), \
            current_app.config.get("OTP_EXPIRES_SECONDS", 300) // 60
        body, html = _code_email_body(code, minutes)
        sender = current_app.config.get("MAIL_DEFAULT_SENDER")
        payload = {
            "Messages": [{
                "From": {"Email": sender, "Name": "TRACEBACK"},
                "To": [{"Email": user.email}],
                "Subject": subject,
                "TextPart": body,
                "HTMLPart": html,
                "CustomID": f"otp-{purpose.lower()}",
            }]
        }
        auth = (current_app.config.get("MAIL_USERNAME"),
                current_app.config.get("MAIL_PASSWORD"))
        resp = requests.post("https://api.mailjet.com/v3.1/send",
                             json=payload, auth=auth, timeout=30)
        if resp.status_code >= 400:
            current_app.logger.error(
                "Mailjet send failed: %s %s", resp.status_code, resp.text[:200])
            raise RuntimeError(f"Mailjet send failed with status {resp.status_code}")


class ConsoleOtpSender(OtpSender):
    """Development only: prints the OTP to the SERVER CONSOLE (never to the client)."""

    name = "console"

    def send(self, user, code, purpose):
        # server log only — production must never hit this path
        print(f"[OTP] {purpose} code for {user.email}: {code}", flush=True)


class TestingOtpSender(OtpSender):
    """Test double: records codes in a module-level outbox for assertions."""

    name = "testing"
    outbox = []  # list of dicts: {email, code, purpose}

    @classmethod
    def reset(cls):
        cls.outbox = []

    @classmethod
    def latest(cls, email, purpose=None):
        for item in reversed(cls.outbox):
            if item["email"] == email and (purpose is None or item["purpose"] == purpose):
                return item["code"]
        return None

    def send(self, user, code, purpose):
        type(self).outbox.append({"email": user.email, "code": code, "purpose": purpose})


class SmsOtpSender(OtpSender):
    """Pluggable SMS adapter (needs a paid provider account; email stays default).

    Configure provider credentials via env; raises a clear error when unset.
    """

    name = "sms"

    def send(self, user, code, purpose):
        import os
        api_url = os.environ.get("SMS_API_URL")
        api_key = os.environ.get("SMS_API_KEY")
        if not (api_url and api_key):
            raise RuntimeError("SMS provider not configured: set SMS_API_URL and SMS_API_KEY")
        import json
        import urllib.request
        phone = user.phone
        if not phone:
            raise RuntimeError("User has no phone number for SMS OTP")
        data = json.dumps({"to": phone, "text": f"TRACEBACK code: {code} (expires in 5 min)"}).encode()
        req = urllib.request.Request(api_url, data=data,
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key}"})
        urllib.request.urlopen(req, timeout=10)


_SENDERS = {"email": EmailOtpSender, "emailapi": EmailApiSender,
            "console": ConsoleOtpSender,
            "testing": TestingOtpSender, "sms": SmsOtpSender}


def get_sender() -> OtpSender:
    name = current_app.config.get("OTP_SENDER", "email")
    cls = _SENDERS.get(name, EmailOtpSender)
    return cls()
