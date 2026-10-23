# 06 · AI module 4 — OCMR certificate verification

**Section goal:** read an uploaded quality certificate and decide whether it can
be trusted, without a human looking at it.

**File:** `app/ai/certificate.py` (~470 lines)

**OCMR = Optical Certificate & Mark Recognition** — the name given to the
combined OCR + machine-mark + tamper-analysis + rule-engine pipeline.

---

## 1. Why this matters

Grapes for export must carry a residue certificate (GrapeNet, run by APEDA). A
buyer who takes a farmer's word for it risks a rejected container at the port.
Today that trust gap is filled by an intermediary who physically checks the
paperwork — and charges for it.

Automating the check is what lets the platform remove that intermediary. The
business rule is enforced in the data model:

```python
@property
def is_tradeable(self):
    if self.certificate_required and self.certificate_status != "verified":
        return False
```

A grapes lot simply cannot be requested until its certificate verifies.

---

## 2. The six stages

```
 uploaded file (JPG / PNG / PDF)
        │
  ┌─────▼──────────────┐
  │ 1 IMAGE PREPARATION│  grayscale → denoise → deskew → adaptive threshold
  └─────┬──────────────┘
  ┌─────▼──────────────┐
  │ 2 TEXT RECOGNITION │  Tesseract OCR + per-word confidence
  └─────┬──────────────┘
  ┌─────▼──────────────┐
  │ 3 FIELD EXTRACTION │  regex → number, issuer, dates, holder, crop, grade
  └─────┬──────────────┘
  ┌─────▼──────────────┐
  │ 4 MARK RECOGNITION │  QR detection + payload cross-check
  └─────┬──────────────┘
  ┌─────▼──────────────┐
  │ 5 TAMPER ANALYSIS  │  Error Level Analysis
  └─────┬──────────────┘
  ┌─────▼──────────────┐
  │ 6 RULE ENGINE      │  10 weighted checks → confidence → verdict
  └─────┬──────────────┘
        ▼
  verified (≥72%) / pending (50-71%) / rejected
```

---

## 3. Stage 1 — image preparation

OCR accuracy on a raw phone photo of a document is poor. Four operations fix
most of it:

```python
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
if width < 1000:  upscale with INTER_CUBIC
gray = cv2.fastNlMeansDenoising(gray, None, 9, 7, 21)
gray = _deskew(gray)
binary = cv2.adaptiveThreshold(gray, 255, ADAPTIVE_THRESH_GAUSSIAN_C,
                               THRESH_BINARY, 35, 15)
```

**Upscaling.** Tesseract wants roughly 300 DPI. Below about 1000 px wide, letter
strokes are too thin to segment, and `INTER_CUBIC` interpolation recovers enough
edge definition to matter.

**Denoising.** `fastNlMeansDenoising` is non-local means: it replaces each pixel
with a weighted average of pixels in *similar neighbourhoods* anywhere in the
image, not just adjacent ones. It removes sensor grain while keeping letter edges
crisp — a plain blur would destroy the text.

**Deskew.** A photo taken at 3° makes Tesseract's line segmentation fail.

```python
coords = np.column_stack(np.where(thr > 0))      # all text pixels
angle = cv2.minAreaRect(coords)[-1]              # smallest rotated rectangle
```

The minimum-area rectangle enclosing all the text pixels is tilted at the same
angle as the text, so its angle *is* the skew. The image is rotated back by it.
Rotations under 0.4° or over 20° are ignored — the first is noise, the second
means something other than skew is going on.

**Adaptive threshold.** A photo of a document is unevenly lit — brighter near the
window. A global threshold loses the shadowed half; adaptive thresholding
compares each pixel against its own 35×35 neighbourhood and handles the gradient.

---

## 4. Stage 2 — OCR with confidence

```python
data = pytesseract.image_to_data(pil, config="--oem 3 --psm 6",
                                 output_type=pytesseract.Output.DICT)
```

`image_to_data` is used rather than `image_to_string` because it returns a
**per-word confidence**, which becomes the readability check. `--oem 3` selects
the LSTM engine; `--psm 6` tells Tesseract to assume a uniform block of text,
which suits a certificate layout.

The average word confidence across the document is returned alongside the text.

---

## 5. Stage 3 — field extraction

Regular expressions pull out six fields. Two of them required real debugging.

### The certificate number

The first attempt was:

```python
r"(?:CERTIFICATE|CERT|REF|...)\s*(?:NO|NUMBER|#)?\s*[:.\-]?\s*([A-Z0-9...]{4,24})"
```

It extracted **`IFICATE`** from every document. The alternation matched `CERT`
*inside* the word `CERTIFICATE`, and the capture group then took the remaining
letters. Two fixes:

```python
r"\b(?:CERTIFICATE|CERT|REF|...)\b\s*\b(?:NO|NUMBER|NO\.|#)\b\s*[:.\-]?\s*(…)"
...
if any(ch.isdigit() for ch in candidate):     # identifiers contain digits
    fields["cert_number"] = candidate
```

`\b` word boundaries stop the partial match, and the digit test rejects any
capture that is purely a word the OCR wandered into. After the fix the field
reads `GN-749780` correctly.

### The crop

Second real bug. A certificate names the crop in a labelled field
(`CROP : POMEGRANATE`) but *also* mentions crops in the body text ("…for export
of fresh grapes"). A naive scan returned `Grapes` for a pomegranate certificate
and the crop-match check failed on a genuine document.

The fix is to prefer the labelled field and only fall back to a loose scan:

```python
labelled = re.search(r"\b(?:CROP|COMMODITY|PRODUCE|PRODUCT)\b\s*[:.\-]?\s*([A-Z ]{3,30})", upper)
```

### Dates

Three formats are recognised (`dd/mm/yyyy`, `yyyy-mm-dd`, `12 March 2026`), and
then the *right* date must be picked from several on the page:

```python
issue  = _date_near(text, found, ["ISSUE", "ISSUED", "DATE OF ISSUE", "DATED"])
expiry = _date_near(text, found, ["VALID", "EXPIR", "UPTO", "VALIDITY"])
```

`_date_near()` finds the date appearing closest **after** one of those labels,
within 70 characters. Without label proximity you cannot tell the issue date from
the sampling date from the printing date.

---

## 6. Stage 4 — machine-readable mark

```python
detector = cv2.QRCodeDetector()
payload, points, _ = detector.detectAndDecode(img)
```

Genuine APEDA/GrapeNet certificates carry a QR code. If one is found **and**
decodes, its payload is compared against the printed certificate number:

```python
consistent = printed_number_normalised in payload_normalised
```

A forger who edits the printed number in an image editor will not regenerate a
matching QR, so this check catches exactly that attack. It is weighted only 4,
because many legitimate state certificates carry no QR at all — its absence must
not condemn an honest document.

---

## 7. Stage 5 — Error Level Analysis

```python
original.save(buffer, "JPEG", quality=92)
diff = ImageChops.difference(original, resaved)
```

JPEG is lossy. Re-saving an image at a known quality and differencing it with
itself produces an **error map**. In an untouched photo every region has the same
compression history, so the error is spatially uniform. A region pasted in from
elsewhere, or drawn over in an editor, has a *different* compression history and
lights up brightly.

```python
if ela_mean > 9.0 and ela_max > 180:
    suspicious = True
```

Both conditions are required: a high mean alone just means a detailed image, and
a high peak alone can be a single sharp edge. The combination — high average
error *with* a strong localised peak — is the signature of local editing.

ELA is advisory. It is weighted 4 out of 110 and flags a document for human
review rather than rejecting it, because ELA produces false positives on
screenshots, heavily recompressed images and scans from certain devices.

---

## 8. Stage 6 — the rule engine

Ten checks with explicit weights:

| # | Check | Weight |
|---|---|---|
| 1 | Document is machine-readable | 14 |
| 2 | Certificate number found | 16 |
| 3 | Issuing authority recognised | 16 |
| 4 | Number matches the authority's format | 10 |
| 5 | Issue date present | 8 |
| 6 | Certificate is currently valid | 12 |
| 7 | Crop matches the listing | 10 |
| 8 | Reads like a quality certificate | 6 |
| 9 | Machine-readable mark verified | 4 |
| 10 | No digital tampering signature | 4 |
| | **Total** | **110** |

```python
confidence = 100 * earned_weight / total_weight
```

### Critical checks override the score

```python
CRITICAL_CHECKS = {"readable", "not_expired", "crop_match"}
```

Failing any of these rejects the document **regardless of the score**. An expired
certificate scoring 88% is still worthless — it is not valid today. A certificate
for a different crop is irrelevant to this listing. An unreadable scan cannot be
verified at all.

This is the key design point of the whole module: a weighted score alone would
let a high-scoring expired document through. The two-layer design — weighted
score *plus* absolute disqualifiers — is what makes it trustworthy.

### Three outcomes, not two

```
critical failure          → rejected
confidence ≥ 72           → verified
confidence 50 – 71        → pending  (queued for manual review)
confidence < 50           → rejected
```

The **pending** state is deliberate. A system that must answer yes or no will
eventually say yes to something it should not. Borderline documents are held for
a human rather than guessed at.

### The authority registry

```python
AUTHORITY_REGISTRY = {
  "APEDA":    {"patterns": [...], "number_regex": r"...", "crops": [...]},
  "GRAPENET": {...}, "NRCG": {...}, "NPOP": {...},
  "AGMARK":   {...}, "FSSAI": {...}, "STATE_AGRI": {...},
}
```

Seven recognised certifying bodies, each with the text patterns that identify it
and the format its certificate numbers follow. In production each entry would
also hold that authority's verification API endpoint, turning check 3 from
pattern-matching into a live registry lookup.

---

## 9. Output and storage

```python
{
  "status": "verified", "confidence": 100.0,
  "checks": [ {key, title, passed, detail, weight} × 10 ],
  "fields": {cert_number, issuer, issue_date, expiry_date, holder_name, …},
  "ocr_text": "…", "ocr_confidence": 88.0,
  "mark": {"found": True, "payload": "GN-749780", "type": "QR"},
  "tamper": {"ela_mean": 3.2, "suspicious": False, "note": "…"},
  "remarks": "Verified automatically with 100% confidence. 10 of 10 checks passed."
}
```

`routes/farmer.py` writes this onto a `Certificate` row (checks as JSON) and then
updates the crop:

```python
crop.certificate_status = _best_cert_status(crop, cert)   # verified > pending > rejected
if crop.certificate_status == "verified":
    _reprice(crop)                                        # the +8% premium applies
```

The report page renders all ten checks with pass/fail icons, the extracted
fields, the raw OCR text in a collapsible block, and the document itself.

---

## 10. Verified behaviour on the seeded data

| Certificate | Result | Reason |
|---|---|---|
| Grapes, valid | **verified, 100%** | all ten checks pass |
| Grapes, valid | **verified, 100%** | all ten checks pass |
| Pomegranate, valid | **verified, 100%** | all ten checks pass |
| Pomegranate, expired | **rejected, 88%** | critical check 6 failed — expired 02 Oct |

The last row is the important demonstration: a document scoring 88% is still
rejected, because validity is a critical check.

---

## 11. Limitations

- **No live registry call.** Format and validity are checked, not existence in
  APEDA's database. A well-forged number in the right format passes. The registry
  structure is in place for a real API.
- **Handwriting is not read reliably.** Tesseract is trained on print.
- **PDF support needs poppler** (`pdftoppm`). Without it the user is asked for an
  image, which is handled gracefully rather than crashing.
- **ELA has false positives** on screenshots and recompressed images — which is
  exactly why it is advisory and low-weighted.

---

## 12. Viva questions

**Q. What does OCMR stand for and what does it do?**
Optical Certificate & Mark Recognition — a six-stage pipeline that prepares the
image, runs OCR, extracts fields by regex, detects and cross-checks a QR code,
runs tamper analysis, and applies a ten-check weighted rule engine.

**Q. How do you detect a tampered certificate?**
Error Level Analysis. The image is re-saved as JPEG and differenced with itself.
Untouched regions share one compression history and show uniform error; edited
regions show a localised spike. A high mean *with* a high peak flags the document
for review.

**Q. Why is an expired certificate rejected even at 88% confidence?**
Validity is a critical check. The weighted score measures how much of the
document could be confirmed; validity is a yes/no fact. Three checks — readable,
not expired, crop match — reject outright regardless of score.

**Q. Why have a "pending" state?**
Because a binary system eventually approves something it should not. Documents
scoring 50–71% are held for human review instead of being guessed at.

**Q. What preprocessing improves OCR and why?**
Upscaling to ~1000 px (Tesseract needs ~300 DPI), non-local-means denoising
(removes grain, keeps letter edges), deskew via the minimum-area rectangle of the
text pixels, and adaptive thresholding for uneven lighting.

**Q. How does deskew find the angle?**
The smallest rotated rectangle enclosing all text pixels is tilted at the same
angle as the text, so `cv2.minAreaRect` gives the skew directly.

**Q. What does the QR check add?**
A forger editing the printed number in an image editor will not regenerate a
matching QR. Cross-checking the decoded payload against the printed number
catches that. It is weighted low because many genuine certificates have no QR.

**Q. What bugs did you hit building this?**
Two. The certificate-number regex matched `CERT` inside `CERTIFICATE` and
returned `IFICATE` — fixed with word boundaries and a digit test. And the crop
field was taken from the body text instead of the labelled field, so a
pomegranate certificate reported "Grapes" — fixed by preferring the labelled
`CROP :` field.

**Q. How would you make this production-grade?**
Call each authority's verification API with the extracted number, so existence is
confirmed rather than inferred from format — the `AUTHORITY_REGISTRY` already has
a slot for it.
