# 00 · System overview

**Read this first.** It explains how the pieces fit together; every other
document in `docs/` zooms into one piece.

---

## 1. The problem the project solves

A farmer selling 85 quintal of grapes faces three disadvantages at the moment of
sale:

1. **He does not know what his produce is worth.** The commission agent does.
2. **He cannot prove quality.** "Good quality" is the agent's word against his.
3. **He cannot reach the buyer directly.** The buyer is three intermediaries away,
   and each one takes a cut.

AgriVision attacks all three. The farmer photographs the lot; a computer-vision
model grades it and publishes that grade to every buyer. A pricing engine reads
the last 45 days of his own district's mandi data and publishes a fair price
band. Buyers browse, filter on the grade, and send a request straight to him.

---

## 2. Architecture

```
                     ┌─────────────────────────────────────────┐
   Browser ────────▶ │          Flask application               │
   (Bootstrap,       │                                          │
    Chart.js)        │  routes/   auth · farmer · buyer ·        │
                     │            deals · insights · main        │
                     │      │                                    │
                     │      ▼                                    │
                     │  ai/       grading · pricing ·            │
                     │            demand  · certificate          │
                     │      │                                    │
                     │      ▼                                    │
                     │  models.py  (SQLAlchemy ORM)              │
                     └──────┬──────────────────┬─────────────────┘
                            ▼                  ▼
                   SQLite (agrivision.db)   static/uploads/
                   9 tables                 crop photos, certificates
```

Three layers, strictly separated:

| Layer | Folder | Rule |
|---|---|---|
| **Presentation** | `app/templates/`, `app/static/` | No business logic. Jinja2 only displays what the view passes it. |
| **Application** | `app/routes/` | Handles HTTP, enforces access control, calls the AI layer, writes to the DB. |
| **Intelligence** | `app/ai/` | Pure Python/NumPy/OpenCV. Knows nothing about Flask, HTTP or sessions. |
| **Data** | `app/models.py` | The nine tables and the relationships between them. |

**Why the AI layer knows nothing about Flask:** every function in `app/ai/` can
be imported and tested from a plain Python script. That matters for the project
report — you can show the grader working on a sample photo without starting a
web server, and you can swap the grading model later without touching a single
route.

---

## 3. The two sides of the platform

Both roles live in one `users` table separated by a `role` column
(`'farmer'` or `'buyer'`). The URL space is split:

| URL prefix | Who can enter | Blueprint |
|---|---|---|
| `/` , `/about` | everyone | `main.py` |
| `/auth/…` | everyone (logged out) | `auth.py` |
| `/farmer/…` | farmers only | `farmer.py` |
| `/buyer/…` | buyers only | `buyer.py` |
| `/deals/…` | both, but only the two parties to that deal | `deals.py` |
| `/insights/…` | both, any logged-in user | `insights.py` |

A buyer who types `/farmer/dashboard` gets a **403 Access denied** page, not a
silent redirect. The guard is the `@role_required("farmer")` decorator in
`app/utils.py` — see `docs/02_authentication.md`.

---

## 4. End-to-end flow — one complete trade

This is the single most useful thing to be able to narrate in a viva.

```
 FARMER                              SYSTEM                           BUYER
   │                                                                    │
   │ 1. uploads 3 photos ────────▶ grading.grade_many()                 │
   │                                 colour / uniformity /              │
   │                                 defects / size  →  Grade B, 58/100 │
   │                                      │                             │
   │                               pricing.suggest_price()              │
   │                                 Nashik median × grade × season     │
   │                                 × demand × premiums                │
   │                                 →  ₹6,690 (band ₹5,490–₹7,900)     │
   │ ◀── "your ₹6,140 is inside the fair band"                          │
   │                                                                    │
   │ 2. uploads certificate ─────▶ certificate.verify_certificate()     │
   │                                 OCR → fields → QR → ELA →          │
   │                                 10 checks → VERIFIED (100%)        │
   │                                 lot becomes tradeable              │
   │                                                                    │
   │                               the lot appears in /buyer/browse ───▶│
   │                                                                    │ 3. filters
   │                                                                    │    Grade B+,
   │                                                                    │    certified
   │                                                                    │
   │                               ◀───────────── 4. sends a request    │
   │ ◀── notification                 DealRequest(status='pending')     │
   │                                                                    │
   │ 5. accepts ─────────────────▶ lot → 'reserved'                     │
   │                                 contact details revealed ─────────▶│
   │                                                                    │
   │ 6. ─────── chat, delivery, payment arranged in the thread ────────▶│
   │                                                                    │
   │ 7. marks complete ──────────▶ quantity reduced, lot → 'sold',      │
   │                                 requirement closed if fulfilled    │
```

The reverse direction also exists: a buyer posts a **requirement**, matching
farmers are notified, and a farmer sends an **offer** against it. Same
`DealRequest` table, `initiated_by='farmer'` instead of `'buyer'`.

---

## 5. Request lifecycle inside Flask

What actually happens when the browser asks for `/farmer/crops/1`:

1. **`run.py`** has already called `create_app()` (the application factory in
   `app/__init__.py`), which registered all six blueprints.
2. Flask matches the URL to `farmer.crop_detail` in `app/routes/farmer.py`.
3. `@role_required("farmer")` runs first. Not logged in → redirect to login.
   Logged in as a buyer → `abort(403)`.
4. `_own_crop(1)` loads the row and checks `crop.farmer_id == current_user.id`,
   so farmer A cannot read farmer B's lot by changing the number in the URL.
5. The view calls `suggest_price()`, `price_trend()` and `demand_index()`.
6. It renders `templates/farmer/crop_detail.html` with those results.
7. Jinja2 produces HTML; Bootstrap and `style.css` make it look like something.

---

## 6. Technology choices and why

| Choice | Reason |
|---|---|
| **Flask** over Django | Small enough to read end to end, which matters when you have to explain every line. No hidden magic. |
| **SQLite** over MySQL | Zero installation — the database is one file. Copy the project folder to another laptop and it still runs. Swapping to MySQL/PostgreSQL is a one-line change in `config.py`. |
| **SQLAlchemy ORM** | Tables are Python classes, relationships are attributes. No hand-written SQL to get wrong, and it keeps the code database-agnostic. |
| **OpenCV** over a deep-learning model | A CNN needs thousands of labelled crop images that do not exist for Indian mandi produce. The metric-based grader is explainable — you can point at *why* a lot scored 58 — and runs on a laptop CPU in milliseconds. |
| **Tesseract OCR** | The only mature open-source OCR engine; free, offline, no API key. |
| **Blueprints** | Each functional area is a separate file. Six people can work on six blueprints without colliding. |
| **Application factory** | Lets the test suite build a second app against a temporary database. |
| **Bundled Bootstrap/Chart.js** | The demo must not fail because the Wi-Fi is down. |

---

## 7. The nine database tables

| Table | Holds | Key relationships |
|---|---|---|
| `users` | farmers and buyers | 1 → many crops / requirements |
| `crops` | a lot offered for sale | belongs to a farmer |
| `crop_photos` | one photo + its CV analysis | belongs to a crop |
| `certificates` | an uploaded certificate + verdict | belongs to a crop |
| `requirements` | a buyer's "crop wanted" notice | belongs to a buyer |
| `deal_requests` | the negotiation thread | links a crop, a farmer, a buyer |
| `messages` | chat inside a deal | belongs to a deal |
| `price_records` | historical mandi prices | the fuel for pricing + demand |
| `notifications` | the bell icon items | belongs to a user |

Full column-by-column description: `docs/01_foundation_and_database.md`.

---

## 8. Where to go next

| You want to… | Read |
|---|---|
| Understand the tables and the app factory | `01_foundation_and_database.md` |
| Explain login and access control | `02_authentication.md` |
| Explain how a photo becomes a grade | `03_ai_crop_grading.md` |
| Explain how the price is computed | `04_ai_price_engine.md` |
| Explain the demand index and forecast | `05_ai_demand_prediction.md` |
| Explain certificate verification | `06_ai_certificate_ocmr.md` |
| Work on the farmer screens | `07_farmer_module.md` |
| Work on the buyer screens | `08_buyer_module.md` |
| Explain the request → deal workflow | `09_deal_lifecycle.md` |
| Change the look of the site | `10_frontend_and_templates.md` |
| Run the tests or deploy it | `11_testing_and_deployment.md` |
| Understand where the crop photos come from | `12_photography_pipeline.md` |
| Add a language, or change the first-run guide | `13_multilingual_and_onboarding.md` |
