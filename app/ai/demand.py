"""
AgriVision — demand prediction and price-trend analytics.

Three questions are answered here:

  1. price_trend()      "How has this crop moved in my district recently?"
                        -> a weekly series ready to plot on a chart.

  2. demand_index()     "Is demand for this crop strong right now?"
                        -> a single 0-100 number plus the drivers behind it.

  3. forecast()         "Where is the price heading over the next 6 weeks?"
                        -> least-squares trend on weekly means, modulated by
                           the crop's seasonal calendar.

  4. top_demand_crops() "Which crops should I plant / sell in my region?"

Method
------
The demand index fuses four independent signals, each mapped to -1..+1 and
then weighted:

    price momentum   recent 30-day mean vs the preceding 90-day mean
    supply pressure  recent arrivals vs the preceding arrivals (inverted —
                     falling arrivals with firm prices means tight supply)
    season           the crop's own lean/glut calendar
    platform pull    open buyer requirements vs available farmer listings for
                     that crop in that region (the marketplace's own signal)

index = 50 + 50 * sum(weight_i * signal_i)

This is a transparent, explainable model — every driver is returned to the UI
so a farmer sees *why* demand is called strong, not just that it is.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

from .pricing import CROP_CATALOGUE, crop_info, season_factor

WEIGHTS = {
    "price_momentum": 0.38,
    "supply_pressure": 0.24,
    "season": 0.18,
    "platform_pull": 0.20,
}


# ======================================================================
# 1. PRICE TREND
# ======================================================================
def price_trend(crop_name: str, state: str | None = None, district: str | None = None,
                days: int = 180) -> dict:
    """
    Weekly mean modal price + weekly total arrivals for the chart on the
    insights page.  Falls back from district -> state -> national.
    """
    rows, scope = _fetch_records(crop_name, state, district, days)
    if not rows:
        return {"ok": False, "scope": scope, "points": [],
                "message": f"No price history available for {crop_name} yet."}

    buckets: dict[date, list] = {}
    for r in rows:
        wk = r.record_date - timedelta(days=r.record_date.weekday())
        buckets.setdefault(wk, []).append(r)

    points = []
    for wk in sorted(buckets):
        group = buckets[wk]
        prices = [g.modal_price for g in group if g.modal_price]
        arrivals = [g.arrivals for g in group if g.arrivals]
        points.append({
            "week": wk.isoformat(),
            "label": wk.strftime("%d %b"),
            "price": round(statistics.mean(prices), 1) if prices else None,
            "low": round(min(g.min_price for g in group if g.min_price), 1) if any(g.min_price for g in group) else None,
            "high": round(max(g.max_price for g in group if g.max_price), 1) if any(g.max_price for g in group) else None,
            "arrivals": round(sum(arrivals), 1) if arrivals else 0,
        })

    valid = [p["price"] for p in points if p["price"]]
    first, last = valid[0], valid[-1]
    change_pct = ((last - first) / first * 100) if first else 0

    return {
        "ok": True,
        "crop": crop_name,
        "scope": scope,
        "points": points,
        "latest": last,
        "period_low": min(valid),
        "period_high": max(valid),
        "average": round(statistics.mean(valid), 1),
        "change_pct": round(change_pct, 1),
        "direction": "rising" if change_pct > 3 else "falling" if change_pct < -3 else "flat",
    }


# ======================================================================
# 2. DEMAND INDEX
# ======================================================================
def demand_index(crop_name: str, state: str | None = None,
                 district: str | None = None) -> dict:
    """A 0-100 demand score with an itemised list of drivers."""
    signals, drivers = {}, []

    rows, scope = _fetch_records(crop_name, state, district, days=150)

    # --- signal 1: price momentum -------------------------------------
    recent_p, base_p = _split_mean(rows, "modal_price", recent_days=30)
    if recent_p and base_p:
        pm = (recent_p - base_p) / base_p
        signals["price_momentum"] = _clip(pm / 0.18)        # +-18% saturates
        drivers.append({
            "name": "Price momentum",
            "value": f"{pm * 100:+.1f}%",
            "detail": (f"Last 30 days averaged Rs {recent_p:,.0f}/quintal against "
                       f"Rs {base_p:,.0f} in the 90 days before that."),
            "positive": pm > 0,
        })
    else:
        signals["price_momentum"] = 0.0

    # --- signal 2: supply pressure (inverted arrivals) -----------------
    recent_a, base_a = _split_mean(rows, "arrivals", recent_days=30)
    if recent_a and base_a:
        sp = (base_a - recent_a) / base_a                   # arrivals falling = positive
        signals["supply_pressure"] = _clip(sp / 0.30)
        drivers.append({
            "name": "Supply pressure",
            "value": f"{-sp * 100:+.1f}% arrivals",
            "detail": (f"Mandi arrivals averaged {recent_a:,.0f} quintal/day recently "
                       f"against {base_a:,.0f} earlier — "
                       + ("tighter supply supports price." if sp > 0
                          else "heavier arrivals push price down.")),
            "positive": sp > 0,
        })
    else:
        signals["supply_pressure"] = 0.0

    # --- signal 3: season ---------------------------------------------
    s_factor, s_note = season_factor(crop_name)
    signals["season"] = _clip((s_factor - 1) / 0.12)
    drivers.append({
        "name": "Seasonal window", "value": f"{(s_factor - 1) * 100:+.0f}%",
        "detail": s_note, "positive": s_factor >= 1,
    })

    # --- signal 4: platform pull --------------------------------------
    wanted, offered = _platform_balance(crop_name, state, district)
    if wanted + offered > 0:
        pull = (wanted - offered) / max(1.0, float(wanted + offered))
        signals["platform_pull"] = _clip(pull * 1.4)
        drivers.append({
            "name": "Marketplace pull",
            "value": f"{wanted} wanted / {offered} listed",
            "detail": (f"{wanted} open buyer requirement(s) against {offered} available "
                       f"listing(s) for {crop_name} in this region."),
            "positive": wanted >= offered,
        })
    else:
        signals["platform_pull"] = 0.0

    raw = sum(WEIGHTS[k] * signals.get(k, 0.0) for k in WEIGHTS)
    index = max(4.0, min(97.0, 50 + 50 * raw))

    if index >= 72:
        label, colour = "Strong demand", "success"
    elif index >= 58:
        label, colour = "Firm demand", "success"
    elif index >= 43:
        label, colour = "Balanced market", "secondary"
    elif index >= 30:
        label, colour = "Soft demand", "warning"
    else:
        label, colour = "Weak demand", "danger"

    return {
        "crop": crop_name, "scope": scope,
        "index": round(index, 1), "label": label, "colour": colour,
        "signals": {k: round(v, 3) for k, v in signals.items()},
        "drivers": drivers,
        "advice": _advice(index, crop_name),
    }


def _advice(index, crop_name):
    if index >= 72:
        return (f"Demand for {crop_name} is strong — this is a good window to sell, and you "
                f"can hold firm near the upper end of the recommended price band.")
    if index >= 58:
        return (f"{crop_name} is holding firm. Listing now is reasonable; price in the middle "
                f"of the recommended band to close quickly.")
    if index >= 43:
        return (f"The market for {crop_name} is balanced. Compare buyer requirements before "
                f"fixing your price.")
    if index >= 30:
        return (f"Demand for {crop_name} is soft. If you have storage, waiting a few weeks may "
                f"pay; otherwise price competitively to move the lot.")
    return (f"Demand for {crop_name} is weak right now. Consider staggered selling, value "
            f"addition, or targeting buyers outside this district.")


# ======================================================================
# 3. FORECAST
# ======================================================================
def forecast(crop_name: str, state: str | None = None, district: str | None = None,
             weeks_ahead: int = 6) -> dict:
    """
    Least-squares linear trend over the last ~20 weekly means, then multiplied
    by the crop's seasonal factor for the month each future week falls in.
    """
    trend = price_trend(crop_name, state, district, days=180)
    if not trend["ok"] or len(trend["points"]) < 4:
        return {"ok": False, "message": "Not enough history to forecast this crop yet.",
                "points": []}

    series = [(i, p["price"]) for i, p in enumerate(trend["points"]) if p["price"]]
    slope, intercept = _least_squares(series)

    n = len(trend["points"])
    last_week = date.fromisoformat(trend["points"][-1]["week"])
    out = []
    for k in range(1, weeks_ahead + 1):
        wk = last_week + timedelta(weeks=k)
        base = intercept + slope * (n - 1 + k)
        # A continuous seasonal curve, not the month-level step used for
        # pricing: a step function makes every week inside one month project
        # to the same rupee, which reads like a broken forecast.
        sf = _smooth_season(crop_name, wk)
        # Damp the linear trend as we go further out — honest about uncertainty.
        damp = 1.0 - 0.06 * k
        value = base * sf * damp + trend["average"] * (1 - damp)
        out.append({
            "week": wk.isoformat(), "label": wk.strftime("%d %b"),
            "price": round(max(0.0, value), 1),
            "band_low": round(max(0.0, value * (1 - crop_info(crop_name)["volatility"] * 0.7)), 1),
            "band_high": round(value * (1 + crop_info(crop_name)["volatility"] * 0.7), 1),
        })

    change = ((out[-1]["price"] - trend["latest"]) / trend["latest"] * 100) if trend["latest"] else 0
    return {
        "ok": True, "crop": crop_name, "points": out,
        "from_price": trend["latest"], "to_price": out[-1]["price"],
        "change_pct": round(change, 1),
        "direction": "rising" if change > 3 else "falling" if change < -3 else "stable",
        "horizon_weeks": weeks_ahead,
        "note": ("Projection from the recent linear trend adjusted for seasonality. "
                 "Confidence narrows the further out you look — treat week 5-6 as indicative."),
    }


# ======================================================================
# 4. REGIONAL RANKING
# ======================================================================
def top_demand_crops(state: str | None = None, district: str | None = None,
                     limit: int = 6) -> list[dict]:
    """Rank every catalogue crop by demand index for this region."""
    results = []
    for name in CROP_CATALOGUE:
        try:
            di = demand_index(name, state, district)
            results.append({
                "crop": name, "index": di["index"], "label": di["label"],
                "colour": di["colour"],
                "top_driver": di["drivers"][0]["detail"] if di["drivers"] else "",
            })
        except Exception:
            continue
    results.sort(key=lambda r: r["index"], reverse=True)
    return results[:limit]


# ======================================================================
# helpers
# ======================================================================
def _fetch_records(crop_name, state, district, days):
    from ..models import PriceRecord

    since = date.today() - timedelta(days=days)
    for dist, st, scope in (
        (district, state, f"{district}, {state}" if district else None),
        (None, state, state),
        (None, None, "All India"),
    ):
        if scope is None:
            continue
        q = PriceRecord.query.filter(
            PriceRecord.crop_name == crop_name, PriceRecord.record_date >= since
        )
        if dist:
            q = q.filter(PriceRecord.district == dist)
        if st:
            q = q.filter(PriceRecord.state == st)
        rows = q.order_by(PriceRecord.record_date).all()
        if len(rows) >= 8:
            return rows, scope
    return [], "All India"


def _split_mean(rows, attr, recent_days=30):
    """Mean of `attr` over the recent window vs the window before it."""
    if not rows:
        return None, None
    cutoff = date.today() - timedelta(days=recent_days)
    recent = [getattr(r, attr) for r in rows if r.record_date >= cutoff and getattr(r, attr)]
    base = [getattr(r, attr) for r in rows if r.record_date < cutoff and getattr(r, attr)]
    if len(recent) < 3 or len(base) < 3:
        return None, None
    return statistics.mean(recent), statistics.mean(base)


def _platform_balance(crop_name, state, district):
    """Open buyer requirements vs available farmer listings in this region."""
    from ..models import Crop, Requirement

    rq = Requirement.query.filter(Requirement.crop_name == crop_name,
                                  Requirement.status == "open")
    cq = Crop.query.filter(Crop.crop_name == crop_name, Crop.status == "available")
    if state:
        rq = rq.filter(Requirement.state == state)
        cq = cq.filter(Crop.state == state)
    return rq.count(), cq.count()


def _smooth_season(crop_name, day):
    """
    Continuous version of the seasonal factor.

    season_factor() returns a step per month because a farmer reading the price
    breakdown wants a single clear reason ("March is a glut month, -12%").  For
    a week-by-week forecast that same step function would hold the projection
    flat inside a month and then jump, so here the crop's peak months are
    turned into the phase of a cosine and the factor varies every day.
    """
    info = crop_info(crop_name)
    peaks = info["peak_months"] or [6]
    peak_doy = ((sum(peaks) / len(peaks)) - 1) * 30.4 + 15
    doy = day.timetuple().tm_yday
    return 1 + 0.10 * math.cos(2 * math.pi * (doy - peak_doy) / 365.0)


def _least_squares(points):
    n = len(points)
    if n < 2:
        return 0.0, points[0][1] if points else 0.0
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _clip(x):
    return max(-1.0, min(1.0, float(x)))
