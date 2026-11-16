"""OTP challenge model (Part C4)."""
import uuid

from ..extensions import db
from . import Boolean, Column, DateTime, ForeignKey, Integer, String, utcnow

PORTALS = ("user", "staff", "admin")
PURPOSES = ("LOGIN", "REGISTER", "PASSWORD_RESET", "SENSITIVE_ACTION")


def new_challenge_id() -> str:
    return uuid.uuid4().hex


class OtpChallenge(db.Model):
    """A single OTP challenge. Only a salted-hash of the code is stored."""

    __tablename__ = "otp_challenges"

    id = Column(String(32), primary_key=True, default=new_challenge_id)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    portal = Column(String(10), nullable=False)          # user | staff | admin
    purpose = Column(String(20), nullable=False)         # LOGIN|REGISTER|PASSWORD_RESET|SENSITIVE_ACTION
    code_hash = Column(String(64), nullable=False)       # HMAC-SHA256 hex
    attempts = Column(Integer, nullable=False, default=0)
    resend_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    ip_hash = Column(String(64), nullable=False)
    ua_hash = Column(String(64), nullable=False)
    destination = Column(String(255), nullable=True)     # masked destination for the UI

    consumed = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        db.Index("ix_otp_challenges_user_id_purpose", "user_id", "purpose"),
        db.Index("ix_otp_challenges_expires_at", "expires_at"),
    )

    @property
    def is_expired(self):
        from datetime import UTC, datetime
        now = datetime.now(UTC).replace(tzinfo=None)
        return bool(self.expires_at and self.expires_at < now)

    @property
    def is_locked(self):
        return bool(self.locked_at) or self.attempts >= 5 or self.consumed

    def __repr__(self):  # pragma: no cover
        return f"<OtpChallenge {self.id} {self.portal}/{self.purpose}>"
