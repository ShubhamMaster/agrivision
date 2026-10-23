# 07 · Farmer module

**Section goal:** everything a farmer can do — list crops, get them graded and
priced, upload certificates, and answer buyer requirements.

**Files:** `app/routes/farmer.py` (~520 lines) and seven templates under
`app/templates/farmer/`.

---

## 1. Routes

| Method | URL | Purpose |
|---|---|---|
| GET | `/farmer/dashboard` | summary, pending requests, regional demand |
| GET | `/farmer/crops` | all my listings, filterable by status |
| GET/POST | `/farmer/crops/new` | create a listing — **the AI runs here** |
| GET | `/farmer/crops/<id>` | manage one lot |
| GET/POST | `/farmer/crops/<id>/edit` | edit details, add photos |
| POST | `/farmer/crops/<id>/regrade` | re-run the CV grader |
| POST | `/farmer/crops/<id>/status/<status>` | available / reserved / sold / withdrawn |
| POST | `/farmer/crops/<id>/delete` | delete the lot and its files |
| POST | `/farmer/crops/<id>/photos/<pid>/delete` | remove a photo and re-grade |
| GET/POST | `/farmer/crops/<id>/certificate` | upload + verify a certificate |
| GET | `/farmer/certificates/<id>` | the verification report |
| POST | `/farmer/certificates/<id>/delete` | remove a certificate |
| GET | `/farmer/requirements` | buyer requirements, best matches first |
| POST | `/farmer/requirements/<id>/offer` | offer one of my lots |
| POST | `/farmer/api/price-suggestion` | JSON — the live price helper |

Every one is guarded by `@role_required("farmer")`, and every one that takes an
id passes through `_own_crop()`.

---

## 2. Creating a listing — the central flow

This is the sequence to be able to narrate in a viva.

```
POST /farmer/crops/new
  │
  ├─ 1. validate  crop, quantity, price, at least one photo
  │        └─ errors → re-render the form with messages and the typed values
  │
  ├─ 2. Crop(...)  +  db.session.flush()
  │        flush assigns crop.id without committing — needed for the filenames
  │
  ├─ 3. for each photo: save_upload() → crop{id}_{timestamp}_{uuid}.jpg
  │        └─ db.session.add(CropPhoto(...))
  │
  ├─ 4. _apply_ai(crop, saved_paths)
  │        ├─ grade_many(paths, crop_name)      → grade, score, per-photo metrics
  │        └─ _reprice(crop)
  │              └─ suggest_price(...)           → ai_price_min / max / recommended
  │
  ├─ 5. db.session.commit()                     one transaction for everything
  │
  └─ 6. redirect to the lot page, flashing "AI grade: B (58/100)"
```

### Why `flush()` and not `commit()` in step 2

`flush()` sends the INSERT to the database and gets back the generated primary
key, but **does not end the transaction**. The id is needed to name the files
(`crop7_20261013_a3f9.jpg`). If a photo then fails to save, the whole thing can
still be rolled back — with `commit()` you would be left with a crop row and no
photos.

```python
if not saved_paths:
    db.session.rollback()
    flash("None of the photos could be saved…")
```

### Upload safety — `save_upload()` in `app/utils.py`

```python
original = secure_filename(file_storage.filename)
if not allowed_file(original, allowed): return None, "Only JPG, PNG… allowed."
stored = f"{prefix}{timestamp}_{uuid4().hex[:8]}.{ext}"
```

Three defences:

1. **`secure_filename`** strips directory components. Without it a file named
   `../../../app/__init__.py` would overwrite application code — a path traversal
   attack.
2. **Extension allow-list** — a file named `shell.php` is refused.
3. **Generated storage name** — two farmers both uploading `IMG_1234.jpg` cannot
   collide, and the original name never reaches the filesystem.

A zero-byte file is deleted and reported rather than stored.

---

## 3. `_apply_ai()` — where the modules meet

```python
def _apply_ai(crop, image_paths):
    result = grade_many(image_paths, crop.crop_name)
    if result.get("ok"):
        crop.ai_grade = result["grade"]
        crop.ai_quality_score = result["score"]
        crop.ai_summary = result["summary"]
        by_path = {r["path"]: r for r in result["per_image"]}
        for photo in crop.photos:
            r = by_path.get(crop_image_path(photo.filename))
            photo.quality_score = r["score"]
            photo.colour_score  = r["sub_scores"]["colour"]
            ...
    _reprice(crop)
```

The per-photo results are matched back to `CropPhoto` rows by file path, so the
UI can show which photo scored what — and so deleting the weak photo honestly
changes the lot's grade.

`_reprice()` is called separately because the price must be recomputed in three
situations where the grade has *not* changed: the farmer edits the quantity or
location, a certificate is verified (+8%), or the organic flag is toggled.

---

## 4. The listing form and the live price helper

The form (`crop_form.html`) is used for both create and edit, switched by a
`mode` variable. On edit the crop type is locked — changing grapes into onion
would invalidate the grade, the price band and the certificate requirement, so
the field is disabled and resubmitted as a hidden input.

Beside the form sits the **AI price assistant**. As soon as a crop is chosen,
JavaScript POSTs to `/farmer/api/price-suggestion` and renders:

- the recommended price and the fair band,
- the demand badge for that crop and district,
- every pricing factor with its percentage and reason,
- a "Use ₹6,690 as my price" button,
- and live feedback as the farmer types his own number.

```javascript
if (v < lastBand.min)  "₹X below the fair band — you may be under-selling."
if (v > lastBand.max)  "₹X above the fair band — buyers may skip this listing."
else                   "Inside the AI fair band. Good pricing."
```

This happens **before** anything is saved, which is the point: the farmer sees
the market before he commits to a number.

---

## 5. The lot page

`crop_detail.html` is the densest screen in the application. Left column:

- **Photos** with each one's grade badge, a delete button (blocked at the last
  photo), and a "Re-run AI grading" button.
- **AI quality report** — the big grade letter, the 0–100 score, and four
  progress bars for colour, uniformity, defects and size, averaged across photos.
  This is where the farmer learns *why* he got a B.
- **Certificates** with status badges and a link to the full report. A warning
  banner appears if the crop needs one and does not have it.
- **Requests on this lot.**

Right column:

- **Pricing** — his asking price, the lot value, a verdict alert, the band with a
  marker showing where his price sits, and a table of every pricing factor.
- **Demand & market** — the index gauge, plain-language advice, the four demand
  drivers, and the latest modal price.
- **Lot details.**

The band visual is pure CSS: a gradient track with an absolutely positioned
marker whose `left` percentage is computed in the template.

---

## 6. Certificate upload

```python
stored, err = save_upload(f, CERTIFICATE_DIR, ALLOWED_DOC_EXTENSIONS, …)
cert = Certificate(crop_id=crop.id, filename=stored, …)
db.session.flush()

result = cert_ai.verify_certificate(certificate_path(stored),
                                    crop_name=crop.crop_name,
                                    holder_name=current_user.full_name)
# copy fields + verdict onto the row
crop.certificate_status = _best_cert_status(crop, cert)
if crop.certificate_status == "verified":
    _reprice(crop)
```

`_best_cert_status()` takes the **best** status across all certificates on the
lot (verified > pending > rejected), so a farmer whose first scan was too dark
can upload a better copy without the rejected one holding him back.

The report page is readable by the farmer who owns it, and by a buyer **only if
that buyer has a deal on the lot** — otherwise the certificate's details are a
private document.

---

## 7. Buyer requirements, from the farmer's side

```python
rows.sort(key=lambda x: (not x["matched"], not x["same_district"]))
```

Requirements the farmer can actually fulfil float to the top, then ones in his
own district. A farmer with ten minutes should see his best opportunities first.

Matching uses `Requirement.matches(crop)` — the one definition on the model, so
the farmer's list and the buyer's list can never disagree.

Each matching row expands into an inline offer form (crop selector, quantity,
price, message) that posts to `/farmer/requirements/<id>/offer` and creates a
`DealRequest` with `initiated_by='farmer'`, plus a notification for the buyer.

Non-matching rows say plainly why: "None of your available lots meets this
requirement (check grade, organic or certificate conditions)."

---

## 8. The dashboard

Six statistic tiles, then:

- **Pending buying requests** — the most urgent thing on the screen.
- **Recent listings** as a table with grade, price, AI band and status.
- **Matching requirements.**
- **Demand in \<district\>** — `top_demand_crops()` for his region, each linking
  to the full crop report. For a farmer deciding what to plant next season, this
  is the most valuable panel in the application.
- **Tips for a better grade** — concrete photography advice that directly raises
  his score, derived from what the grading model actually measures.

---

## 9. Data flow summary

```
new_crop()  → save photos → grade_many() → suggest_price() → commit
edit_crop() → new photos? → _apply_ai()  : _reprice()      → commit
regrade()   → _apply_ai()                                   → commit
upload_certificate() → verify_certificate() → _best_cert_status()
                     → verified? _reprice()                 → commit
offer()     → DealRequest(initiated_by='farmer') + Notification → commit
```

---

## 10. Viva questions

**Q. Walk through what happens when a farmer lists a crop.**
Validate; create the Crop row and flush to get its id; save each photo under a
generated name; run `grade_many()` for the grade, score and per-photo metrics;
run `suggest_price()` for the band; commit everything in one transaction;
redirect with a flash showing the grade.

**Q. Why `flush()` rather than `commit()` before saving the photos?**
Flush assigns the primary key without ending the transaction, so the id can be
used in the filenames while the whole operation remains rollback-able if a photo
fails.

**Q. How are uploads made safe?**
`secure_filename` strips path components to prevent traversal; the extension is
checked against an allow-list; the file is stored under a generated
timestamp+UUID name so uploads cannot collide or carry a dangerous name;
`MAX_CONTENT_LENGTH` caps the size at 8 MB.

**Q. Why can a farmer not change the crop type when editing?**
The grade, the price band and the certificate requirement are all specific to the
crop. Changing it would leave stale AI results attached to a different product.

**Q. What happens when a photo is deleted?**
The file is removed, the row is deleted, and the lot is re-graded from the
remaining photos. The last photo cannot be deleted, because the grade must rest
on some evidence.

**Q. Why re-price when a certificate is verified?**
A verified certificate adds an 8% premium, so the band is recomputed and stored.

**Q. How does the farmer know which requirements he can fulfil?**
`Requirement.matches(crop)` is evaluated for each of his available lots, matching
rows are sorted to the top, and non-matching rows explain which condition failed.

**Q. Where does the live price suggestion come from?**
`/farmer/api/price-suggestion` returns JSON from the same `suggest_price()` the
server uses on submit, so the preview and the stored result cannot disagree.
