"""Claim state machine service (Section 10)."""
from datetime import datetime

from ..extensions import db
from ..models import Claim, Match, Report
from ..models.enums import ClaimStatus, MatchStatus, ReportStatus
from .audit import log_action
from .notifications import notify


class TransitionError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.status = 409


def _live_claims_on_found(found_report: Report, exclude_claim_id=None):
    from ..models.enums import ClaimStatus
    q = Claim.query.filter(
        Claim.report_id == found_report.id,
        Claim.verification_status.in_(
            [ClaimStatus.PENDING, ClaimStatus.APPROVED, ClaimStatus.DISPUTED]))
    if exclude_claim_id:
        q = q.filter(Claim.id != exclude_claim_id)
    return q.all()


def approve_claim(claim: Claim, reviewer, review_note=None):
    if claim.verification_status not in (ClaimStatus.PENDING, ClaimStatus.DISPUTED):
        raise TransitionError(
            f"Cannot approve a claim in state {claim.verification_status.value}")
    claim.verification_status = ClaimStatus.APPROVED
    claim.reviewer_id = reviewer.id
    claim.review_note = review_note
    log_action("claim_approve", actor=reviewer, target_type="claim", target_id=claim.id,
               details={"from": claim.verification_status.value, "note": review_note})
    notify(claim.claimant_id, "CLAIM_APPROVED",
           "Your claim was approved. Arrange handover.", link=f"/claims/{claim.id}",
           related_claim_id=claim.id, related_match_id=claim.match_id)
    db.session.commit()


def reject_claim(claim: Claim, reviewer, review_note):
    if claim.verification_status not in (ClaimStatus.PENDING, ClaimStatus.DISPUTED):
        raise TransitionError(
            f"Cannot reject a claim in state {claim.verification_status.value}")
    claim.verification_status = ClaimStatus.REJECTED
    claim.reviewer_id = reviewer.id
    claim.review_note = review_note
    _after_rejection(claim)
    log_action("claim_reject", actor=reviewer, target_type="claim", target_id=claim.id,
               details={"note": review_note})
    notify(claim.claimant_id, "CLAIM_REJECTED",
           "Your claim was not approved. You may dispute.", link=f"/claims/{claim.id}",
           related_claim_id=claim.id, related_match_id=claim.id)
    db.session.commit()


def _after_rejection(claim: Claim):
    """Reject cascade: match back to SUGGESTED (if no other live claim) and
    found report back to ACTIVE (if no other live claims)."""
    match = claim.match
    found_report = claim.report
    if not _live_claims_on_found(found_report, exclude_claim_id=claim.id):
        found_report.status = ReportStatus.ACTIVE
        if match.status == MatchStatus.CLAIMED:
            match.status = MatchStatus.SUGGESTED
    lost = match.lost_report
    if not any(c.verification_status in (
            ClaimStatus.PENDING, ClaimStatus.APPROVED, ClaimStatus.DISPUTED)
            for m in [match] for c in m.claims if c.id != claim.id):
        if lost.status == ReportStatus.CLAIM_PENDING:
            lost.status = ReportStatus.ACTIVE


def withdraw_claim(claim: Claim, claimant):
    if claim.verification_status not in (ClaimStatus.PENDING, ClaimStatus.APPROVED):
        raise TransitionError(
            f"Cannot withdraw a claim in state {claim.verification_status.value}")
    claim.verification_status = ClaimStatus.WITHDRAWN
    _after_rejection(claim)
    log_action("claim_withdraw", actor=claimant, target_type="claim", target_id=claim.id)
    db.session.commit()


def dispute_claim(claim: Claim, claimant, reason):
    if claim.verification_status != ClaimStatus.REJECTED:
        raise TransitionError("Only rejected claims can be disputed")
    claim.verification_status = ClaimStatus.DISPUTED
    claim.review_note = reason
    log_action("claim_dispute", actor=claimant, target_type="claim", target_id=claim.id,
               details={"reason": reason})
    # notify admins and institution staff
    from ..models import User
    from ..models.enums import Role
    for admin in User.query.filter_by(role=Role.ADMIN, is_active=True).all():
        notify(admin.id, "CLAIM_DISPUTED", "A claim was disputed",
               link="/admin/claims", related_claim_id=claim.id)
    db.session.commit()


def mark_handed_over(claim: Claim, reviewer):
    if claim.verification_status != ClaimStatus.APPROVED:
        raise TransitionError("Only approved claims can be marked handed over")
    claim.handed_over_at = datetime.utcnow()
    claim.reviewer_id = reviewer.id
    log_action("claim_handover_marked", actor=reviewer, target_type="claim",
               target_id=claim.id)
    notify(claim.claimant_id, "HANDOVER_MARKED",
           "Please confirm you received the item", link=f"/claims/{claim.id}",
           related_claim_id=claim.id, related_match_id=claim.match_id)
    db.session.commit()


def confirm_received(claim: Claim, claimant):
    if claim.handed_over_at is None:
        raise TransitionError("Handover must be marked before confirming receipt")
    if claim.verification_status != ClaimStatus.APPROVED:
        raise TransitionError(
            f"Cannot complete a claim in state {claim.verification_status.value}")

    claim.verification_status = ClaimStatus.COMPLETED
    claim.received_confirmed_at = datetime.utcnow()

    now = datetime.utcnow()
    match = claim.match
    found_report = claim.report
    lost_report = match.lost_report
    lost_report.status = ReportStatus.RECOVERED
    lost_report.recovered_at = now
    found_report.status = ReportStatus.RECOVERED
    found_report.recovered_at = now
    match.status = MatchStatus.CONFIRMED

    # auto-reject other live claims on the same found report
    others = _live_claims_on_found(found_report, exclude_claim_id=claim.id)
    for other in others:
        other.verification_status = ClaimStatus.REJECTED
        other.review_note = "Another claim was completed for this item."
        notify(other.claimant_id, "CLAIM_REJECTED",
               "Your claim was not approved. You may dispute.",
               link=f"/claims/{other.id}", related_claim_id=other.id)

    log_action("recovery_completed", actor=claimant, target_type="claim", target_id=claim.id,
               details={"match_id": match.id})
    notify(claim.claimant_id, "RECOVERY_COMPLETED",
           "Case closed: item recovered", link=f"/reports/{lost_report.id}",
           related_claim_id=claim.id)
    notify(found_report.user_id, "RECOVERY_COMPLETED",
           "Case closed: item recovered", link=f"/reports/{found_report.id}",
           related_claim_id=claim.id)
    db.session.commit()
