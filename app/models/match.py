"""Match model: a scored candidate pairing of a LOST and a FOUND report."""
from ..extensions import db
from . import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    utc_iso,
    utcnow,
)
from .enums import MatchStatus


class Match(db.Model):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("lost_report_id", "found_report_id", name="uq_match_pair"),
        Index("ix_matches_total_score", "total_score"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    lost_report_id = Column(ForeignKey("reports.id"), nullable=False)
    found_report_id = Column(ForeignKey("reports.id"), nullable=False)
    image_score = Column(Float, nullable=True)
    text_score = Column(Float, nullable=True)
    location_score = Column(Float, nullable=True)
    time_score = Column(Float, nullable=True)
    total_score = Column(Float, nullable=False)
    signals_used = Column(JSON, nullable=False, default=list)
    status = Column(Enum(MatchStatus), nullable=False, default=MatchStatus.SUGGESTED)
    lost_dismissed = Column(Boolean, nullable=False, default=False)
    found_dismissed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    lost_report = db.relationship("Report", foreign_keys=[lost_report_id])
    found_report = db.relationship("Report", foreign_keys=[found_report_id])

    def scores_dict(self) -> dict:
        """0-100 breakdown, or null for missing signals."""
        def pct(v):
            return round(v * 100) if v is not None else None
        return {
            "image": pct(self.image_score),
            "text": pct(self.text_score),
            "location": pct(self.location_score),
            "time": pct(self.time_score),
        }

    def confidence_label(self) -> str:
        if self.total_score >= 0.75:
            return "HIGH"
        if self.total_score >= 0.55:
            return "MEDIUM"
        return "LOW"

    def to_dict(self, for_lost_side: bool, include_reports: bool = True) -> dict:
        """Serialise a match for one side. The counterpart report is public-only."""
        counterpart = self.found_report if for_lost_side else self.lost_report
        own = self.lost_report if for_lost_side else self.found_report
        data = {
            "id": self.id,
            "score": round(self.total_score * 100),
            "confidence": self.confidence_label(),
            "breakdown": self.scores_dict(),
            "signals_used": self.signals_used or [],
            "status": self.status.value,
            "created_at": utc_iso(self.created_at),
            "own_report_id": own.id,
        }
        if include_reports:
            data["counterpart"] = counterpart.public_dict()
        return data
