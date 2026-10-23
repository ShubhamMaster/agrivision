"""
AgriVision — buyer blueprint.

    /buyer/dashboard                     overview + recommended lots
    /buyer/browse                        the marketplace, with filters + sorting
    /buyer/crop/<id>                     full lot page (quality, price, trend)
    /buyer/crop/<id>/request             send a buying request to the farmer
    /buyer/compare                       side-by-side comparison of up to 4 lots
    /buyer/requirements                  my posted requirements
    /buyer/requirements/new              post a requirement
    /buyer/requirements/<id>             requirement + matching lots + offers
    /buyer/requirements/<id>/edit
    /buyer/requirements/<id>/close
    /buyer/requirements/<id>/delete

Filtering happens in SQL where possible (crop, district, price, status) and in
Python only for the derived checks that depend on the AI columns, so the
listing page stays fast as the table grows.
"""

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from ..ai import demand as demand_ai
from ..ai.pricing import CROP_CATALOGUE, crop_info, grade_rank, suggest_price
from ..extensions import db
from ..i18n import t
from ..models import Crop, DealRequest, Notification, Requirement, User
from ..utils import clean, role_required, to_date, to_float

buyer_bp = Blueprint("buyer", __name__, template_folder="../templates/buyer")

SORT_OPTIONS = {
    "newest": "Newest first",
    "price_low": "Price: low to high",
    "price_high": "Price: high to low",
    "quality": "Best quality first",
    "quantity": "Largest lot first",
}


# ======================================================================
# DASHBOARD
# ======================================================================
@buyer_bp.route("/dashboard")
@role_required("buyer")
def dashboard():
    reqs = (Requirement.query.filter_by(buyer_id=current_user.id)
            .order_by(Requirement.created_at.desc()).all())

    my_deals = (DealRequest.query.filter_by(buyer_id=current_user.id)
                .order_by(DealRequest.created_at.desc()).all())

    stats = {
        "requirements": len(reqs),
        "open_requirements": sum(1 for r in reqs if r.status == "open"),
        "sent": sum(1 for d in my_deals if d.initiated_by == "buyer"),
        "offers_received": sum(1 for d in my_deals
                               if d.initiated_by == "farmer" and d.status == "pending"),
        "accepted": sum(1 for d in my_deals if d.status in ("accepted", "completed")),
        "committed_value": sum(d.total_value for d in my_deals
                               if d.status in ("accepted", "completed")),
    }

    # Lots that satisfy at least one open requirement.
    recommended, seen = [], set()
    for r in [x for x in reqs if x.status == "open"]:
        candidates = (Crop.query
                      .filter(Crop.crop_name == r.crop_name, Crop.status == "available")
                      .order_by(Crop.ai_quality_score.desc()).limit(12).all())
        for c in candidates:
            if c.id in seen or not r.matches(c):
                continue
            seen.add(c.id)
            recommended.append({"crop": c, "requirement": r})
            if len(recommended) >= 6:
                break
        if len(recommended) >= 6:
            break

    pending_offers = [d for d in my_deals
                      if d.initiated_by == "farmer" and d.status == "pending"][:5]

    return render_template("buyer/dashboard.html", reqs=reqs[:5], stats=stats,
                           recommended=recommended, pending_offers=pending_offers)


# ======================================================================
# MARKETPLACE
# ======================================================================
@buyer_bp.route("/browse")
@role_required("buyer")
def browse():
    f = {
        "crop": request.args.get("crop", ""),
        "district": request.args.get("district", ""),
        "state": request.args.get("state", ""),
        "grade": request.args.get("grade", ""),
        "max_price": to_float(request.args.get("max_price")),
        "min_qty": to_float(request.args.get("min_qty")),
        "organic": request.args.get("organic") == "1",
        "certified": request.args.get("certified") == "1",
        "sort": request.args.get("sort", "newest"),
    }

    q = Crop.query.filter(Crop.status == "available")
    if f["crop"]:
        q = q.filter(Crop.crop_name == f["crop"])
    if f["district"]:
        q = q.filter(Crop.district.ilike(f"%{f['district']}%"))
    if f["state"]:
        q = q.filter(Crop.state == f["state"])
    if f["max_price"]:
        q = q.filter(Crop.expected_price <= f["max_price"])
    if f["min_qty"]:
        q = q.filter(Crop.quantity >= f["min_qty"])
    if f["organic"]:
        q = q.filter(Crop.organic.is_(True))
    if f["certified"]:
        q = q.filter(Crop.certificate_status == "verified")

    sort = f["sort"]
    if sort == "price_low":
        q = q.order_by(Crop.expected_price.asc())
    elif sort == "price_high":
        q = q.order_by(Crop.expected_price.desc())
    elif sort == "quality":
        q = q.order_by(Crop.ai_quality_score.desc().nullslast())
    elif sort == "quantity":
        q = q.order_by(Crop.quantity.desc())
    else:
        q = q.order_by(Crop.created_at.desc())

    items = q.limit(200).all()

    # Grade filter uses the ranking helper so "B" means "B or better".
    if f["grade"]:
        wanted = grade_rank(f["grade"])
        items = [c for c in items if grade_rank(c.ai_grade) >= wanted]

    districts = sorted({c.district for c in Crop.query.filter(
        Crop.status == "available", Crop.district.isnot(None)).all() if c.district})

    return render_template("buyer/browse.html", items=items, f=f,
                           sort_options=SORT_OPTIONS, districts=districts)


@buyer_bp.route("/crop/<int:crop_id>")
@role_required("buyer")
def crop_detail(crop_id):
    crop = Crop.query.get_or_404(crop_id)

    crop.views = (crop.views or 0) + 1
    db.session.commit()

    band = suggest_price(crop.crop_name, crop.ai_grade, crop.ai_quality_score,
                         crop.state, crop.district, crop.organic,
                         crop.certificate_status == "verified")
    trend = demand_ai.price_trend(crop.crop_name, crop.state, crop.district, days=120)
    di = demand_ai.demand_index(crop.crop_name, crop.state, crop.district)

    # Fairness read-out for the buyer: is the asking price above the fair band?
    if crop.expected_price and crop.expected_price > band["max"]:
        price_note = {"colour": "warning",
                      "text": f"Asking price is above the AI fair band "
                              f"(Rs {band['min']:,.0f}–{band['max']:,.0f}). There is room to negotiate."}
    elif crop.expected_price and crop.expected_price < band["min"]:
        price_note = {"colour": "success",
                      "text": "Asking price is below the AI fair band — this lot is competitively priced."}
    else:
        price_note = {"colour": "secondary",
                      "text": "Asking price sits inside the AI fair band for this grade and region."}

    my_open_reqs = Requirement.query.filter_by(
        buyer_id=current_user.id, status="open", crop_name=crop.crop_name).all()

    existing = DealRequest.query.filter_by(
        crop_id=crop.id, buyer_id=current_user.id, status="pending").first()

    other_lots = (Crop.query
                  .filter(Crop.crop_name == crop.crop_name, Crop.status == "available",
                          Crop.id != crop.id)
                  .order_by(Crop.ai_quality_score.desc()).limit(4).all())

    return render_template("buyer/crop_detail.html", crop=crop, band=band, trend=trend,
                           demand=di, price_note=price_note, my_reqs=my_open_reqs,
                           existing=existing, other_lots=other_lots,
                           info=crop_info(crop.crop_name))


@buyer_bp.route("/crop/<int:crop_id>/request", methods=["POST"])
@role_required("buyer")
def send_request(crop_id):
    crop = Crop.query.get_or_404(crop_id)

    if crop.status != "available":
        flash(t("This lot is no longer available."), "warning")
        return redirect(url_for("buyer.browse"))
    if crop.certificate_required and crop.certificate_status != "verified":
        flash(t("This lot needs a verified quality certificate before it can be traded."), "warning")
        return redirect(url_for("buyer.crop_detail", crop_id=crop.id))

    quantity = to_float(request.form.get("quantity"))
    price = to_float(request.form.get("offered_price"), crop.expected_price)

    if not quantity or quantity <= 0 or quantity > crop.quantity:
        flash(t("Enter a quantity between 1 and {max:g} quintal.", max=crop.quantity), "danger")
        return redirect(url_for("buyer.crop_detail", crop_id=crop.id))

    duplicate = DealRequest.query.filter_by(
        crop_id=crop.id, buyer_id=current_user.id, status="pending").first()
    if duplicate:
        flash(t("You already have a pending request on this lot."), "info")
        return redirect(url_for("deals.detail", deal_id=duplicate.id))

    req_id = request.form.get("requirement_id") or None
    deal = DealRequest(
        crop_id=crop.id,
        requirement_id=int(req_id) if req_id and req_id.isdigit() else None,
        farmer_id=crop.farmer_id, buyer_id=current_user.id,
        initiated_by="buyer", quantity=quantity, offered_price=price,
        message=clean(request.form.get("message"), 500),
    )
    db.session.add(deal)
    db.session.flush()

    Notification.push(
        crop.farmer_id,
        title=f"New buying request for your {crop.crop_name}",
        body=(f"{current_user.company_name or current_user.full_name} wants {quantity:g} quintal "
              f"at Rs {price:,.0f}/quintal."),
        link=url_for("deals.detail", deal_id=deal.id), icon="request",
    )
    db.session.commit()

    flash(t("Buying request sent to the farmer."), "success")
    return redirect(url_for("deals.detail", deal_id=deal.id))


@buyer_bp.route("/compare")
@role_required("buyer")
def compare():
    ids = [int(i) for i in request.args.getlist("id") if i.isdigit()][:4]
    crops = Crop.query.filter(Crop.id.in_(ids)).all() if ids else []

    rows = []
    for c in crops:
        band = suggest_price(c.crop_name, c.ai_grade, c.ai_quality_score,
                             c.state, c.district, c.organic,
                             c.certificate_status == "verified")
        rows.append({
            "crop": c, "band": band,
            "value_score": _value_score(c, band),
        })
    rows.sort(key=lambda r: r["value_score"], reverse=True)
    return render_template("buyer/compare.html", rows=rows)


def _value_score(crop, band):
    """
    A single "worth buying" number: quality per rupee, with bonuses for
    certification and penalties for over-pricing.
    """
    if not crop.expected_price:
        return 0
    quality = crop.ai_quality_score or 50
    fairness = band["recommended"] / crop.expected_price     # >1 = cheap
    score = quality * min(1.35, max(0.65, fairness))
    if crop.certificate_status == "verified":
        score *= 1.06
    if crop.organic:
        score *= 1.04
    return round(score, 1)


# ======================================================================
# REQUIREMENTS
# ======================================================================
@buyer_bp.route("/requirements")
@role_required("buyer")
def requirements():
    status = request.args.get("status", "all")
    q = Requirement.query.filter_by(buyer_id=current_user.id)
    if status != "all":
        q = q.filter_by(status=status)
    items = q.order_by(Requirement.created_at.desc()).all()

    counts = {}
    for r in items:
        counts[r.id] = DealRequest.query.filter_by(
            requirement_id=r.id, status="pending").count()

    return render_template("buyer/requirements.html", items=items,
                           status=status, counts=counts)


@buyer_bp.route("/requirements/new", methods=["GET", "POST"])
@role_required("buyer")
def new_requirement():
    if request.method == "POST":
        errors = {}
        crop_name = clean(request.form.get("crop_name"), 60)
        quantity = to_float(request.form.get("quantity"))
        price_min = to_float(request.form.get("price_min"))
        price_max = to_float(request.form.get("price_max"))

        if not crop_name:
            errors["crop_name"] = "Select the crop you need."
        if not quantity or quantity <= 0:
            errors["quantity"] = "Enter the quantity you need in quintal."
        if price_min and price_max and price_min > price_max:
            errors["price_max"] = "The maximum price must be above the minimum."

        if errors:
            flash(t("Please correct the highlighted fields."), "danger")
            return render_template("buyer/requirement_form.html", errors=errors,
                                   form=request.form, req=None, mode="new")

        req = Requirement(
            buyer_id=current_user.id, crop_name=crop_name,
            variety=clean(request.form.get("variety"), 60),
            quantity=quantity,
            min_grade=clean(request.form.get("min_grade"), 1) or "B",
            price_min=price_min, price_max=price_max,
            state=clean(request.form.get("state"), 60) or current_user.state,
            district=clean(request.form.get("district"), 60) or current_user.district,
            delivery_location=clean(request.form.get("delivery_location"), 120),
            needed_by=to_date(request.form.get("needed_by")),
            organic_only=bool(request.form.get("organic_only")),
            certificate_mandatory=bool(request.form.get("certificate_mandatory")),
            notes=clean(request.form.get("notes"), 800),
        )
        db.session.add(req)
        db.session.flush()

        # Tell farmers in that district who have this crop listed.
        matching_farmers = {
            c.farmer_id for c in Crop.query.filter(
                Crop.crop_name == crop_name, Crop.status == "available").all()
        }
        for fid in list(matching_farmers)[:50]:
            Notification.push(
                fid,
                title=f"New requirement posted for {crop_name}",
                body=(f"{current_user.company_name or current_user.full_name} needs "
                      f"{quantity:g} quintal" +
                      (f" at up to Rs {price_max:,.0f}/quintal." if price_max else ".")),
                link=url_for("farmer.requirements"), icon="requirement",
            )
        db.session.commit()

        flash(t("Requirement posted. Matching farmers have been notified."), "success")
        return redirect(url_for("buyer.requirement_detail", req_id=req.id))

    return render_template("buyer/requirement_form.html", errors={}, form={},
                           req=None, mode="new")


@buyer_bp.route("/requirements/<int:req_id>")
@role_required("buyer")
def requirement_detail(req_id):
    req = _own_req(req_id)

    candidates = (Crop.query
                  .filter(Crop.crop_name == req.crop_name, Crop.status == "available")
                  .order_by(Crop.ai_quality_score.desc()).limit(60).all())
    matches = [c for c in candidates if req.matches(c)]
    near_misses = [c for c in candidates if c not in matches][:6]

    offers = (DealRequest.query.filter_by(requirement_id=req.id)
              .order_by(DealRequest.created_at.desc()).all())

    di = demand_ai.demand_index(req.crop_name, req.state, req.district)
    trend = demand_ai.price_trend(req.crop_name, req.state, req.district, days=120)

    return render_template("buyer/requirement_detail.html", req=req, matches=matches,
                           near_misses=near_misses, offers=offers, demand=di, trend=trend)


@buyer_bp.route("/requirements/<int:req_id>/edit", methods=["GET", "POST"])
@role_required("buyer")
def edit_requirement(req_id):
    req = _own_req(req_id)

    if request.method == "POST":
        req.variety = clean(request.form.get("variety"), 60)
        req.quantity = to_float(request.form.get("quantity"), req.quantity)
        req.min_grade = clean(request.form.get("min_grade"), 1) or req.min_grade
        req.price_min = to_float(request.form.get("price_min"))
        req.price_max = to_float(request.form.get("price_max"))
        req.state = clean(request.form.get("state"), 60) or req.state
        req.district = clean(request.form.get("district"), 60)
        req.delivery_location = clean(request.form.get("delivery_location"), 120)
        req.needed_by = to_date(request.form.get("needed_by")) or req.needed_by
        req.organic_only = bool(request.form.get("organic_only"))
        req.certificate_mandatory = bool(request.form.get("certificate_mandatory"))
        req.notes = clean(request.form.get("notes"), 800)
        db.session.commit()
        flash(t("Requirement updated."), "success")
        return redirect(url_for("buyer.requirement_detail", req_id=req.id))

    return render_template("buyer/requirement_form.html", errors={}, form={},
                           req=req, mode="edit")


@buyer_bp.route("/requirements/<int:req_id>/close", methods=["POST"])
@role_required("buyer")
def close_requirement(req_id):
    req = _own_req(req_id)
    req.status = "closed" if req.status == "open" else "open"
    db.session.commit()
    flash(t("Requirement closed.") if req.status == "closed"
          else t("Requirement reopened."), "info")
    return redirect(url_for("buyer.requirement_detail", req_id=req.id))


@buyer_bp.route("/requirements/<int:req_id>/delete", methods=["POST"])
@role_required("buyer")
def delete_requirement(req_id):
    req = _own_req(req_id)
    db.session.delete(req)
    db.session.commit()
    flash(t("Requirement deleted."), "info")
    return redirect(url_for("buyer.requirements"))


def _own_req(req_id):
    req = Requirement.query.get_or_404(req_id)
    if req.buyer_id != current_user.id:
        abort(403)
    return req
