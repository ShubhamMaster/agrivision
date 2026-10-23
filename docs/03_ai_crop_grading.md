# 03 · AI module 1 — crop quality grading (computer vision)

**Section goal:** turn a photograph of a lot into a defensible quality score and
a Grade A / B / C verdict.

**File:** `app/ai/grading.py` (~320 lines, pure OpenCV + NumPy, no Flask)

---

## 1. Why metric-based computer vision and not a CNN

A convolutional neural network would need thousands of labelled photographs of
Indian mandi produce, graded by an expert. That dataset does not exist publicly,
and building it is a year's work on its own.

The approach taken here measures **the same four attributes a mandi grader
measures by eye** — colour, uniformity, surface defects and size — and fuses
them with published weights.

| | CNN | This approach |
|---|---|---|
| Training data | thousands of labelled images per crop | none |
| Explainability | a number, no reason | "defects 35/100 is what capped the grade" |
| Hardware | GPU preferred | runs on a laptop CPU in ~40 ms |
| Adding a crop | retrain | one dictionary entry |
| Accuracy ceiling | higher, with the data | adequate, and honest |

Explainability is the decisive argument: a farmer told his lot is Grade C will
not accept "the neural network said so". He will accept "your photos show a 35%
blemish score — sort the damaged pieces and re-shoot".

---

## 2. The pipeline

```
     photo
       │
   ┌───▼────────────────┐
   │ 1. LOAD + RESIZE   │  every image to 640 px wide, so metrics are
   └───┬────────────────┘  comparable between a phone and a DSLR
   ┌───▼────────────────┐
   │ 2. BLUR CHECK      │  variance of the Laplacian
   └───┬────────────────┘
   ┌───▼────────────────┐
   │ 3. SEGMENTATION    │  saturation-Otsu + value floor + morphology
   └───┬────────────────┘  → binary mask: produce vs background
       │
   ┌───┴──────┬──────────┬──────────┐
   ▼          ▼          ▼          ▼
 4.COLOUR  5.UNIFORM  6.DEFECT   7.SIZE
   │          │          │          │
   └──────────┴────┬─────┴──────────┘
                   ▼
           8. WEIGHTED FUSION → score 0-100 → Grade A / B / C
```

---

## 3. Stage by stage

### Stage 1 — resize to a fixed width

```python
TARGET_WIDTH = 640
```

Without this, a 12-megapixel photo and a 0.5-megapixel photo would produce
different values for every area-based metric. Normalising the width makes
"fraction of the frame" mean the same thing for both. `INTER_AREA` is used when
shrinking because it averages the pixels being discarded instead of dropping
them, which preserves colour statistics.

### Stage 2 — blur detection

> **Note.** Sharpness and exposure are measured **inside the produce mask**,
> not over the whole frame, so segmentation runs before this step. Measuring
> over the frame meant a pale background (a white sweep, a tarpaulin, an
> overcast sky) dragged the Laplacian variance down and capped the score of a
> perfectly sharp photo. See `docs/12_photography_pipeline.md` §7.1.

```python
sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
```

The Laplacian is a second-derivative edge operator. A sharp image has many
strong edges, so the variance of the Laplacian response is high; a blurred image
has soft edges and low variance. Below `BLUR_THRESHOLD = 55` the photo is treated
as unreliable.

**Crucially, a blurry photo caps the score rather than raising it:**

```python
if sharpness < BLUR_THRESHOLD:
    raw = min(raw, 68.0)
    penalties.append("Photo is soft/blurred — score capped, please re-shoot…")
```

This closes an obvious cheat. Blur hides surface defects, so a naive grader would
*reward* a blurry photo with a high defect score. Capping at 68 means a blurred
lot can never reach Grade A (threshold 76).

The same logic applies to exposure: under-exposed (mean < 55) and over-exposed
(mean > 215) photos are capped too, because darkness hides bruising and blown
highlights hide surface texture.

### Stage 3 — segmentation: separating produce from background

The problem: a photo of grapes on a grey tarpaulin is maybe 30% grapes. Measuring
colour over the whole frame would measure the tarpaulin.

```python
otsu_t, _ = cv2.threshold(s, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
min_sat = max(crop_info(crop_name)["min_sat"], otsu_t * 0.55)
mask = ((s >= min_sat) & (v >= 40) & (v <= 250)).astype(np.uint8) * 255
```

The insight is that farm backgrounds — tarpaulin, cement, crates, sky, shadow —
are nearly always **low-saturation**, while ripe produce is vivid. So the
saturation channel of HSV separates them.

**Otsu's method** finds the threshold automatically by choosing the value that
minimises the variance within each of the two resulting groups. It adapts to the
particular photo instead of relying on a fixed number. A crop-specific floor
(`min_sat`) is combined with it, because cotton and rice are genuinely pale and
would otherwise be erased along with the background.

The value bounds `(40, 250)` drop deep shadow and blown highlights.

Then morphology cleans the mask:

```python
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)   # specks out
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)   # holes filled
```

- **Opening** (erode then dilate) removes isolated bright specks of background.
- **Closing** (dilate then erode) fills small holes inside the produce, such as
  the gaps a specular highlight leaves.

If less than 4% of the frame is detected as produce, the code falls back to
grading the whole frame rather than returning nonsense from 200 pixels.

### Stage 4 — colour score (weight 34%)

```python
bands = crop_info(crop_name)["hue_bands"]      # e.g. Grapes: [(32,85),(118,165)]
inside = any(lo <= hue <= hi for each band)
in_band = inside.mean()                        # fraction of produce in range
```

Each crop declares the hue ranges a healthy sample should occupy. OpenCV's hue
channel is 0–179 (not 0–359), so green is roughly 35–85 and purple 118–165 —
grapes may legitimately be either, hence two bands.

The score blends that fraction with **vividness**:

```python
vivid = 1 - abs(mean_sat - 135) / 135          # peak at saturation 135
colour = 100 * (0.72 * in_band + 0.28 * vivid)
```

Saturation around 135 is the healthy window: too low means pale or unripe, too
high usually means an over-saturated phone filter.

### Stage 5 — uniformity score (weight 22%)

This stage contains the most interesting mathematics in the project.

**Hue is a circular quantity.** Red sits at both 0 and 179. A lot of red tomatoes
with hues clustered at 2 and 178 is perfectly uniform, but an ordinary standard
deviation would compute a mean of 90 (green!) and a huge spread.

The fix is **circular statistics**: treat each hue as an angle, average the unit
vectors, and read the length of the resultant.

```python
ang = hue_vals * (2 * math.pi / 180.0)
r = math.hypot(np.cos(ang).mean(), np.sin(ang).mean())   # 0 = scattered, 1 = identical
circ_std = math.sqrt(-2.0 * math.log(r))
```

If every hue is identical the vectors all point the same way, `r = 1`, and
`circ_std = 0`. If they are spread around the circle they cancel out, `r → 0`,
and `circ_std → ∞`. This is the standard definition of circular standard
deviation and it handles the wrap-around correctly.

Uniformity matters commercially: buyers pay a premium for a consistent lot
because it can be packed and sold as one grade.

### Stage 6 — defect score (weight 28%)

Two independent detectors, because bruises and spots look different:

```python
# (a) bruises: pixels much darker than the produce's own median
dark_cut = max(25.0, np.median(val_vals) * 0.55)
dark_ratio = (val_vals < dark_cut).mean()

# (b) spots: small dark blobs found by adaptive thresholding
adaptive = cv2.adaptiveThreshold(gray, 255, ADAPTIVE_THRESH_GAUSSIAN_C,
                                 THRESH_BINARY_INV, 31, 12)
```

Using the **median of this lot** as the reference, rather than a fixed
brightness, is what makes the detector work on both dark purple grapes and pale
potatoes: "dark" means dark *relative to this produce*.

Adaptive thresholding compares each pixel to the mean of its own 31×31
neighbourhood, so it finds a small dark spot even if that part of the photo is
in shadow — a global threshold would flag the entire shadowed region instead.

```python
defect_ratio = 0.55 * dark_ratio + 0.45 * spot_ratio
score = 100 * (1 - min(1, defect_ratio * 3.2))
```

The ×3.2 multiplier means roughly 31% defective pixels drives the score to zero —
calibrated so that a visibly blemished lot lands in the 30s, not the 80s.

### Stage 7 — size score (weight 16%)

```python
contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
```

`RETR_EXTERNAL` returns only outer boundaries — one contour per fruit, not one
per highlight inside it. Contours smaller than 0.04% of the frame are discarded
as noise, and the largest 40 are kept.

Two components:

```python
size_part   = min(1, (mean_area / total) / 0.045)      # saturates at 4.5% of frame
consistency = 1 - (std(areas) / mean(areas)) / 1.4     # coefficient of variation
size = 100 * (0.55 * size_part + 0.45 * consistency)
```

`std/mean` is the **coefficient of variation**, a scale-free measure of spread.
Using it rather than raw standard deviation means the consistency measure works
identically for large mangoes and small grapes.

A low size score also catches a photo taken from too far away — a legitimate
complaint, since you cannot grade what you cannot see.

### Stage 8 — fusion

```python
WEIGHTS = {"colour": 0.34, "uniformity": 0.22, "defect": 0.28, "size": 0.16}
GRADE_THRESHOLDS = [("A", 76.0), ("B", 56.0), ("C", 0.0)]
```

Colour and defects carry the most weight because they are what a buyer looks at
first. The weights live in one dictionary at the top of the file, so they can be
re-tuned without touching the logic.

---

## 4. Grading a lot, not a photo

```python
fused = 0.65 * mean(scores) + 0.35 * min(scores)
```

A lot is only as good as its worst visible side. Weighting the **minimum** at 35%
stops a farmer from lifting his grade by adding one flattering close-up of the
best bunch. This is an anti-gaming measure, and it mirrors how a real buyer
inspects — he digs into the middle of the crate.

---

## 5. Output structure

```python
{
  "ok": True,
  "grade": "B",
  "score": 58.2,
  "confidence": 65.0,
  "sub_scores": {"colour": 96.2, "uniformity": 62.0,
                 "defect": 35.1, "size": 17.4},
  "metrics": {"sharpness": 2.3, "brightness": 113.3,
              "coverage_pct": 17.9, "mean_saturation": 152.9},
  "warnings": ["Photo is soft/blurred — score capped…"],
  "notes": ["Colour is typical of healthy, well-ripened Grapes.", …],
  "summary": "Across 3 photos, this Grapes lot scores 58/100 and is graded B…"
}
```

**Confidence** is separate from score, and the distinction matters: *score* is
how good the produce is, *confidence* is how much the system trusts its own
reading. A blurry photo of excellent grapes gets a mediocre score and a low
confidence.

The function never raises. A corrupt upload returns `{"ok": False, …}` with a
readable message, so a bad file cannot break the listing flow.

---

## 6. Where it is called

| Caller | When |
|---|---|
| `routes/farmer.py` → `_apply_ai()` | a listing is created |
| same | a photo is added or deleted |
| same | "Re-run AI grading" is pressed |
| `seed.py` | generating demo data |

```python
result = grade_many(image_paths, crop.crop_name)
crop.ai_grade = result["grade"]
crop.ai_quality_score = result["score"]
crop.ai_summary = result["summary"]
# then each photo's sub-scores are stored on its CropPhoto row
```

---

## 7. Adding a new crop

One entry in `CROP_CATALOGUE` in `app/ai/pricing.py`:

```python
"Guava": {
    "base_price": 2800, "volatility": 0.20,
    "peak_months": [4, 5], "glut_months": [9, 10],
    "hue_bands": [(30, 60)],     # green-yellow
    "min_sat": 30,
    "certificate": False,
    "unit_note": "",
},
```

No change to `grading.py` at all. To find the hue band for a new crop, run
`python tools/check_hue_bands.py`, which measures the real hue distribution of
the cached specimen photographs against the declared band and flags anything
under 70%. Remember OpenCV's hue scale is 0–179, so halve a 0–360 figure from a
colour picker.

Four crops' bands were wrong when first measured this way — real maize scored
22% in-band because the band stopped at hue 40 and corn kernels sit at 45. See
`docs/12_photography_pipeline.md` §7.2.

---

## 8. Tuning guide

| Symptom | Fix |
|---|---|
| Everything grades too high | raise `GRADE_THRESHOLDS`, or raise the ×3.2 defect multiplier |
| Everything grades too low | widen `hue_bands` for that crop; check `min_sat` is not eating the produce |
| Background counted as produce | raise `min_sat` for that crop |
| Produce erased by the mask | lower `min_sat` (pale crops: cotton, rice) |
| Size score always low | the photos are taken too far away — a true finding, not a bug |

To inspect a mask while tuning, add temporarily inside `_segment_produce`:

```python
cv2.imwrite("mask_debug.png", mask)
```

---

## 9. Testing it standalone

```python
from app.ai.grading import grade_image, grade_many
print(grade_image("photo.jpg", "Grapes")["sub_scores"])
print(grade_many(["a.jpg", "b.jpg", "c.jpg"], "Grapes")["summary"])
```

No Flask, no database. This is the demo to run in a viva.

---

## 10. Honest limitations

- **2D only.** It cannot measure firmness, sugar content (brix), internal rot or
  weight.
- **It can be fooled by staging** — photographing only the best crate. The
  min-weighted fusion mitigates it; it does not eliminate it. Production would
  need geotagged, timestamped in-app capture.
- **No absolute size.** Without a reference object the system measures relative
  size within the frame, not millimetres. A coin or a standard crate in frame
  would fix this.
- **Lighting still influences colour** despite the exposure penalty. A colour
  calibration card would make it robust.

Stating these clearly is a strength in a viva, not a weakness.

---

## 11. Viva questions

**Q. Walk me through how a photo becomes a grade.**
Resize to 640 px → Laplacian blur check → segment produce from background with
Otsu on the saturation channel plus morphology → measure colour, uniformity,
defects and size inside the mask → weighted sum 34/22/28/16 → thresholds at 76
and 56 give A, B or C.

**Q. Why did you not use a CNN?**
No labelled dataset exists for Indian mandi produce, and a CNN cannot explain
*why* it graded a lot. This approach measures the same four attributes a human
grader uses and shows the farmer which one cost him the grade.

**Q. How do you separate the crop from the background?**
Backgrounds in farm photos are low-saturation; produce is vivid. Otsu's method
picks the saturation threshold automatically for each photo, a crop-specific
floor protects pale crops, and opening/closing cleans the mask.

**Q. What is Otsu's method?**
An automatic thresholding algorithm that selects the threshold minimising the
intra-class variance of the two resulting pixel groups — it adapts to each image
instead of using a fixed value.

**Q. Why circular statistics for hue?**
Hue is an angle: 0 and 179 are both red. Ordinary standard deviation would
report a huge spread for a uniformly red lot. Averaging unit vectors and taking
the resultant length handles the wrap-around correctly.

**Q. How does blur detection work and why does it cap the score?**
Variance of the Laplacian measures edge strength; blur lowers it. Blur hides
defects, so without the cap a blurry photo would score *better*. Capping at 68
puts Grade A out of reach for an unreliable photo.

**Q. Why weight the minimum photo score at 35%?**
So a farmer cannot raise his grade by adding one flattering photo. A lot is worth
what its worst visible side is worth.

**Q. What is adaptive thresholding and why use it for spots?**
It compares each pixel with the mean of its local neighbourhood instead of a
global value, so a small dark spot is detected even inside a shadowed region.

**Q. What are the weaknesses of this module?**
No firmness, brix or internal quality; no absolute size without a reference
object; it can be partly gamed by selective photography; lighting still affects
colour despite the exposure penalty.
