"""Notification endpoints (Section 7.5)."""
from flask import Blueprint, jsonify, request

from .. import ApiError
from ..extensions import db
from ..models import Notification
from ._auth import current_user

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@notifications_bp.get("")
def list_notifications():
    user = current_user()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    q = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc(),
                                                              Notification.id.desc())
    if request.args.get("unread") in ("true", "1"):
        q = q.filter_by(is_read=False)
    pag = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"data": [n.to_dict() for n in pag.items], "meta": {
        "page": pag.page, "per_page": pag.per_page, "total": pag.total, "pages": pag.pages}})


@notifications_bp.get("/unread-count")
def unread_count():
    user = current_user()
    count = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    return jsonify({"data": {"count": count}})


@notifications_bp.post("/<int:nid>/read")
def mark_read(nid):
    user = current_user()
    n = db.session.get(Notification, nid)
    if n is None or n.user_id != user.id:
        raise ApiError("NOT_FOUND", "Notification not found", status=404)
    n.is_read = True
    db.session.commit()
    return jsonify({"data": n.to_dict()})


@notifications_bp.post("/read-all")
def mark_all_read():
    user = current_user()
    Notification.query.filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"data": {"ok": True}})
