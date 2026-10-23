"""
AgriVision — demo data generator.

    python seed.py            build a fresh demo database
    python seed.py --keep     add demo data to the existing database

What it creates
---------------
  * 6 farmer accounts and 4 buyer accounts across Maharashtra districts
  * ~2 years of daily mandi price history for every catalogue crop in
    4 districts, with realistic seasonality, trend and noise
  * synthetic but genuinely analysable crop photographs, written to
    app/static/uploads/crops and then run through the real CV grader
  * a GrapeNet-style quality certificate rendered as an image and run
    through the real OCMR verification pipeline
  * buyer requirements, buying requests, farmer offers, chat messages
    and notifications, so every screen has something on it

Nothing here is hard-coded into the models: the seed calls the same AI
functions the live application calls.
"""

import math
import os
import random
import shutil
import sys
from datetime import date, datetime, timedelta

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2                                                   # noqa: E402

from config import Config                                     # noqa: E402
from app import create_app                                    # noqa: E402
from app.extensions import db                                 # noqa: E402
from app.ai.certificate import verify_certificate             # noqa: E402
from app.ai.grading import grade_many                         # noqa: E402
from app.ai.pricing import CROP_CATALOGUE, suggest_price      # noqa: E402
from app.photo_lot import has_specimens, make_lot_photo       # noqa: E402
from app.models import (Certificate, Crop, CropPhoto, DealRequest, Message,
                        Notification, PriceRecord, Requirement, User)

random.seed(20261013)
np.random.seed(20261013)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

DISTRICTS = [
    ("Maharashtra", "Nashik", "Lasalgaon"),
    ("Maharashtra", "Pune", "Pune Market Yard"),
    ("Maharashtra", "Solapur", "Solapur APMC"),
    ("Maharashtra", "Jalgaon", "Jalgaon APMC"),
]


# ======================================================================
# 1. USERS
# ======================================================================
def make_users():
    farmers = [
        ("Ramesh Patil", "ramesh@agrivision.in", "9876500001", "Nashik", "Niphad", 12.5),
        ("Sunita Deshmukh", "sunita@agrivision.in", "9876500002", "Nashik", "Dindori", 6.0),
        ("Vikram Jadhav", "vikram@agrivision.in", "9876500003", "Pune", "Junnar", 18.0),
        ("Anil Shinde", "anil@agrivision.in", "9876500004", "Solapur", "Pandharpur", 9.0),
        ("Kavita More", "kavita@agrivision.in", "9876500005", "Jalgaon", "Raver", 15.0),
        ("Prakash Gaikwad", "prakash@agrivision.in", "9876500006", "Nashik", "Sinnar", 4.5),
    ]
    buyers = [
        ("Nitin Shah", "sahyadri@agrivision.in", "9876600001", "Nashik",
         "Sahyadri Exports Pvt Ltd", "Exporter", "27AABCS1429B1ZX"),
        ("Meera Agarwal", "freshmart@agrivision.in", "9876600002", "Pune",
         "FreshMart Retail", "Retailer / Mall", "27AADCF3321K1Z2"),
        ("Rajesh Kulkarni", "agrotrade@agrivision.in", "9876600003", "Mumbai",
         "AgroTrade Commodities", "Trader", "27AAACA9812M1Z9"),
        ("Farid Shaikh", "sunfoods@agrivision.in", "9876600004", "Jalgaon",
         "SunFoods Processing", "Food Processor", "27AAFCS7781L1ZK"),
    ]

    created = {"farmers": [], "buyers": []}

    for name, email, phone, district, taluka, acres in farmers:
        u = User(full_name=name, email=email, phone=phone, role="farmer",
                 state="Maharashtra", district=district, taluka=taluka,
                 farm_size_acres=acres, is_verified=True,
                 created_at=datetime.utcnow() - timedelta(days=random.randint(60, 400)))
        u.set_password("farmer123")
        db.session.add(u)
        created["farmers"].append(u)

    for name, email, phone, district, company, btype, gst in buyers:
        u = User(full_name=name, email=email, phone=phone, role="buyer",
                 state="Maharashtra", district=district, company_name=company,
                 buyer_type=btype, gst_number=gst, is_verified=True,
                 created_at=datetime.utcnow() - timedelta(days=random.randint(60, 400)))
        u.set_password("buyer123")
        db.session.add(u)
        created["buyers"].append(u)

    db.session.commit()
    print(f"  users            : {len(farmers)} farmers, {len(buyers)} buyers")
    return created


# ======================================================================
# 2. PRICE HISTORY
# ======================================================================
def make_price_history(days=730):
    """
    Build a believable daily series per crop per district:

        price(t) = base
                   x seasonal(t)        sinusoid peaking in the lean months
                   x trend(t)           slow multi-year drift
                   x shock(t)           occasional market shocks that decay
                   x noise

    Arrivals move inversely to price with their own seasonal pattern, which is
    what gives the demand model a real supply signal to read.
    """
    today = date.today()
    rows = []

    for crop, info in CROP_CATALOGUE.items():
        base = info["base_price"]
        vol = info["volatility"]
        peak = info["peak_months"] or [6]
        peak_doy = ((sum(peak) / len(peak)) - 1) * 30.4 + 15

        for state, district, market in DISTRICTS:
            # Each district trades at its own small premium/discount.
            region_factor = random.uniform(0.90, 1.10)
            drift = random.uniform(-0.04, 0.10)          # per year
            shock, shock_decay = 0.0, 0.0

            for d in range(days, 0, -1):
                day = today - timedelta(days=d)
                doy = day.timetuple().tm_yday

                seasonal = 1 + 0.16 * math.cos(2 * math.pi * (doy - peak_doy) / 365.0)
                trend = 1 + drift * ((days - d) / 365.0)

                if random.random() < 0.006:              # a shock starts
                    shock = random.uniform(-0.25, 0.30)
                    shock_decay = random.uniform(0.90, 0.97)
                shock *= shock_decay

                noise = random.gauss(0, vol * 0.22)
                modal = base * region_factor * seasonal * trend * (1 + shock + noise)
                modal = max(base * 0.35, modal)

                spread = modal * random.uniform(0.05, 0.13)
                arrivals = max(
                    20.0,
                    random.gauss(900, 260)
                    * (2 - seasonal)                      # more arrivals when price is low
                    * random.uniform(0.75, 1.25),
                )

                rows.append(PriceRecord(
                    crop_name=crop, state=state, district=district, market=market,
                    record_date=day,
                    modal_price=round(modal, 2),
                    min_price=round(modal - spread, 2),
                    max_price=round(modal + spread, 2),
                    arrivals=round(arrivals, 1),
                ))

    # Bulk insert — 14 crops x 4 districts x 730 days is ~41,000 rows.
    db.session.bulk_save_objects(rows)
    db.session.commit()
    print(f"  price history    : {len(rows):,} daily records "
          f"({len(CROP_CATALOGUE)} crops x {len(DISTRICTS)} districts x {days} days)")


# ======================================================================
# 3. SYNTHETIC CROP PHOTOS
# ======================================================================
# NOTE: lot photographs are produced by app/photo_lot.py — real photographed
# specimens where they exist, and a matching studio render for the bulk grain
# and fibre crops. The earlier procedural renderer that lived here drew
# full-frame speckle, which looked nothing like the photographed crops beside
# it on the marketplace; see docs/12_photography_pipeline.md.


# ======================================================================
# 4. SYNTHETIC CERTIFICATE
# ======================================================================
def synth_certificate(path, crop, holder, cert_no, issue, expiry, valid=True):
    """Render a GrapeNet-style residue certificate that the OCR can actually read."""
    W, H = 1240, 1754                                   # A4 at 150 dpi
    img = Image.new("RGB", (W, H), (255, 255, 253))
    d = ImageDraw.Draw(img)

    f_title = ImageFont.truetype(FONT_BOLD, 40)
    f_sub = ImageFont.truetype(FONT_PATH, 24)
    f_h = ImageFont.truetype(FONT_BOLD, 26)
    f = ImageFont.truetype(FONT_PATH, 24)
    f_small = ImageFont.truetype(FONT_PATH, 20)

    d.rectangle([30, 30, W - 30, H - 30], outline=(20, 70, 40), width=4)
    d.rectangle([44, 44, W - 44, H - 44], outline=(20, 70, 40), width=1)

    y = 90
    d.text((W / 2, y), "APEDA", font=f_title, fill=(20, 70, 40), anchor="mm"); y += 46
    d.text((W / 2, y), "AGRICULTURAL AND PROCESSED FOOD PRODUCTS",
           font=f_sub, fill=(40, 40, 40), anchor="mm"); y += 30
    d.text((W / 2, y), "EXPORT DEVELOPMENT AUTHORITY", font=f_sub,
           fill=(40, 40, 40), anchor="mm"); y += 30
    d.text((W / 2, y), "GRAPENET — RESIDUE MONITORING SYSTEM", font=f_sub,
           fill=(90, 60, 20), anchor="mm"); y += 50

    d.line([80, y, W - 80, y], fill=(20, 70, 40), width=2); y += 36
    d.text((W / 2, y), "CERTIFICATE OF QUALITY AND RESIDUE ANALYSIS",
           font=f_h, fill=(0, 0, 0), anchor="mm"); y += 56

    variety = {"Grapes": "THOMPSON SEEDLESS", "Pomegranate": "BHAGWA",
               "Mango": "KESAR", "Banana": "GRAND NAINE"}.get(crop, "STANDARD")

    rows = [
        ("CERTIFICATE NO", cert_no),
        ("DATE OF ISSUE", issue.strftime("%d/%m/%Y")),
        ("VALID UPTO", expiry.strftime("%d/%m/%Y")),
        ("ISSUED TO", holder),
        ("CROP", crop.upper()),
        ("VARIETY", variety),
        ("GRADE", "A"),
        ("PLOT REGISTRATION", "MH/NSK/NPD/2026/00418"),
        ("LABORATORY", "NRCG ACCREDITED LAB, PUNE"),
        ("SAMPLE DRAWN ON", (issue - timedelta(days=6)).strftime("%d/%m/%Y")),
    ]
    for label, value in rows:
        d.text((110, y), label, font=f_small, fill=(90, 90, 90))
        d.text((480, y), ":", font=f, fill=(0, 0, 0))
        d.text((520, y), str(value), font=f, fill=(0, 0, 0))
        y += 48

    y += 20
    d.line([80, y, W - 80, y], fill=(170, 170, 170), width=1); y += 30
    d.text((110, y), "ANALYSIS RESULT", font=f_h, fill=(0, 0, 0)); y += 44

    for line in [
        "The sample drawn from the above plot has been tested for pesticide",
        "residue and COMPLIES with the maximum residue limits prescribed",
        f"under the applicable EU STANDARD for export of fresh {crop.lower()}.",
        "No residue was detected above the limit of quantification.",
    ]:
        d.text((110, y), line, font=f, fill=(0, 0, 0)); y += 36

    y += 30
    d.text((110, y), "INSPECTION STATUS : PASSED", font=f_h, fill=(20, 90, 40)); y += 70

    # QR code carrying the certificate number (the mark-recognition check reads this).
    qr = make_qr_image(cert_no, box=7)
    img.paste(qr, (W - 110 - qr.width, y))

    d.text((110, y + 40), "AUTHORISED SIGNATORY", font=f_small, fill=(90, 90, 90))
    d.line([110, y + 36, 420, y + 36], fill=(0, 0, 0), width=2)
    d.text((110, y + 80), "Dy. General Manager (Horticulture)", font=f_small, fill=(60, 60, 60))
    d.text((110, y + 110), "APEDA Regional Office, Mumbai", font=f_small, fill=(60, 60, 60))

    d.text((W / 2, H - 70),
           "This is a system generated certificate issued under the GrapeNet traceability system.",
           font=f_small, fill=(120, 120, 120), anchor="mm")

    if not valid:
        d.text((W / 2, H / 2), "SPECIMEN", font=ImageFont.truetype(FONT_BOLD, 150),
               fill=(230, 215, 215), anchor="mm")

    img.save(path, "JPEG", quality=94)
    return path


def make_qr_image(payload, box=7):
    """
    A real, scannable QR code carrying the certificate number, so the
    mark-recognition stage of the OCMR pipeline has a genuine payload to decode
    and cross-check against the printed number.
    """
    try:
        import qrcode
        qr = qrcode.QRCode(version=3, box_size=box, border=3,
                           error_correction=qrcode.constants.ERROR_CORRECT_H)
        qr.add_data(payload)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").convert("RGB")
    except ImportError:
        # Fallback if the qrcode package is not installed: a QR-shaped block
        # that the detector can see but not decode.
        modules, size = 25, 25 * box
        img = Image.new("RGB", (size + 2 * box, size + 2 * box), "white")
        d = ImageDraw.Draw(img)
        rnd = random.Random(payload)
        for r in range(modules):
            for c in range(modules):
                if rnd.random() < 0.45:
                    d.rectangle([box + c * box, box + r * box,
                                 box + c * box + box - 1, box + r * box + box - 1], fill="black")
        for cx, cy in [(0, 0), (modules - 7, 0), (0, modules - 7)]:
            x, y = box + cx * box, box + cy * box
            d.rectangle([x, y, x + 7 * box, y + 7 * box], fill="black")
            d.rectangle([x + box, y + box, x + 6 * box, y + 6 * box], fill="white")
            d.rectangle([x + 2 * box, y + 2 * box, x + 5 * box, y + 5 * box], fill="black")
        return img


# ======================================================================
# 5. CROP LISTINGS
# ======================================================================
# (farmer index, crop, variety, quantity, quality tier, organic, price offset %,
#  photo source group)
#
# The last column pins which cached specimen group the photographs are built
# from, so the picture matches the variety in the listing: Thompson Seedless
# and Sonaka are green grapes, Lasalgaon Red is a red onion. Left as None the
# composer picks a group itself.
LISTINGS = [
    (0, "Grapes", "Thompson Seedless", 85, "good", False, 0, "grape-white"),
    (0, "Onion", "Lasalgaon Red", 220, "medium", False, -4, "onion-red"),
    (1, "Grapes", "Sonaka", 46, "medium", True, 6, "grape-white-4"),
    (1, "Tomato", "Hybrid Abhinav", 120, "good", False, -2, "tomato-1"),
    (2, "Pomegranate", "Bhagwa", 64, "good", False, 8, "pomegranate"),
    (2, "Wheat", "Lokwan", 310, "good", False, 0, None),
    (3, "Pomegranate", "Ganesh", 38, "poor", False, -6, "pomegranate"),
    (3, "Soybean", "JS-335", 180, "medium", False, 2, None),
    (4, "Banana", "Grand Naine", 420, "good", True, 4, "banana"),
    (4, "Cotton", "Bt Cotton", 95, "medium", False, 0, None),
    (5, "Chilli", "Jwala", 28, "medium", False, 10, "pepper-red"),
    (5, "Potato", "Kufri Jyoti", 140, "good", False, -3, "potato-white"),
    (0, "Maize", "Pioneer 3396", 260, "medium", False, 0, "corn"),
    (2, "Rice", "Indrayani", 150, "good", True, 5, None),
]


def make_crops(farmers):
    app_root = os.path.dirname(os.path.abspath(__file__))
    crop_dir = Config.CROP_IMAGE_DIR
    os.makedirs(crop_dir, exist_ok=True)

    crops = []
    for i, (fi, name, variety, qty, quality, organic, offset, photo_group) in \
            enumerate(LISTINGS, start=1):
        farmer = farmers[fi]
        state, district, market = next(
            (s, d, m) for s, d, m in DISTRICTS if d == farmer.district)

        crop = Crop(
            farmer_id=farmer.id, crop_name=name, variety=variety, quantity=qty,
            harvest_date=date.today() - timedelta(days=random.randint(2, 20)),
            description=f"{variety} {name.lower()} from {farmer.taluka or district}. "
                        f"Hand-sorted, ready for immediate lifting. "
                        f"Transport can be arranged up to the nearest highway.",
            organic=organic, state=state, district=district, market=market,
            status="available",
            views=random.randint(3, 90),
            created_at=datetime.utcnow() - timedelta(days=random.randint(0, 18)),
        )
        crop.certificate_required = CROP_CATALOGUE[name]["certificate"]
        crop.certificate_status = "pending" if crop.certificate_required else "not_required"
        db.session.add(crop)
        db.session.flush()

        # --- photos -------------------------------------------------
        # Real photographed specimens where they exist (compose_lot), and the
        # procedural renderer as the fallback for the bulk grain and fibre
        # crops, which have no photographic source. Each photo of one listing
        # is a separate arrangement of the same variety, so the gallery shows
        # the lot from several angles rather than one picture repeated.
        paths = []
        for n in range(random.randint(2, 3)):
            fname = f"crop{crop.id}_seed{n}.jpg"
            p = os.path.join(crop_dir, fname)

            make_lot_photo(name, p, quality=quality,
                           seed=crop.id * 100 + n, variety=photo_group)

            db.session.add(CropPhoto(crop_id=crop.id, filename=fname))
            paths.append(p)
        db.session.flush()

        # --- run the real AI ----------------------------------------
        result = grade_many(paths, name)
        if result.get("ok"):
            crop.ai_grade = result["grade"]
            crop.ai_quality_score = result["score"]
            crop.ai_summary = result["summary"]
            by_path = {r.get("path"): r for r in result["per_image"]}
            for photo in crop.photos:
                r = by_path.get(os.path.join(crop_dir, photo.filename))
                if r and r.get("ok"):
                    photo.quality_score = r["score"]
                    photo.grade = r["grade"]
                    photo.colour_score = r["sub_scores"]["colour"]
                    photo.uniformity_score = r["sub_scores"]["uniformity"]
                    photo.defect_score = r["sub_scores"]["defect"]
                    photo.size_score = r["sub_scores"]["size"]
                    photo.sharpness = r["metrics"].get("sharpness")
                    photo.notes = " ".join(r.get("notes", []))

        band = suggest_price(name, crop.ai_grade, crop.ai_quality_score,
                             state, district, organic, False)
        crop.ai_price_min = band["min"]
        crop.ai_price_max = band["max"]
        crop.ai_price_recommended = band["recommended"]
        crop.expected_price = round(band["recommended"] * (1 + offset / 100.0) / 10) * 10

        crops.append(crop)

    db.session.commit()
    photographed = sum(len(c.photos) for c in crops if has_specimens(c.crop_name))
    total_photos = sum(len(c.photos) for c in crops)
    print(f"  crop listings    : {len(crops)} lots, {total_photos} photos graded "
          f"by the CV model ({photographed} composed from real specimens, "
          f"{total_photos - photographed} procedural)")
    return crops


# ======================================================================
# 6. CERTIFICATES
# ======================================================================
def make_certificates(crops):
    cert_dir = Config.CERTIFICATE_DIR
    os.makedirs(cert_dir, exist_ok=True)

    targets = [c for c in crops if c.certificate_required][:4]
    done = 0

    for idx, crop in enumerate(targets):
        issue = date.today() - timedelta(days=random.randint(5, 40))
        # Give the last one an expired certificate so the rejection path is visible.
        expired = idx == len(targets) - 1
        expiry = (issue - timedelta(days=1)) if expired else issue + timedelta(days=90)
        cert_no = f"GN-{random.randint(100000, 999999)}"

        fname = f"cert{crop.id}_seed.jpg"
        path = os.path.join(cert_dir, fname)
        synth_certificate(path, crop.crop_name, crop.farmer.full_name.upper(),
                          cert_no, issue, expiry)

        result = verify_certificate(path, crop_name=crop.crop_name,
                                    holder_name=crop.farmer.full_name,
                                    cert_type="GRAPENET")
        fields = result.get("fields", {})

        cert = Certificate(
            crop_id=crop.id, filename=fname,
            cert_type=result.get("cert_type") or "GRAPENET",
            cert_number=fields.get("cert_number"),
            issuer=fields.get("issuer"),
            holder_name=fields.get("holder_name"),
            issue_date=_iso(fields.get("issue_date")),
            expiry_date=_iso(fields.get("expiry_date")),
            ocr_text=result.get("ocr_text"),
            status=result.get("status"),
            confidence=result.get("confidence"),
            remarks=result.get("remarks"),
        )
        import json
        cert.checks_json = json.dumps(result.get("checks", []))
        if cert.status == "verified":
            cert.verified_at = datetime.utcnow()
        db.session.add(cert)

        crop.certificate_status = cert.status
        if cert.status == "verified":
            band = suggest_price(crop.crop_name, crop.ai_grade, crop.ai_quality_score,
                                 crop.state, crop.district, crop.organic, True)
            crop.ai_price_min, crop.ai_price_max = band["min"], band["max"]
            crop.ai_price_recommended = band["recommended"]
        done += 1

    db.session.commit()
    verified = sum(1 for c in Certificate.query.all() if c.status == "verified")
    print(f"  certificates     : {done} uploaded through the real OCMR pipeline "
          f"({verified} verified)")


def _iso(v):
    try:
        return date.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


# ======================================================================
# 7. REQUIREMENTS, DEALS, MESSAGES
# ======================================================================
REQUIREMENTS = [
    # (buyer index, crop, variety, qty, min grade, organic, certificate, days, notes)
    (0, "Grapes", "Thompson Seedless", 120, "B", False, True, 20,
     "Export consignment for EU. Need a current residue certificate and 8 kg punnets."),
    (0, "Pomegranate", "Bhagwa", 60, "B", False, True, 30,
     "Counts 8-12 preferred, uniform size, careful packing."),
    (1, "Tomato", None, 200, "B", False, False, 10,
     "Daily lifting for retail stores across Pune. Need steady supply."),
    (1, "Potato", "Kufri Jyoti", 150, "B", False, False, 25,
     "Cold-store quality, 50 kg bags."),
    (2, "Onion", None, 500, "C", False, False, 15,
     "Bulk trading lot. Any grade accepted if dry and well cured."),
    (3, "Banana", "Grand Naine", 300, "B", True, False, 18,
     "For pulp processing. Organic preferred, ripeness stage 3-4."),
    (3, "Soybean", None, 250, "C", False, False, 35,
     "For oil extraction. Moisture under 10%."),
]


def make_requirements(buyers):
    """
    Price ranges are derived from the live pricing engine rather than
    hard-coded, so a seeded requirement always sits in the same rupee
    neighbourhood as the seeded listings and real matches appear on both
    dashboards. A hard-coded ceiling would drift away from the generated
    price history and silently match nothing.
    """
    reqs = []
    for bi, crop, variety, qty, grade, organic, cert, days, notes in REQUIREMENTS:
        buyer = buyers[bi]

        band = suggest_price(crop, grade, None, "Maharashtra", buyer.district)
        pmin = round(band["min"] * 0.95 / 10) * 10
        pmax = round(band["max"] * 1.08 / 10) * 10

        r = Requirement(
            buyer_id=buyer.id, crop_name=crop, variety=variety, quantity=qty,
            min_grade=grade, price_min=pmin, price_max=pmax,
            state="Maharashtra", district=buyer.district,
            delivery_location=f"{buyer.company_name}, {buyer.district}",
            needed_by=date.today() + timedelta(days=days),
            organic_only=organic, certificate_mandatory=cert, notes=notes,
            status="open",
            created_at=datetime.utcnow() - timedelta(days=random.randint(0, 12)),
        )
        db.session.add(r)
        reqs.append(r)
    db.session.commit()
    print(f"  requirements     : {len(reqs)} open buyer requirements")
    return reqs


def make_deals(crops, reqs, farmers, buyers):
    deals = []

    def push(crop, buyer, initiated_by, qty, price, msg, status, req=None):
        d = DealRequest(
            crop_id=crop.id, requirement_id=req.id if req else None,
            farmer_id=crop.farmer_id, buyer_id=buyer.id,
            initiated_by=initiated_by, quantity=qty, offered_price=price,
            message=msg, status=status,
            created_at=datetime.utcnow() - timedelta(days=random.randint(0, 6),
                                                     hours=random.randint(0, 20)),
        )
        if status in ("accepted", "rejected", "completed"):
            d.responded_at = datetime.utcnow() - timedelta(hours=random.randint(1, 30))
        db.session.add(d)
        deals.append(d)
        return d

    by_crop = {}
    for c in crops:
        by_crop.setdefault(c.crop_name, []).append(c)

    # a pending buying request on a grapes lot
    if by_crop.get("Grapes"):
        g = by_crop["Grapes"][0]
        d1 = push(g, buyers[0], "buyer", 60, round(g.expected_price * 0.95),
                  "We need 60 quintal for an EU consignment leaving on the 28th. "
                  "Residue certificate must be current. Can you pack in 8 kg punnets?",
                  "pending", reqs[0])
        db.session.flush()
        db.session.add(Message(deal_id=d1.id, sender_id=buyers[0].id,
                               body="Also — can you confirm the pruning date and the last spray?"))

    # an accepted deal with chat
    if by_crop.get("Tomato"):
        t = by_crop["Tomato"][0]
        d2 = push(t, buyers[1], "buyer", 80, round(t.expected_price * 1.02),
                  "Looking for steady supply for our Pune stores. Starting with 80 quintal.",
                  "accepted", reqs[2])
        db.session.flush()
        for sid, body in [
            (t.farmer_id, "Thank you. I can load 80 quintal on Thursday morning."),
            (buyers[1].id, "Thursday works. Our vehicle will reach your field by 7 am."),
            (t.farmer_id, "Good. Crates will be ready. Payment on delivery as discussed."),
        ]:
            db.session.add(Message(deal_id=d2.id, sender_id=sid, body=body))

    # a farmer offer against a requirement
    if by_crop.get("Pomegranate"):
        p = by_crop["Pomegranate"][0]
        push(p, buyers[0], "farmer", 40, p.expected_price,
             "Bhagwa, counts 10-12, uniform. Can deliver to Nashik within 3 days.",
             "pending", reqs[1])

    # a completed deal
    if by_crop.get("Wheat"):
        w = by_crop["Wheat"][0]
        d4 = push(w, buyers[2], "buyer", 150, round(w.expected_price * 0.98),
                  "Standard trading lot, payment within 48 hours of weighment.", "completed")
        db.session.flush()
        db.session.add(Message(deal_id=d4.id, sender_id=buyers[2].id,
                               body="Weighment done, payment released. Good quality, thank you."))

    # a rejected one
    if by_crop.get("Onion"):
        o = by_crop["Onion"][0]
        d5 = push(o, buyers[2], "buyer", 200, round(o.expected_price * 0.72),
                  "Can you do 200 quintal at this rate for immediate lifting?", "rejected")
        d5.response_note = ("That rate is well below the current Lasalgaon modal price. "
                            "I can do it at my listed price for 200 quintal.")

    db.session.commit()

    # notifications for the pending ones
    for d in deals:
        if d.status != "pending":
            continue
        if d.initiated_by == "buyer":
            Notification.push(
                d.farmer_id, f"New buying request for your {d.crop.crop_name}",
                f"{d.buyer.company_name or d.buyer.full_name} wants {d.quantity:g} quintal "
                f"at Rs {d.offered_price:,.0f}/quintal.",
                f"/deals/{d.id}", "request")
        else:
            Notification.push(
                d.buyer_id, f"New offer for your {d.crop.crop_name} requirement",
                f"{d.farmer.full_name} offered {d.quantity:g} quintal "
                f"at Rs {d.offered_price:,.0f}/quintal.",
                f"/deals/{d.id}", "offer")
    db.session.commit()
    print(f"  deals            : {len(deals)} request threads with messages and notifications")


# ======================================================================
# MAIN
# ======================================================================
def main():
    keep = "--keep" in sys.argv
    app = create_app()

    with app.app_context():
        if not keep:
            print("\nAgriVision — building the demo database")
            print("=" * 58)
            db.drop_all()
            db.create_all()
            for folder in (Config.CROP_IMAGE_DIR, Config.CERTIFICATE_DIR):
                if os.path.isdir(folder):
                    shutil.rmtree(folder)
                os.makedirs(folder, exist_ok=True)
        else:
            print("\nAgriVision — adding demo data to the existing database")
            print("=" * 58)

        users = make_users()
        make_price_history()
        crops = make_crops(users["farmers"])
        make_certificates(crops)
        reqs = make_requirements(users["buyers"])
        make_deals(crops, reqs, users["farmers"], users["buyers"])

        print("=" * 58)
        print("Done. Start the server with:  python run.py")
        print("\nLog in with:")
        print("  Farmer  ramesh@agrivision.in     / farmer123")
        print("  Buyer   sahyadri@agrivision.in   / buyer123")
        print("  (every seeded farmer uses farmer123, every buyer buyer123)\n")


if __name__ == "__main__":
    main()
