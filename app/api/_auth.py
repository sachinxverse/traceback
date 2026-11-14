"""Reusable authorization helpers for the API (Section 6)."""
from functools import wraps

from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from .. import ApiError
from ..extensions import db
from ..models import User, Report
from ..models.enums import Custody, ReportStatus, Role


def current_user() -> User:
    """Load the authenticated user from the JWT, raising 401 if missing/inactive."""
    verify_jwt_in_request()
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))
    if user is None or not user.is_active:
        raise ApiError("UNAUTHENTICATED", "User not found or inactive", status=401)
    return user


def roles_required(*roles):
    """Decorator restricting a route to the given roles. ADMIN always allowed
    unless the route is ADMIN-only."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if Role.ADMIN in roles:
                allowed = user.role == Role.ADMIN
            else:
                allowed = user.role in roles or user.role == Role.ADMIN
            if not allowed:
                raise ApiError("FORBIDDEN", "Role not allowed", status=403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def can_view_report(user, report: Report) -> bool:
    """Visibility rule: owner, admin, institution staff, or match counterpart
    with a live relationship. REMOVED reports are visible only to owner/admin."""
    if user is None:
        return False
    if report.user_id == user.id or user.role == Role.ADMIN:
        return True
    if user.role == Role.STAFF and user.institution_id == report.institution_id:
        return True
    if report.removed:
        return False
    # Match counterpart
    from ..models import Match
    other_id = report.id
    m = Match.query.filter(
        ((Match.lost_report_id == other_id) | (Match.found_report_id == other_id)) &
        ((Match.lost_report.has(user_id=user.id)) | (Match.found_report.has(user_id=user.id)))
    ).first()
    return m is not None


def get_report_or_404(report_id, user, level="public") -> Report:
    """Load a report enforcing visibility. Returns 404 when the user must not
    learn the resource exists. level: 'public' (counterpart view) or 'owner'
    (must own or be staff/admin)."""
    report = db.session.get(Report, report_id)
    if report is None:
        raise ApiError("NOT_FOUND", "Report not found", status=404)
    if not can_view_report(user, report):
        raise ApiError("NOT_FOUND", "Report not found", status=404)
    if level == "owner":
        from ..models.enums import Role
        if (report.user_id != user.id and user.role != Role.ADMIN
                and not user.is_staff_of(report.institution_id)):
            raise ApiError("NOT_FOUND", "Report not found", status=404)
    return report


def can_view_claim(user, claim) -> bool:
    if user is None:
        return False
    return (claim.claimant_id == user.id or claim.can_review(user)
            or claim.match.lost_report.user_id == user.id)


def can_participate_in_match(user, match) -> bool:
    """Participant of a match = owner of the lost report or owner of the found
    report (or institution staff of the found report's institution, or admin)."""
    if user is None:
        return False
    if user.role == Role.ADMIN:
        return True
    if match.lost_report.user_id == user.id:
        return True
    if match.found_report.user_id == user.id:
        return True
    if user.role == Role.STAFF and user.institution_id == match.found_report.institution_id:
        return True
    return False


def messaging_allowed(match) -> bool:
    """Messaging is enabled only while a claim on the match is PENDING,
    APPROVED or DISPUTED."""
    from ..models.enums import ClaimStatus
    return any(c.verification_status in (
        ClaimStatus.PENDING, ClaimStatus.APPROVED, ClaimStatus.DISPUTED)
        for c in match.claims)


def report_for_staff(user, report) -> bool:
    """Staff may view/act on reports of their own institution."""
    return user.role == Role.STAFF and user.institution_id == report.institution_id
