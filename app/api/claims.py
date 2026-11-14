"""Claim endpoints (Section 7.5 / 10)."""
from flask import Blueprint, current_app, jsonify, request

from .. import ApiError
from ..extensions import db, limiter
from ..models import Claim, Match, Report, User
from ..models.enums import (ClaimStatus, MatchStatus, ReportStatus, Role)
from ..schemas import DisputeSchema, RejectSchema, ReviewNoteSchema, load_json
from ._auth import current_user
from ..services import claims as claim_service
from ..services import images as image_service
from ..services.audit import log_action
from ..services.notifications import notify

claims_bp = Blueprint("claims", __name__)  # routes carry full paths


@claims_bp.post("/matches/<int:match_id>/claims")
@limiter.limit("10 per hour")
def submit_claim(match_id):
    user = current_user()
    match = db.session.get(Match, match_id)
    if match is None or match.lost_report.user_id != user.id:
        # only the owner of the LOST report may claim; hide existence otherwise
        raise ApiError("NOT_FOUND", "Match not found", status=404)

    found_report = match.found_report
    lost_report = match.lost_report
    if Claim.query.filter(
            Claim.match_id == match.id, Claim.claimant_id == user.id,
            Claim.verification_status.in_(
                [ClaimStatus.PENDING, ClaimStatus.APPROVED, ClaimStatus.DISPUTED])).first():
        raise ApiError("CONFLICT", "A live claim already exists for this match", status=409)
    if lost_report.status != ReportStatus.ACTIVE:
        raise ApiError("CONFLICT", "Your lost report is not active", status=409)
    if found_report.status not in (ReportStatus.ACTIVE, ReportStatus.CLAIM_PENDING):
        raise ApiError("CONFLICT", "The found report is not claimable", status=409)

    from ..schemas import ClaimCreateSchema
    if request.content_type and "multipart" in (request.content_type or ""):
        form = request.form
        data = load_json(ClaimCreateSchema(), {"claim_details": form.get("claim_details", "")})
        proof_files = [f for f in request.files.getlist("proof_images") if f and f.filename]
    else:
        data = load_json(ClaimCreateSchema(), request.get_json(silent=True) or {})
        proof_files = []

    claim = Claim(
        match_id=match.id, claimant_id=user.id, report_id=found_report.id,
        claim_details=data["claim_details"].strip(),
        verification_status=ClaimStatus.PENDING,
    )
    db.session.add(claim)
    db.session.flush()  # assign claim.id for images
    image_service.save_claim_images(
        claim, proof_files, max_images=current_app.config["MAX_IMAGES_PER_CLAIM"],
        max_mb=current_app.config["MAX_IMAGE_MB"])

    # state transitions
    match.status = MatchStatus.CLAIMED
    found_report.status = ReportStatus.CLAIM_PENDING
    lost_report.status = ReportStatus.CLAIM_PENDING
    db.session.commit()

    # notify reviewer(s)
    from ..models.enums import Custody
    if found_report.custody == Custody.WITH_FINDER:
        reviewers = [db.session.get(User, found_report.user_id)]
    else:
        reviewers = User.query.filter(
            User.role == Role.STAFF, User.institution_id == found_report.institution_id,
            User.is_active.is_(True)).all()
    for rv in reviewers:
        notify(rv.id, "CLAIM_SUBMITTED", f'New claim on "{found_report.title}"',
               link=f"/claims/{claim.id}", related_claim_id=claim.id,
               related_match_id=match.id)
    return jsonify({"data": claim.to_dict(user)}), 201


@claims_bp.get("/claims/mine")
def my_claims():
    user = current_user()
    claims = Claim.query.filter_by(claimant_id=user.id).order_by(Claim.created_at.desc()).all()
    return jsonify({"data": [c.to_dict(user) for c in claims]})


@claims_bp.get("/claims/incoming")
def incoming_claims():
    user = current_user()
    from ..models.enums import Custody

    def _reviewable(claim):
        found = claim.report
        if user.role == Role.ADMIN:
            return True
        if found.custody == Custody.WITH_FINDER:
            return found.user_id == user.id
        return user.is_staff_of(found.institution_id)

    status = request.args.get("status")
    claims = Claim.query.order_by(Claim.created_at.desc()).all()
    claims = [c for c in claims if _reviewable(c)]
    if status:
        try:
            wanted = ClaimStatus(status)
        except ValueError:
            raise ApiError("VALIDATION_ERROR", "Unknown status",
                           details={"status": ["Unknown status"]})
        claims = [c for c in claims if c.verification_status == wanted]
    return jsonify({"data": [c.to_dict(user) for c in claims]})


@claims_bp.get("/claims/<int:claim_id>")
def get_claim(claim_id):
    user = current_user()
    claim = _get_claim_or_404(claim_id, user)
    return jsonify({"data": claim.to_dict(user)})


def _get_claim_or_404(claim_id, user):
    claim = db.session.get(Claim, claim_id)
    visible = claim is not None and (
        claim.claimant_id == user.id or claim.can_review(user)
        or user.role == Role.ADMIN
        or claim.match.lost_report.user_id == user.id)
    if not visible:
        raise ApiError("NOT_FOUND", "Claim not found", status=404)
    return claim


@claims_bp.post("/claims/<int:claim_id>/approve")
def approve(claim_id):
    user = current_user()
    claim = _get_claim_or_404(claim_id, user)
    if not claim.can_review(user):
        raise ApiError("FORBIDDEN", "Only the reviewer can approve this claim", status=403)
    data = load_json(ReviewNoteSchema(), request.get_json(silent=True) or {})
    try:
        claim_service.approve_claim(claim, user, data.get("review_note"))
    except claim_service.TransitionError as e:
        raise ApiError("CONFLICT", str(e), status=409)
    return jsonify({"data": claim.to_dict(user)})


@claims_bp.post("/claims/<int:claim_id>/reject")
def reject(claim_id):
    user = current_user()
    claim = _get_claim_or_404(claim_id, user)
    if not claim.can_review(user):
        raise ApiError("FORBIDDEN", "Only the reviewer can reject this claim", status=403)
    data = load_json(RejectSchema(), request.get_json(silent=True) or {})
    try:
        claim_service.reject_claim(claim, user, data["review_note"])
    except claim_service.TransitionError as e:
        raise ApiError("CONFLICT", str(e), status=409)
    return jsonify({"data": claim.to_dict(user)})


@claims_bp.post("/claims/<int:claim_id>/withdraw")
def withdraw(claim_id):
    user = current_user()
    claim = _get_claim_or_404(claim_id, user)
    if claim.claimant_id != user.id:
        raise ApiError("FORBIDDEN", "Only the claimant can withdraw", status=403)
    try:
        claim_service.withdraw_claim(claim, user)
    except claim_service.TransitionError as e:
        raise ApiError("CONFLICT", str(e), status=409)
    return jsonify({"data": claim.to_dict(user)})


@claims_bp.post("/claims/<int:claim_id>/dispute")
def dispute(claim_id):
    user = current_user()
    claim = _get_claim_or_404(claim_id, user)
    if claim.claimant_id != user.id:
        raise ApiError("FORBIDDEN", "Only the claimant can dispute", status=403)
    data = load_json(DisputeSchema(), request.get_json(silent=True) or {})
    try:
        claim_service.dispute_claim(claim, user, data["reason"])
    except claim_service.TransitionError as e:
        raise ApiError("CONFLICT", str(e), status=409)
    return jsonify({"data": claim.to_dict(user)})


@claims_bp.post("/claims/<int:claim_id>/mark-handed-over")
def mark_handed_over(claim_id):
    user = current_user()
    claim = _get_claim_or_404(claim_id, user)
    if not claim.can_review(user):
        raise ApiError("FORBIDDEN", "Only the reviewer can mark handover", status=403)
    try:
        claim_service.mark_handed_over(claim, user)
    except claim_service.TransitionError as e:
        raise ApiError("CONFLICT", str(e), status=409)
    return jsonify({"data": claim.to_dict(user)})


@claims_bp.post("/claims/<int:claim_id>/confirm-received")
def confirm_received(claim_id):
    user = current_user()
    claim = _get_claim_or_404(claim_id, user)
    if claim.claimant_id != user.id:
        raise ApiError("FORBIDDEN", "Only the claimant can confirm receipt", status=403)
    try:
        claim_service.confirm_received(claim, user)
    except claim_service.TransitionError as e:
        raise ApiError("CONFLICT", str(e), status=409)
    return jsonify({"data": claim.to_dict(user)})
