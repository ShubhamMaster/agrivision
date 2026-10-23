"""
AgriVision — central configuration.

Every tunable value of the project lives here so that no module has to
hard-code a path, a secret or a limit.  Flask reads this object once at
start-up (see app/__init__.py -> create_app).
"""

import os

# Absolute path of the folder that contains this file (the project root).
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ------------------------------------------------------------------
    # Core Flask settings
    # ------------------------------------------------------------------
    # The secret key signs the session cookie.  In production it must come
    # from an environment variable; the fallback keeps development simple.
    SECRET_KEY = os.environ.get("SECRET_KEY", "agrivision-dev-secret-key-change-me")

    # ------------------------------------------------------------------
    # Database (SQLite file stored inside the instance/ folder)
    # ------------------------------------------------------------------
    INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(INSTANCE_DIR, "agrivision.db")
    )
    # Heroku hands out "postgres://", which SQLAlchemy 2 no longer accepts.
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ------------------------------------------------------------------
    # File uploads
    # ------------------------------------------------------------------
    UPLOAD_ROOT = os.path.join(BASE_DIR, "app", "static", "uploads")
    CROP_IMAGE_DIR = os.path.join(UPLOAD_ROOT, "crops")
    CERTIFICATE_DIR = os.path.join(UPLOAD_ROOT, "certificates")

    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    ALLOWED_DOC_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}

    # Largest request Flask will accept: 8 MB.
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024

    # ------------------------------------------------------------------
    # Business rules
    # ------------------------------------------------------------------
    # Crops that legally/commercially need a quality certificate before they
    # can be sold to an export or institutional buyer.
    CERTIFICATE_REQUIRED_CROPS = {"Grapes", "Pomegranate", "Mango", "Banana"}

    # Quality grades used across the whole platform, best first.
    GRADE_ORDER = ["A", "B", "C"]

    # Number of items per page in listing screens.
    PAGE_SIZE = 9


def ensure_directories():
    """Create every folder the app writes into. Called once at start-up."""
    for path in (
        Config.INSTANCE_DIR,
        Config.UPLOAD_ROOT,
        Config.CROP_IMAGE_DIR,
        Config.CERTIFICATE_DIR,
    ):
        os.makedirs(path, exist_ok=True)
