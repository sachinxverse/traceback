"""Match endpoints (Section 7.5)."""
from flask import Blueprint, jsonify

from .. import ApiError
from ..extensions import db
from ..models import Match
from ..models.enums import MatchStatus
from ._auth import can_participate_in_match, current_user

matches_bp = Blueprint("matches", __name__, url_prefix="/matches")


def _get_match_or_404(match_id, user):
    match = db.session.get(Match, match_id)
    if match is None or not can_participate_in_match(user, match):
        raise ApiError("NOT_FOUND", "Match not found", status=404)
    return match


def _is_lost_side(user, match):
    return match.lost_report.user_id == user.id


@matches_bp.get("/<int:match_id>")
def get_match(match_id):
    user = current_user()
    match = _get_match_or_404(match_id, user)
    for_lost = _is_lost_side(user, match)
    own = match.lost_report if for_lost else match.found_report
    data = match.to_dict(for_lost_side=for_lost)
    data["own_report"] = own.owner_dict()
    data["distance_km"] = _distance(match)
    return jsonify({"data": data})


def _distance(match):
    from ..services.geo import haversine_km
    a, b = match.lost_report, match.found_report
    if a.latitude is not None and a.longitude is not None \
            and b.latitude is not None and b.longitude is not None:
        return round(haversine_km(a.latitude, a.longitude, b.latitude, b.longitude), 3)
    return None


@matches_bp.post("/<int:match_id>/dismiss")
def dismiss(match_id):
    user = current_user()
    match = _get_match_or_404(match_id, user)
    if _is_lost_side(user, match):
        match.lost_dismissed = True
    else:
        match.found_dismissed = True
    if match.lost_dismissed and match.found_dismissed:
        match.status = MatchStatus.DISMISSED
    db.session.commit()
    return jsonify({"data": {"ok": True}})
