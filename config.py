"""Central configuration. Secrets come from the .env file (never commit it)."""
import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env():
    """Read KEY=VALUE lines from .env into os.environ (no extra dependency).
    Values in .env win over old variables left in the terminal session."""
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _secret_key():
    """Use SECRET_KEY from .env; otherwise create one once and keep it in .secret_key."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    return key


_load_env()


class Config:
    # --- Security / sessions ---
    SECRET_KEY = _secret_key()
    APP_DEBUG = _flag("APP_DEBUG")                       # set to 0 for the defense / production
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.environ.get("SESSION_MINUTES", "30")))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("SESSION_COOKIE_SECURE")  # enable when served over HTTPS

    # --- Database (XAMPP defaults: user root, empty password) ---
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_NAME = os.environ.get("DB_NAME", "barbertrack")

    # --- Email (Gmail SMTP with an App Password) ---
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_SSL = _flag("MAIL_USE_SSL")   # set MAIL_USE_SSL=1 and MAIL_PORT=465 if port 587 is blocked
    MAIL_USE_TLS = not MAIL_USE_SSL        # STARTTLS (port 587) otherwise
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME") or None
    MAIL_PASSWORD = (os.environ.get("MAIL_PASSWORD") or "").replace(" ", "") or None
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_USERNAME") or None

    # --- Uploads ---
    UPLOAD_FOLDER = str(BASE_DIR / "static" / "uploads")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB
