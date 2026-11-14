"""Institution model."""
import re

from ..extensions import db
from .enums import InstitutionType
from . import Column, Integer, String, Text, Float, Boolean, DateTime, Enum, utcnow


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:100] or "institution"


class Institution(db.Model):
    __tablename__ = "institutions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    institution_type = Column(Enum(InstitutionType), nullable=True)
    address = Column(Text, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    contact_email = Column(String(255), nullable=True)
    verified = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    staff_members = db.relationship("User", back_populates="institution")
    reports = db.relationship("Report", back_populates="institution")

    @classmethod
    def unique_slug(cls, name: str) -> str:
        """Generate a unique slug from a name, auto-suffixing -2, -3 on collision."""
        base = slugify(name)
        slug, n = base, 1
        while cls.query.filter_by(slug=slug).first() is not None:
            n += 1
            slug = f"{base}-{n}"[:100]
        return slug

    def to_dict(self, public: bool = True) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "institution_type": self.institution_type.value if self.institution_type else None,
            "address": self.address,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }
        if not public:
            data.update({
                "contact_email": self.contact_email,
                "verified": self.verified,
                "is_active": self.is_active,
                "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            })
        return data
