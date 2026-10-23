"""
AgriVision — authentication blueprint.

Routes
    GET  /auth/register              role chooser
    GET  /auth/register/<role>       farmer or buyer sign-up form
    POST /auth/register/<role>       create the account
    GET  /auth/login                 login form
    POST /auth/login                 verify credentials, start the session
    GET  /auth/logout                end the session
    GET/POST /auth/profile           view and edit own profile

Design decisions
----------------
* One `users` table with a `role` column rather than two tables.  Both sides
  share identity, location and security logic; only a few columns differ.
  Access separation is enforced at the route level by @role_required.
* Passwords are stored as PBKDF2-SHA256 hashes (Werkzeug default) — the raw
  password never touches the database or the logs.
* A user who lands on a protected page is bounced to /auth/login?next=...
  and returned to the original page after a successful login.  `next` is
  validated to be a relative path so it cannot be used for open redirects.
"""

from flask import (Blueprint, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..i18n import t
from ..models import User
from ..utils import (clean, to_float, validate_email, validate_password,
                     validate_phone)

auth_bp = Blueprint("auth", __name__, template_folder="../templates/auth")

ROLE_LABELS = {"farmer": "Farmer", "buyer": "Buyer"}
BUYER_TYPES = ["Trader", "Exporter", "Retailer / Mall", "Food Processor",
               "FPO / Co-operative", "Hotel / Restaurant"]


# ----------------------------------------------------------------------
# REGISTRATION
# ----------------------------------------------------------------------
@auth_bp.route("/register")
def register_choice():
    """Step 1 — pick which kind of account to open."""
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    return render_template("auth/register_choice.html")


@auth_bp.route("/register/<role>", methods=["GET", "POST"])
def register(role):
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    if role not in ROLE_LABELS:
        flash(t("Unknown account type."), "danger")
        return redirect(url_for("auth.register_choice"))

    form = {}
    errors = {}

    if request.method == "POST":
        form = {k: clean(v) for k, v in request.form.items() if k != "password"}

        full_name = clean(request.form.get("full_name"), 120)
        email = clean(request.form.get("email"), 120).lower()
        phone = clean(request.form.get("phone"), 15)
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        # --- field validation ----------------------------------------
        if len(full_name) < 3:
            errors["full_name"] = "Please enter your full name."
        errors["email"] = validate_email(email)
        errors["phone"] = validate_phone(phone)
        errors["password"] = validate_password(password)
        if not errors.get("password") and password != confirm:
            errors["confirm_password"] = "The two passwords do not match."
        if not clean(request.form.get("district")):
            errors["district"] = "District is required — it drives regional price insights."

        # --- uniqueness ----------------------------------------------
        if not errors.get("email") and User.query.filter_by(email=email).first():
            errors["email"] = "An account with this email already exists."
        if not errors.get("phone") and User.query.filter_by(phone=phone).first():
            errors["phone"] = "An account with this mobile number already exists."

        errors = {k: v for k, v in errors.items() if v}

        if not errors:
            user = User(
                full_name=full_name, email=email, phone=phone, role=role,
                state=clean(request.form.get("state"), 60) or "Maharashtra",
                district=clean(request.form.get("district"), 60),
                taluka=clean(request.form.get("taluka"), 60),
                pincode=clean(request.form.get("pincode"), 6),
            )
            user.set_password(password)

            if role == "farmer":
                user.farm_size_acres = to_float(request.form.get("farm_size_acres"))
            else:
                user.company_name = clean(request.form.get("company_name"), 120)
                user.buyer_type = clean(request.form.get("buyer_type"), 40)
                user.gst_number = clean(request.form.get("gst_number"), 20)

            # Carry the language they were reading the sign-up form in, so the
            # account starts in the language they already chose.
            from ..i18n import get_locale
            user.language = get_locale()

            db.session.add(user)
            db.session.commit()

            login_user(user)
            # Straight to the one-screen guide for their role rather than the
            # dashboard; the guide itself offers Skip.
            return redirect(url_for("main.guide"))

        flash(t("Please correct the highlighted fields."), "danger")

    return render_template(
        "auth/register.html", role=role, role_label=ROLE_LABELS[role],
        form=form, errors=errors, buyer_types=BUYER_TYPES,
    )


# ----------------------------------------------------------------------
# LOGIN / LOGOUT
# ----------------------------------------------------------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(f"{current_user.role}.dashboard"))

    error = None
    identifier = ""

    if request.method == "POST":
        identifier = clean(request.form.get("identifier"), 120).lower()
        password = request.form.get("password") or ""
        chosen_role = request.form.get("role")          # optional role tab

        # Accept either the email or the mobile number as the username.
        user = (User.query.filter_by(email=identifier).first()
                or User.query.filter_by(phone=identifier).first())

        if not user or not user.check_password(password):
            # Deliberately vague: never reveal which half was wrong.
            error = "Incorrect email/mobile or password."
        elif chosen_role and chosen_role in ROLE_LABELS and user.role != chosen_role:
            error = (f"This account is registered as a {ROLE_LABELS[user.role]}. "
                     f"Switch to the {ROLE_LABELS[user.role]} tab to log in.")
        else:
            login_user(user, remember=bool(request.form.get("remember")))
            session.permanent = True
            flash(t("Logged in as {name}.", name=user.full_name), "success")

            nxt = request.args.get("next") or request.form.get("next")
            if nxt and nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for(f"{user.role}.dashboard"))

        flash(t(error), "danger")

    return render_template("auth/login.html", error=error, identifier=identifier,
                           next=request.args.get("next", ""))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash(t("You have been logged out."), "info")
    return redirect(url_for("main.home"))


# ----------------------------------------------------------------------
# PROFILE
# ----------------------------------------------------------------------
@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        action = request.form.get("action", "details")

        if action == "password":
            current = request.form.get("current_password") or ""
            new = request.form.get("new_password") or ""
            confirm = request.form.get("confirm_password") or ""

            if not current_user.check_password(current):
                flash(t("Your current password is incorrect."), "danger")
            elif validate_password(new):
                flash(t(validate_password(new)), "danger")
            elif new != confirm:
                flash(t("The new passwords do not match."), "danger")
            else:
                current_user.set_password(new)
                db.session.commit()
                flash(t("Password updated."), "success")
            return redirect(url_for("auth.profile"))

        current_user.full_name = clean(request.form.get("full_name"), 120) or current_user.full_name
        current_user.state = clean(request.form.get("state"), 60)
        current_user.district = clean(request.form.get("district"), 60)
        current_user.taluka = clean(request.form.get("taluka"), 60)
        current_user.pincode = clean(request.form.get("pincode"), 6)

        if current_user.is_farmer:
            current_user.farm_size_acres = to_float(request.form.get("farm_size_acres"))
        else:
            current_user.company_name = clean(request.form.get("company_name"), 120)
            current_user.buyer_type = clean(request.form.get("buyer_type"), 40)
            current_user.gst_number = clean(request.form.get("gst_number"), 20)

        db.session.commit()
        flash(t("Profile updated."), "success")
        return redirect(url_for("auth.profile"))

    return render_template("auth/profile.html", buyer_types=BUYER_TYPES)
