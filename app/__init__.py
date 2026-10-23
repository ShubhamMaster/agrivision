"""
AgriVision — application factory.

create_app() builds a fully wired Flask application:
    1. loads configuration
    2. makes sure upload/instance folders exist
    3. binds the database and the login manager
    4. registers every blueprint (url prefix -> module)
    5. registers Jinja filters, context processors and error pages
    6. creates the tables on first run

Using a factory (instead of a module-level `app = Flask(__name__)`) keeps the
project testable: a test can build a second app pointing at a temp database.
"""

import os
from datetime import datetime

from flask import Flask, render_template

from config import Config, ensure_directories
from .extensions import db, login_manager


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_object)

    ensure_directories()

    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)

    # ------------------------------------------------------------------
    # Blueprints — each one owns a section of the URL space
    # ------------------------------------------------------------------
    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.farmer import farmer_bp
    from .routes.buyer import buyer_bp
    from .routes.deals import deals_bp
    from .routes.insights import insights_bp

    app.register_blueprint(main_bp)                            # /
    app.register_blueprint(auth_bp, url_prefix="/auth")        # /auth/login ...
    app.register_blueprint(farmer_bp, url_prefix="/farmer")    # /farmer/...
    app.register_blueprint(buyer_bp, url_prefix="/buyer")      # /buyer/...
    app.register_blueprint(deals_bp, url_prefix="/deals")      # /deals/...
    app.register_blueprint(insights_bp, url_prefix="/insights")  # /insights/...

    # ------------------------------------------------------------------
    # Jinja helpers available inside every template
    # ------------------------------------------------------------------
    @app.template_filter("rupee")
    def rupee(value):
        """12345.6 -> '₹12,346'  (Indian digit grouping)"""
        if value is None:
            return "—"
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "—"
        n = int(round(value))
        s = str(abs(n))
        if len(s) > 3:
            head, tail = s[:-3], s[-3:]
            parts = []
            while len(head) > 2:
                parts.insert(0, head[-2:])
                head = head[:-2]
            if head:
                parts.insert(0, head)
            s = ",".join(parts) + "," + tail
        return ("-" if n < 0 else "") + "₹" + s

    @app.template_filter("nicedate")
    def nicedate(value):
        if not value:
            return "—"
        return value.strftime("%d %b %Y")

    @app.template_filter("ago")
    def ago(value):
        """
        Relative time, translated. It appears on every card in the
        marketplace, so leaving it in English would undo most of the visible
        effect of switching language.
        """
        from .i18n import t
        if not value:
            return ""
        delta = datetime.utcnow() - value
        secs = delta.total_seconds()
        if secs < 60:
            return t("just now")
        if secs < 3600:
            return t("{n} min ago", n=int(secs // 60))
        if secs < 86400:
            return t("{n} hr ago", n=int(secs // 3600))
        if delta.days < 30:
            return t("{n} days ago", n=delta.days) if delta.days > 1 \
                else t("yesterday")
        return value.strftime("%d %b %Y")

    # Translation helpers are registered as Jinja *globals*, not through a
    # context processor. Context processors do not reach inside imported
    # macros — `{% from "macros.html" import crop_card %}` gets a bare context
    # unless it is imported "with context" — and the macros are exactly where
    # most of the repeated UI text lives. Globals are visible everywhere.
    from .i18n import LANGUAGES, crop_name, get_locale, script_for, t
    app.jinja_env.globals.update(
        t=t,
        crop_name=crop_name,
        LANGUAGES=LANGUAGES,
        current_lang=get_locale,      # called in templates as current_lang()
        page_script=script_for,
    )

    @app.context_processor
    def inject_globals():
        """Values every template can use without the view passing them."""
        from .ai.pricing import CROP_CATALOGUE
        return {
            "CROP_LIST": sorted(CROP_CATALOGUE.keys()),
            "APP_NAME": "AgriVision",
            "current_year": datetime.utcnow().year,
            # Resolved per request so base.html can use them as plain values.
            "current_lang": get_locale(),
            "page_script": script_for(),
        }

    @app.template_filter("tr")
    def tr(value):
        """`{{ crop.status | tr }}` — translate a value that came from the DB."""
        from .i18n import t
        return t(value) if value else value

    # ------------------------------------------------------------------
    # Error pages
    # ------------------------------------------------------------------
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(413)
    def too_large(e):
        return render_template(
            "errors/error.html",
            code=413,
            title="File too large",
            message="Uploads are limited to 8 MB. Please compress the image and try again.",
        ), 413

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("errors/error.html", code=500,
                               title="Something went wrong",
                               message="An internal error occurred. Please try again."), 500

    # ------------------------------------------------------------------
    # Create tables on first run
    # ------------------------------------------------------------------
    with app.app_context():
        db.create_all()

    return app
