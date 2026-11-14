"""Application factory for Project TRACEBACK."""
import logging
import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .extensions import db, jwt, limiter, mail, migrate

log = logging.getLogger("traceback")


class ApiError(Exception):
    """Raised by API code to produce a consistent JSON error response."""

    def __init__(self, code, message, status=400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def error_body(code, message, details=None):
    err = {"code": code, "message": message}
    if details:
        err["details"] = details
    return {"error": err}


def _wants_json() -> bool:
    return request.path.startswith("/api/")


def _jwt_error_response(status, code, message):
    resp = jsonify(error_body(code, message))
    resp.status_code = status
    return resp


def create_app(config_name=None, **overrides):
    app = Flask(__name__, template_folder="templates", static_folder="static")

    from config import get_config
    cfg = get_config(config_name)
    app.config.from_object(cfg)
    for key, value in overrides.items():
        app.config[key.upper()] = value
    if cfg is not None and hasattr(cfg, "validate"):
        try:
            cfg.validate()
        except RuntimeError:
            if app.config.get("TESTING") or app.config.get("DEBUG"):
                log.warning("Config validation warning in dev/test")
            else:
                raise

    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    # Ensure instance path exists for SQLite default
    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)
    jwt.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)

    # -- JWT callbacks --------------------------------------------------------
    from .models import TokenBlocklist

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        jti = jwt_payload["jti"]
        return db.session.query(
            TokenBlocklist.id).filter_by(jti=jti).first() is not None

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return _jwt_error_response(401, "TOKEN_EXPIRED", "The token has expired")

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return _jwt_error_response(401, "UNAUTHENTICATED", f"Invalid token: {reason}")

    @jwt.unauthorized_loader
    def missing_token(reason):
        return _jwt_error_response(401, "UNAUTHENTICATED", "Missing authorization token")

    @jwt.revoked_token_loader
    def revoked_token(jwt_header, jwt_payload):
        return _jwt_error_response(401, "TOKEN_REVOKED", "The token has been revoked")

    # -- Blueprints -----------------------------------------------------------
    from .api.auth import auth_bp
    from .api.reports import reports_bp
    from .api.images import images_bp
    from .api.matches import matches_bp
    from .api.claims import claims_bp
    from .api.messages import messages_bp
    from .api.notifications import notifications_bp
    from .api.institutions import institutions_bp
    from .api.admin import admin_bp
    from .api.health import health_bp
    from .web.routes import web_bp

    for bp in (auth_bp, reports_bp, images_bp, matches_bp, claims_bp, messages_bp,
               notifications_bp, institutions_bp, admin_bp, health_bp):
        own = bp.url_prefix or ""
        app.register_blueprint(bp, url_prefix="/api/v1" + own)
    app.register_blueprint(web_bp)

    # -- Error handlers -------------------------------------------------------
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e.code, e.message, e.details)), e.status

    @app.errorhandler(413)
    def handle_too_large(e):
        return jsonify(error_body("FILE_TOO_LARGE", "Upload exceeds size limit")), 413

    @app.errorhandler(404)
    def handle_404(e):
        if _wants_json():
            return jsonify(error_body("NOT_FOUND", "Resource not found")), 404
        return app.jinja_env.get_or_select_template("errors/404.html").render(), 404

    @app.errorhandler(403)
    def handle_403(e):
        if _wants_json():
            return jsonify(error_body("FORBIDDEN", "Not allowed")), 403
        return app.jinja_env.get_or_select_template("errors/403.html").render(), 403

    @app.errorhandler(405)
    def handle_405(e):
        if _wants_json():
            return jsonify(error_body("BAD_REQUEST", "Method not allowed")), 405
        return handle_404(e)

    @app.errorhandler(429)
    def handle_429(e):
        if _wants_json():
            return jsonify(error_body("RATE_LIMITED", "Too many requests")), 429
        return app.jinja_env.get_or_select_template("errors/429.html").render(), 429

    @app.errorhandler(500)
    def handle_500(e):
        log.exception("Unhandled server error on %s", request.path)
        if _wants_json():
            return jsonify(error_body("INTERNAL_ERROR", "An unexpected error occurred")), 500
        return app.jinja_env.get_or_select_template("errors/500.html").render(), 500

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Let HTTPExceptions (e.g. abort) pass through to their own handlers.
        if isinstance(e, HTTPException):
            handlers = {
                404: handle_404, 403: handle_403, 429: handle_429, 413: handle_too_large,
            }
            handler = handlers.get(e.code)
            if handler:
                return handler(e)
            return e
        log.exception("Unhandled exception on %s", request.path)
        if _wants_json():
            return jsonify(error_body("INTERNAL_ERROR", "An unexpected error occurred")), 500
        return app.jinja_env.get_or_select_template("errors/500.html").render(), 500

    # -- Security headers -----------------------------------------------------
    @app.after_request
    def set_headers(resp):
        csp = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com; "
            "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
            "connect-src 'self' https://nominatim.openstreetmap.org; "
            "frame-ancestors 'none'"
            
        )
        resp.headers.setdefault("Content-Security-Policy", csp)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    # -- CLI ------------------------------------------------------------------
    from . import cli as cli_module
    cli_module.register(app)

    return app
