# 11 · Testing, seeding and deployment

**Section goal:** prove the system works, generate demo data, and get it running
on another machine.

---

## 1. The test suite

```bash
python tests/test_routes.py
```

Expected output ends with:

```
RESULT:  75 passed, 0 failed
```

It uses Flask's **test client**, which drives the application in-process without
a running server or a browser.

### What the 75 checks cover

| Group | Checks |
|---|---|
| Public pages | home, about, login, both registration forms, 404 handling, anonymous redirect |
| Farmer side | all 15 farmer pages, the price-suggestion API, creating a listing with a real image upload, re-grading, status change, deletion |
| Buyer side | all buyer pages, filtered browse, comparison, posting a requirement, sending a buying request |
| Deal lifecycle | open thread → post message → accept → verify lot reserved → complete → verify quantity reduced |
| Access control | farmer→buyer area 403, buyer→farmer area 403, farmer A opening farmer B's lot 403, buyer accepting their own request 403, third party opening a deal 403 |
| Languages | Marathi and Hindi render Devanagari, `<html lang>` follows the choice, the choice is saved to the account, an unknown code is refused, and the switcher cannot redirect off-site |
| Onboarding | registration redirects to the guide, each role sees its own steps, skipping marks it seen and reaches the dashboard, finishing reaches the matching action, the guide stays reachable |

### The checks worth having

Five of the 59 are security assertions:

```python
get(c, f"/farmer/crops/{other_crop_id}", 403,
    "farmer cannot open another farmer's lot (403)")
get(c, "/buyer/browse", 403, "farmer cannot reach the buyer marketplace (403)")
r = c.post(f"/deals/{deal_id}/accept", follow_redirects=True)
check("buyer cannot accept their own request", r.status_code == 403)
```

These are the ones to point at when asked "how do you know your access control
works?" They catch IDOR regressions — the classic vulnerability where
`/crops/5` shows you someone else's data.

And three assert that the AI actually ran, not just that a page returned 200:

```python
check("new listing received an AI grade and a price band",
      new_crop.ai_grade is not None and new_crop.ai_price_min is not None)
check("deal is accepted and the lot is reserved",
      d.status == "accepted" and d.crop.status == "reserved")
check("price-suggestion API returns a band",
      js["min"] < js["recommended"] < js["max"])
```

A status-code-only test suite would pass on a page that silently graded nothing.

**Note:** the suite mutates the database (it creates a listing, posts a
requirement and completes a deal). Re-run `python seed.py` afterwards for a clean
demo.

---

## 2. Testing the AI modules directly

Every module in `app/ai/` is plain Python and runs without Flask. This is the
best live demonstration in a viva:

```python
from app.ai.grading import grade_image
r = grade_image("my_photo.jpg", "Grapes")
print(r["grade"], r["score"], r["sub_scores"])
```

The two that touch the database (`pricing`, `demand`) need an app context:

```python
from app import create_app
from app.ai.demand import demand_index, forecast
app = create_app()
with app.app_context():
    print(demand_index("Grapes", "Maharashtra", "Nashik"))
    print(forecast("Grapes", "Maharashtra", "Nashik")["points"])
```

Certificate verification needs only a file:

```python
from app.ai.certificate import verify_certificate
r = verify_certificate("cert.jpg", crop_name="Grapes")
for c in r["checks"]:
    print("PASS" if c["passed"] else "FAIL", c["title"], "|", c["detail"])
```

---

## 3. `seed.py` — the demo data generator

```bash
python seed.py           # drop everything and rebuild
python seed.py --keep    # add to the existing database
```

It produces:

| | |
|---|---|
| Users | 6 farmers, 4 buyers across Nashik, Pune, Solapur, Jalgaon |
| Price history | ~40,900 rows — 14 crops × 4 districts × 730 days |
| Listings | 14 lots with 37 photos, **graded by the real CV model** |
| Certificates | 4, run through the **real OCMR pipeline** (3 verified, 1 expired → rejected) |
| Requirements | 7 open buyer requirements |
| Deals | 5 threads with messages and notifications |

### The important principle

The seed **calls the same AI functions the live application calls**. It does not
write `ai_grade = 'A'` directly. That means:

- the demo data is internally consistent — scores, grades and bands agree;
- running the seed is itself an integration test of all four AI modules;
- a bug in grading shows up as implausible seed data.

### Lot photographs

`app/photo_lot.py` builds each lot photograph: real photographed specimens
composed into a studio shot for nine crops, and a matching render for the five
bulk grain and fibre crops. Three quality tiers vary colour scatter, bruising
and size spread, and the CV grader then analyses the result for real. Full
detail, including the two bugs the real photographs exposed in the grader, is
in `docs/12_photography_pipeline.md`.

### Synthetic certificates

`synth_certificate()` renders an APEDA/GrapeNet-style document with PIL — real
header, labelled fields, analysis clause, signature block, and **a real scannable
QR code** carrying the certificate number. The OCMR pipeline then OCRs it,
extracts the fields, decodes the QR, runs ELA and applies the ten checks.

One certificate is deliberately generated with an expiry date in the past, so the
rejection path is visible in the demo.

### Price history model

```
price(t) = base × seasonal(t) × trend(t) × shock(t) × noise
```

with arrivals moving inversely to price. The inverse relationship is what gives
the demand model's supply-pressure signal something genuine to detect.

**Replacing it with real data** is the strongest single improvement for a final
report: Agmarknet (`agmarknet.gov.in`) and data.gov.in publish real daily mandi
prices. Write a loader that inserts `PriceRecord` rows and every model works
unchanged.

---

## 4. Running on another machine

```bash
# 1. Python 3.10 or newer
python --version

# 2. a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux / macOS

# 3. dependencies
pip install -r requirements.txt

# 4. Tesseract OCR  (needed only for certificate verification)
#    Windows : https://github.com/UB-Mannheim/tesseract/wiki
#    Ubuntu  : sudo apt install tesseract-ocr
#    macOS   : brew install tesseract

# 5. demo data
python seed.py

# 6. run
python run.py
```

Open <http://127.0.0.1:5000>.

### Tesseract on Windows

If it is installed but not on PATH, add this near the top of
`app/ai/certificate.py`:

```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

The code already degrades gracefully: without Tesseract the readability check
fails and certificates are rejected with a readable message rather than crashing.

### PDF certificates

PDF support needs poppler (`pdftoppm`). Without it the user is told to upload an
image instead — handled, not crashed.

---

## 5. Common problems

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: flask_sqlalchemy` | dependencies not installed — `pip install -r requirements.txt` |
| `no such table: users` | run `python seed.py` |
| Icons show as empty boxes | the icon fonts must be in `app/static/vendor/css/fonts/` |
| Charts blank | check the browser console; `/insights/api/trend` must return `ok: true` |
| Every certificate rejected | Tesseract is not installed or not on PATH |
| Crops all grade C | run `python tools/check_hue_bands.py`; a crop under 70% in-band has a miscalibrated `hue_bands` entry in `CROP_CATALOGUE` |
| Crop photos missing | run `python tools/fetch_specimens.py`, then `python seed.py` |
| Changed a model, errors on start | `db.create_all()` never alters existing tables — delete `instance/agrivision.db` and re-seed |
| Port 5000 busy | change the port in `run.py` (macOS AirPlay uses 5000) |

---

## 6. Showing it to an examiner — suggested sequence

1. **Home page** — explain the problem and the four AI modules.
2. **Log in as Ramesh (farmer)** — dashboard, demand panel for Nashik.
3. **List a new crop** — pick the crop, watch the AI price assistant appear,
   type a price and watch the live feedback, upload a photo, submit.
4. **The lot page** — grade, the four sub-scores, the price band with the marker,
   the factor table.
5. **The certificate report** — ten checks, extracted fields, the raw OCR text.
   Then open the rejected one and show that an expired certificate is refused
   despite an 88% score.
6. **Log in as Sahyadri (buyer)** — marketplace, filter on Grade B+ and
   certificate-verified, open a lot, point out that both sides see the same fair
   band.
7. **Compare three lots** — explain the value score.
8. **Send a buying request**, switch back to the farmer, accept it, show the
   contact details appearing, complete it, show the quantity reduce.
9. **Market insights** — the trend chart, the six-week forecast, the four demand
   drivers.
10. **Run `python tests/test_routes.py`** — 59 passed, 0 failed.

---

## 7. Production deployment

Nothing in this project should run as-is on a public server. The development
server is single-threaded and `debug=True` exposes an interactive console.

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 "run:app"
```

The real checklist:

- `SECRET_KEY` from an environment variable, never the fallback.
- `debug=False`.
- PostgreSQL or MySQL instead of SQLite — SQLite serialises writes and will not
  take concurrent users.
- Nginx in front, serving `/static` directly and terminating HTTPS.
- Uploads on object storage (S3) rather than the application disk.
- Grading and OCR moved to a background worker (Celery + Redis) — OCR takes a few
  seconds and should not block a web request.
- CSRF protection (Flask-WTF) and rate limiting (Flask-Limiter).
- Database migrations (Flask-Migrate) instead of `db.create_all()`.
- Logging and error monitoring.

---

## 8. Honest future work

| Area | Next step |
|---|---|
| Price data | load real Agmarknet / data.gov.in history |
| Grading | collect labelled photos and train a CNN to compare against the metric model |
| Certificates | call each authority's verification API instead of checking format |
| Mobile | a PWA or an Android app — farmers photograph with a phone |
| Language | Marathi and Hindi interface; this is a usability blocker, not a nicety |
| Payments | escrow or UPI integration |
| Logistics | transport matching, which is a real friction point in the trade |
| Trust | ratings and transaction history for both sides |
| Scale | pagination, caching, background jobs |

---

## 9. Viva questions

**Q. How did you test it?**
A 59-check end-to-end suite using Flask's test client, covering every route for
both roles, the full deal lifecycle, five access-control assertions and three
assertions that the AI actually produced results — not just that pages returned
200.

**Q. How do you know access control works?**
Five explicit 403 assertions: farmer into the buyer area, buyer into the farmer
area, farmer A opening farmer B's lot, a buyer accepting their own request, and a
third party opening someone else's deal thread.

**Q. Is the demo data hard-coded?**
No. The seed calls the same grading, pricing and verification functions the live
application calls, so the data is internally consistent and running the seed is
itself an integration test.

**Q. Where does the price history come from?**
It is generated by a seasonality + trend + shock + noise model so the project
runs immediately. Agmarknet and data.gov.in publish real daily mandi prices; a
loader writing `PriceRecord` rows is the only change needed.

**Q. What would you change for production?**
Gunicorn behind Nginx, PostgreSQL instead of SQLite, debug off and the secret key
from the environment, uploads on S3, grading and OCR in a Celery worker, CSRF
protection, rate limiting and database migrations.

**Q. What is the biggest limitation?**
The price history is synthetic. Everything else — the CV grading, the OCR
verification, the pricing and demand mathematics — operates on real inputs and
works unchanged the moment real mandi data is loaded.
