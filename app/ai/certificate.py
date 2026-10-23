"""
AgriVision — OCMR certificate verification.

OCMR = Optical Certificate & Mark Recognition.  It is the name we give to the
combined pipeline that reads a quality certificate and decides whether it can
be trusted:

    STAGE 1  IMAGE PREPARATION   grayscale -> denoise -> deskew -> adaptive
                                 binarisation.  Scanned/phone-shot documents
                                 OCR far better after this.
    STAGE 2  TEXT RECOGNITION    Tesseract OCR (pytesseract) produces the raw
                                 text plus a per-word confidence average.
    STAGE 3  FIELD EXTRACTION    regular expressions pull out certificate
                                 number, issuing authority, issue/expiry date,
                                 holder name, crop and grade.
    STAGE 4  MARK RECOGNITION    OpenCV QR/barcode detection.  Genuine APEDA /
                                 GrapeNet / NPOP certificates carry a machine-
                                 readable mark; its payload is cross-checked
                                 against the printed certificate number.
    STAGE 5  TAMPER ANALYSIS     Error Level Analysis (ELA): the image is
                                 re-compressed as JPEG and differenced with
                                 itself.  Regions edited in a photo editor
                                 compress differently and light up in the
                                 error map.
    STAGE 6  RULE ENGINE         nine weighted checks produce a confidence
                                 score, and any critical failure (expired,
                                 wrong crop, unreadable) forces a rejection.

Output: a dict the Flask layer stores on the Certificate row and renders on
the verification report page.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from difflib import SequenceMatcher

import cv2
import numpy as np

try:
    import pytesseract
    from PIL import Image, ImageChops
    OCR_AVAILABLE = shutil.which("tesseract") is not None
except Exception:                                    # pragma: no cover
    pytesseract = None
    OCR_AVAILABLE = False


# ======================================================================
# Known certifying authorities (the "registry")
# ======================================================================
# In a production deployment each entry would also carry the authority's
# verification API endpoint.  Here the registry is used for issuer
# recognition and certificate-number format validation.
AUTHORITY_REGISTRY = {
    "APEDA": {
        "full": "Agricultural & Processed Food Products Export Development Authority",
        "patterns": [r"\bAPEDA\b", r"AGRICULTURAL\s+AND\s+PROCESSED\s+FOOD"],
        "number_regex": r"\b(?:APEDA[-/ ]?)?[A-Z]{2,4}[-/]?\d{6,10}\b",
        "crops": ["Grapes", "Pomegranate", "Mango", "Banana"],
    },
    "GRAPENET": {
        "full": "GrapeNet residue monitoring system (APEDA)",
        "patterns": [r"GRAPE\s*NET", r"GRAPENET", r"RESIDUE\s+MONITOR"],
        "number_regex": r"\b(?:GN|GRP)[-/ ]?\d{6,12}\b",
        "crops": ["Grapes"],
    },
    "NRCG": {
        "full": "ICAR — National Research Centre for Grapes, Pune",
        "patterns": [r"\bNRCG\b", r"NATIONAL\s+RESEARCH\s+CENTRE\s+FOR\s+GRAPES"],
        "number_regex": r"\bNRCG[-/ ]?\d{4,10}\b",
        "crops": ["Grapes"],
    },
    "NPOP": {
        "full": "National Programme for Organic Production",
        "patterns": [r"\bNPOP\b", r"ORGANIC\s+PRODUCTION", r"\bINDIA\s+ORGANIC\b"],
        "number_regex": r"\b(?:NPOP|ORG)[-/ ]?[A-Z0-9]{4,12}\b",
        "crops": [],
    },
    "AGMARK": {
        "full": "AGMARK — Directorate of Marketing & Inspection",
        "patterns": [r"\bAGMARK\b", r"MARKETING\s+AND\s+INSPECTION"],
        "number_regex": r"\bAG[-/ ]?\d{5,10}\b",
        "crops": [],
    },
    "FSSAI": {
        "full": "Food Safety and Standards Authority of India",
        "patterns": [r"\bFSSAI\b", r"FOOD\s+SAFETY\s+AND\s+STANDARDS"],
        "number_regex": r"\b\d{14}\b",
        "crops": [],
    },
    "STATE_AGRI": {
        "full": "State Department of Agriculture",
        "patterns": [r"DEPARTMENT\s+OF\s+AGRICULTURE", r"KRISHI\s+VIBHAG",
                     r"DIRECTORATE\s+OF\s+HORTICULTURE"],
        "number_regex": r"\b[A-Z]{2,4}[-/]\d{4,8}\b",
        "crops": [],
    },
}

# Words that should appear somewhere on a genuine quality certificate.
EXPECTED_KEYWORDS = [
    "CERTIFICATE", "QUALITY", "RESIDUE", "ANALYSIS", "LABORATORY", "GRADE",
    "ISSUED", "VALID", "SAMPLE", "COMPLIES", "STANDARD", "INSPECTION", "EXPORT",
]

# How each check contributes to the final confidence score.
CHECK_WEIGHTS = {
    "readable": 14,
    "certificate_number": 16,
    "issuer_recognised": 16,
    "number_format": 10,
    "dates_present": 8,
    "not_expired": 12,
    "crop_match": 10,
    "keywords": 6,
    "machine_mark": 4,
    "no_tampering": 4,
}

# Failing any of these makes the certificate invalid regardless of the score.
CRITICAL_CHECKS = {"readable", "not_expired", "crop_match"}


# ======================================================================
# PUBLIC API
# ======================================================================
def verify_certificate(file_path: str, crop_name: str = "",
                       holder_name: str = "", cert_type: str = "") -> dict:
    """Run the full OCMR pipeline on one uploaded certificate file."""
    if not os.path.exists(file_path):
        return _reject("The uploaded file could not be found on the server.")

    image_path, cleanup = _as_image(file_path)
    if image_path is None:
        return _reject(
            "PDF certificates need the poppler toolkit on the server. "
            "Please upload a clear photo or scan (JPG/PNG) of the certificate instead."
        )

    try:
        img = cv2.imread(image_path)
        if img is None:
            return _reject("The file could not be read as an image.")

        # ---- STAGE 1 + 2 : prepare and OCR ---------------------------
        prepared = _prepare(img)
        text, ocr_conf = _ocr(prepared)
        upper = text.upper()

        # ---- STAGE 3 : field extraction ------------------------------
        fields = _extract_fields(text, upper)

        # ---- STAGE 4 : machine-readable mark -------------------------
        mark = _detect_mark(img)

        # ---- STAGE 5 : tamper analysis -------------------------------
        tamper = _tamper_analysis(image_path)

        # ---- STAGE 6 : rule engine -----------------------------------
        checks = _run_checks(upper, fields, crop_name, holder_name, mark, tamper, ocr_conf)

        earned = sum(CHECK_WEIGHTS[c["key"]] for c in checks if c["passed"])
        possible = sum(CHECK_WEIGHTS[c["key"]] for c in checks)
        confidence = round(100.0 * earned / possible, 1) if possible else 0.0

        critical_failed = [c for c in checks if c["key"] in CRITICAL_CHECKS and not c["passed"]]

        if critical_failed:
            status = "rejected"
            remark = "Rejected: " + "; ".join(c["detail"] for c in critical_failed)
        elif confidence >= 72:
            status = "verified"
            remark = (f"Verified automatically with {confidence:.0f}% confidence. "
                      f"{len([c for c in checks if c['passed']])} of {len(checks)} checks passed.")
        elif confidence >= 50:
            status = "pending"
            remark = (f"Partially verified ({confidence:.0f}%). Some details could not be "
                      f"confirmed automatically — queued for manual review.")
        else:
            status = "rejected"
            remark = (f"Rejected: only {confidence:.0f}% of verification checks passed. "
                      f"Please upload a clearer, complete copy of the certificate.")

        return {
            "ok": True,
            "status": status,
            "confidence": confidence,
            "checks": checks,
            "fields": fields,
            "cert_type": cert_type or fields.get("issuer_key") or "Quality Certificate",
            "ocr_text": text.strip()[:6000],
            "ocr_confidence": ocr_conf,
            "mark": mark,
            "tamper": tamper,
            "remarks": remark,
        }
    finally:
        if cleanup and image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
            except OSError:
                pass


# ======================================================================
# STAGE 1 — image preparation
# ======================================================================
def _prepare(img):
    """Grayscale -> denoise -> deskew -> adaptive threshold."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Upscale small scans; OCR accuracy falls off below ~1000 px width.
    h, w = gray.shape
    if w < 1000:
        scale = 1000.0 / w
        gray = cv2.resize(gray, (1000, int(h * scale)), interpolation=cv2.INTER_CUBIC)

    gray = cv2.fastNlMeansDenoising(gray, None, 9, 7, 21)
    gray = _deskew(gray)

    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 15
    )
    return binary


def _deskew(gray):
    """Rotate the page so text lines are horizontal (improves OCR a lot)."""
    inv = cv2.bitwise_not(gray)
    thr = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thr > 0))
    if coords.shape[0] < 50:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.4 or abs(angle) > 20:
        return gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


# ======================================================================
# STAGE 2 — OCR
# ======================================================================
def _ocr(binary_img):
    if not OCR_AVAILABLE:
        return "", 0.0
    try:
        pil = Image.fromarray(binary_img)
        data = pytesseract.image_to_data(
            pil, config="--oem 3 --psm 6", output_type=pytesseract.Output.DICT
        )
        words, confs = [], []
        for txt, conf in zip(data["text"], data["conf"]):
            if txt and txt.strip():
                words.append(txt)
                try:
                    c = float(conf)
                    if c >= 0:
                        confs.append(c)
                except (TypeError, ValueError):
                    pass
        text = " ".join(words)
        return text, round(sum(confs) / len(confs), 1) if confs else 0.0
    except Exception:
        return "", 0.0


# ======================================================================
# STAGE 3 — field extraction
# ======================================================================
DATE_PATTERNS = [
    (r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", "dmy"),
    (r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", "ymd"),
    (r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b", "dmonthy"),
]
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _extract_fields(text, upper):
    fields = {
        "cert_number": None, "issuer": None, "issuer_key": None,
        "issue_date": None, "expiry_date": None, "holder_name": None,
        "crop_mentioned": None, "grade": None, "all_dates": [],
    }

    # --- issuing authority -------------------------------------------
    for key, meta in AUTHORITY_REGISTRY.items():
        if any(re.search(p, upper) for p in meta["patterns"]):
            fields["issuer_key"] = key
            fields["issuer"] = meta["full"]
            break

    # --- certificate number ------------------------------------------
    # The \b around the label words matters: without it "CERT" matches inside
    # the word CERTIFICATE and the capture group walks away with "IFICATE".
    labelled = re.search(
        r"\b(?:CERTIFICATE|CERT|REF|REGISTRATION|LICENCE|LICENSE|REPORT)\b\s*"
        r"\b(?:NO|NUMBER|NO\.|#)\b\s*[:.\-]?\s*([A-Z0-9][A-Z0-9/\-]{4,24})", upper)
    if not labelled:
        # Same label words, but the document omitted "NO"/"NUMBER".
        labelled = re.search(
            r"\b(?:CERTIFICATE|CERT|REF|REGISTRATION|LICENCE|LICENSE|REPORT)\b"
            r"\s*[:.\-]\s*([A-Z0-9][A-Z0-9/\-]{4,24})", upper)
    if labelled:
        candidate = labelled.group(1).strip(" .-")
        # A capture made purely of letters is almost always a word the OCR
        # ran into, not an identifier — real numbers carry digits.
        if any(ch.isdigit() for ch in candidate):
            fields["cert_number"] = candidate
    elif fields["issuer_key"]:
        m = re.search(AUTHORITY_REGISTRY[fields["issuer_key"]]["number_regex"], upper)
        if m:
            fields["cert_number"] = m.group(0)
    if not fields["cert_number"]:
        m = re.search(r"\b[A-Z]{2,5}[-/ ]?\d{5,12}\b", upper)
        if m:
            fields["cert_number"] = m.group(0)

    # --- dates ---------------------------------------------------------
    found = []
    for pattern, kind in DATE_PATTERNS:
        for m in re.finditer(pattern, text):
            d = _parse_date(m.groups(), kind)
            if d:
                found.append((m.start(), d))
    found.sort()
    fields["all_dates"] = [d.isoformat() for _, d in found]

    issue = _date_near(text, found, ["ISSUE", "ISSUED", "DATE OF ISSUE", "DATED", "SAMPLING"])
    expiry = _date_near(text, found, ["VALID", "EXPIR", "UPTO", "UP TO", "VALIDITY"])
    if not issue and found:
        issue = min(d for _, d in found)
    if not expiry and len(found) > 1:
        latest = max(d for _, d in found)
        if issue and latest > issue:
            expiry = latest
    fields["issue_date"] = issue.isoformat() if issue else None
    fields["expiry_date"] = expiry.isoformat() if expiry else None

    # --- holder --------------------------------------------------------
    m = re.search(r"(?:ISSUED\s+TO|NAME\s+OF\s+(?:THE\s+)?(?:FARMER|GROWER|EXPORTER|APPLICANT)"
                  r"|GROWER|FARMER|M/S)\s*[:.\-]?\s*([A-Z][A-Za-z.\s]{3,45})", text, re.I)
    if m:
        fields["holder_name"] = " ".join(m.group(1).split())[:60]

    # --- crop + grade ---------------------------------------------------
    # A certificate names the crop in a labelled field ("CROP : GRAPES") and
    # often mentions other crops in the body text of the analysis clause.  The
    # labelled field is authoritative; only fall back to a loose scan when no
    # label is present, otherwise a passing mention hijacks the crop check.
    from .pricing import CROP_CATALOGUE
    labelled_crop = re.search(
        r"\b(?:CROP|COMMODITY|PRODUCE|PRODUCT)\b\s*[:.\-]?\s*([A-Z ]{3,30})", upper)
    if labelled_crop:
        text_after = labelled_crop.group(1)
        for name in CROP_CATALOGUE:
            if re.search(r"\b" + name.upper() + r"S?\b", text_after):
                fields["crop_mentioned"] = name
                break
    if not fields["crop_mentioned"]:
        for name in CROP_CATALOGUE:
            if re.search(r"\b" + name.upper() + r"S?\b", upper):
                fields["crop_mentioned"] = name
                break
    m = re.search(r"\bGRADE\s*[:.\-]?\s*([A-C])\b", upper)
    if m:
        fields["grade"] = m.group(1)
    return fields


def _parse_date(groups, kind):
    try:
        if kind == "dmy":
            d, mth, y = int(groups[0]), int(groups[1]), int(groups[2])
        elif kind == "ymd":
            y, mth, d = int(groups[0]), int(groups[1]), int(groups[2])
        else:
            d = int(groups[0])
            mth = MONTHS.get(groups[1][:3].lower())
            y = int(groups[2])
            if not mth:
                return None
        if not (1 <= mth <= 12 and 1 <= d <= 31 and 1990 <= y <= 2100):
            return None
        return date(y, mth, d)
    except (ValueError, TypeError, IndexError):
        return None


def _date_near(text, found, labels, window=70):
    """Pick the date that appears closest after one of these labels."""
    up = text.upper()
    best = None
    for label in labels:
        for m in re.finditer(re.escape(label), up):
            for pos, d in found:
                if 0 <= pos - m.end() <= window:
                    if best is None or (pos - m.end()) < best[0]:
                        best = (pos - m.end(), d)
    return best[1] if best else None


# ======================================================================
# STAGE 4 — machine-readable mark
# ======================================================================
def _detect_mark(img):
    """Look for a QR code; decode it if present."""
    result = {"found": False, "payload": None, "type": None}
    try:
        detector = cv2.QRCodeDetector()
        payload, points, _ = detector.detectAndDecode(img)
        if points is not None:
            result["found"] = True
            result["type"] = "QR"
            if payload:
                result["payload"] = payload[:300]
    except Exception:
        pass
    return result


# ======================================================================
# STAGE 5 — Error Level Analysis (tamper heuristic)
# ======================================================================
def _tamper_analysis(image_path, quality=92):
    """
    Re-save the image as JPEG and difference it with the original.  Areas that
    were pasted or re-drawn in an editor have a different compression history
    and show up as bright patches in the error map.

    Reported as an advisory signal — it flags documents for human review, it
    does not by itself reject them.
    """
    out = {"ela_mean": None, "ela_max": None, "suspicious": False, "note": ""}
    try:
        original = Image.open(image_path).convert("RGB")
        buf = io.BytesIO()
        original.save(buf, "JPEG", quality=quality)
        buf.seek(0)
        resaved = Image.open(buf)

        diff = ImageChops.difference(original, resaved)
        arr = np.asarray(diff).astype(np.float32)

        out["ela_mean"] = round(float(arr.mean()), 2)
        out["ela_max"] = round(float(arr.max()), 2)

        # High mean error with a very high peak = localised editing.
        if out["ela_mean"] > 9.0 and out["ela_max"] > 180:
            out["suspicious"] = True
            out["note"] = ("Error-level analysis shows localised compression anomalies. "
                           "The document may have been edited — flagged for manual review.")
        else:
            out["note"] = "No localised compression anomaly detected."
    except Exception:
        out["note"] = "Tamper analysis could not run on this file type."
    return out


# ======================================================================
# STAGE 6 — rule engine
# ======================================================================
def _run_checks(upper, fields, crop_name, holder_name, mark, tamper, ocr_conf):
    checks = []

    def add(key, title, passed, detail):
        checks.append({"key": key, "title": title, "passed": bool(passed),
                       "detail": detail, "weight": CHECK_WEIGHTS[key]})

    # 1 readable -------------------------------------------------------
    readable = len(upper) >= 120 and ocr_conf >= 35
    add("readable", "Document is machine-readable", readable,
        (f"OCR extracted {len(upper)} characters at {ocr_conf:.0f}% average confidence."
         if readable else
         "The document text could not be read reliably. Upload a sharper, well-lit scan."))

    # 2 certificate number ---------------------------------------------
    add("certificate_number", "Certificate number found", bool(fields["cert_number"]),
        f"Certificate number detected: {fields['cert_number']}" if fields["cert_number"]
        else "No certificate/reference number could be located on the document.")

    # 3 issuer ----------------------------------------------------------
    add("issuer_recognised", "Issuing authority recognised", bool(fields["issuer_key"]),
        f"Issued by {fields['issuer']}." if fields["issuer"]
        else "The issuing authority is not one of the recognised certifying bodies.")

    # 4 number format ----------------------------------------------------
    fmt_ok = False
    if fields["cert_number"] and fields["issuer_key"]:
        fmt_ok = bool(re.fullmatch(
            AUTHORITY_REGISTRY[fields["issuer_key"]]["number_regex"].replace(r"\b", ""),
            fields["cert_number"]))
    elif fields["cert_number"]:
        fmt_ok = bool(re.fullmatch(r"[A-Z0-9][A-Z0-9/\-]{4,24}", fields["cert_number"]))
    add("number_format", "Number matches the authority's format", fmt_ok,
        "The certificate number follows the expected pattern for this authority." if fmt_ok
        else "The certificate number does not match the expected format for this authority.")

    # 5 dates -------------------------------------------------------------
    has_dates = bool(fields["issue_date"])
    add("dates_present", "Issue date present", has_dates,
        f"Issue date read as {fields['issue_date']}." if has_dates
        else "No issue date could be read from the document.")

    # 6 not expired --------------------------------------------------------
    expired = False
    if fields["expiry_date"]:
        expired = date.fromisoformat(fields["expiry_date"]) < date.today()
    future_issue = False
    if fields["issue_date"]:
        future_issue = date.fromisoformat(fields["issue_date"]) > date.today()
    valid_dates = not expired and not future_issue
    add("not_expired", "Certificate is currently valid", valid_dates,
        ("This certificate expired on " + fields["expiry_date"] + "." if expired else
         "The issue date is in the future, which is not possible." if future_issue else
         ("Valid until " + fields["expiry_date"] + "." if fields["expiry_date"]
          else "No expiry date printed; treated as currently valid.")))

    # 7 crop match ----------------------------------------------------------
    if crop_name and fields["crop_mentioned"]:
        crop_ok = fields["crop_mentioned"].lower() == crop_name.lower()
        detail = (f"The certificate refers to {fields['crop_mentioned']}, matching this listing."
                  if crop_ok else
                  f"The certificate refers to {fields['crop_mentioned']} but the listing is "
                  f"for {crop_name}.")
    elif crop_name:
        crop_ok = bool(re.search(r"\b" + re.escape(crop_name.upper()) + r"S?\b", upper))
        detail = ("The crop name appears on the certificate." if crop_ok else
                  f"'{crop_name}' is not mentioned anywhere on the certificate.")
    else:
        crop_ok, detail = True, "No crop specified for cross-checking."
    add("crop_match", "Crop matches the listing", crop_ok, detail)

    # 8 keywords -------------------------------------------------------------
    hits = [k for k in EXPECTED_KEYWORDS if k in upper]
    kw_ok = len(hits) >= 3
    add("keywords", "Document reads like a quality certificate", kw_ok,
        f"Found {len(hits)} expected terms ({', '.join(h.title() for h in hits[:5])})."
        if hits else "None of the terms expected on a quality certificate were found.")

    # 9 machine mark ----------------------------------------------------------
    mark_ok = mark.get("found", False)
    if mark_ok and mark.get("payload") and fields["cert_number"]:
        consistent = fields["cert_number"].replace("-", "").replace("/", "") in \
            mark["payload"].upper().replace("-", "").replace("/", "")
        detail = ("QR code found and its payload matches the printed certificate number."
                  if consistent else
                  "QR code found, but its content does not contain the printed number.")
        mark_ok = consistent
    else:
        detail = ("Machine-readable mark detected." if mark_ok
                  else "No QR/barcode found. Many state certificates do not carry one.")
    add("machine_mark", "Machine-readable mark verified", mark_ok, detail)

    # 10 tampering --------------------------------------------------------------
    clean = not tamper.get("suspicious")
    add("no_tampering", "No digital tampering signature", clean, tamper.get("note", ""))

    # Holder name is informational only (OCR of handwritten names is unreliable),
    # so it is appended as a note rather than a weighted check.
    if holder_name and fields.get("holder_name"):
        ratio = SequenceMatcher(None, holder_name.lower(),
                                fields["holder_name"].lower()).ratio()
        fields["holder_match_pct"] = round(ratio * 100, 1)

    return checks


# ======================================================================
# helpers
# ======================================================================
def _as_image(path):
    """
    Return (image_path, is_temporary).  PDFs are rasterised with pdftoppm when
    poppler is installed; otherwise (None, False) signals an unsupported file.
    """
    if not path.lower().endswith(".pdf"):
        return path, False
    if not shutil.which("pdftoppm"):
        return None, False
    tmp = tempfile.mktemp(prefix="agv_cert_")
    try:
        subprocess.run(["pdftoppm", "-png", "-r", "200", "-f", "1", "-l", "1", path, tmp],
                       check=True, capture_output=True, timeout=60)
        for cand in (tmp + "-1.png", tmp + "-01.png", tmp + "-001.png"):
            if os.path.exists(cand):
                return cand, True
    except Exception:
        pass
    return None, False


def _reject(message):
    return {
        "ok": False, "status": "rejected", "confidence": 0.0,
        "checks": [], "fields": {}, "ocr_text": "", "ocr_confidence": 0.0,
        "mark": {"found": False}, "tamper": {},
        "cert_type": "", "remarks": message,
    }
