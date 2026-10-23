"""
AgriVision — market intelligence blueprint.

    /insights/                     regional demand ranking + crop picker
    /insights/crop/<crop_name>     full report: trend, forecast, demand drivers
    /insights/api/trend            JSON feed for the charts (Chart.js)

Both roles can read these pages: a farmer uses them to decide what to grow and
when to sell, a buyer uses them to judge whether an asking price is fair.
"""

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from ..ai import demand as demand_ai
from ..ai.pricing import CROP_CATALOGUE, crop_info, suggest_price
from ..models import Crop, Requirement

insights_bp = Blueprint("insights", __name__, template_folder="../templates/insights")


@insights_bp.route("/")
@login_required
def overview():
    state = request.args.get("state") or current_user.state
    district = request.args.get("district") or current_user.district

    ranking = demand_ai.top_demand_crops(state, district, limit=len(CROP_CATALOGUE))

    districts = sorted({
        c.district for c in Crop.query.filter(Crop.district.isnot(None)).all() if c.district
    })

    return render_template("insights/overview.html", ranking=ranking,
                           state=state, district=district, districts=districts)


@insights_bp.route("/crop/<crop_name>")
@login_required
def crop_report(crop_name):
    state = request.args.get("state") or current_user.state
    district = request.args.get("district") or current_user.district

    trend = demand_ai.price_trend(crop_name, state, district, days=180)
    fc = demand_ai.forecast(crop_name, state, district, weeks_ahead=6)
    di = demand_ai.demand_index(crop_name, state, district)
    band = suggest_price(crop_name, "B", None, state, district)

    supply = Crop.query.filter_by(crop_name=crop_name, status="available").count()
    wanted = Requirement.query.filter_by(crop_name=crop_name, status="open").count()

    return render_template("insights/crop_report.html", crop_name=crop_name,
                           trend=trend, forecast=fc, demand=di, band=band,
                           info=crop_info(crop_name), state=state, district=district,
                           supply=supply, wanted=wanted)


@insights_bp.route("/api/trend")
@login_required
def api_trend():
    """JSON used by the Chart.js canvases: history + forecast in one payload."""
    crop_name = request.args.get("crop", "")
    state = request.args.get("state") or current_user.state
    district = request.args.get("district") or current_user.district

    if crop_name not in CROP_CATALOGUE:
        return jsonify({"ok": False, "error": "Unknown crop."}), 400

    trend = demand_ai.price_trend(crop_name, state, district, days=180)
    fc = demand_ai.forecast(crop_name, state, district, weeks_ahead=6)

    return jsonify({
        "ok": True, "crop": crop_name, "scope": trend.get("scope"),
        "history": [{"label": p["label"], "price": p["price"], "arrivals": p["arrivals"]}
                    for p in trend.get("points", [])],
        "forecast": [{"label": p["label"], "price": p["price"],
                      "low": p["band_low"], "high": p["band_high"]}
                     for p in fc.get("points", [])],
        "summary": {
            "latest": trend.get("latest"), "average": trend.get("average"),
            "change_pct": trend.get("change_pct"), "direction": trend.get("direction"),
            "forecast_change": fc.get("change_pct"),
        },
    })
