"""
Shared Flask extension objects.

They are created here *without* an application so that models and blueprints
can import them freely without causing circular imports.  They are bound to
the real application inside create_app() with .init_app(app).
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()

login_manager = LoginManager()
# Anonymous users who hit a protected page are sent to this endpoint.
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "warning"
