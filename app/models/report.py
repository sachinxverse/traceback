"""Report model (LOST or FOUND) and report image."""
from ..extensions import db
from . import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    utc_iso,
    utcnow,
)
from .enums import Category, Custody, ProcessingStatus, ReportStatus, ReportType


class Report(db.Model):
    __tablename__ = "reports"
    __table_args__ = (
        db.Index("ix_reports_type_status", "report_type", "status"),
        db.Index("ix_reports_category", "category"),
        db.Index("ix_reports_user", "user_id"),
        db.Index("ix_reports_institution", "institution_id"),
        db.Index("ix_reports_incident_date", "incident_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(ForeignKey("users.id"), nullable=False, index=True)
    institution_id = Column(ForeignKey("institutions.id"), nullable=True)
    report_type = Column(Enum(ReportType), nullable=False)
    category = Column(Enum(Category), nullable=False)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)
    private_details = Column(Text, nullable=True)  # NEVER public
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_text = Column(String(255), nullable=True)
    incident_date = Column(DateTime, nullable=False)
    custody = Column(Enum(Custody), nullable=True)  # required if FOUND
    status = Column(Enum(ReportStatus), nullable=False, default=ReportStatus.ACTIVE)
    processing_status = Column(Enum(ProcessingStatus), nullable=False, default=ProcessingStatus.PENDING)
    text_embedding = Column(LargeBinary, nullable=True)
    removed_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    recovered_at = Column(DateTime, nullable=True)

    owner = db.relationship("User", back_populates="reports", foreign_keys=[user_id])
    institution = db.relationship("Institution", back_populates="reports")
    images = db.relationship(
        "ReportImage", back_populates="report", cascade="all, delete-orphan",
        order_by="ReportImage.position", lazy="selectin",
    )

    # ---------------------------------------------------------------- helpers
    @property
    def is_found(self) -> bool:
        return self.report_type == ReportType.FOUND

    @property
    def is_lost(self) -> bool:
        return self.report_type == ReportType.LOST

    @property
    def removed(self) -> bool:
        return self.status == ReportStatus.REMOVED

    def public_dict(self) -> dict:
        """Public fields shown to a match counterpart (Section 6). Coordinates
        rounded to 3 decimals; owner shown as first name only; no contact data
        and no private_details."""
        return {
            "id": self.id,
            "report_type": self.report_type.value,
            "category": self.category.value,
            "title": self.title,
            "description": self.description,
            "incident_date": utc_iso(self.incident_date),
            "location_text": self.location_text,
            "latitude": round(self.latitude, 3) if self.latitude is not None else None,
            "longitude": round(self.longitude, 3) if self.longitude is not None else None,
            "institution": {"id": self.institution.id, "name": self.institution.name}
            if self.institution else None,
            "custody": self.custody.value if self.custody else None,
            "image_urls": [f"/api/v1/images/{img.id}" for img in self.images],
            "created_at": utc_iso(self.created_at),
            "owner_first_name": self.owner.first_name if self.owner else None,
            "status": self.status.value,
        }

    def owner_dict(self) -> dict:
        """Full fields for the owner/staff/admin (includes private_details)."""
        data = self.public_dict()
        data.update({
            "private_details": self.private_details,
            "processing_status": self.processing_status.value,
            "removed_reason": self.removed_reason,
            "recovered_at": utc_iso(self.recovered_at),
            "updated_at": utc_iso(self.updated_at),
            "owner_id": self.user_id,
            "owner_name": self.owner.name if self.owner else None,
            "institution_id": self.institution_id,
        })
        return data

    def __repr__(self):  # pragma: no cover
        return f"<Report id={self.id} type={self.report_type} status={self.status}>"


class ReportImage(db.Model):
    __tablename__ = "report_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    storage_key = Column(String(255), nullable=False)
    mime_type = Column(String(50), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    position = Column(Integer, nullable=False, default=0)
    embedding = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    report = db.relationship("Report", back_populates="images")

    @property
    def url(self) -> str:
        return f"/api/v1/images/{self.id}"
