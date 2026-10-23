"""
AgriVision — public pages and cross-cutting routes.

    /                 landing page with live platform statistics
    /about            how the platform and its AI modules work
    /notifications    the alert centre
"""

from flask import (Blueprint, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_required
from sqlalchemy import func

from ..extensions import db
from ..i18n import LANGUAGES, t
from ..models import Crop, DealRequest, Notification, Requirement, User

main_bp = Blueprint("main", __name__)


# ----------------------------------------------------------------------
# LANGUAGE
# ----------------------------------------------------------------------
@main_bp.route("/lang/<code>")
def set_language(code):
    """
    Switch the interface language.

    Stored in the session so it survives the visit, and on the user record
    when signed in so it follows them to another device. Returns the visitor
    to the page they were on, after checking the target is a path on this site
    — `next`-style parameters are a classic open-redirect hole.
    """
    if code not in LANGUAGES:
        return redirect(url_for("main.home"))

    session["lang"] = code
    session.permanent = True

    if current_user.is_authenticated:
        current_user.language = code
        db.session.commit()

    nxt = request.args.get("next") or request.referrer or url_for("main.home")
    if not nxt.startswith("/") or nxt.startswith("//"):
        from urllib.parse import urlparse
        ref = urlparse(nxt)
        nxt = ref.path or url_for("main.home")
        if ref.query:
            nxt = f"{nxt}?{ref.query}"
    return redirect(nxt)


@main_bp.route("/")
def home():
    stats = {
        "farmers": User.query.filter_by(role="farmer").count(),
        "buyers": User.query.filter_by(role="buyer").count(),
        "listings": Crop.query.filter_by(status="available").count(),
        "requirements": Requirement.query.filter_by(status="open").count(),
        "deals": DealRequest.query.filter(
            DealRequest.status.in_(["accepted", "completed"])).count(),
        "quantity": db.session.query(func.sum(Crop.quantity)).filter(
            Crop.status == "available").scalar() or 0,
    }

    featured = (Crop.query
                .filter(Crop.status == "available", Crop.ai_grade.isnot(None))
                .order_by(Crop.ai_quality_score.desc(), Crop.created_at.desc())
                .limit(6).all())

    open_reqs = (Requirement.query
                 .filter_by(status="open")
                 .order_by(Requirement.created_at.desc())
                 .limit(4).all())

    return render_template("main/home.html", stats=stats,
                           featured=featured, open_reqs=open_reqs)


@main_bp.route("/about")
def about():
    return render_template("main/about.html")


# ----------------------------------------------------------------------
# ONBOARDING — the one-screen quick-start guide
# ----------------------------------------------------------------------
# Shown once, right after registration, with the steps that matter for that
# role. It is a single screen rather than a multi-step tour on purpose: a
# farmer opening this on a phone wants to see the whole thing and get on with
# listing a crop, not click "Next" four times.
#
# Skipping is a first-class choice, not a hidden link — an experienced user
# should not have to read a guide to reach their dashboard. Either way the
# guide stays reachable from the profile menu, so skipping costs nothing.

FARMER_STEPS = [
    {
        "icon": "camera",
        "title": "Photograph your crop",
        "body": "Spread the lot out in daylight and take 3 to 5 photos from "
                "different sides, filling the frame with the produce. The clearer "
                "the photo, the fairer the grade.",
    },
    {
        "icon": "cpu",
        "title": "Let the AI grade and price it",
        "body": "Colour, uniformity, blemishes and size are scored automatically "
                "into a Grade A, B or C. A fair price band is then worked out from "
                "the last 45 days of your own district's mandi rates.",
    },
    {
        "icon": "patch-check",
        "title": "Upload your certificate",
        "body": "Grapes, pomegranate, mango and banana need a quality certificate "
                "before they can be sold here. Photograph the whole page and it is "
                "checked and verified in seconds.",
    },
    {
        "icon": "chat-dots",
        "title": "Answer buyers directly",
        "body": "Buyers send you requests, and you can offer your lot against what "
                "they have asked for. Accept, decline or negotiate — contact "
                "details are shared once you accept.",
    },
]

BUYER_STEPS = [
    {
        "icon": "megaphone",
        "title": "Post what you need",
        "body": "Give the crop, quantity, minimum grade and your price range. "
                "Every farmer growing that crop is notified, and matching lots "
                "appear on your requirement page.",
    },
    {
        "icon": "funnel",
        "title": "Filter on grade, not on guesswork",
        "body": "Every lot carries an independent AI quality grade and, where it "
                "applies, a verified certificate. Filter on both so you only look "
                "at lots worth travelling for.",
    },
    {
        "icon": "currency-rupee",
        "title": "Check the fair price band",
        "body": "Each lot shows the fair price band for its grade and district "
                "alongside the asking price, so you can see at a glance whether "
                "there is room to negotiate.",
    },
    {
        "icon": "columns-gap",
        "title": "Compare, then buy direct",
        "body": "Put up to four lots side by side and compare quality per rupee. "
                "Send a buying request straight to the farmer — no commission "
                "agent in between.",
    },
]


@main_bp.route("/guide")
@login_required
def guide():
    """The quick-start guide. Shown once after registration, and on demand."""
    steps = FARMER_STEPS if current_user.is_farmer else BUYER_STEPS
    first_run = not current_user.onboarding_seen
    return render_template("main/guide.html", steps=steps, first_run=first_run)


@main_bp.route("/guide/done", methods=["POST"])
@login_required
def guide_done():
    """
    Mark the guide as seen, whether it was read through or skipped, so it is
    never forced on this user again.

    Skipping lands on the dashboard; finishing lands on the thing the guide
    just told them to do, because a guide that ends by dropping you somewhere
    unrelated wastes the attention it asked for.
    """
    current_user.onboarding_seen = True
    db.session.commit()

    if request.form.get("skip"):
        return redirect(url_for(f"{current_user.role}.dashboard"))

    if current_user.is_farmer:
        return redirect(url_for("farmer.new_crop"))
    return redirect(url_for("buyer.browse"))


# ----------------------------------------------------------------------
# NOTIFICATIONS
# ----------------------------------------------------------------------
@main_bp.route("/notifications")
@login_required
def notifications():
    items = (Notification.query
             .filter_by(user_id=current_user.id)
             .order_by(Notification.created_at.desc())
             .limit(60).all())
    return render_template("main/notifications.html", items=items)


@main_bp.route("/notifications/<int:nid>/open")
@login_required
def open_notification(nid):
    n = Notification.query.get_or_404(nid)
    if n.user_id != current_user.id:
        flash(t("That notification does not belong to your account."), "danger")
        return redirect(url_for("main.notifications"))
    n.is_read = True
    db.session.commit()
    return redirect(n.link or url_for("main.notifications"))


@main_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .update({"is_read": True})
    db.session.commit()
    flash(t("All notifications marked as read."), "info")
    return redirect(url_for("main.notifications"))
