# 09 · Deal lifecycle — requests, negotiation, completion

**Section goal:** the shared workflow where the two sides actually meet. One
state machine serves both a buyer's request and a farmer's offer.

**Files:** `app/routes/deals.py` (~250 lines), `app/templates/deals/`.

---

## 1. One table, two directions

```python
class DealRequest:
    crop_id, requirement_id, farmer_id, buyer_id
    initiated_by   # 'buyer' or 'farmer'
    quantity, offered_price, message
    status         # pending | accepted | rejected | cancelled | completed
```

A buying request and a farmer's offer are the same object seen from opposite
ends: one party proposes a quantity and a price, the other answers. Two tables
would duplicate the state machine, the chat, the notifications and the guards.

`initiated_by` is the only thing that distinguishes them — and it is also what
the accept/reject guard reads.

---

## 2. The state machine

```
                    ┌────────── accept ──────────▶ accepted ──── complete ──▶ completed
                    │                                 │
   pending ─────────┼────────── reject ──────────▶ rejected
                    │                                 │
                    └────────── cancel ──────────▶ cancelled ◀─── cancel ────┘
```

| Transition | Who may do it | Side effects |
|---|---|---|
| accept | **recipient only** | lot → `reserved`; contact details revealed; notification |
| reject | **recipient only** | notification with the response note |
| cancel | **initiator only** | if it was accepted, lot returns to `available` |
| complete | either party | quantity reduced; lot → `sold` or back to `available`; requirement closed if filled |

---

## 3. The two guards

```python
def _access(deal_id):
    deal = DealRequest.query.get_or_404(deal_id)
    if current_user.id not in (deal.farmer_id, deal.buyer_id):
        abort(403)
    return deal

def _require_recipient(deal):
    if deal.initiated_by == current_user.role:
        abort(403)
```

`_access` is the ownership check — a deal is private to its two parties, and a
third farmer poking at `/deals/6` gets a 403. There is a test for exactly this.

`_require_recipient` encodes the rule that **you cannot accept your own offer**.
If the buyer started the thread (`initiated_by == 'buyer'`) and the current user
is a buyer, the roles match and the action is forbidden. The test suite asserts
this too.

The comparison works because `initiated_by` stores the same vocabulary as
`User.role` — `'buyer'` and `'farmer'`. That is a deliberate choice, not a
coincidence.

---

## 4. Accept — the state change that matters

```python
crop = deal.crop
if crop and deal.quantity > crop.quantity:
    flash(f"Only {crop.quantity:g} quintal is left in this lot…")
    return redirect(...)

deal.status = "accepted"
deal.responded_at = datetime.utcnow()
deal.response_note = clean(request.form.get("note"), 400)
if crop:
    crop.status = "reserved"
Notification.push(deal.counterparty(current_user).id, "Your request was accepted", …)
db.session.commit()
```

**The quantity re-check is a race-condition guard.** Between the buyer sending
the request and the farmer accepting it, the farmer may have sold part of the lot
to someone else. Re-checking at accept time — not just at request time — prevents
promising 60 quintal when only 40 remain.

**Reserving the lot** removes it from `is_tradeable`, so two buyers cannot both
be promised the same stock.

**Contact details** become visible at exactly this moment, in the template:

```jinja
{% if deal.status in ['accepted', 'completed'] %}
  <i class="bi bi-telephone"></i> {{ other.phone }}
  <i class="bi bi-envelope"></i> {{ other.email }}
{% else %}
  <i class="bi bi-lock"></i> Phone and email are revealed once the deal is accepted.
{% endif %}
```

---

## 5. Complete — partial fulfilment

```python
remaining = crop.quantity - deal.quantity
if remaining <= 0.01:
    crop.quantity = 0
    crop.status = "sold"
else:
    crop.quantity = round(remaining, 2)
    crop.status = "available"          # the rest goes back on the market
```

A buyer taking 60 of 85 quintal leaves 25 quintal still for sale, so the lot
returns to `available` with the reduced quantity. Only a fully consumed lot is
marked `sold`.

The `0.01` tolerance is floating-point hygiene: `85.0 - 85.0` can leave
`7.1e-15`, and without the tolerance the lot would stay "available" with an
effectively zero quantity.

Completion also closes the buyer's requirement if it has been filled:

```python
done = sum(d.quantity for d in req.deal_requests if d.status == "completed")
if done >= req.quantity - 0.01:
    req.status = "closed"
```

Summing across **all** completed deals handles a requirement filled by three
different farmers.

---

## 6. Cancel — releasing a reservation

```python
was_accepted = deal.status == "accepted"
deal.status = "cancelled"
if was_accepted and deal.crop.status == "reserved":
    deal.crop.status = "available"
```

Without the release, a cancelled deal would leave the lot reserved forever and
invisible to every other buyer.

---

## 7. The inbox

```python
if box == "received":
    q = q.filter(DealRequest.initiated_by != current_user.role)
elif box == "sent":
    q = q.filter(DealRequest.initiated_by == current_user.role)
```

"Received" means threads the other side started — the ones needing an answer.
The same expression serves both roles because `initiated_by` and `role` share a
vocabulary. The pending count on the Received tab is the badge the user acts on.

---

## 8. The chat

A simple `Message` table scoped to one deal, rendered as bubbles — the current
user's on the right in green, the other party's on the left. Each message raises
a notification for the counterparty.

```python
{% if deal.status in ['pending', 'accepted'] %}  show the compose box
{% else %}  "This thread is closed for new messages."
```

Closed deals are read-only, so the thread stays as an accurate record of what was
agreed.

The negotiation itself happens here in plain language. A formal counter-offer
object was considered and rejected as over-engineering: in practice the buyer
says "can you do ₹5,900?", and if the farmer disagrees he declines and the buyer
sends a fresh request. Fewer states, less to explain, and closer to how the trade
actually happens.

---

## 9. Notifications

Every state change raises one:

```python
Notification.push(deal.counterparty(current_user).id,
                  title="Your request was accepted",
                  body=f"{current_user.full_name} accepted {deal.quantity:g} quintal…",
                  link=url_for("deals.detail", deal_id=deal.id), icon="accept")
```

`counterparty()` is a method on the model:

```python
def counterparty(self, user):
    return self.buyer if user.id == self.farmer_id else self.farmer
```

so no view has to work out who the "other person" is.

Opening a deal marks its notifications read:

```python
Notification.query.filter_by(user_id=current_user.id,
                             link=url_for("deals.detail", deal_id=deal.id))\
                  .update({"is_read": True})
```

---

## 10. Full trade walkthrough

```
1. Buyer opens /buyer/crop/3, sends a request for 60 q at ₹5,833
      → DealRequest(initiated_by='buyer', status='pending')
      → Notification to the farmer

2. Farmer opens /deals/6
      → is_recipient = True, so Accept and Decline are shown

3. Farmer accepts with a note
      → status='accepted', crop.status='reserved'
      → contact details now visible to both
      → Notification to the buyer

4. Both chat to arrange lifting and payment

5. Either marks complete
      → status='completed'
      → crop.quantity 85 → 25, status back to 'available'
      → the linked requirement closes if fully met
      → Notification to the other party
```

This is the end-to-end demo to run in a viva. `tests/test_routes.py` executes
exactly this sequence and asserts each state change.

---

## 11. Viva questions

**Q. Why one table for both buying requests and farmer offers?**
They are the same object from opposite ends — a proposed quantity and price
awaiting an answer. `initiated_by` records which end started it. Two tables would
duplicate the state machine, chat, notifications and guards.

**Q. Who can accept a request?**
Only the recipient — the side that did **not** initiate it. `_require_recipient`
compares `deal.initiated_by` with `current_user.role` and aborts on a match. A
test asserts that a buyer cannot accept their own request.

**Q. What happens to the lot when a deal is accepted?**
It becomes `reserved`, which removes it from the tradeable pool so two buyers
cannot be promised the same stock. Contact details are revealed at the same
moment.

**Q. Why re-check the quantity at accept time?**
The lot may have been partly sold between the request and the acceptance. Checking
only at request time would allow promising stock that no longer exists.

**Q. How is partial fulfilment handled?**
On completion the deal quantity is subtracted. If anything remains the lot goes
back to `available` with the reduced quantity; only a fully consumed lot is
marked `sold`.

**Q. Why the 0.01 tolerance?**
Floating-point subtraction can leave a residue like 7e-15. Without the tolerance
a fully sold lot would remain "available" with a near-zero quantity.

**Q. What happens if an accepted deal is cancelled?**
The lot's reservation is released and it returns to `available`; otherwise it
would be invisible to every other buyer forever.

**Q. Can a third party read a deal thread?**
No. `_access()` checks the current user is one of the two parties and aborts with
403 otherwise. There is a test for it.

**Q. Why no formal counter-offer object?**
It adds states for little gain. In practice negotiation happens in the chat, and
if the parties disagree the request is declined and a fresh one sent.
