"""
AgriVision — price recommendation engine.

The question this module answers:

    "A farmer in Nashik has 40 quintal of Grade-A Thompson grapes, certified,
     in March.  What price per quintal should he ask for?"

The recommended price is built from five multiplicative factors applied on a
regional base price:

    price = base_regional_price
            x grade_factor          (quality assessed by the CV model)
            x season_factor         (where we are in that crop's calendar)
            x demand_factor         (demand index from app/ai/demand.py)
            x premium_factor        (organic / certified bonuses)

`base_regional_price` is the median modal price of the last 45 days for that
crop in the farmer's district, taken from the PriceRecord table.  When the
district has no data we fall back to the state, then to the catalogue's
reference price — so the engine always returns something sensible.

The band (min, max) is the recommended price +/- the crop's volatility, which
is wider for perishables (tomato, grapes) and narrower for storables (wheat).
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

# ======================================================================
# CROP CATALOGUE
# ----------------------------------------------------------------------
# One entry per crop the platform supports.
#
#   base_price     reference modal price, Rs per quintal (fallback only)
#   volatility     typical +/- swing as a fraction of price
#   peak_months    months when supply is low / price is high
#   glut_months    harvest-flood months when price collapses
#   hue_bands      OpenCV HSV hue ranges (0-179) a healthy sample should show
#   min_sat        minimum saturation for a pixel to count as "produce"
#   certificate    True if this crop needs a quality certificate to trade
#   unit_note      shown in the UI
# ======================================================================
CROP_CATALOGUE = {
    # The hue bands below were re-measured against the real specimen
    # photographs in assets/specimens (see tools/check_hue_bands.py). The
    # earlier values were fitted to drawn stand-ins and were wrong for several
    # crops — notably maize, whose kernels sit around hue 45, well outside the
    # old 16-40 band.
    "Grapes": {
        "base_price": 5800, "volatility": 0.18,
        "peak_months": [6, 7, 8, 9], "glut_months": [2, 3, 4],
        # green/white table grapes run yellow-green from ~24; black varieties
        # sit in the purple band
        "hue_bands": [(24, 90), (115, 168)], "min_sat": 30,
        "certificate": True, "unit_note": "Export lots usually 20-100 quintal",
    },
    "Pomegranate": {
        "base_price": 7200, "volatility": 0.17,
        "peak_months": [5, 6, 7], "glut_months": [10, 11, 12],
        "hue_bands": [(0, 14), (160, 179)], "min_sat": 45,
        "certificate": True, "unit_note": "Bhagwa variety fetches the premium",
    },
    "Mango": {
        "base_price": 6500, "volatility": 0.22,
        "peak_months": [3, 4], "glut_months": [5, 6],
        # unripe green through to ripe yellow-orange, plus the red blush some
        # varieties carry on the shoulder
        "hue_bands": [(8, 82), (168, 179)], "min_sat": 32,
        "certificate": True, "unit_note": "Alphonso / Kesar graded by size",
    },
    "Banana": {
        "base_price": 1600, "volatility": 0.20,
        "peak_months": [4, 5, 8], "glut_months": [11, 12, 1],
        "hue_bands": [(18, 40), (35, 85)], "min_sat": 35,
        "certificate": True, "unit_note": "Priced per quintal of bunch weight",
    },
    "Tomato": {
        "base_price": 1400, "volatility": 0.38,
        "peak_months": [7, 8, 9], "glut_months": [12, 1, 2],
        "hue_bands": [(0, 12), (165, 179)], "min_sat": 60,
        "certificate": False, "unit_note": "Highly volatile — check trend before fixing",
    },
    "Onion": {
        "base_price": 2200, "volatility": 0.32,
        "peak_months": [8, 9, 10], "glut_months": [3, 4, 5],
        "hue_bands": [(0, 22), (140, 179)], "min_sat": 25,
        "certificate": False, "unit_note": "Lasalgaon is the price benchmark",
    },
    "Potato": {
        "base_price": 1500, "volatility": 0.24,
        "peak_months": [8, 9, 10], "glut_months": [2, 3],
        # white/yellow skins are earthy browns; red-skinned varieties wrap
        # around into the red band
        "hue_bands": [(0, 32), (160, 179)], "min_sat": 18,
        "certificate": False, "unit_note": "Cold-store stock sells year-round",
    },
    "Wheat": {
        "base_price": 2450, "volatility": 0.09,
        "peak_months": [9, 10, 11], "glut_months": [3, 4],
        "hue_bands": [(14, 38)], "min_sat": 25,
        "certificate": False, "unit_note": "MSP acts as a floor price",
    },
    "Rice": {
        "base_price": 2300, "volatility": 0.10,
        "peak_months": [5, 6, 7], "glut_months": [10, 11],
        "hue_bands": [(12, 40)], "min_sat": 12,
        "certificate": False, "unit_note": "Basmati grades separately",
    },
    "Maize": {
        "base_price": 2050, "volatility": 0.13,
        "peak_months": [6, 7], "glut_months": [10, 11],
        # golden kernels measure around hue 45, not 25 as first assumed
        "hue_bands": [(18, 62)], "min_sat": 32,
        "certificate": False, "unit_note": "Poultry-feed demand drives price",
    },
    "Soybean": {
        "base_price": 4600, "volatility": 0.15,
        "peak_months": [6, 7, 8], "glut_months": [10, 11],
        "hue_bands": [(14, 38)], "min_sat": 25,
        "certificate": False, "unit_note": "Oil-mill demand is the main driver",
    },
    "Cotton": {
        "base_price": 7400, "volatility": 0.14,
        "peak_months": [5, 6, 7], "glut_months": [11, 12, 1],
        "hue_bands": [(0, 179)], "min_sat": 0,
        "certificate": False, "unit_note": "Staple length decides the grade",
    },
    "Sugarcane": {
        "base_price": 340, "volatility": 0.07,
        "peak_months": [8, 9], "glut_months": [12, 1, 2],
        "hue_bands": [(30, 85)], "min_sat": 30,
        "certificate": False, "unit_note": "FRP-linked, priced per quintal",
    },
    "Chilli": {
        "base_price": 9500, "volatility": 0.26,
        "peak_months": [7, 8, 9], "glut_months": [1, 2, 3],
        "hue_bands": [(0, 12), (165, 179), (35, 85)], "min_sat": 55,
        "certificate": False, "unit_note": "Dry chilli priced far above green",
    },
}

GRADE_FACTORS = {"A": 1.18, "B": 1.00, "C": 0.82}
GRADE_RANK = {"A": 3, "B": 2, "C": 1}


# ----------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------
def grade_rank(grade: str | None) -> int:
    """'A' -> 3, 'B' -> 2, 'C' -> 1, unknown -> 0. Used for comparisons."""
    return GRADE_RANK.get((grade or "").upper(), 0)


def crop_info(crop_name: str) -> dict:
    """Catalogue entry for a crop, with a neutral default for unknown crops."""
    return CROP_CATALOGUE.get(
        crop_name,
        {
            "base_price": 2500, "volatility": 0.20,
            "peak_months": [], "glut_months": [],
            "hue_bands": [(0, 179)], "min_sat": 0,
            "certificate": False, "unit_note": "",
        },
    )


def needs_certificate(crop_name: str) -> bool:
    return bool(crop_info(crop_name).get("certificate"))


def season_factor(crop_name: str, month: int | None = None) -> tuple[float, str]:
    """
    Where the crop sits in its own price calendar.

    Peak (lean supply) months get up to +12%, glut (harvest flood) months get
    up to -12%, everything else is interpolated towards neutral.
    """
    month = month or date.today().month
    info = crop_info(crop_name)
    if month in info["peak_months"]:
        return 1.12, f"{_month_name(month)} is a lean-supply month for {crop_name} (+12%)"
    if month in info["glut_months"]:
        return 0.88, f"{_month_name(month)} is peak-harvest season — supply glut (-12%)"

    # Neighbouring a peak/glut month gives a softened effect.
    prev_m = 12 if month == 1 else month - 1
    next_m = 1 if month == 12 else month + 1
    if prev_m in info["peak_months"] or next_m in info["peak_months"]:
        return 1.05, f"Approaching the lean-supply window for {crop_name} (+5%)"
    if prev_m in info["glut_months"] or next_m in info["glut_months"]:
        return 0.95, f"Close to the harvest-flood window for {crop_name} (-5%)"
    return 1.00, "Normal season — no seasonal adjustment"


def _month_name(m: int) -> str:
    return ["", "January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"][m]


# ----------------------------------------------------------------------
# regional base price
# ----------------------------------------------------------------------
def regional_base_price(crop_name: str, state: str | None = None,
                        district: str | None = None, days: int = 45) -> tuple[float, str]:
    """
    Median modal price of recent PriceRecord rows, narrowing from district to
    state to national, and finally to the catalogue reference price.

    Returns (price, source_label).
    """
    from ..models import PriceRecord          # imported here to avoid a cycle

    since = date.today() - timedelta(days=days)

    attempts = [
        (district, state, f"{district} mandi data (last {days} days)"),
        (None, state, f"{state} state average (last {days} days)"),
        (None, None, f"all-India average (last {days} days)"),
    ]

    for dist, st, label in attempts:
        q = PriceRecord.query.filter(
            PriceRecord.crop_name == crop_name,
            PriceRecord.record_date >= since,
        )
        if dist:
            q = q.filter(PriceRecord.district == dist)
        if st:
            q = q.filter(PriceRecord.state == st)
        prices = [r.modal_price for r in q.all() if r.modal_price]
        if len(prices) >= 3:
            return float(statistics.median(prices)), label

    return float(crop_info(crop_name)["base_price"]), "catalogue reference price (no mandi data yet)"


# ----------------------------------------------------------------------
# the main entry point
# ----------------------------------------------------------------------
def suggest_price(crop_name: str, grade: str | None = "B", quality_score: float | None = None,
                  state: str | None = None, district: str | None = None,
                  organic: bool = False, certified: bool = False,
                  month: int | None = None, use_demand: bool = True) -> dict:
    """
    Recommend a selling price band.

    Returns a dict:
        recommended, min, max, base, factors[], explanation[], source
    """
    info = crop_info(crop_name)
    base, source = regional_base_price(crop_name, state, district)

    factors = []          # (name, multiplier, explanation)

    # 1) quality ------------------------------------------------------
    g = (grade or "B").upper()
    g_factor = GRADE_FACTORS.get(g, 1.0)
    # A high score inside a grade nudges the factor up slightly (smooth, not stepped).
    if quality_score is not None:
        g_factor *= 1 + (float(quality_score) - 65.0) / 1000.0   # +/- 3.5% max
    g_factor = round(max(0.70, min(1.30, g_factor)), 4)
    factors.append(("Quality grade", g_factor,
                    f"Grade {g}" + (f" (score {quality_score:.0f}/100)" if quality_score else "")))

    # 2) season -------------------------------------------------------
    s_factor, s_note = season_factor(crop_name, month)
    factors.append(("Season", s_factor, s_note))

    # 3) demand -------------------------------------------------------
    d_factor, d_note = 1.0, "Demand signal not used"
    if use_demand:
        try:
            from .demand import demand_index
            di = demand_index(crop_name, state, district)
            # demand index 0-100, 50 is neutral -> factor between 0.92 and 1.10
            d_factor = round(1 + (di["index"] - 50) / 550.0, 4)
            d_note = f"Demand index {di['index']:.0f}/100 — {di['label']}"
        except Exception:
            pass
    factors.append(("Market demand", d_factor, d_note))

    # 4) premiums -----------------------------------------------------
    p_factor = 1.0
    notes = []
    if organic:
        p_factor *= 1.15
        notes.append("organic +15%")
    if certified:
        p_factor *= 1.08
        notes.append("verified certificate +8%")
    factors.append(("Premiums", round(p_factor, 4),
                    ", ".join(notes) if notes else "No premium applicable"))

    # ------------------------------------------------------------------
    recommended = base
    for _, f, _n in factors:
        recommended *= f

    vol = info["volatility"]
    # A confident, high-quality lot gets a tighter band than a doubtful one.
    spread = vol * (0.75 if g == "A" else 1.0 if g == "B" else 1.15)

    result = {
        "crop": crop_name,
        "base": round(base, 2),
        "source": source,
        "recommended": round(recommended / 10) * 10,         # round to nearest Rs 10
        "min": round(recommended * (1 - spread) / 10) * 10,
        "max": round(recommended * (1 + spread) / 10) * 10,
        "grade": g,
        "factors": [
            {"name": n, "multiplier": f, "effect": f"{(f - 1) * 100:+.1f}%", "note": note}
            for n, f, note in factors
        ],
        "volatility_pct": round(spread * 100, 1),
        "unit": "Rs / quintal",
        "unit_note": info.get("unit_note", ""),
    }
    result["explanation"] = _build_explanation(result)
    return result


def _build_explanation(r: dict) -> str:
    bits = [f"Starting from {r['source']} at Rs {r['base']:,.0f}/quintal."]
    for f in r["factors"]:
        if abs(f["multiplier"] - 1) > 0.001:
            bits.append(f"{f['name']} {f['effect']} ({f['note']}).")
    bits.append(
        f"Recommended ask: Rs {r['recommended']:,.0f}/quintal, "
        f"realistic band Rs {r['min']:,.0f} – Rs {r['max']:,.0f}."
    )
    return " ".join(bits)


def evaluate_asking_price(crop_name: str, asking: float, band: dict) -> dict:
    """Compare what the farmer typed with the AI band and produce UI feedback."""
    if not asking:
        return {"verdict": "unknown", "colour": "secondary", "message": "No price entered."}
    if asking < band["min"]:
        gap = band["min"] - asking
        return {
            "verdict": "below", "colour": "warning",
            "message": (f"Your price is Rs {gap:,.0f}/quintal below the fair band. "
                        f"You may be under-selling by about Rs {gap:,.0f} per quintal."),
        }
    if asking > band["max"]:
        gap = asking - band["max"]
        return {
            "verdict": "above", "colour": "danger",
            "message": (f"Your price is Rs {gap:,.0f}/quintal above the fair band. "
                        f"Buyers may skip this listing — consider lowering it."),
        }
    return {
        "verdict": "within", "colour": "success",
        "message": "Your price sits inside the AI-recommended fair band. Good pricing.",
    }
