"""Case messaging endpoints (Section 10.4 / 7.5)."""
import re

from flask import Blueprint, jsonify, request

from .. import ApiError
from ..extensions import db, limiter
from ..models import Match, Message
from ._auth import can_participate_in_match, current_user, messaging_allowed
from ..services.notifications import notify

messages_bp = Blueprint("messages", __name__, url_prefix="")

PHONE_RE = re.compile(r"(?:\+\d[\d\s\-()]{7,}\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _get_match_or_404(match_id, user):
    match = db.session.get(Match, match_id)
    if match is None or not can_participate_in_match(user, match):
        raise ApiError("NOT_FOUND", "Match not found", status=404)
    return match


@messages_bp.get("/matches/<int:match_id>/messages")
def list_messages(match_id):
    user = current_user()
    match = _get_match_or_404(match_id, user)
    if not messaging_allowed(match):
        raise ApiError("CONFLICT", "Messaging is enabled only after a claim exists", status=409)
    after_id = request.args.get("after_id", type=int)
    q = Message.query.filter_by(match_id=match.id).order_by(Message.created_at, Message.id)
    if after_id:
        q = q.filter(Message.id > after_id)
    msgs = q.all()
    return jsonify({"data": [m.to_dict() for m in msgs]})


@messages_bp.post("/matches/<int:match_id>/messages")
@limiter.limit("20 per minute")
def send_message(match_id):
    user = current_user()
    match = _get_match_or_404(match_id, user)
    if not messaging_allowed(match):
        raise ApiError("CONFLICT", "Messaging is enabled only after a claim exists", status=409)
    data = request.get_json(silent=True) or {}
    text = (data.get("message") or "").strip()
    if not text or len(text) > 1000:
        raise ApiError("VALIDATION_ERROR", "Message must be 1-1000 characters",
                       details={"message": ["Message must be 1-1000 characters"]})
    msg = Message(match_id=match.id, sender_id=user.id, message=text)
    db.session.add(msg)
    db.session.commit()

    # notify the other participant
    others = {match.lost_report.user_id, match.found_report.user_id} - {user.id}
    for uid in others:
        notify(uid, "NEW_MESSAGE", "New message on your case", link=f"/matches/{match.id}",
               related_match_id=match.id)
    return jsonify({"data": msg.to_dict()}), 201
