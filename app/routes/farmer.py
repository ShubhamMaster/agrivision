"""
AgriVision — farmer blueprint (everything a farmer can do).

    /farmer/dashboard                     summary of lots, requests, insights
    /farmer/crops                         my listings
    /farmer/crops/new                     create a listing  (AI runs here)
    /farmer/crops/<id>                    manage one listing
    /farmer/crops/<id>/edit               edit details / add photos
    /farmer/crops/<id>/regrade            re-run the CV grader
    /farmer/crops/<id>/status/<status>    mark sold / withdrawn / available
    /farmer/crops/<id>/delete             delete the listing and its files
    /farmer/crops/<id>/certificate        upload + OCMR-verify a certificate
    /farmer/certificates/<id>             the verification report
    /farmer/requirements                  buyer requirements, best matches first
    /farmer/requirements/<id>/offer       offer one of my lots against it
    /farmer/api/price-suggestion          JSON — live price helper for the form

The AI call sequence when a listing is created
----------------------------------------------
    photos saved to disk
        -> grading.grade_many(paths, crop)        quality score + grade
        -> pricing.suggest_price(...)             price band using that grade
        -> demand.demand_index(...) (inside pricing) regional demand factor
    results written onto the Crop row so the buyer side can filter on them
    without re-running the models.
"""

import json
import os
from datetime import datetime

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required

from ..ai import certificate as cert_ai
from ..ai import demand as demand_ai
from ..ai.grading import grade_many
from ..ai.pricing import (crop_info, evaluate_asking_price, needs_certificate,
                          suggest_price)
from ..extensions import db
from ..i18n import t
from ..models import Certificate, Crop, CropPhoto, DealRequest, Notification, Requirement
from ..utils import (certificate_path, clean, crop_image_path, delete_file,
                     role_required, save_upload, to_date, to_float)

farmer_bp = Blueprint("farmer", __name__, template_folder="../templates/farmer")

MAX_PHOTOS = 5


# ======================================================================
# DASHBOARD
# ======================================================================
@farmer_bp.route("/dashboard")
@role_required("farmer")
def dashboard():
    crops = (Crop.query.filter_by(farmer_id=current_user.id)
             .order_by(Crop.created_at.desc()).all())

    incoming = (DealRequest.query
                .filter_by(farmer_id=current_user.id, status="pending")
                .order_by(DealRequest.created_at.desc()).limit(5).all())

    accepted = DealRequest.query.filter_by(
        farmer_id=current_user.id, status="accepted").count()

    stats = {
        "total": len(crops),
        "available": sum(1 for c in crops if c.status == "available"),
        "sold": sum(1 for c in crops if c.status == "sold"),
        "quantity": sum(c.quantity or 0 for c in crops if c.status == "available"),
        "views": sum(c.views or 0 for c in crops),
        "pending_requests": len(incoming),
        "accepted_deals": accepted,
        "potential_value": sum((c.quantity or 0) * (c.expected_price or 0)
                               for c in crops if c.status == "available"),
    }

    # Regional intelligence for this farmer's district.
    top_crops = demand_ai.top_demand_crops(current_user.state, current_user.district, limit=5)

    # Buyer requirements that match something this farmer already has.
    matches = []
    open_reqs = Requirement.query.filter_by(status="open").order_by(
        Requirement.created_at.desc()).limit(40).all()
    for r in open_reqs:
        for c in crops:
            if r.matches(c):
                matches.append({"requirement": r, "crop": c})
                break
        if len(matches) >= 5:
            break

    return render_template("farmer/dashboard.html", crops=crops[:6], stats=stats,
                           incoming=incoming, top_crops=top_crops, matches=matches)


# ======================================================================
# LISTINGS
# ======================================================================
@farmer_bp.route("/crops")
@role_required("farmer")
def crops():
    status = request.args.get("status", "all")
    q = Crop.query.filter_by(farmer_id=current_user.id)
    if status != "all":
        q = q.filter_by(status=status)
    items = q.order_by(Crop.created_at.desc()).all()
    return render_template("farmer/crops.html", items=items, status=status)


@farmer_bp.route("/crops/new", methods=["GET", "POST"])
@role_required("farmer")
def new_crop():
    if request.method == "POST":
        errors = {}
        crop_name = clean(request.form.get("crop_name"), 60)
        quantity = to_float(request.form.get("quantity"))
        expected_price = to_float(request.form.get("expected_price"))

        if not crop_name:
            errors["crop_name"] = "Select the crop."
        if not quantity or quantity <= 0:
            errors["quantity"] = "Enter the available quantity in quintal."
        if not expected_price or expected_price <= 0:
            errors["expected_price"] = "Enter your expected price per quintal."

        files = [f for f in request.files.getlist("photos") if f and f.filename]
        if not files:
            errors["photos"] = "At least one photo is required — the AI grades the lot from it."
        if len(files) > MAX_PHOTOS:
            errors["photos"] = f"You can upload at most {MAX_PHOTOS} photos."

        if errors:
            flash(t("Please correct the highlighted fields."), "danger")
            return render_template("farmer/crop_form.html", errors=errors,
                                   form=request.form, crop=None, mode="new")

        # --- 1. create the row ---------------------------------------
        crop = Crop(
            farmer_id=current_user.id,
            crop_name=crop_name,
            variety=clean(request.form.get("variety"), 60),
            quantity=quantity,
            harvest_date=to_date(request.form.get("harvest_date")),
            description=clean(request.form.get("description"), 1000),
            organic=bool(request.form.get("organic")),
            state=clean(request.form.get("state"), 60) or current_user.state,
            district=clean(request.form.get("district"), 60) or current_user.district,
            market=clean(request.form.get("market"), 60),
            expected_price=expected_price,
        )
        crop.certificate_required = needs_certificate(crop_name)
        crop.certificate_status = "pending" if crop.certificate_required else "not_required"
        db.session.add(crop)
        db.session.flush()                    # we need crop.id for the filenames

        # --- 2. save the photos ---------------------------------------
        saved_paths = []
        for f in files:
            stored, err = save_upload(
                f, current_app.config["CROP_IMAGE_DIR"],
                current_app.config["ALLOWED_IMAGE_EXTENSIONS"], prefix=f"crop{crop.id}_")
            if err:
                flash(f"{f.filename}: {t(err)}", "warning")
                continue
            db.session.add(CropPhoto(crop_id=crop.id, filename=stored))
            saved_paths.append(crop_image_path(stored))

        if not saved_paths:
            db.session.rollback()
            flash(t("None of the photos could be saved. Please try again with JPG or PNG files."),
                  "danger")
            return redirect(url_for("farmer.new_crop"))

        db.session.flush()

        # --- 3. run the AI --------------------------------------------
        _apply_ai(crop, saved_paths)
        db.session.commit()

        flash(t("Listing created. AI grade: {grade} ({score:.0f}/100).",
                grade=crop.ai_grade, score=crop.ai_quality_score), "success")
        return redirect(url_for("farmer.crop_detail", crop_id=crop.id))

    return render_template("farmer/crop_form.html", errors={}, form={},
                           crop=None, mode="new")


@farmer_bp.route("/crops/<int:crop_id>")
@role_required("farmer")
def crop_detail(crop_id):
    crop = _own_crop(crop_id)

    band = suggest_price(
        crop.crop_name, crop.ai_grade, crop.ai_quality_score,
        crop.state, crop.district, crop.organic,
        crop.certificate_status == "verified",
    )
    verdict = evaluate_asking_price(crop.crop_name, crop.expected_price, band)
    trend = demand_ai.price_trend(crop.crop_name, crop.state, crop.district, days=120)
    di = demand_ai.demand_index(crop.crop_name, crop.state, crop.district)

    requests_in = (DealRequest.query.filter_by(crop_id=crop.id)
                   .order_by(DealRequest.created_at.desc()).all())

    return render_template("farmer/crop_detail.html", crop=crop, band=band,
                           verdict=verdict, trend=trend, demand=di,
                           requests_in=requests_in, info=crop_info(crop.crop_name))


@farmer_bp.route("/crops/<int:crop_id>/edit", methods=["GET", "POST"])
@role_required("farmer")
def edit_crop(crop_id):
    crop = _own_crop(crop_id)

    if request.method == "POST":
        crop.variety = clean(request.form.get("variety"), 60)
        crop.quantity = to_float(request.form.get("quantity"), crop.quantity)
        crop.expected_price = to_float(request.form.get("expected_price"), crop.expected_price)
        crop.harvest_date = to_date(request.form.get("harvest_date")) or crop.harvest_date
        crop.description = clean(request.form.get("description"), 1000)
        crop.organic = bool(request.form.get("organic"))
        crop.state = clean(request.form.get("state"), 60) or crop.state
        crop.district = clean(request.form.get("district"), 60) or crop.district
        crop.market = clean(request.form.get("market"), 60)

        # Optional extra photos — they trigger a re-grade.
        new_files = [f for f in request.files.getlist("photos") if f and f.filename]
        room = MAX_PHOTOS - len(crop.photos)
        for f in new_files[:max(0, room)]:
            stored, err = save_upload(
                f, current_app.config["CROP_IMAGE_DIR"],
                current_app.config["ALLOWED_IMAGE_EXTENSIONS"], prefix=f"crop{crop.id}_")
            if err:
                flash(f"{f.filename}: {t(err)}", "warning")
                continue
            db.session.add(CropPhoto(crop_id=crop.id, filename=stored))
        db.session.flush()

        if new_files:
            _apply_ai(crop, [crop_image_path(p.filename) for p in crop.photos])
        else:
            _reprice(crop)

        db.session.commit()
        flash(t("Listing updated."), "success")
        return redirect(url_for("farmer.crop_detail", crop_id=crop.id))

    return render_template("farmer/crop_form.html", errors={}, form={},
                           crop=crop, mode="edit")


@farmer_bp.route("/crops/<int:crop_id>/regrade", methods=["POST"])
@role_required("farmer")
def regrade(crop_id):
    crop = _own_crop(crop_id)
    paths = [crop_image_path(p.filename) for p in crop.photos]
    if not paths:
        flash(t("This listing has no photos to analyse."), "warning")
    else:
        _apply_ai(crop, paths)
        db.session.commit()
        flash(t("Re-analysed: grade {grade} ({score:.0f}/100).",
                  grade=crop.ai_grade, score=crop.ai_quality_score), "success")
    return redirect(url_for("farmer.crop_detail", crop_id=crop.id))


@farmer_bp.route("/crops/<int:crop_id>/photos/<int:photo_id>/delete", methods=["POST"])
@role_required("farmer")
def delete_photo(crop_id, photo_id):
    crop = _own_crop(crop_id)
    photo = CropPhoto.query.get_or_404(photo_id)
    if photo.crop_id != crop.id:
        abort(403)
    if len(crop.photos) <= 1:
        flash(t("A listing must keep at least one photo."), "warning")
        return redirect(url_for("farmer.crop_detail", crop_id=crop.id))

    delete_file(crop_image_path(photo.filename))
    db.session.delete(photo)
    db.session.flush()
    _apply_ai(crop, [crop_image_path(p.filename) for p in crop.photos])
    db.session.commit()
    flash(t("Photo removed and the lot re-graded."), "info")
    return redirect(url_for("farmer.crop_detail", crop_id=crop.id))


@farmer_bp.route("/crops/<int:crop_id>/status/<new_status>", methods=["POST"])
@role_required("farmer")
def change_status(crop_id, new_status):
    crop = _own_crop(crop_id)
    if new_status not in ("available", "reserved", "sold", "withdrawn"):
        abort(400)
    crop.status = new_status
    db.session.commit()
    flash(t("Listing marked as {status}.", status=t(new_status)), "info")
    return redirect(url_for("farmer.crop_detail", crop_id=crop.id))


@farmer_bp.route("/crops/<int:crop_id>/delete", methods=["POST"])
@role_required("farmer")
def delete_crop(crop_id):
    crop = _own_crop(crop_id)
    for p in crop.photos:
        delete_file(crop_image_path(p.filename))
    for c in crop.certificates:
        delete_file(certificate_path(c.filename))
    db.session.delete(crop)
    db.session.commit()
    flash(t("Listing deleted."), "info")
    return redirect(url_for("farmer.crops"))


# ======================================================================
# CERTIFICATES  (OCMR verification)
# ======================================================================
@farmer_bp.route("/crops/<int:crop_id>/certificate", methods=["GET", "POST"])
@role_required("farmer")
def upload_certificate(crop_id):
    crop = _own_crop(crop_id)

    if request.method == "POST":
        f = request.files.get("certificate")
        if not f or not f.filename:
            flash(t("Choose the certificate file to upload."), "danger")
            return redirect(url_for("farmer.upload_certificate", crop_id=crop.id))

        stored, err = save_upload(
            f, current_app.config["CERTIFICATE_DIR"],
            current_app.config["ALLOWED_DOC_EXTENSIONS"], prefix=f"cert{crop.id}_")
        if err:
            flash(t(err), "danger")
            return redirect(url_for("farmer.upload_certificate", crop_id=crop.id))

        cert = Certificate(crop_id=crop.id, filename=stored,
                           cert_type=clean(request.form.get("cert_type"), 60))
        db.session.add(cert)
        db.session.flush()

        # ---- run the OCMR pipeline ----------------------------------
        result = cert_ai.verify_certificate(
            certificate_path(stored), crop_name=crop.crop_name,
            holder_name=current_user.full_name,
            cert_type=cert.cert_type,
        )

        fields = result.get("fields", {})
        cert.cert_number = fields.get("cert_number")
        cert.issuer = fields.get("issuer")
        cert.holder_name = fields.get("holder_name")
        cert.issue_date = _iso(fields.get("issue_date"))
        cert.expiry_date = _iso(fields.get("expiry_date"))
        cert.ocr_text = result.get("ocr_text")
        cert.status = result.get("status", "pending")
        cert.confidence = result.get("confidence", 0)
        cert.checks_json = json.dumps(result.get("checks", []))
        cert.remarks = result.get("remarks")
        cert.cert_type = cert.cert_type or result.get("cert_type")
        if cert.status == "verified":
            cert.verified_at = datetime.utcnow()

        # The crop's certificate status is the best status among its certificates.
        crop.certificate_status = _best_cert_status(crop, cert)
        if crop.certificate_status == "verified":
            _reprice(crop)                    # verified lots get the +8% premium

        db.session.commit()

        flash(t({"verified": "Certificate verified successfully.",
                 "pending": "Certificate uploaded — some checks need manual review.",
                 "rejected": "Certificate could not be verified."}[cert.status]),
              {"verified": "success", "pending": "warning", "rejected": "danger"}[cert.status])
        return redirect(url_for("farmer.certificate_report", cert_id=cert.id))

    return render_template("farmer/certificate_upload.html", crop=crop,
                           authorities=cert_ai.AUTHORITY_REGISTRY)


@farmer_bp.route("/certificates/<int:cert_id>")
@login_required
def certificate_report(cert_id):
    cert = Certificate.query.get_or_404(cert_id)
    crop = cert.crop
    # A farmer sees his own; a buyer may see it only if he has a deal on that lot.
    if current_user.is_farmer and crop.farmer_id != current_user.id:
        abort(403)
    if current_user.is_buyer:
        allowed = DealRequest.query.filter_by(
            crop_id=crop.id, buyer_id=current_user.id).first()
        if not allowed:
            abort(403)

    checks = json.loads(cert.checks_json) if cert.checks_json else []
    return render_template("farmer/certificate_report.html", cert=cert,
                           crop=crop, checks=checks)


@farmer_bp.route("/certificates/<int:cert_id>/delete", methods=["POST"])
@role_required("farmer")
def delete_certificate(cert_id):
    cert = Certificate.query.get_or_404(cert_id)
    crop = cert.crop
    if crop.farmer_id != current_user.id:
        abort(403)
    delete_file(certificate_path(cert.filename))
    db.session.delete(cert)
    db.session.flush()
    crop.certificate_status = _best_cert_status(crop, None)
    db.session.commit()
    flash(t("Certificate removed."), "info")
    return redirect(url_for("farmer.crop_detail", crop_id=crop.id))


# ======================================================================
# BUYER REQUIREMENTS (farmer side)
# ======================================================================
@farmer_bp.route("/requirements")
@role_required("farmer")
def requirements():
    crop_filter = request.args.get("crop", "")
    only_matching = request.args.get("matching") == "1"

    q = Requirement.query.filter_by(status="open")
    if crop_filter:
        q = q.filter(Requirement.crop_name == crop_filter)
    items = q.order_by(Requirement.created_at.desc()).all()

    my_crops = Crop.query.filter_by(farmer_id=current_user.id, status="available").all()

    rows = []
    for r in items:
        matched = [c for c in my_crops if r.matches(c)]
        if only_matching and not matched:
            continue
        rows.append({"req": r, "matched": matched,
                     "same_district": r.district == current_user.district})

    # Requirements that match one of my lots float to the top.
    rows.sort(key=lambda x: (not x["matched"], not x["same_district"]))
    return render_template("farmer/requirements.html", rows=rows,
                           crop_filter=crop_filter, only_matching=only_matching,
                           my_crops=my_crops)


@farmer_bp.route("/requirements/<int:req_id>/offer", methods=["POST"])
@role_required("farmer")
def offer(req_id):
    req = Requirement.query.get_or_404(req_id)
    if req.status != "open":
        flash(t("That requirement is already closed."), "warning")
        return redirect(url_for("farmer.requirements"))

    crop = _own_crop(int(request.form.get("crop_id", 0)))
    quantity = to_float(request.form.get("quantity"), min(req.quantity, crop.quantity))
    price = to_float(request.form.get("offered_price"), crop.expected_price)

    if quantity <= 0 or quantity > crop.quantity:
        flash(t("Enter a quantity between 1 and {max:g} quintal.", max=crop.quantity), "danger")
        return redirect(url_for("farmer.requirements"))

    existing = DealRequest.query.filter_by(
        requirement_id=req.id, crop_id=crop.id, status="pending").first()
    if existing:
        flash(t("You have already offered this lot against that requirement."), "info")
        return redirect(url_for("deals.detail", deal_id=existing.id))

    deal = DealRequest(
        crop_id=crop.id, requirement_id=req.id,
        farmer_id=current_user.id, buyer_id=req.buyer_id,
        initiated_by="farmer", quantity=quantity, offered_price=price,
        message=clean(request.form.get("message"), 500),
    )
    db.session.add(deal)
    db.session.flush()

    Notification.push(
        req.buyer_id,
        title=f"New offer for your {req.crop_name} requirement",
        body=(f"{current_user.full_name} offered {quantity:g} quintal at "
              f"Rs {price:,.0f}/quintal (Grade {crop.ai_grade or '-'})."),
        link=url_for("deals.detail", deal_id=deal.id), icon="offer",
    )
    db.session.commit()
    flash(t("Your offer has been sent to the buyer."), "success")
    return redirect(url_for("deals.detail", deal_id=deal.id))


# ======================================================================
# JSON helper used by the listing form
# ======================================================================
@farmer_bp.route("/api/price-suggestion", methods=["POST"])
@role_required("farmer")
def api_price_suggestion():
    data = request.get_json(silent=True) or {}
    crop_name = clean(data.get("crop_name"), 60)
    if not crop_name:
        return jsonify({"ok": False, "error": "No crop selected."}), 400

    band = suggest_price(
        crop_name,
        grade=data.get("grade") or "B",
        state=clean(data.get("state"), 60) or current_user.state,
        district=clean(data.get("district"), 60) or current_user.district,
        organic=bool(data.get("organic")),
    )
    di = demand_ai.demand_index(crop_name, current_user.state, current_user.district)
    band["demand"] = {"index": di["index"], "label": di["label"], "colour": di["colour"]}
    band["certificate_required"] = needs_certificate(crop_name)
    band["ok"] = True
    return jsonify(band)


# ======================================================================
# internals
# ======================================================================
def _own_crop(crop_id):
    crop = Crop.query.get_or_404(crop_id)
    if crop.farmer_id != current_user.id:
        abort(403)
    return crop


def _apply_ai(crop, image_paths):
    """Run the grader on every photo of the lot, then recompute the price band."""
    result = grade_many(image_paths, crop.crop_name)

    if result.get("ok"):
        crop.ai_grade = result["grade"]
        crop.ai_quality_score = result["score"]
        crop.ai_summary = result["summary"]

        by_path = {r.get("path"): r for r in result.get("per_image", [])}
        for photo in crop.photos:
            r = by_path.get(crop_image_path(photo.filename))
            if not r or not r.get("ok"):
                continue
            photo.quality_score = r["score"]
            photo.grade = r["grade"]
            photo.colour_score = r["sub_scores"]["colour"]
            photo.uniformity_score = r["sub_scores"]["uniformity"]
            photo.defect_score = r["sub_scores"]["defect"]
            photo.size_score = r["sub_scores"]["size"]
            photo.sharpness = r["metrics"].get("sharpness")
            photo.notes = " ".join(r.get("notes", []))
    else:
        crop.ai_summary = result.get("summary", "Automatic grading failed for these photos.")

    _reprice(crop)


def _reprice(crop):
    band = suggest_price(
        crop.crop_name, crop.ai_grade, crop.ai_quality_score,
        crop.state, crop.district, crop.organic,
        crop.certificate_status == "verified",
    )
    crop.ai_price_min = band["min"]
    crop.ai_price_max = band["max"]
    crop.ai_price_recommended = band["recommended"]


def _best_cert_status(crop, new_cert):
    """verified > pending > rejected, across every certificate on the lot."""
    statuses = [c.status for c in crop.certificates if c is not new_cert]
    if new_cert:
        statuses.append(new_cert.status)
    if not statuses:
        return "pending" if crop.certificate_required else "not_required"
    for s in ("verified", "pending", "rejected"):
        if s in statuses:
            return s
    return "pending"


def _iso(value):
    from datetime import date as _date
    if not value:
        return None
    try:
        return _date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
