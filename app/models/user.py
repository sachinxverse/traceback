"""User model."""
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from .enums import Role
from . import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, utcnow


class User(db.Model):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    phone = Column(String(30), nullable=True)
    role = Column(Enum(Role), nullable=False, default=Role.USER)
    institution_id = Column(ForeignKey("institutions.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    last_login_at = Column(DateTime, nullable=True)

    institution = db.relationship("Institution", back_populates="staff_members")
    reports = db.relationship("Report", back_populates="owner", foreign_keys="Report.user_id")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        try:
            return check_password_hash(self.password_hash, password)
        except (ValueError, TypeError):
            return False

    @property
    def first_name(self) -> str:
        """First name only - used for public display (privacy)."""
        return (self.name or "").strip().split(" ")[0] if self.name else ""

    def is_staff_of(self, institution_id) -> bool:
        return self.role == Role.STAFF and self.institution_id == institution_id

    def to_dict(self, include_email: bool = True) -> dict:
        out = {
            "id": self.id,
            "name": self.name,
            "role": self.role.value if self.role else None,
            "institution_id": self.institution_id,
            "institution": {"id": self.institution.id, "name": self.institution.name}
            if self.institution else None,
            "is_active": self.is_active,
        }
        if include_email:
            out["email"] = self.email
            out["phone"] = self.phone
        return out

    def __repr__(self):  # pragma: no cover
        return f"<User id={self.id} role={self.role}>"
