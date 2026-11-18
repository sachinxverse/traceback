"""Application configuration classes for Project TRACEBACK."""
import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _parse_weights(raw, default="image=0.40,text=0.25,location=0.20,time=0.15"):
    """Parse a MATCH_WEIGHTS string like 'image=0.4,text=0.25,...' into a dict."""
    parsed = {}
    try:
        for part in (raw or default).split(","):
            k, v = part.split("=")
            parsed[k.strip()] = float(v)
        if parsed:
            return parsed
    except (ValueError, AttributeError):
        pass
    return {"image": 0.40, "text": 0.25, "location": 0.20, "time": 0.15}


def _float_env(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


class BaseConfig:
    APP_NAME = "TRACEBACK"
    # B2: insecure defaults are DEVELOPMENT-ONLY fallbacks (clearly marked,
    # 32+ bytes to keep JWT signing warnings away). Production and Testing
    # configs must never fall back to them (see validate() / TestingConfig).
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-insecure-fallback-key-0123456789abcdef"
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or os.environ.get("SECRET_KEY") or "dev-insecure-fallback-jwt-0123456789abcdef"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///traceback.db"

    # JWT tokens in HttpOnly cookies + CSRF double submit.
    JWT_TOKEN_LOCATION = ["cookies"]
    JWT_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_CSRF_CHECK_FORM = False
    JWT_ACCESS_COOKIE_NAME = "access_token_cookie"
    JWT_REFRESH_COOKIE_NAME = "refresh_token_cookie"
    JWT_CSRF_ACCESS_COOKIE_NAME = "csrf_access_token"
    JWT_CSRF_REFRESH_COOKIE_NAME = "csrf_refresh_token"
    JWT_COOKIE_SAMESITE = "Lax"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=30)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=14)
    JWT_ERROR_MESSAGE_KEY = "message"

    # Jobs
    JOBS_SYNC = os.environ.get("JOBS_SYNC", "false").lower() in ("1", "true", "yes")
    JOBS_MAX_WORKERS = _int_env("JOBS_MAX_WORKERS", 2)

    # Issue 7: who may file FOUND reports.
    #   Mode A (false): only STAFF file FOUND (items held at institutions).
    #   Mode B (true, default = the original specification): any verified
    #   USER may also file FOUND and choose custody WITH_FINDER or
    #   AT_INSTITUTION. STAFF filing stays allowed in both modes.
    ALLOW_PUBLIC_FOUND_REPORTS = os.environ.get(
        "ALLOW_PUBLIC_FOUND_REPORTS", "true").lower() in ("1", "true", "yes")

    # Embeddings / matching
    EMBEDDING_BACKEND = os.environ.get("EMBEDDING_BACKEND", "stub")
    CLIP_MODEL = os.environ.get("CLIP_MODEL", "ViT-B-32")
    CLIP_PRETRAINED = os.environ.get("CLIP_PRETRAINED", "laion2b_s34b_b79k")
    TEXT_MODEL = os.environ.get("TEXT_MODEL", "all-MiniLM-L6-v2")
    MATCH_WEIGHTS = _parse_weights(os.environ.get("MATCH_WEIGHTS", ""))
    MATCH_MIN_SCORE = _float_env("MATCH_MIN_SCORE", 0.45)
    NOTIFY_MIN_SCORE = _float_env("NOTIFY_MIN_SCORE", 0.55)
    MATCH_TOP_N = _int_env("MATCH_TOP_N", 10)
    MATCH_MAX_DAYS = _int_env("MATCH_MAX_DAYS", 90)
    MATCH_MAX_DISTANCE_KM = _float_env("MATCH_MAX_DISTANCE_KM", 50)
    IMG_LOW = _float_env("IMG_LOW", 0.55)
    IMG_HIGH = _float_env("IMG_HIGH", 0.92)
    TXT_LOW = _float_env("TXT_LOW", 0.25)
    TXT_HIGH = _float_env("TXT_HIGH", 0.85)
    LOC_DECAY_KM = _float_env("LOC_DECAY_KM", 1.0)
    TIME_DECAY_DAYS = _float_env("TIME_DECAY_DAYS", 7)

    # Images
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR") or os.path.join(BASE_DIR, "instance", "uploads")
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL") or None
    S3_BUCKET = os.environ.get("S3_BUCKET") or ""
    S3_REGION = os.environ.get("S3_REGION") or None
    S3_PREFIX = os.environ.get("S3_PREFIX") or "traceback"
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID") or None
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY") or None
    # Issue 5 guard: production must not silently use the ephemeral local disk
    ALLOW_EPHEMERAL_STORAGE = os.environ.get("ALLOW_EPHEMERAL_STORAGE", "").lower() in ("1", "true", "yes")
    MAX_IMAGE_MB = _int_env("MAX_IMAGE_MB", 5)
    MAX_IMAGES_PER_REPORT = _int_env("MAX_IMAGES_PER_REPORT", 4)
    MAX_IMAGES_PER_CLAIM = _int_env("MAX_IMAGES_PER_CLAIM", 2)
    MAX_CONTENT_LENGTH = MAX_IMAGE_MB * 1024 * 1024 * 4  # request body cap (multiple files)

    # Retention
    REPORT_RETENTION_DAYS = _int_env("REPORT_RETENTION_DAYS", 180)

    # URLs
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")
    # Default map centre (string 'lat,lng' env override; used by /api/v1/meta)
    MAP_DEFAULT_CENTER = [float(x) for x in os.environ.get(
        "MAP_DEFAULT_CENTER", "30.0668,79.0193").split(",")]

    # --- Auth portals (Part B) -------------------------------------------------
    # Progressive lockout after repeated failed passwords (Part C2).
    LOGIN_MAX_FAILURES = _int_env("LOGIN_MAX_FAILURES", 5)
    LOGIN_LOCKOUT_WINDOW_SECONDS = _int_env("LOGIN_LOCKOUT_WINDOW_SECONDS", 15 * 60)
    LOGIN_LOCKOUT_SECONDS = _int_env("LOGIN_LOCKOUT_SECONDS", 15 * 60)

    # --- OTP (Part C) -----------------------------------------------------------
    OTP_CODE_LENGTH = _int_env("OTP_CODE_LENGTH", 6)
    OTP_EXPIRES_SECONDS = _int_env("OTP_EXPIRES_SECONDS", 300)      # 5 minutes
    OTP_MAX_ATTEMPTS = _int_env("OTP_MAX_ATTEMPTS", 5)              # then challenge locks
    OTP_RESEND_COOLDOWN_SECONDS = _int_env("OTP_RESEND_COOLDOWN_SECONDS", 30)
    OTP_MAX_RESENDS = _int_env("OTP_MAX_RESENDS", 3)                # per challenge
    OTP_HOURLY_LIMIT = _int_env("OTP_HOURLY_LIMIT", 5)              # per email per hour
    # Delivery channel: 'email' (SMTP, default) or 'console' (prints to server
    # console in development only). 'sms' adapter exists but needs a provider.
    OTP_SENDER = os.environ.get("OTP_SENDER", "email")
    # OTP_DEV_ECHO may echo the code to the UI — DEVELOPMENT ONLY. Production
    # refuses to start when true (ProductionConfig.validate).
    OTP_DEV_ECHO = os.environ.get("OTP_DEV_ECHO", "false").lower() in ("1", "true", "yes")

    # Mail
    MAIL_ENABLED = os.environ.get("MAIL_ENABLED", "false").lower() in ("1", "true", "yes")
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = _int_env("MAIL_PORT", 25)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@traceback.local")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "false").lower() in ("1", "true", "yes")
    # HTTP mail API (used by OTP_SENDER=emailapi when the host blocks SMTP ports)
    MAIL_API_PROVIDER = os.environ.get("MAIL_API_PROVIDER", "")

    # Rate limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = "200 per minute"

    # Generic hardening
    SESSION_COOKIE_HTTPONLY = True
    PREFERRED_URL_SCHEME = "https" if JWT_COOKIE_SECURE else "http"

    # High watermark text
    CONFIDENCE_HIGH = 0.75
    CONFIDENCE_MEDIUM = 0.55


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL") or "sqlite:///:memory:"
    DEBUG = False
    RATELIMIT_ENABLED = False
    JOBS_SYNC = True
    MAIL_SUPPRESS_SEND = True
    WTF_CSRF_ENABLED = False
    # B2: stable 32+ byte keys so no insecure-key warnings appear in test runs.
    SECRET_KEY = os.environ.get("SECRET_KEY") or "testing-secret-key-0123456789abcdef012345"
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or "testing-jwt-key-0123456789abcdef01234567"
    # JWT cookies must still behave like production for tests (CSRF on).
    JWT_COOKIE_SECURE = False
    # Tests capture OTPs via the built-in TestingOtpSender (records codes in
    # memory); there is deliberately no skip-OTP switch in any config.
    OTP_SENDER = "testing"
    OTP_DEV_ECHO = False


class ProductionConfig(BaseConfig):
    DEBUG = False

    # B2: placeholders that must never reach production.
    _PLACEHOLDERS = (
        "change-me", "changeme", "please-change", "insecure", "secret",
        "password", "traceback", "dev-insecure", "testing",
    )

    @classmethod
    def _is_weak(cls, value):
        if not value:
            return True
        v = value.lower()
        return any(p in v for p in cls._PLACEHOLDERS) or len(value) < 32

    @classmethod
    def validate(cls):
        missing = [k for k in ("SECRET_KEY", "JWT_SECRET_KEY") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"Missing required environment variables in production: {', '.join(missing)}")
        weak = [k for k in ("SECRET_KEY", "JWT_SECRET_KEY")
                if cls._is_weak(os.environ.get(k))]
        if weak:
            raise RuntimeError(
                "Refusing to start with weak/placeholder "
                f"{', '.join(weak)}: use 32+ random bytes "
                '(e.g. python -c "import secrets; print(secrets.token_urlsafe(32))") '
                "and never reuse values containing words like change-me/insecure")
        if os.environ.get("DATABASE_URL", "").startswith("sqlite") and not os.environ.get("ALLOW_SQLITE_IN_PRODUCTION"):
            raise RuntimeError(
                "Refusing SQLite in production; set DATABASE_URL to PostgreSQL "
                "(or set ALLOW_SQLITE_IN_PRODUCTION=1 for single-box demos)")
        # Part C: OTP safety rails in production.
        if os.environ.get("OTP_DEV_ECHO", "").lower() in ("1", "true", "yes"):
            raise RuntimeError("OTP_DEV_ECHO=true is a development-only convenience; "
                               "refusing to start in production")
        sender = os.environ.get("OTP_SENDER", "email")
        mail_on = os.environ.get("MAIL_ENABLED", "").lower() in ("1", "true", "yes")
        if not mail_on and sender == "email":
            raise RuntimeError(
                "MAIL_ENABLED=false without a configured alternative OTP sender "
                "(set MAIL_ENABLED=true with SMTP settings, or OTP_SENDER=sms)")
        # Issue 5: uploads must survive restarts/deployments — the free-tier
        # local disk is ephemeral. Require object storage unless explicitly
        # overridden for a single-box demo.
        if (os.environ.get("STORAGE_BACKEND", "local") != "s3"
                and not os.environ.get("ALLOW_EPHEMERAL_STORAGE", "").lower() in ("1", "true", "yes")):
            raise RuntimeError(
                "Refusing STORAGE_BACKEND=local in production: uploaded photos "
                "would be erased on every restart/deploy. Set "
                "STORAGE_BACKEND=s3 with S3_* credentials, or set "
                "ALLOW_EPHEMERAL_STORAGE=true to accept data loss explicitly.")


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name=None):
    name = name or os.environ.get("APP_CONFIG") or os.environ.get("FLASK_ENV") or "development"
    return CONFIG_MAP.get(name, DevelopmentConfig)
