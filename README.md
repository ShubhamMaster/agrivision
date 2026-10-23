# AgriVision — AI-powered farmer-to-buyer marketplace

A single platform that connects farmers directly with buyers, removing the
commission agent from the middle. Four AI modules do the work the agent used to
do: grade the produce, fix a fair price, judge demand, and verify the paperwork.

Built with **Python Flask + SQLite + OpenCV + Tesseract OCR**.

---

## Quick start

```bash
# 1. install the dependencies
pip install -r requirements.txt

# 2. install the OCR engine (needed for certificate verification)
#    Windows : download the installer from
#              https://github.com/UB-Mannheim/tesseract/wiki
#    Ubuntu  : sudo apt install tesseract-ocr
#    macOS   : brew install tesseract

# 3. build the demo database (users, 2 years of mandi prices, graded listings)
python seed.py

# 4. run it
python run.py
```

Then open <http://127.0.0.1:5000>.

### Demo logins

| Role   | Email                       | Password    |
|--------|-----------------------------|-------------|
| Farmer | `ramesh@agrivision.in`      | `farmer123` |
| Buyer  | `sahyadri@agrivision.in`    | `buyer123`  |

Every seeded farmer uses `farmer123`, every buyer uses `buyer123`.
Other farmers: sunita@, vikram@, anil@, kavita@, prakash@ — all `@agrivision.in`.
Other buyers: freshmart@, agrotrade@, sunfoods@.

### Check that everything works

```bash
python tests/test_routes.py        # 75 end-to-end checks, expect 0 failures
```

---

## What is in the box

```
agrivision/
├── run.py                  entry point
├── config.py               all settings in one place
├── seed.py                 demo data generator
├── requirements.txt
├── assets/specimens/       real produce photographs (committed, used offline)
├── tools/
│   ├── fetch_specimens.py    one-time specimen download
│   ├── check_hue_bands.py    grading calibration check
│   └── check_translations.py translation coverage report
├── docs/                   ← the explanation sheet for every section
│   ├── 00_overview.md
│   ├── 01_foundation_and_database.md
│   ├── 02_authentication.md
│   ├── 03_ai_crop_grading.md
│   ├── 04_ai_price_engine.md
│   ├── 05_ai_demand_prediction.md
│   ├── 06_ai_certificate_ocmr.md
│   ├── 07_farmer_module.md
│   ├── 08_buyer_module.md
│   ├── 09_deal_lifecycle.md
│   ├── 10_frontend_and_templates.md
│   └── 11_testing_and_deployment.md
├── tests/
│   └── test_routes.py
└── app/
    ├── __init__.py         application factory
    ├── extensions.py       db + login manager
    ├── models.py           9 tables
    ├── utils.py            access control, uploads, validators
    ├── photo_lot.py        builds lot photographs from real specimens
    ├── i18n.py             English / Marathi / Hindi translation catalogue
    ├── ai/
    │   ├── grading.py      OpenCV crop quality grading
    │   ├── pricing.py      price band recommendation
    │   ├── demand.py       demand index + forecast
    │   └── certificate.py  OCMR certificate verification
    ├── routes/
    │   ├── main.py         landing, about, notifications
    │   ├── auth.py         register / login / profile
    │   ├── farmer.py       listings, grading, certificates
    │   ├── buyer.py        marketplace, requirements, comparison
    │   ├── deals.py        request → accept → complete
    │   └── insights.py     market intelligence pages
    ├── templates/          27 Jinja2 templates
    └── static/
        ├── css/style.css
        ├── js/app.js
        ├── vendor/         Bootstrap, Chart.js and the typeface, bundled for offline use
        └── uploads/        crop photos and certificates
```

**The app runs with no internet connection.** Bootstrap, Bootstrap Icons,
Chart.js and the IBM Plex Sans typeface are bundled in `app/static/vendor/`
rather than loaded from a CDN, and the produce photographs are cached in
`assets/specimens/`, so a demo does not depend on the college Wi-Fi.

**Crop photographs.** Nine crops are shown as real photographed produce,
composed into lot shots from the public Fruits-360 dataset (CC BY-SA 4.0); the
five bulk grain and fibre crops are rendered in the same studio style. See
`docs/12_photography_pipeline.md`, including how to substitute your own
photographs.

---

## The four AI modules at a glance

| Module | File | Input | Output |
|---|---|---|---|
| Crop quality grading | `app/ai/grading.py` | crop photos | score 0–100 + Grade A/B/C + 4 sub-scores |
| Price recommendation | `app/ai/pricing.py` | crop, grade, district, month | recommended price + fair band + reasons |
| Demand prediction | `app/ai/demand.py` | crop, district | demand index 0–100 + 6-week forecast |
| Certificate verification | `app/ai/certificate.py` | certificate scan | verified/pending/rejected + 10 checks |

Calibration of the grading hue bands against the real photographs:

```bash
python tools/check_hue_bands.py     # expect every crop above 70% in-band
```

---

## Languages

The whole interface runs in **English, Marathi (मराठी) and Hindi (हिन्दी)** —
including crop names, status words and relative times. Switch from the globe
icon in the navigation; the choice is saved to the account and follows the user
to another device.

```bash
python tools/check_translations.py   # coverage report; currently 100% in both
```

Both typefaces are bundled, so Devanagari renders correctly offline. See
`docs/13_multilingual_and_onboarding.md`.

## First-run guide

A new user lands on a one-screen quick-start guide written for their role —
four steps for a farmer, four different ones for a buyer — with a **Skip**
option. It stays available afterwards under *How to use AgriVision* in the
profile menu.

Each one is plain Python and can be tested on its own without Flask running:

```python
from app.ai.grading import grade_image
print(grade_image("some_photo.jpg", "Grapes"))
```

---

## Reading order for the documentation

Start with `docs/00_overview.md`, which explains the architecture and how a
single request flows through the system. Then read the section document for
whichever part you are working on. Each one contains: what the part does, the
files involved, a walkthrough of the important code, the database tables it
touches, the data flow, and a set of viva-style questions with answers.
