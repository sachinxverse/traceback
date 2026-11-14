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
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-insecure-secret-key-change-me"
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or os.environ.get("SECRET_KEY") or "dev-insecure-jwt-key-change-me"

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
    MAX_IMAGE_MB = _int_env("MAX_IMAGE_MB", 5)
    MAX_IMAGES_PER_REPORT = _int_env("MAX_IMAGES_PER_REPORT", 4)
    MAX_IMAGES_PER_CLAIM = _int_env("MAX_IMAGES_PER_CLAIM", 2)
    MAX_CONTENT_LENGTH = MAX_IMAGE_MB * 1024 * 1024 * 4  # request body cap (multiple files)

    # Retention
    REPORT_RETENTION_DAYS = _int_env("REPORT_RETENTION_DAYS", 180)

    # URLs
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")

    # Mail
    MAIL_ENABLED = os.environ.get("MAIL_ENABLED", "false").lower() in ("1", "true", "yes")
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = _int_env("MAIL_PORT", 25)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@traceback.local")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "false").lower() in ("1", "true", "yes")

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
    # JWT cookies must still behave like production for tests (CSRF on).
    JWT_COOKIE_SECURE = False


class ProductionConfig(BaseConfig):
    DEBUG = False

    @classmethod
    def validate(cls):
        missing = [k for k in ("SECRET_KEY", "JWT_SECRET_KEY") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"Missing required environment variables in production: {', '.join(missing)}")


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name=None):
    name = name or os.environ.get("APP_CONFIG") or os.environ.get("FLASK_ENV") or "development"
    return CONFIG_MAP.get(name, DevelopmentConfig)
