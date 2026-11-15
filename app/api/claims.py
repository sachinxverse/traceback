"""Claim endpoints (Section 7.5 / 10)."""
from flask import Blueprint, current_app, jsonify, request

from .. import ApiError
from ..extensions import db, limiter
from ..models import Claim, Match, Report, User
from ..models.enums import ClaimStatus, MatchStatus, ReportStatus, Role
from ..schemas import DisputeSchema, RejectSchema, ReviewNoteSchema, load_json
from ..services import claims as claim_service
from ..services import images as image_service
from ..services.notifications import notify
from ._auth import current_user
from ._paging import page_params, paginated

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
    # A5: while another claim is APPROVED or DISPUTED the item is held and
    # cannot receive new claims.
    if Claim.query.filter(
            Claim.report_id == found_report.id,
            Claim.verification_status.in_(
                [ClaimStatus.APPROVED, ClaimStatus.DISPUTED])).first():
        raise ApiError("CONFLICT", "The item is currently held by another claim",
                       status=409)

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
    page, per_page = page_params()
    q = (Claim.query.filter_by(claimant_id=user.id)
         .options(db.joinedload(Claim.report),
                  db.joinedload(Claim.match).joinedload(Match.lost_report)))
    return jsonify(paginated(q, page, per_page, lambda c: c.to_dict(user),
                             order_by=Claim.created_at.desc()))


@claims_bp.get("/claims/incoming")
def incoming_claims():
    """Claims the current user may review, scoped in SQL (no full scans)."""
    user = current_user()
    page, per_page = page_params()
    from sqlalchemy import and_, or_

    from ..models.enums import Custody

    found_report = db.aliased(Report)
    q = (Claim.query.join(found_report, Claim.report_id == found_report.id)
         .options(db.joinedload(Claim.report),
                  db.joinedload(Claim.match).joinedload(Match.lost_report)))
    if user.role == Role.ADMIN:
        pass  # admins review everything
    else:
        scopes = [and_(found_report.custody == Custody.WITH_FINDER,
                       found_report.user_id == user.id)]
        if user.role == Role.STAFF and user.institution_id:
            scopes.append(found_report.institution_id == user.institution_id)
        q = q.filter(or_(*scopes))
    status = request.args.get("status")
    if status:
        try:
            q = q.filter(Claim.verification_status == ClaimStatus(status))
        except ValueError:
            raise ApiError("VALIDATION_ERROR", "Unknown status",
                           details={"status": ["Unknown status"]})
    return jsonify(paginated(q, page, per_page, lambda c: c.to_dict(user),
                             order_by=Claim.created_at.desc()))


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
