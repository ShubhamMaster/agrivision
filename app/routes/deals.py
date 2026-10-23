"""
AgriVision — deal blueprint: the request/offer lifecycle shared by both roles.

    /deals/                      inbox — everything I sent and received
    /deals/<id>                  one negotiation thread
    /deals/<id>/accept           recipient accepts
    /deals/<id>/reject           recipient rejects
    /deals/<id>/cancel           initiator withdraws
    /deals/<id>/complete         either side marks the trade done
    /deals/<id>/message          post a chat message

State machine
-------------
    pending ──accept──▶ accepted ──complete──▶ completed
       │                    │
       ├──reject──▶ rejected│
       └──cancel──▶ cancelled

Rules enforced here:
  * only the *recipient* (the side that did not initiate) can accept/reject;
  * only the *initiator* can cancel;
  * accepting reserves the lot and reduces the remaining quantity;
  * completing a deal closes the lot if nothing is left;
  * every state change raises a notification for the other side.
"""

from datetime import datetime

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from ..extensions import db
from ..i18n import t
from ..models import DealRequest, Message, Notification
from ..utils import clean

deals_bp = Blueprint("deals", __name__, template_folder="../templates/deals")


@deals_bp.route("/")
@login_required
def inbox():
    box = request.args.get("box", "received")
    status = request.args.get("status", "all")

    q = DealRequest.query.filter(
        (DealRequest.farmer_id == current_user.id) |
        (DealRequest.buyer_id == current_user.id)
    )

    # "received" = threads the other side started; "sent" = threads I started.
    if box == "received":
        q = q.filter(DealRequest.initiated_by != current_user.role)
    elif box == "sent":
        q = q.filter(DealRequest.initiated_by == current_user.role)

    if status != "all":
        q = q.filter(DealRequest.status == status)

    items = q.order_by(DealRequest.created_at.desc()).all()

    counts = {
        "received": DealRequest.query.filter(
            ((DealRequest.farmer_id == current_user.id) |
             (DealRequest.buyer_id == current_user.id)),
            DealRequest.initiated_by != current_user.role,
            DealRequest.status == "pending").count(),
        "sent": DealRequest.query.filter(
            ((DealRequest.farmer_id == current_user.id) |
             (DealRequest.buyer_id == current_user.id)),
            DealRequest.initiated_by == current_user.role).count(),
    }

    return render_template("deals/inbox.html", items=items, box=box,
                           status=status, counts=counts)


@deals_bp.route("/<int:deal_id>")
@login_required
def detail(deal_id):
    deal = _access(deal_id)

    # Mark related notifications as read when the thread is opened.
    Notification.query.filter_by(
        user_id=current_user.id,
        link=url_for("deals.detail", deal_id=deal.id)).update({"is_read": True})
    db.session.commit()

    is_recipient = deal.initiated_by != current_user.role
    return render_template("deals/detail.html", deal=deal,
                           is_recipient=is_recipient,
                           other=deal.counterparty(current_user))


# ----------------------------------------------------------------------
# STATE TRANSITIONS
# ----------------------------------------------------------------------
@deals_bp.route("/<int:deal_id>/accept", methods=["POST"])
@login_required
def accept(deal_id):
    deal = _access(deal_id)
    _require_recipient(deal)
    if deal.status != "pending":
        flash(t("This request has already been answered."), "warning")
        return redirect(url_for("deals.detail", deal_id=deal.id))

    crop = deal.crop
    if crop and deal.quantity > crop.quantity:
        flash(t("Only {left:g} quintal is left in this lot. Reject this request "
                "or ask the buyer to revise the quantity.", left=crop.quantity), "danger")
        return redirect(url_for("deals.detail", deal_id=deal.id))

    deal.status = "accepted"
    deal.responded_at = datetime.utcnow()
    deal.response_note = clean(request.form.get("note"), 400)

    if crop:
        crop.status = "reserved"

    Notification.push(
        deal.counterparty(current_user).id,
        title="Your request was accepted",
        body=(f"{current_user.full_name} accepted {deal.quantity:g} quintal of "
              f"{crop.crop_name if crop else 'the lot'} at Rs {deal.offered_price:,.0f}/quintal."),
        link=url_for("deals.detail", deal_id=deal.id), icon="accept",
    )
    db.session.commit()
    flash(t("Request accepted. The lot is now reserved — use the chat to arrange delivery."),
          "success")
    return redirect(url_for("deals.detail", deal_id=deal.id))


@deals_bp.route("/<int:deal_id>/reject", methods=["POST"])
@login_required
def reject(deal_id):
    deal = _access(deal_id)
    _require_recipient(deal)
    if deal.status != "pending":
        flash(t("This request has already been answered."), "warning")
        return redirect(url_for("deals.detail", deal_id=deal.id))

    deal.status = "rejected"
    deal.responded_at = datetime.utcnow()
    deal.response_note = clean(request.form.get("note"), 400)

    Notification.push(
        deal.counterparty(current_user).id,
        title="Your request was declined",
        body=deal.response_note or f"{current_user.full_name} declined the request.",
        link=url_for("deals.detail", deal_id=deal.id), icon="reject",
    )
    db.session.commit()
    flash(t("Request declined."), "info")
    return redirect(url_for("deals.detail", deal_id=deal.id))


@deals_bp.route("/<int:deal_id>/cancel", methods=["POST"])
@login_required
def cancel(deal_id):
    deal = _access(deal_id)
    if deal.initiated_by != current_user.role:
        abort(403)
    if deal.status not in ("pending", "accepted"):
        flash(t("This request can no longer be withdrawn."), "warning")
        return redirect(url_for("deals.detail", deal_id=deal.id))

    was_accepted = deal.status == "accepted"
    deal.status = "cancelled"
    deal.responded_at = datetime.utcnow()

    if was_accepted and deal.crop and deal.crop.status == "reserved":
        deal.crop.status = "available"

    Notification.push(
        deal.counterparty(current_user).id,
        title="A request was withdrawn",
        body=f"{current_user.full_name} withdrew the request.",
        link=url_for("deals.detail", deal_id=deal.id), icon="cancel",
    )
    db.session.commit()
    flash(t("Request withdrawn."), "info")
    return redirect(url_for("deals.detail", deal_id=deal.id))


@deals_bp.route("/<int:deal_id>/complete", methods=["POST"])
@login_required
def complete(deal_id):
    deal = _access(deal_id)
    if deal.status != "accepted":
        flash(t("Only an accepted deal can be marked complete."), "warning")
        return redirect(url_for("deals.detail", deal_id=deal.id))

    deal.status = "completed"
    crop = deal.crop
    if crop:
        remaining = (crop.quantity or 0) - (deal.quantity or 0)
        if remaining <= 0.01:
            crop.quantity = 0
            crop.status = "sold"
        else:
            crop.quantity = round(remaining, 2)
            crop.status = "available"

    # Close the buyer's requirement when the full quantity has been met.
    req = deal.requirement
    if req:
        done = sum(d.quantity for d in req.deal_requests if d.status == "completed")
        if done >= (req.quantity or 0) - 0.01:
            req.status = "closed"

    Notification.push(
        deal.counterparty(current_user).id,
        title="Deal marked complete",
        body=(f"{current_user.full_name} marked the trade of {deal.quantity:g} quintal "
              f"as completed."),
        link=url_for("deals.detail", deal_id=deal.id), icon="complete",
    )
    db.session.commit()
    flash(t("Deal marked as completed."), "success")
    return redirect(url_for("deals.detail", deal_id=deal.id))


# ----------------------------------------------------------------------
# CHAT
# ----------------------------------------------------------------------
@deals_bp.route("/<int:deal_id>/message", methods=["POST"])
@login_required
def message(deal_id):
    deal = _access(deal_id)
    body = clean(request.form.get("body"), 1000)
    if not body:
        flash(t("Write a message before sending."), "warning")
        return redirect(url_for("deals.detail", deal_id=deal.id))

    db.session.add(Message(deal_id=deal.id, sender_id=current_user.id, body=body))
    Notification.push(
        deal.counterparty(current_user).id,
        title=f"New message from {current_user.full_name}",
        body=body[:120],
        link=url_for("deals.detail", deal_id=deal.id), icon="message",
    )
    db.session.commit()
    return redirect(url_for("deals.detail", deal_id=deal.id) + "#chat")


# ----------------------------------------------------------------------
# guards
# ----------------------------------------------------------------------
def _access(deal_id):
    deal = DealRequest.query.get_or_404(deal_id)
    if current_user.id not in (deal.farmer_id, deal.buyer_id):
        abort(403)
    return deal


def _require_recipient(deal):
    """Only the side that did not start the thread may accept or reject it."""
    if deal.initiated_by == current_user.role:
        abort(403)
