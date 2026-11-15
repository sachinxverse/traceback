"""Claim state machine service (Section 10).

Invariants enforced here (review fixes A1/A2/A4/A5):
- At most one APPROVED claim per found report at a time (row-locked check).
- A claim can only be approved while the found and lost reports are
  ACTIVE/CLAIM_PENDING; approving a DISPUTED/REJECTED claim re-locks the item
  (both reports -> CLAIM_PENDING, match -> CLAIMED).
- A RECOVERED item can never be disputed or approved.
- While a claim is DISPUTED the found report stays CLAIM_PENDING (locked)
  until an admin resolves it.
- Every audit log records {"from", "to"} status transitions.
"""
from datetime import datetime

from ..extensions import db
from ..models import Claim, Match, Report
from ..models.enums import ClaimStatus, MatchStatus, ReportStatus
from .audit import log_action
from .notifications import notify

CLOSE_NOTE = "Item report was closed"
RECOVERED_MSG = "Item already recovered"


class TransitionError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.status = 409


def _live_statuses():
    return (ClaimStatus.PENDING, ClaimStatus.APPROVED, ClaimStatus.DISPUTED)


def _locked_report_claims(found_report_id, exclude_claim_id=None):
    """SELECT the live claims on a found report with a row lock so two
    simultaneous approvals cannot both pass the check (with_for_update is a
    no-op on SQLite and a real row lock on PostgreSQL)."""
    q = Claim.query.filter(
        Claim.report_id == found_report_id,
        Claim.verification_status == ClaimStatus.APPROVED,
        Claim.id != (exclude_claim_id or 0),
    ).with_for_update()
    return q.all()


def _other_approved_claim(claim: Claim):
    return _locked_report_claims(claim.report_id, exclude_claim_id=claim.id)


def _lock_claim(claim_id) -> Claim:
    """Re-read the claim with a row lock for the transition."""
    claim = db.session.query(Claim).filter_by(id=claim_id).with_for_update().one()
    return claim


def _require_claimable_item(claim: Claim):
    """A2: the item must still be recoverable."""
    found = claim.report
    lost = claim.match.lost_report
    if found.status == ReportStatus.RECOVERED or lost.status == ReportStatus.RECOVERED:
        raise TransitionError(RECOVERED_MSG)
    if found.status not in (ReportStatus.ACTIVE, ReportStatus.CLAIM_PENDING):
        raise TransitionError(
            f"The found report is {found.status.value}; the item is not claimable")
    if lost.status not in (ReportStatus.ACTIVE, ReportStatus.CLAIM_PENDING):
        raise TransitionError(
            f"Your lost report is {lost.status.value}; the claim cannot be approved")


def _relock_item(claim: Claim):
    """A2/A5: when a previously-released claim (DISPUTED/REJECTED) is approved,
    lock the item again so it cannot be claimed elsewhere."""
    match: Match = claim.match
    if claim.report.status == ReportStatus.ACTIVE:
        claim.report.status = ReportStatus.CLAIM_PENDING
    if match.lost_report.status == ReportStatus.ACTIVE:
        match.lost_report.status = ReportStatus.CLAIM_PENDING
    if match.status in (MatchStatus.SUGGESTED, MatchStatus.EXPIRED):
        match.status = MatchStatus.CLAIMED


def _release_item(claim: Claim):
    """Release the item when a live claim no longer holds it (reject/withdraw
    or admin rejection). Restores the reports/match only when no OTHER live
    claim keeps the item locked."""
    match = claim.match
    found_report = claim.report
    lost_report = match.lost_report
    others = [c for c in match.claims
              if c.id != claim.id and c.verification_status in _live_statuses()]
    others_on_item = [c for c in Claim.query.filter(
        Claim.report_id == found_report.id,
        Claim.verification_status.in_(_live_statuses()),
        Claim.id != claim.id).all()]
    if not others_on_item:
        if found_report.status == ReportStatus.CLAIM_PENDING:
            found_report.status = ReportStatus.ACTIVE
        if match.status == MatchStatus.CLAIMED:
            match.status = MatchStatus.SUGGESTED
    if not others:
        if lost_report.status == ReportStatus.CLAIM_PENDING:
            lost_report.status = ReportStatus.ACTIVE


def _audit(claim, action, actor, old_status, note=None, extra=None):
    details = {"from": old_status.value if old_status else None,
               "to": claim.verification_status.value}
    if note:
        details["note"] = note
    if extra:
        details.update(extra)
    return log_action(action, actor=actor, target_type="claim", target_id=claim.id,
                      details=details)


def approve_claim(claim: Claim, reviewer, review_note=None):
    old_status = claim.verification_status
    if old_status not in (ClaimStatus.PENDING, ClaimStatus.DISPUTED):
        raise TransitionError(
            f"Cannot approve a claim in state {old_status.value}")
    if _other_approved_claim(claim):
        raise TransitionError("Another claim on this item is already approved")
    _require_claimable_item(claim)
    if old_status in (ClaimStatus.DISPUTED, ClaimStatus.REJECTED):
        _relock_item(claim)

    claim.verification_status = ClaimStatus.APPROVED
    claim.reviewer_id = reviewer.id
    claim.review_note = review_note
    _audit(claim, "claim_approve", reviewer, old_status, note=review_note)
    notify(claim.claimant_id, "CLAIM_APPROVED",
           "Your claim was approved. Arrange handover.", link=f"/claims/{claim.id}",
           related_claim_id=claim.id, related_match_id=claim.match_id)
    db.session.commit()


def reject_claim(claim: Claim, reviewer, review_note):
    old_status = claim.verification_status
    if old_status not in (ClaimStatus.PENDING, ClaimStatus.DISPUTED):
        raise TransitionError(
            f"Cannot reject a claim in state {old_status.value}")
    claim.verification_status = ClaimStatus.REJECTED
    claim.reviewer_id = reviewer.id
    claim.review_note = review_note
    # A4: correct related_match_id (was claim.id in the rejected notification)
    notify(claim.claimant_id, "CLAIM_REJECTED",
           "Your claim was not approved. You may dispute.", link=f"/claims/{claim.id}",
           related_claim_id=claim.id, related_match_id=claim.match_id)
    if old_status == ClaimStatus.DISPUTED:
        # A5: the dispute was decided as a rejection -> release the item.
        _release_item(claim)
    else:
        _release_item(claim)
    _audit(claim, "claim_reject", reviewer, old_status, note=review_note)
    db.session.commit()


def close_claims_for_report(report: Report, actor=None, reason: str = CLOSE_NOTE):
    """A3: when a report is closed or removed, reject every live claim linked
    to it, release the counterpart report, expire matches and notify."""
    affected = 0
    for claim in Claim.query.filter(
            Claim.report_id == report.id,
            Claim.verification_status.in_(_live_statuses())).all():
        old_status = claim.verification_status
        claim.verification_status = ClaimStatus.REJECTED
        claim.review_note = reason
        _release_item(claim)
        _audit(claim, "claim_auto_closed", actor, old_status, note=reason)
        notify(claim.claimant_id, "CLAIM_REJECTED",
               f"Your claim was not approved. {reason}.", link=f"/claims/{claim.id}",
               related_claim_id=claim.id, related_match_id=claim.match_id)
        affected += 1
    # claims whose LOST report is this report (claimant closed their lost side)
    match_ids = [m.id for m in _matches_of(report)]
    for claim in Claim.query.filter(
            Claim.match_id.in_(match_ids),
            Claim.verification_status.in_(_live_statuses())).all():
        if claim.report_id == report.id:
            continue  # already handled above
        old_status = claim.verification_status
        claim.verification_status = ClaimStatus.REJECTED
        claim.review_note = reason
        _release_item(claim)
        _audit(claim, "claim_auto_closed", actor, old_status, note=reason)
        notify(claim.claimant_id, "CLAIM_REJECTED",
               f"Your claim was not approved. {reason}.", link=f"/claims/{claim.id}",
               related_claim_id=claim.id, related_match_id=claim.match_id)
        affected += 1
    return affected


def _matches_of(report: Report):
    return Match.query.filter(
        (Match.lost_report_id == report.id) | (Match.found_report_id == report.id)).all()


def withdraw_claim(claim: Claim, claimant):
    old_status = claim.verification_status
    if old_status not in (ClaimStatus.PENDING, ClaimStatus.APPROVED):
        raise TransitionError(
            f"Cannot withdraw a claim in state {old_status.value}")
    claim.verification_status = ClaimStatus.WITHDRAWN
    _release_item(claim)
    _audit(claim, "claim_withdraw", claimant, old_status)
    db.session.commit()


def dispute_claim(claim: Claim, claimant, reason):
    old_status = claim.verification_status
    found_report = claim.report
    if found_report.status == ReportStatus.RECOVERED:
        raise TransitionError(RECOVERED_MSG)  # A2
    if found_report.status == ReportStatus.CLOSED:
        raise TransitionError("Item report was closed")  # A3 follow-up
    if found_report.status not in (ReportStatus.ACTIVE, ReportStatus.CLAIM_PENDING):
        raise TransitionError(
            f"The found report is {found_report.status.value}; cannot dispute")
    if old_status != ClaimStatus.REJECTED:
        raise TransitionError("Only rejected claims can be disputed")
    claim.verification_status = ClaimStatus.DISPUTED
    claim.review_note = reason
    # A5: while disputed, the item stays locked (CLAIM_PENDING) until an
    # admin resolves it.
    if found_report.status == ReportStatus.ACTIVE:
        found_report.status = ReportStatus.CLAIM_PENDING
    match = claim.match
    if match.lost_report.status == ReportStatus.ACTIVE:
        match.lost_report.status = ReportStatus.CLAIM_PENDING
    if match.status in (MatchStatus.SUGGESTED, MatchStatus.EXPIRED):
        match.status = MatchStatus.CLAIMED
    log_action("claim_dispute", actor=claimant, target_type="claim", target_id=claim.id,
               details={"from": old_status.value, "to": ClaimStatus.DISPUTED.value,
                        "reason": reason})
    from ..models import User
    from ..models.enums import Role
    for admin in User.query.filter_by(role=Role.ADMIN, is_active=True).all():
        notify(admin.id, "CLAIM_DISPUTED", "A claim was disputed",
               link="/admin/claims", related_claim_id=claim.id,
               related_match_id=claim.match_id)
    db.session.commit()


def resolve_disputed_rejection(claim: Claim, admin, note):
    """Admin resolves a dispute as REJECT: release the item."""
    old_status = claim.verification_status
    claim.verification_status = ClaimStatus.REJECTED
    claim.reviewer_id = admin.id
    claim.review_note = note
    _release_item(claim)
    _audit(claim, "claim_resolve", admin, old_status, note=note,
           extra={"decision": "REJECT"})
    notify(claim.claimant_id, "CLAIM_REJECTED",
           "Your dispute was decided: the claim was not approved.",
           link=f"/claims/{claim.id}", related_claim_id=claim.id,
           related_match_id=claim.match_id)
    db.session.commit()


def mark_handed_over(claim: Claim, reviewer):
    old_status = claim.verification_status
    if claim.verification_status != ClaimStatus.APPROVED:
        raise TransitionError("Only approved claims can be marked handed over")
    claim.handed_over_at = datetime.utcnow()
    claim.reviewer_id = reviewer.id
    _audit(claim, "claim_handover_marked", reviewer, old_status)
    notify(claim.claimant_id, "HANDOVER_MARKED",
           "Please confirm you received the item", link=f"/claims/{claim.id}",
           related_claim_id=claim.id, related_match_id=claim.match_id)
    db.session.commit()


def confirm_received(claim: Claim, claimant):
    old_status = claim.verification_status
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
    others = Claim.query.filter(
        Claim.report_id == found_report.id,
        Claim.verification_status.in_(_live_statuses()),
        Claim.id != claim.id).all()
    for other in others:
        other_old = other.verification_status
        other.verification_status = ClaimStatus.REJECTED
        other.review_note = "Another claim was completed for this item."
        notify(other.claimant_id, "CLAIM_REJECTED",
               "Your claim was not approved. You may dispute.",
               link=f"/claims/{other.id}", related_claim_id=other.id,
               related_match_id=match.id)
        _audit(other, "claim_auto_rejected", claimant, other_old,
               note="Another claim was completed for this item.")

    _audit(claim, "recovery_completed", claimant, old_status,
           extra={"match_id": match.id})
    notify(claim.claimant_id, "RECOVERY_COMPLETED",
           "Case closed: item recovered", link=f"/reports/{lost_report.id}",
           related_claim_id=claim.id)
    notify(found_report.user_id, "RECOVERY_COMPLETED",
           "Case closed: item recovered", link=f"/reports/{found_report.id}",
           related_claim_id=claim.id)
    db.session.commit()
