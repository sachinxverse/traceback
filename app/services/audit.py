"""Audit logging service (Section 10.3)."""
from flask import request, has_request_context

from ..extensions import db
from ..models import AuditLog


def log_action(action, actor=None, target_type=None, target_id=None, details=None):
    """Write an audit_logs row. Never log passwords, tokens or private details."""
    entry = AuditLog(
        actor_id=actor.id if actor is not None else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=request.remote_addr if has_request_context() else None,
    )
    db.session.add(entry)
    return entry
