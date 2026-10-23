"""
AgriVision — database models (the complete data layer).

Nine tables:

    User           one row per farmer or buyer
    Crop           a crop lot a farmer has put up for sale
    CropPhoto      one photo of a crop lot + the AI analysis of that photo
    Certificate    a quality certificate uploaded against a crop lot
    Requirement    a "crop wanted" notice posted by a buyer
    DealRequest    a buying/offering request exchanged between the two sides
    Message        free-text chat attached to a deal request
    PriceRecord    historical mandi price + arrival data (feeds AI pricing)
    Notification   per-user alert bell items

Relationships are declared with back_populates on both sides so navigation
works in either direction (crop.farmer and farmer.crops, etc.).
"""

from datetime import datetime, date

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db, login_manager


# ======================================================================
# 1. USER
# ======================================================================
class User(UserMixin, db.Model):
    """A platform account. `role` decides which half of the app is unlocked."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # --- identity -----------------------------------------------------
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(15), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # 'farmer' or 'buyer' — the single most important column in the schema.
    role = db.Column(db.String(10), nullable=False, index=True)

    # --- location (used for regional price + demand intelligence) ------
    state = db.Column(db.String(60), default="Maharashtra")
    district = db.Column(db.String(60))
    taluka = db.Column(db.String(60))
    pincode = db.Column(db.String(6))

    # --- role-specific extras ----------------------------------------
    farm_size_acres = db.Column(db.Float)        # farmers only
    company_name = db.Column(db.String(120))     # buyers only
    buyer_type = db.Column(db.String(40))        # Trader / Exporter / Retailer / Processor
    gst_number = db.Column(db.String(20))        # buyers only

    is_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # --- preferences --------------------------------------------------
    # The interface language, so a farmer who picked Marathi on his phone
    # still gets Marathi when he signs in from somewhere else.
    language = db.Column(db.String(5), default="en")
    # Whether the one-screen quick-start guide has been seen or skipped.
    # It is shown once after registration; the guide stays reachable from
    # the profile menu afterwards.
    onboarding_seen = db.Column(db.Boolean, default=False)

    # --- relationships ------------------------------------------------
    crops = db.relationship(
        "Crop", back_populates="farmer", cascade="all, delete-orphan"
    )
    requirements = db.relationship(
        "Requirement", back_populates="buyer", cascade="all, delete-orphan"
    )
    notifications = db.relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )

    # --- password helpers --------------------------------------------
    def set_password(self, raw_password: str) -> None:
        """Hash and store. The plain password is never written to the DB."""
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    # --- convenience --------------------------------------------------
    @property
    def is_farmer(self) -> bool:
        return self.role == "farmer"

    @property
    def is_buyer(self) -> bool:
        return self.role == "buyer"

    @property
    def location_label(self) -> str:
        parts = [p for p in (self.taluka, self.district, self.state) if p]
        return ", ".join(parts) if parts else "Location not set"

    def unread_notification_count(self) -> int:
        return Notification.query.filter_by(user_id=self.id, is_read=False).count()

    def __repr__(self):
        return f"<User {self.id} {self.email} ({self.role})>"


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login calls this on every request to rebuild current_user."""
    return db.session.get(User, int(user_id))


# ======================================================================
# 2. CROP  (a lot offered for sale by a farmer)
# ======================================================================
class Crop(db.Model):
    __tablename__ = "crops"

    id = db.Column(db.Integer, primary_key=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # --- what is being sold -------------------------------------------
    crop_name = db.Column(db.String(60), nullable=False, index=True)
    variety = db.Column(db.String(60))
    quantity = db.Column(db.Float, nullable=False)      # in quintal
    unit = db.Column(db.String(10), default="quintal")
    harvest_date = db.Column(db.Date)
    description = db.Column(db.Text)
    organic = db.Column(db.Boolean, default=False)

    # --- where -------------------------------------------------------
    state = db.Column(db.String(60))
    district = db.Column(db.String(60))
    market = db.Column(db.String(60))                   # nearest APMC / mandi

    # --- price -------------------------------------------------------
    expected_price = db.Column(db.Float)                # what the farmer asks (Rs/quintal)
    ai_price_min = db.Column(db.Float)                  # AI suggested band, lower edge
    ai_price_max = db.Column(db.Float)                  # AI suggested band, upper edge
    ai_price_recommended = db.Column(db.Float)

    # --- AI quality verdict (filled by app/ai/grading.py) -------------
    ai_grade = db.Column(db.String(1))                  # 'A' / 'B' / 'C'
    ai_quality_score = db.Column(db.Float)              # 0-100
    ai_summary = db.Column(db.Text)                     # human-readable explanation

    # --- certification ------------------------------------------------
    certificate_required = db.Column(db.Boolean, default=False)
    certificate_status = db.Column(db.String(12), default="not_required")
    # not_required | pending | verified | rejected

    # --- lifecycle ----------------------------------------------------
    status = db.Column(db.String(12), default="available", index=True)
    # available | reserved | sold | withdrawn
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- relationships ------------------------------------------------
    farmer = db.relationship("User", back_populates="crops")
    photos = db.relationship(
        "CropPhoto", back_populates="crop",
        cascade="all, delete-orphan", order_by="CropPhoto.id",
    )
    certificates = db.relationship(
        "Certificate", back_populates="crop", cascade="all, delete-orphan"
    )
    deal_requests = db.relationship(
        "DealRequest", back_populates="crop", cascade="all, delete-orphan"
    )

    # --- convenience --------------------------------------------------
    @property
    def cover_photo(self):
        return self.photos[0].filename if self.photos else None

    @property
    def grade_label(self) -> str:
        return {
            "A": "Grade A — Premium",
            "B": "Grade B — Standard",
            "C": "Grade C — Economy",
        }.get(self.ai_grade, "Not graded yet")

    @property
    def price_vs_ai(self):
        """
        How the farmer's asking price compares with the AI band.
        Returns 'below' / 'within' / 'above' / None.
        """
        if not self.expected_price or not self.ai_price_min or not self.ai_price_max:
            return None
        if self.expected_price < self.ai_price_min:
            return "below"
        if self.expected_price > self.ai_price_max:
            return "above"
        return "within"

    @property
    def is_tradeable(self) -> bool:
        """A certificate-required crop cannot be traded until it is verified."""
        if self.status != "available":
            return False
        if self.certificate_required and self.certificate_status != "verified":
            return False
        return True

    def __repr__(self):
        return f"<Crop {self.id} {self.crop_name} {self.quantity}q>"


# ======================================================================
# 3. CROP PHOTO  (+ the per-image AI analysis)
# ======================================================================
class CropPhoto(db.Model):
    __tablename__ = "crop_photos"

    id = db.Column(db.Integer, primary_key=True)
    crop_id = db.Column(db.Integer, db.ForeignKey("crops.id"), nullable=False, index=True)

    filename = db.Column(db.String(160), nullable=False)

    # Per-image computer-vision metrics (see app/ai/grading.py)
    quality_score = db.Column(db.Float)
    grade = db.Column(db.String(1))
    colour_score = db.Column(db.Float)
    uniformity_score = db.Column(db.Float)
    defect_score = db.Column(db.Float)
    size_score = db.Column(db.Float)
    sharpness = db.Column(db.Float)
    notes = db.Column(db.Text)

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    crop = db.relationship("Crop", back_populates="photos")

    def __repr__(self):
        return f"<CropPhoto {self.id} grade={self.grade}>"


# ======================================================================
# 4. CERTIFICATE  (quality / residue certificate + OCR verification)
# ======================================================================
class Certificate(db.Model):
    __tablename__ = "certificates"

    id = db.Column(db.Integer, primary_key=True)
    crop_id = db.Column(db.Integer, db.ForeignKey("crops.id"), nullable=False, index=True)

    filename = db.Column(db.String(160), nullable=False)
    cert_type = db.Column(db.String(60))        # GrapeNet / Residue / Organic / AGMARK ...

    # --- fields the OCR engine pulls out of the document --------------
    cert_number = db.Column(db.String(60))
    issuer = db.Column(db.String(120))
    issue_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    holder_name = db.Column(db.String(120))
    ocr_text = db.Column(db.Text)

    # --- verification verdict -----------------------------------------
    status = db.Column(db.String(12), default="pending")   # pending|verified|rejected
    confidence = db.Column(db.Float)                       # 0-100
    checks_json = db.Column(db.Text)                       # JSON list of individual checks
    remarks = db.Column(db.Text)

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_at = db.Column(db.DateTime)

    crop = db.relationship("Crop", back_populates="certificates")

    @property
    def is_expired(self) -> bool:
        return bool(self.expiry_date and self.expiry_date < date.today())

    def __repr__(self):
        return f"<Certificate {self.id} {self.cert_number} {self.status}>"


# ======================================================================
# 5. REQUIREMENT  (a buyer's "crop wanted" notice)
# ======================================================================
class Requirement(db.Model):
    __tablename__ = "requirements"

    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    crop_name = db.Column(db.String(60), nullable=False, index=True)
    variety = db.Column(db.String(60))
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(10), default="quintal")

    min_grade = db.Column(db.String(1), default="B")     # accepts this grade or better
    price_min = db.Column(db.Float)
    price_max = db.Column(db.Float)

    state = db.Column(db.String(60))
    district = db.Column(db.String(60))
    delivery_location = db.Column(db.String(120))
    needed_by = db.Column(db.Date)

    organic_only = db.Column(db.Boolean, default=False)
    certificate_mandatory = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)

    status = db.Column(db.String(10), default="open", index=True)   # open | closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    buyer = db.relationship("User", back_populates="requirements")
    deal_requests = db.relationship(
        "DealRequest", back_populates="requirement", cascade="all, delete-orphan"
    )

    @property
    def is_expired(self) -> bool:
        return bool(self.needed_by and self.needed_by < date.today())

    def matches(self, crop: "Crop") -> bool:
        """Cheap server-side matcher used to suggest crops for a requirement."""
        from .ai.pricing import grade_rank

        if crop.crop_name.lower() != self.crop_name.lower():
            return False
        if crop.status != "available":
            return False
        if self.organic_only and not crop.organic:
            return False
        if self.certificate_mandatory and crop.certificate_status != "verified":
            return False
        if self.min_grade and crop.ai_grade:
            if grade_rank(crop.ai_grade) < grade_rank(self.min_grade):
                return False
        if self.price_max and crop.expected_price and crop.expected_price > self.price_max * 1.1:
            return False
        return True

    def __repr__(self):
        return f"<Requirement {self.id} {self.crop_name} {self.quantity}q>"


# ======================================================================
# 6. DEAL REQUEST  (the actual transaction thread)
# ======================================================================
class DealRequest(db.Model):
    __tablename__ = "deal_requests"

    id = db.Column(db.Integer, primary_key=True)

    crop_id = db.Column(db.Integer, db.ForeignKey("crops.id"), index=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey("requirements.id"), index=True)

    farmer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # Who started the thread: 'buyer' (buying request) or 'farmer' (offer).
    initiated_by = db.Column(db.String(10), nullable=False)

    quantity = db.Column(db.Float, nullable=False)
    offered_price = db.Column(db.Float, nullable=False)
    message = db.Column(db.Text)

    status = db.Column(db.String(12), default="pending", index=True)
    # pending | accepted | rejected | cancelled | completed
    response_note = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime)

    crop = db.relationship("Crop", back_populates="deal_requests")
    requirement = db.relationship("Requirement", back_populates="deal_requests")
    farmer = db.relationship("User", foreign_keys=[farmer_id])
    buyer = db.relationship("User", foreign_keys=[buyer_id])
    messages = db.relationship(
        "Message", back_populates="deal",
        cascade="all, delete-orphan", order_by="Message.created_at",
    )

    @property
    def total_value(self) -> float:
        return (self.quantity or 0) * (self.offered_price or 0)

    @property
    def status_colour(self) -> str:
        return {
            "pending": "warning",
            "accepted": "success",
            "rejected": "danger",
            "cancelled": "secondary",
            "completed": "primary",
        }.get(self.status, "secondary")

    def counterparty(self, user: User) -> User:
        return self.buyer if user.id == self.farmer_id else self.farmer

    def __repr__(self):
        return f"<DealRequest {self.id} {self.status}>"


# ======================================================================
# 7. MESSAGE  (chat inside an accepted/pending deal)
# ======================================================================
class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey("deal_requests.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    deal = db.relationship("DealRequest", back_populates="messages")
    sender = db.relationship("User")


# ======================================================================
# 8. PRICE RECORD  (history that powers trends + demand prediction)
# ======================================================================
class PriceRecord(db.Model):
    __tablename__ = "price_records"

    id = db.Column(db.Integer, primary_key=True)

    crop_name = db.Column(db.String(60), nullable=False, index=True)
    state = db.Column(db.String(60), index=True)
    district = db.Column(db.String(60), index=True)
    market = db.Column(db.String(60))

    record_date = db.Column(db.Date, nullable=False, index=True)
    min_price = db.Column(db.Float)
    max_price = db.Column(db.Float)
    modal_price = db.Column(db.Float, nullable=False)   # most-traded price, Rs/quintal
    arrivals = db.Column(db.Float)                      # quintal arriving that day

    def __repr__(self):
        return f"<PriceRecord {self.crop_name} {self.district} {self.record_date} {self.modal_price}>"


# ======================================================================
# 9. NOTIFICATION
# ======================================================================
class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.String(300))
    link = db.Column(db.String(200))
    icon = db.Column(db.String(30), default="bell")
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="notifications")

    @staticmethod
    def push(user_id, title, body=None, link=None, icon="bell"):
        """Create a notification. The caller is responsible for db.session.commit()."""
        db.session.add(
            Notification(user_id=user_id, title=title, body=body, link=link, icon=icon)
        )
