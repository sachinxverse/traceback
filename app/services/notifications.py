"""Notification service (Section 12): in-app rows plus optional email."""
import logging

from flask import render_template, current_app

from ..extensions import db, mail
from ..models import Notification, User
from ..models.enums import NotificationType

log = logging.getLogger("traceback.notifications")


def notify(user_id, type_, message, link=None, related_report_id=None,
           related_match_id=None, related_claim_id=None):
    """Create an in-app notification row and, when enabled, send an email.
    Email failures must never break the request."""
    n = Notification(
        user_id=user_id,
        type=NotificationType(type_) if isinstance(type_, str) else type_,
        message=message[:500],
        link=link,
        related_report_id=related_report_id,
        related_match_id=related_match_id,
        related_claim_id=related_claim_id,
    )
    db.session.add(n)

    app = current_app._get_current_object()
    if app.config.get("MAIL_ENABLED"):
        try:
            user = db.session.get(User, user_id)
            if user and user.email:
                _send_email(user.email, f"TRACEBACK: {message[:100]}", message,
                            link and _absolute(link, app))
        except Exception:
            log.exception("Email send failed for user %s (continuing)", user_id)
    return n


def _absolute(path, app):
    if path.startswith("http"):
        return path
    return f"{app.config.get('BASE_URL', '').rstrip('/')}{path}"


def _send_email(to, subject, body_text, link=None):
    from flask_mail import Message
    html = render_template("emails/notification.html", message=body_text, link=link)
    msg = Message(subject=subject, recipients=[to], body=body_text, html=html)
    mail.send(msg)
