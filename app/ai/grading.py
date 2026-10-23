"""
AgriVision — crop quality grading from a photograph (OpenCV).

Pipeline for one image
----------------------
  1. LOAD + RESIZE     work at a fixed 640 px width so every metric is
                       comparable between a phone photo and a DSLR photo.
  2. BLUR CHECK        variance of the Laplacian.  A blurred photo cannot be
                       graded honestly, so it lowers the confidence and the
                       farmer is asked to re-shoot.
  3. SEGMENTATION      separate produce from background.  Saturation-Otsu plus
                       a value floor removes most table-tops, tarpaulins and
                       sky; morphological opening/closing cleans the mask.
  4. COLOUR SCORE      share of produce pixels whose hue falls in the healthy
                       hue band(s) declared for that crop in the catalogue,
                       combined with mean saturation (ripeness/vividness).
  5. UNIFORMITY SCORE  circular standard deviation of hue + std of saturation
                       inside the mask.  A uniform lot grades higher because
                       buyers pay for consistency.
  6. DEFECT SCORE      dark-spot / bruise ratio: pixels that are much darker
                       than the local median inside the mask, plus black-spot
                       blobs found by adaptive thresholding.
  7. SIZE SCORE        contour analysis — how big and how consistent the
                       individual units (bunches, fruits, tubers) are.
  8. FUSION            weighted sum -> 0-100 quality score -> A / B / C.

Everything is deterministic and explainable; each sub-score is stored so the
farmer can see *why* a lot was graded B instead of A.
"""

from __future__ import annotations

import math
import os

import cv2
import numpy as np

from .pricing import crop_info

# Weight of each sub-score in the final quality number.
WEIGHTS = {
    "colour": 0.34,
    "uniformity": 0.22,
    "defect": 0.28,
    "size": 0.16,
}

# Score thresholds for the three grades.
GRADE_THRESHOLDS = [("A", 76.0), ("B", 56.0), ("C", 0.0)]

TARGET_WIDTH = 640
BLUR_THRESHOLD = 55.0       # Laplacian variance below this = too blurry


# ======================================================================
# public API
# ======================================================================
def grade_image(image_path: str, crop_name: str = "") -> dict:
    """
    Grade a single photo.  Always returns a dict — never raises — so a bad
    upload can't break the listing flow.
    """
    if not os.path.exists(image_path):
        return _failure("File not found on disk.")

    image = cv2.imread(image_path)
    if image is None:
        return _failure("The file could not be decoded as an image.")

    img = _resize(image, TARGET_WIDTH)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # --- 2. segmentation ---------------------------------------------
    # Segment before judging photo quality: both sharpness and exposure have
    # to be measured on the produce itself, not on the frame as a whole.
    mask, coverage = _segment_produce(hsv, crop_name)
    if coverage < 0.04:
        # Almost nothing detected — grade on the whole frame instead.
        mask = np.full(gray.shape, 255, np.uint8)
        coverage = 1.0

    h_ch, s_ch, v_ch = cv2.split(hsv)
    sel = mask > 0
    hue_vals = h_ch[sel].astype(np.float32)
    sat_vals = s_ch[sel].astype(np.float32)
    val_vals = v_ch[sel].astype(np.float32)

    if hue_vals.size < 500:
        return _failure("Not enough produce detected in the photo. "
                        "Take the photo closer, filling the frame with the crop.")

    # --- 3. photo quality, measured on the produce only ----------------
    # Measuring these over the whole frame is wrong whenever the background is
    # large and featureless — a white studio sweep, a pale tarpaulin, an
    # overcast sky. A flat background has almost no Laplacian response, so it
    # drags the variance below the blur threshold and the score gets capped
    # even though the produce itself is perfectly sharp. The same applies to
    # exposure: a white backdrop pushes the frame mean past the over-exposure
    # limit while the fruit is correctly exposed.
    sharpness = _masked_sharpness(gray, mask)
    brightness = float(val_vals.mean())

    # --- 4..7 sub-scores ----------------------------------------------
    colour = _colour_score(hue_vals, sat_vals, crop_name)
    uniformity = _uniformity_score(hue_vals, sat_vals)
    defect = _defect_score(gray, mask, val_vals)
    size = _size_score(mask)

    # --- 8. fusion -----------------------------------------------------
    raw = (colour * WEIGHTS["colour"] + uniformity * WEIGHTS["uniformity"]
           + defect * WEIGHTS["defect"] + size * WEIGHTS["size"])

    # Photo-quality penalty: a blurry or badly lit photo cannot support a
    # premium grade, so we cap the score rather than inflate it.
    penalties = []
    if sharpness < BLUR_THRESHOLD:
        raw = min(raw, 68.0)
        penalties.append("Photo is soft/blurred — score capped, please re-shoot in daylight.")
    if brightness < 55:
        raw = min(raw, 70.0)
        penalties.append("Photo is under-exposed — colour assessment is less reliable.")
    elif brightness > 215:
        raw = min(raw, 72.0)
        penalties.append("Photo is over-exposed — highlights hide surface defects.")

    score = float(max(0.0, min(100.0, raw)))
    grade = next(g for g, t in GRADE_THRESHOLDS if score >= t)
    confidence = _confidence(sharpness, coverage, hue_vals.size)

    return {
        "ok": True,
        "grade": grade,
        "score": round(score, 1),
        "confidence": round(confidence, 1),
        "sub_scores": {
            "colour": round(colour, 1),
            "uniformity": round(uniformity, 1),
            "defect": round(defect, 1),
            "size": round(size, 1),
        },
        "metrics": {
            "sharpness": round(sharpness, 1),
            "brightness": round(brightness, 1),
            "coverage_pct": round(coverage * 100, 1),
            "mean_saturation": round(float(sat_vals.mean()), 1),
            "mean_value": round(float(val_vals.mean()), 1),
        },
        "warnings": penalties,
        "notes": _notes(colour, uniformity, defect, size, crop_name),
    }


def grade_many(image_paths: list[str], crop_name: str = "") -> dict:
    """
    Grade a set of photos of the same lot and fuse them.

    A lot is only as good as its weakest visible side, so the final score is
    65% of the mean and 35% of the minimum — this stops a farmer from lifting
    the grade by adding one flattering photo.
    """
    per_image = []
    for p in image_paths:
        r = grade_image(p, crop_name)
        r["path"] = p
        per_image.append(r)

    good = [r for r in per_image if r.get("ok")]
    if not good:
        return {
            "ok": False, "grade": None, "score": None,
            "per_image": per_image,
            "summary": "No photo could be analysed. Please upload a clear, close-up photo of the produce.",
        }

    scores = [r["score"] for r in good]
    fused = 0.65 * (sum(scores) / len(scores)) + 0.35 * min(scores)
    grade = next(g for g, t in GRADE_THRESHOLDS if fused >= t)

    sub = {k: round(sum(r["sub_scores"][k] for r in good) / len(good), 1)
           for k in ("colour", "uniformity", "defect", "size")}

    return {
        "ok": True,
        "grade": grade,
        "score": round(fused, 1),
        "confidence": round(sum(r["confidence"] for r in good) / len(good), 1),
        "sub_scores": sub,
        "per_image": per_image,
        "summary": _lot_summary(grade, fused, sub, len(good), crop_name),
    }


# ======================================================================
# internals
# ======================================================================
def _masked_sharpness(gray, mask):
    """
    Variance of the Laplacian over the produce pixels only.

    The Laplacian is computed on the whole image so each pixel keeps its real
    neighbourhood (computing it on a cut-out would invent huge edges along the
    mask boundary), but the variance is then taken only where the mask is set.
    Pixels within 2 px of the boundary are dropped, because the produce/
    background edge is a genuine strong edge that would otherwise read as
    "sharp" no matter how blurred the subject is.
    """
    lap = cv2.Laplacian(gray, cv2.CV_64F)

    eroded = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
                       iterations=1)
    sel = eroded > 0
    if int(sel.sum()) < 500:
        sel = mask > 0
    if int(sel.sum()) < 100:
        return float(lap.var())

    return float(lap[sel].var())


def _resize(img, width):
    h, w = img.shape[:2]
    if w == width:
        return img
    scale = width / float(w)
    return cv2.resize(img, (width, max(1, int(h * scale))),
                      interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)


def _segment_produce(hsv, crop_name):
    """
    Build a binary mask of 'produce' pixels.

    Backgrounds in farm photos are usually low-saturation (grey tarpaulin,
    cement floor, sky) or very dark (shadow).  Otsu on the saturation channel
    finds the split automatically; we then enforce a crop-specific minimum.
    """
    _h, s, v = cv2.split(hsv)

    otsu_t, _ = cv2.threshold(s, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    min_sat = max(crop_info(crop_name).get("min_sat", 25), otsu_t * 0.55)

    mask = ((s >= min_sat) & (v >= 40) & (v <= 250)).astype(np.uint8) * 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    coverage = float((mask > 0).sum()) / mask.size
    return mask, coverage


def _colour_score(hue_vals, sat_vals, crop_name):
    """
    Share of pixels whose hue is inside the healthy band for this crop,
    blended with how vivid the colour is.
    """
    bands = crop_info(crop_name).get("hue_bands") or [(0, 179)]
    inside = np.zeros(hue_vals.shape, dtype=bool)
    for lo, hi in bands:
        inside |= (hue_vals >= lo) & (hue_vals <= hi)
    in_band = float(inside.mean())                       # 0..1

    # Vividness: saturation 70-200 is the healthy window for ripe produce.
    mean_sat = float(sat_vals.mean())
    vivid = 1.0 - abs(mean_sat - 135.0) / 135.0
    vivid = max(0.0, min(1.0, vivid))

    return 100.0 * (0.72 * in_band + 0.28 * vivid)


def _uniformity_score(hue_vals, sat_vals):
    """
    Hue is circular (0 and 179 are neighbours), so a plain std would be wrong
    for red produce.  We use the circular standard deviation instead.
    """
    ang = hue_vals * (2 * math.pi / 180.0)
    r = math.hypot(float(np.cos(ang).mean()), float(np.sin(ang).mean()))
    r = min(1.0, max(1e-6, r))
    circ_std = math.sqrt(-2.0 * math.log(r))             # 0 = perfectly uniform

    hue_uniform = max(0.0, 1.0 - circ_std / 1.2)
    sat_uniform = max(0.0, 1.0 - float(sat_vals.std()) / 70.0)
    return 100.0 * (0.65 * hue_uniform + 0.35 * sat_uniform)


def _defect_score(gray, mask, val_vals):
    """
    100 = flawless.  We look for two defect signatures inside the produce
    mask: pixels much darker than the produce median (bruises, rot), and
    small dark blobs found by adaptive thresholding (spots, fungal marks).
    """
    median_v = float(np.median(val_vals))
    dark_cut = max(25.0, median_v * 0.55)
    dark_ratio = float((val_vals < dark_cut).mean())

    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12
    )
    adaptive = cv2.bitwise_and(adaptive, adaptive, mask=mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    adaptive = cv2.morphologyEx(adaptive, cv2.MORPH_OPEN, kernel)

    produce_px = max(1, int((mask > 0).sum()))
    spot_ratio = float((adaptive > 0).sum()) / produce_px

    # Blend, then convert "ratio of bad pixels" into a 0-100 goodness score.
    defect_ratio = 0.55 * dark_ratio + 0.45 * spot_ratio
    return 100.0 * max(0.0, 1.0 - min(1.0, defect_ratio * 3.2))


def _size_score(mask):
    """
    Contour statistics: a lot of similar, reasonably large units scores high;
    tiny fragmented blobs (shrivelled produce, or a photo taken too far away)
    score low.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total = float(mask.size)
    areas = sorted((cv2.contourArea(c) for c in contours), reverse=True)
    areas = [a for a in areas if a > total * 0.0004][:40]

    if not areas:
        return 45.0

    mean_area = sum(areas) / len(areas)
    size_part = min(1.0, (mean_area / total) / 0.045)        # saturates at 4.5% of frame

    if len(areas) > 1:
        m = mean_area
        sd = math.sqrt(sum((a - m) ** 2 for a in areas) / len(areas))
        consistency = max(0.0, 1.0 - (sd / m) / 1.4)
    else:
        consistency = 0.85

    return 100.0 * (0.55 * size_part + 0.45 * consistency)


def _confidence(sharpness, coverage, pixel_count):
    c = 100.0
    if sharpness < BLUR_THRESHOLD:
        c -= 28
    elif sharpness < BLUR_THRESHOLD * 2:
        c -= 12
    if coverage < 0.15:
        c -= 18
    elif coverage < 0.30:
        c -= 7
    if pixel_count < 20000:
        c -= 10
    return max(25.0, c)


def _notes(colour, uniformity, defect, size, crop_name):
    out = []
    if colour >= 78:
        out.append(f"Colour is typical of healthy, well-ripened {crop_name or 'produce'}.")
    elif colour >= 58:
        out.append("Colour is acceptable but not fully uniform with the ideal range for this crop.")
    else:
        out.append("Colour deviates from the healthy range — possible under-ripeness or discolouration.")

    if uniformity >= 75:
        out.append("The lot looks consistent — buyers pay a premium for this.")
    elif uniformity < 55:
        out.append("Mixed colour across the lot — consider sorting before listing.")

    if defect >= 80:
        out.append("Very few surface blemishes detected.")
    elif defect >= 60:
        out.append("Some dark spots/bruising visible on the surface.")
    else:
        out.append("Significant blemishes or bruising detected — this limits the grade.")

    if size < 55:
        out.append("Units look small or the photo was taken too far away.")
    return out


def _lot_summary(grade, score, sub, n, crop_name):
    label = {"A": "Premium", "B": "Standard", "C": "Economy"}[grade]
    strongest = max(sub, key=sub.get)
    weakest = min(sub, key=sub.get)
    names = {"colour": "colour", "uniformity": "uniformity",
             "defect": "freedom from blemishes", "size": "unit size"}
    return (
        f"Across {n} photo{'s' if n > 1 else ''}, this {crop_name or 'crop'} lot scores "
        f"{score:.0f}/100 and is graded {grade} ({label}). "
        f"Strongest attribute: {names[strongest]} ({sub[strongest]:.0f}/100). "
        f"Weakest attribute: {names[weakest]} ({sub[weakest]:.0f}/100)."
    )


def _failure(msg):
    return {"ok": False, "grade": None, "score": None, "confidence": 0,
            "sub_scores": {"colour": 0, "uniformity": 0, "defect": 0, "size": 0},
            "metrics": {}, "warnings": [msg], "notes": [msg]}
