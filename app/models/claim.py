"""Claim model and claim proof images."""
from ..extensions import db
from . import Column, DateTime, Enum, ForeignKey, Integer, Text, utc_iso, utcnow
from .enums import ClaimStatus, Custody


class Claim(db.Model):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(ForeignKey("matches.id"), nullable=False, index=True)
    claimant_id = Column(ForeignKey("users.id"), nullable=False, index=True)
    report_id = Column(ForeignKey("reports.id"), nullable=False)  # the FOUND report
    claim_details = Column(Text, nullable=False)  # private identifying details
    verification_status = Column(Enum(ClaimStatus), nullable=False, default=ClaimStatus.PENDING)
    reviewer_id = Column(ForeignKey("users.id"), nullable=True)
    review_note = Column(Text, nullable=True)
    handed_over_at = Column(DateTime, nullable=True)
    received_confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    match = db.relationship("Match", backref=db.backref("claims", lazy="selectin"))
    claimant = db.relationship("User", foreign_keys=[claimant_id])
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])
    report = db.relationship("Report", foreign_keys=[report_id])
    proof_images = db.relationship(
        "ClaimImage", back_populates="claim", cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ------------------------------------------------------------------ rules
    def is_live(self) -> bool:
        """A live claim is one not in a terminal rejected/withdrawn state."""
        return self.verification_status in (ClaimStatus.PENDING, ClaimStatus.APPROVED,
                                            ClaimStatus.DISPUTED)

    def can_review(self, user) -> bool:
        """True if this user is authorised to review this claim (Section 6).
        custody=WITH_FINDER -> the finder (found report owner).
        custody=AT_INSTITUTION -> STAFF of the found report's institution.
        ADMIN can review any claim."""
        from .enums import Custody, Role
        if user is None:
            return False
        if user.role == Role.ADMIN:
            return True
        found = self.report
        if found.custody == Custody.WITH_FINDER:
            return user.id == found.user_id
        return user.is_staff_of(found.institution_id)

    @property
    def review_target(self) -> str:
        if self.report.custody == Custody.WITH_FINDER:
            return "finder"
        return "institution"

    def to_dict(self, viewer) -> dict:
        """Serialise a claim for a viewer. Claimant and reviewer see
        claim_details; the reviewer also sees the found report's
        private_details for side-by-side comparison."""
        can_review = self.can_review(viewer)
        is_claimant = viewer.id == self.claimant_id
        data = {
            "id": self.id,
            "match_id": self.match_id,
            "status": self.verification_status.value,
            "created_at": utc_iso(self.created_at),
            "updated_at": utc_iso(self.updated_at),
            "handed_over_at": utc_iso(self.handed_over_at),
            "received_confirmed_at": utc_iso(self.received_confirmed_at),
            "reviewer_id": self.reviewer_id,
            "review_note": self.review_note,
            "report_id": self.report_id,
            "proof_image_urls": [f"/api/v1/claim-images/{img.id}" for img in self.proof_images],
            "review_target": self.review_target,
        }
        if is_claimant or can_review or viewer.role.value == "ADMIN":
            data["claim_details"] = self.claim_details
            data["claimant_id"] = self.claimant_id
        if can_review or viewer.role.value == "ADMIN":
            found = self.report
            data["found_private_details"] = found.private_details
            data["found_public"] = found.public_dict()
        # claimant sees their own lost report too
        if is_claimant:
            lost = self.match.lost_report
            data["lost_report"] = lost.owner_dict()
        return data
