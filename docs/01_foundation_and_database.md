# 01 · Foundation and database

**Section goal:** the skeleton every other part is bolted onto — configuration,
the application factory, and the nine-table schema.

---

## 1. Files in this section

| File | Lines | Responsibility |
|---|---|---|
| `config.py` | ~70 | Every tunable value: secret key, database URI, upload folders, size limits, business rules. |
| `app/extensions.py` | ~15 | Creates the `db` and `login_manager` objects without an app attached. |
| `app/__init__.py` | ~140 | `create_app()` — builds and wires the whole application. |
| `app/models.py` | ~420 | The nine tables. |
| `run.py` | ~15 | Starts the development server. |

---

## 2. `config.py` — one place for every setting

Nothing anywhere else in the project hard-codes a path or a limit. Three groups:

```python
class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "agrivision-dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(INSTANCE_DIR, "agrivision.db")

    CROP_IMAGE_DIR  = .../app/static/uploads/crops
    CERTIFICATE_DIR = .../app/static/uploads/certificates
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024          # 8 MB

    CERTIFICATE_REQUIRED_CROPS = {"Grapes", "Pomegranate", "Mango", "Banana"}
```

**`SECRET_KEY`** signs the session cookie. If it changes, every logged-in user is
logged out. In production it must come from an environment variable — the
fallback exists only so `python run.py` works out of the box.

**`MAX_CONTENT_LENGTH`** makes Flask reject an oversized upload *before* reading
it into memory, which is what stops someone from exhausting the server's RAM with
a 2 GB file. The rejection is caught by the 413 error handler.

**Moving to MySQL** is one line:

```python
SQLALCHEMY_DATABASE_URI = "mysql+pymysql://user:password@localhost/agrivision"
```

Nothing else in the project changes, because every query goes through the ORM.

---

## 3. `app/extensions.py` — breaking the circular import

```python
db = SQLAlchemy()
login_manager = LoginManager()
```

These are created **without an application**. The reason is a circular import
that otherwise bites you:

- `models.py` needs `db` to define the tables.
- `__init__.py` needs `models.py` to create the tables.
- So if `db` lived in `__init__.py`, `models` would import `__init__`, which
  imports `models`… and Python raises `ImportError`.

Putting the extension objects in a third module that imports nothing from the
project breaks the cycle. They are attached to the real app later with
`db.init_app(app)`.

---

## 4. `app/__init__.py` — the application factory

```python
def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    ensure_directories()

    db.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp,   url_prefix="/auth")
    app.register_blueprint(farmer_bp, url_prefix="/farmer")
    ...
    with app.app_context():
        db.create_all()
    return app
```

**Why a factory instead of a module-level `app = Flask(__name__)`?**
Because a function can be called twice. `tests/test_routes.py` builds its own
application; a second one could point at a temporary database. With a global
`app` object you are stuck with one configuration for the life of the process.

### What else the factory installs

**Three Jinja filters**, usable in any template:

| Filter | Example | Output |
|---|---|---|
| `rupee` | `{{ 1756300 \| rupee }}` | `₹17,56,300` (Indian lakh/crore grouping, not Western thousands) |
| `nicedate` | `{{ crop.harvest_date \| nicedate }}` | `05 Oct 2026` |
| `ago` | `{{ deal.created_at \| ago }}` | `2 days ago` |

The `rupee` filter is worth a look — Indian digit grouping is 2-2-3 from the
right (`17,56,300`), not 3-3-3 (`1,756,300`), so Python's `{:,}` is wrong here
and the grouping is done by hand.

**A context processor** that injects `CROP_LIST`, `APP_NAME` and `current_year`
into every template, so no view has to pass the crop dropdown list.

**Four error handlers** (403, 404, 413, 500). The 500 handler calls
`db.session.rollback()` first — without it a failed transaction stays open and
every subsequent request on that connection fails too.

---

## 5. The database schema

### 5.1 `users`

One table for both roles. The alternative — separate `farmers` and `buyers`
tables — was rejected because both share identity, password hashing, location
and notifications; you would duplicate all of it and then need a union query for
anything that touches both.

| Column | Type | Note |
|---|---|---|
| `id` | int PK | |
| `full_name`, `email`, `phone` | str | email and phone are **unique** and indexed; either can be used to log in |
| `password_hash` | str | PBKDF2-SHA256; the raw password is never stored |
| `role` | str | `'farmer'` or `'buyer'` — **the most important column in the schema** |
| `state`, `district`, `taluka`, `pincode` | str | district drives all regional price and demand queries |
| `farm_size_acres` | float | farmers only |
| `company_name`, `buyer_type`, `gst_number` | str | buyers only |

Helper properties: `is_farmer`, `is_buyer`, `location_label`,
`unread_notification_count()`.

`User` inherits from `UserMixin`, which supplies the four attributes Flask-Login
requires (`is_authenticated`, `is_active`, `is_anonymous`, `get_id`).

### 5.2 `crops` — a lot offered for sale

The central table. Three groups of columns:

- **Declared by the farmer:** `crop_name`, `variety`, `quantity`,
  `harvest_date`, `organic`, `state`, `district`, `market`, `expected_price`,
  `description`.
- **Written by the AI:** `ai_grade`, `ai_quality_score`, `ai_summary`,
  `ai_price_min`, `ai_price_max`, `ai_price_recommended`.
- **Lifecycle:** `status` (`available` / `reserved` / `sold` / `withdrawn`),
  `certificate_required`, `certificate_status`, `views`.

**Why store the AI results instead of computing them on demand?** Because
`/buyer/browse` filters and sorts on grade and price band. Re-running the CV
model for every card on every page load would make the marketplace unusable.
The models run once at upload and the results are cached in these columns.

Three computed properties carry real logic:

```python
@property
def price_vs_ai(self):      # 'below' / 'within' / 'above'
@property
def is_tradeable(self):     # False if a required certificate is not verified
```

`is_tradeable` is the business rule that stops a grapes lot from being sold
before its residue certificate is verified.

### 5.3 `crop_photos`

One row per photo, carrying that photo's own CV analysis: `quality_score`,
`grade`, `colour_score`, `uniformity_score`, `defect_score`, `size_score`,
`sharpness`, `notes`.

**Why per-photo and not just per-lot?** So the farmer can see *which* photo
dragged the grade down and re-shoot that one, and so deleting a photo can
trigger an honest re-grade.

### 5.4 `certificates`

Holds both the extracted fields (`cert_number`, `issuer`, `issue_date`,
`expiry_date`, `holder_name`, `ocr_text`) and the verdict (`status`,
`confidence`, `checks_json`, `remarks`).

`checks_json` stores the full list of ten checks as a JSON string. SQLite has no
array type, and the checks are only ever read back as a whole to render the
report page — so a JSON blob is the right call here rather than an eleventh
table.

### 5.5 `requirements`

A buyer's "crop wanted" notice. The interesting part is a **method on the
model**, not a column:

```python
def matches(self, crop):
    if crop.crop_name.lower() != self.crop_name.lower():      return False
    if crop.status != "available":                             return False
    if self.organic_only and not crop.organic:                 return False
    if self.certificate_mandatory and crop.certificate_status != "verified":
                                                               return False
    if grade_rank(crop.ai_grade) < grade_rank(self.min_grade): return False
    if self.price_max and crop.expected_price > self.price_max * 1.1:
                                                               return False
    return True
```

Putting the matching rule on the model means the farmer dashboard, the farmer's
requirements page and the buyer's requirement page all use **one** definition of
"matching". If the rule changes, it changes in one place.

The 10% tolerance on `price_max` is deliberate: a lot priced slightly over the
ceiling is still worth showing, because price is negotiable.

### 5.6 `deal_requests`

The negotiation thread. Carries `crop_id`, optional `requirement_id`,
`farmer_id`, `buyer_id`, and crucially `initiated_by` (`'farmer'` or `'buyer'`).

`initiated_by` is what makes one table serve both directions: a buying request
and a farmer's offer are the same object seen from opposite ends. It is also
what the accept/reject guard reads — only the side that did **not** start the
thread may answer it.

Two foreign keys point at `users`, so SQLAlchemy cannot guess which is which and
the relationships must be disambiguated:

```python
farmer = db.relationship("User", foreign_keys=[farmer_id])
buyer  = db.relationship("User", foreign_keys=[buyer_id])
```

### 5.7 `messages`, `price_records`, `notifications`

- `messages` — chat inside a deal; `deal_id`, `sender_id`, `body`.
- `price_records` — the historical mandi data: `crop_name`, `state`, `district`,
  `market`, `record_date`, `min/max/modal_price`, `arrivals`. Indexed on
  crop, state, district and date because every pricing and demand query filters
  on exactly those four. The seed loads ~41,000 rows.
- `notifications` — bell items, with a static helper `Notification.push(...)`
  that creates the row and leaves the commit to the caller, so one commit covers
  the whole operation.

---

## 6. Relationships and cascade

```python
crops = db.relationship("Crop", back_populates="farmer",
                        cascade="all, delete-orphan")
```

`back_populates` declares both ends, so `crop.farmer` and `farmer.crops` both
work and stay in sync.

`cascade="all, delete-orphan"` means deleting a crop deletes its photos,
certificates and deal requests automatically — no orphan rows. **Note the limit:**
the cascade removes the database rows but not the JPEG files on disk, which is
why `farmer.delete_crop()` explicitly calls `delete_file()` for each photo
before deleting the row.

---

## 7. Data flow for this section

```
run.py
  └── create_app()
        ├── reads config.py
        ├── ensure_directories()      creates instance/ and uploads/
        ├── db.init_app(app)
        ├── login_manager.init_app(app)
        ├── registers 6 blueprints
        ├── registers filters, context processor, error handlers
        └── db.create_all()           creates the 9 tables if absent
```

`db.create_all()` only creates **missing** tables — it never alters an existing
one. If you add a column to a model later, delete `instance/agrivision.db` and
re-run `python seed.py`, or add Flask-Migrate.

---

## 8. Viva questions

**Q. Why one `users` table instead of separate farmer and buyer tables?**
Both roles share identity, authentication, location and notifications. Splitting
them would duplicate all of that and force a UNION for anything spanning both.
Separation of access is a routing concern, handled by `@role_required`, not a
storage concern.

**Q. What is an application factory and why use one?**
`create_app()` is a function that builds and returns a configured Flask app
instead of creating one at import time. It allows a second app instance with a
different configuration — which is how the test suite runs.

**Q. Why are `db` and `login_manager` in a separate file?**
To break a circular import between `models.py` and `__init__.py`. `extensions.py`
imports nothing from the project, so both can import it safely.

**Q. Why store AI results in columns rather than recomputing?**
The marketplace filters and sorts on grade and price. Recomputing the CV model
per card per page load would take seconds. The models run once at upload.

**Q. What does `cascade="all, delete-orphan"` do, and what does it not do?**
It deletes child rows when the parent is deleted. It does **not** delete uploaded
files from disk — the view does that explicitly.

**Q. Why is `checks_json` a JSON string instead of a table?**
SQLite has no array type and the checks are always read back as a complete set
for one report. A separate table would add a join for no benefit.

**Q. How would you move this to MySQL?**
Change `SQLALCHEMY_DATABASE_URI` in `config.py` and install the driver. The ORM
makes everything else database-agnostic.
