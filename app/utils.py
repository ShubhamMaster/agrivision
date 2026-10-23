"""
AgriVision — shared helpers used by every blueprint.

    role_required()      access-control decorator (farmer-only / buyer-only)
    save_upload()        safe, collision-free file saving
    validators           small field validators that return error strings
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from functools import wraps

from flask import abort, current_app, flash, redirect, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename


# ======================================================================
# ACCESS CONTROL
# ======================================================================
def role_required(*roles):
    """
    Guard a view so only the listed roles can reach it.

        @farmer_bp.route("/dashboard")
        @role_required("farmer")
        def dashboard(): ...

    An anonymous visitor is sent to the login page; a logged-in user with the
    wrong role gets a 403 page instead of a silent redirect, because silently
    bouncing a buyer to the farmer dashboard would be confusing.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("auth.login", next=request_path()))
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def request_path():
    from flask import request
    return request.full_path if request.query_string else request.path


# ======================================================================
# FILE UPLOADS
# ======================================================================
def allowed_file(filename: str, allowed: set[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def save_upload(file_storage, folder: str, allowed: set[str],
                prefix: str = "") -> tuple[str | None, str | None]:
    """
    Save one uploaded file.

    Returns (stored_filename, error_message).  The stored name is
    `<prefix><timestamp>_<uuid8>.<ext>` so two farmers uploading "IMG_1234.jpg"
    never collide and the original name can never traverse the filesystem.
    """
    if not file_storage or not file_storage.filename:
        return None, "No file selected."

    original = secure_filename(file_storage.filename)
    if not allowed_file(original, allowed):
        return None, f"Only {', '.join(sorted(allowed)).upper()} files are allowed."

    ext = original.rsplit(".", 1)[1].lower()
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    stored = f"{prefix}{stamp}_{uuid.uuid4().hex[:8]}.{ext}"

    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, stored)
    file_storage.save(path)

    if os.path.getsize(path) == 0:
        os.remove(path)
        return None, "The uploaded file was empty."
    return stored, None


def crop_image_path(filename: str) -> str:
    return os.path.join(current_app.config["CROP_IMAGE_DIR"], filename)


def certificate_path(filename: str) -> str:
    return os.path.join(current_app.config["CERTIFICATE_DIR"], filename)


def delete_file(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ======================================================================
# VALIDATORS  (each returns None when valid, or an error string)
# ======================================================================
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")


def validate_email(value: str):
    if not value:
        return "Email is required."
    if not EMAIL_RE.match(value.strip()):
        return "Enter a valid email address."
    return None


def validate_phone(value: str):
    if not value:
        return "Mobile number is required."
    if not PHONE_RE.match(value.strip()):
        return "Enter a valid 10-digit Indian mobile number."
    return None


def validate_password(value: str):
    if not value or len(value) < 6:
        return "Password must be at least 6 characters long."
    if value.isdigit():
        return "Password cannot be only digits."
    return None


def to_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def clean(value, limit=200):
    return (value or "").strip()[:limit]
