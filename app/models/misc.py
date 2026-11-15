"""Message, notification, token blocklist, audit log models and claim images."""
from ..extensions import db
from . import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    utc_iso,
    utcnow,
)
from .enums import NotificationType


class ClaimImage(db.Model):
    __tablename__ = "claim_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    storage_key = Column(String(255), nullable=False)
    mime_type = Column(String(50), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    claim = db.relationship("Claim", back_populates="proof_images")


class Message(db.Model):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_match_created", "match_id", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(ForeignKey("matches.id"), nullable=False)
    sender_id = Column(ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    sender = db.relationship("User")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "match_id": self.match_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender.first_name if self.sender else None,
            "message": self.message,  # plain text; escaped by Jinja on output
            "created_at": utc_iso(self.created_at),
        }


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    type = Column(Enum(NotificationType), nullable=False)
    message = Column(String(500), nullable=False)
    link = Column(String(255), nullable=True)
    related_report_id = Column(Integer, nullable=True)
    related_match_id = Column(Integer, nullable=True)
    related_claim_id = Column(Integer, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value if self.type else None,
            "message": self.message,
            "link": self.link,
            "is_read": self.is_read,
            "created_at": utc_iso(self.created_at),
            "related_report_id": self.related_report_id,
            "related_match_id": self.related_match_id,
            "related_claim_id": self.related_claim_id,
        }


class TokenBlocklist(db.Model):
    __tablename__ = "token_blocklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(36), unique=True, nullable=False, index=True)
    token_type = Column(String(10), nullable=True)
    user_id = Column(ForeignKey("users.id"), nullable=True)
    revoked_at = Column(DateTime, nullable=False, default=utcnow)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_action", "action"), Index("ix_audit_timestamp", "timestamp"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(ForeignKey("users.id"), nullable=True)
    action = Column(String(80), nullable=False)
    target_type = Column(String(40), nullable=True)
    target_id = Column(Integer, nullable=True)
    details = Column(db.JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=utcnow)

    actor = db.relationship("User")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "actor_id": self.actor_id,
            "actor_name": self.actor.name if self.actor else None,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "timestamp": utc_iso(self.timestamp),
        }
