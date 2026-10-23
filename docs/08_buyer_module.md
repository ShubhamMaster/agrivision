# 08 · Buyer module

**Section goal:** everything a buyer can do — browse and filter graded lots,
compare them, post requirements, and send buying requests.

**Files:** `app/routes/buyer.py` (~400 lines) and seven templates under
`app/templates/buyer/`.

---

## 1. Routes

| Method | URL | Purpose |
|---|---|---|
| GET | `/buyer/dashboard` | overview, offers to answer, recommended lots |
| GET | `/buyer/browse` | the marketplace with filters and sorting |
| GET | `/buyer/crop/<id>` | full lot page with quality and price analysis |
| POST | `/buyer/crop/<id>/request` | send a buying request |
| GET | `/buyer/compare` | side-by-side comparison of up to 4 lots |
| GET | `/buyer/requirements` | my posted requirements |
| GET/POST | `/buyer/requirements/new` | post a requirement |
| GET | `/buyer/requirements/<id>` | requirement + matching lots + offers |
| GET/POST | `/buyer/requirements/<id>/edit` | edit it |
| POST | `/buyer/requirements/<id>/close` | close or reopen |
| POST | `/buyer/requirements/<id>/delete` | delete |

All guarded by `@role_required("buyer")`; requirement routes additionally pass
through `_own_req()`.

---

## 2. The marketplace — filtering strategy

Nine filters: crop, minimum grade, district, maximum price, minimum quantity,
organic, certificate verified, and five sort orders.

The important design decision is **where each filter runs**:

```python
# in SQL — the database does the work
q = Crop.query.filter(Crop.status == "available")
if f["crop"]:      q = q.filter(Crop.crop_name == f["crop"])
if f["max_price"]: q = q.filter(Crop.expected_price <= f["max_price"])
if f["certified"]: q = q.filter(Crop.certificate_status == "verified")
...
items = q.limit(200).all()

# in Python — needs the ranking helper
if f["grade"]:
    wanted = grade_rank(f["grade"])
    items = [c for c in items if grade_rank(c.ai_grade) >= wanted]
```

Everything that can be expressed as a column comparison runs in SQL, so the
database returns only the rows that matter. The grade filter is the exception:
"Grade B or better" is an *ordering* over text values where `'A' < 'B'`
alphabetically but A outranks B commercially. `grade_rank()` maps A→3, B→2, C→1
and the comparison happens in Python over the already-narrowed result set.

`nullslast()` on the quality sort keeps ungraded lots at the bottom rather than
the top, which is what SQLite would otherwise do with NULLs.

The `limit(200)` is a safety valve. Proper pagination is the right fix for a
large catalogue and is noted as future work.

---

## 3. The lot page from the buyer's side

Same underlying data as the farmer's lot page, presented for a different
decision. The buyer sees:

- **The AI quality assessment** — described in the template as *independent*,
  which is the point. The grade did not come from the seller.
- **A fairness read-out**, computed from the opposite direction to the farmer's:

```python
if crop.expected_price > band["max"]:
    "Asking price is above the AI fair band. There is room to negotiate."
elif crop.expected_price < band["min"]:
    "Asking price is below the AI fair band — this lot is competitively priced."
```

Both parties see the same band. That symmetry is what makes it a neutral
marketplace rather than a tool for one side.

- **Certificates**, with the full verification report locked until the buyer has
  a deal on the lot.
- **The seller**, with phone and email hidden until a deal is accepted. Exposing
  contact details earlier would let anyone scrape the farmer list and take the
  trade off-platform.
- **Market context** — demand gauge, latest modal price, period range, trend.
- **The request form**, pre-filled with the full quantity and the asking price.

### Guards on sending a request

```python
if crop.status != "available":                       refuse
if crop.certificate_required and
   crop.certificate_status != "verified":            refuse
if quantity <= 0 or quantity > crop.quantity:        refuse
if a pending request from this buyer exists:         send them to it
```

The duplicate check prevents the farmer's inbox from filling with the same
request from an impatient buyer clicking twice.

---

## 4. Comparison — the value score

Up to four lots compare side by side on fourteen rows. The header row carries a
computed **value score**:

```python
def _value_score(crop, band):
    quality  = crop.ai_quality_score or 50
    fairness = band["recommended"] / crop.expected_price      # > 1 means cheap
    score = quality * min(1.35, max(0.65, fairness))
    if crop.certificate_status == "verified": score *= 1.06
    if crop.organic:                          score *= 1.04
    return round(score, 1)
```

The idea is **quality per rupee**. A Grade A lot priced 20% above its fair band
may be worse value than a Grade B lot priced below it, and a raw grade comparison
would hide that. The fairness ratio is clamped to [0.65, 1.35] so one absurdly
cheap listing cannot dominate the ranking.

Rows are sorted by this score and the leader is badged "Best value".

The comparison tray on the marketplace is client-side: checkboxes collect ids,
a fixed bar appears at the bottom, and the link is assembled as
`?id=1&id=3&id=5`. Beyond four, the remaining checkboxes disable themselves —
five columns do not fit on a laptop screen and the comparison stops being useful.

---

## 5. Posting a requirement

The inverse of a listing: instead of the farmer advertising supply, the buyer
advertises demand.

Fields: crop, variety, quantity, minimum grade, price range, state, district,
delivery location, needed-by date, organic-only, certificate-mandatory, notes.

On submit, every farmer with that crop listed is notified:

```python
matching_farmers = {c.farmer_id for c in Crop.query.filter(
    Crop.crop_name == crop_name, Crop.status == "available").all()}
for fid in list(matching_farmers)[:50]:
    Notification.push(fid, f"New requirement posted for {crop_name}", …)
```

A set comprehension deduplicates farmers with several lots of the same crop, and
the cap at 50 stops one requirement from generating thousands of rows. (In
production this belongs in a background queue.)

---

## 6. The requirement page

Three sections:

- **Offers received** — farmers who have responded.
- **Lots that meet every condition** — `[c for c in candidates if req.matches(c)]`.
- **Close, but not matching every condition** — the near misses.

Showing near misses is a deliberate nicety: a buyer who sees six near misses and
no exact matches learns that his conditions are too tight, which is more useful
than an empty page.

The sidebar warns when the buyer's own ceiling is unrealistic:

```jinja
{% if req.price_max and trend.latest and req.price_max < trend.latest %}
  Your ceiling of ₹X is below the current market price of ₹Y — expect few offers.
{% endif %}
```

This is market intelligence used to correct the *buyer*, not just the farmer —
again, the platform serving both sides.

---

## 7. The dashboard

Six tiles, then:

- **Farmer offers waiting for your answer** — the actionable item.
- **Lots that match your open requirements** — computed by iterating the buyer's
  open requirements and running `matches()` over candidate lots, deduplicated by
  crop id and capped at six.
- **My requirements** with status badges.
- **Buying smart on AgriVision** — guidance on using the grade filter, the fair
  band, the certificate filter and the demand index.

---

## 8. Symmetry with the farmer module

| Farmer | Buyer |
|---|---|
| lists a crop | posts a requirement |
| sees matching requirements | sees matching lots |
| sends an offer | sends a buying request |
| accepts a buying request | accepts an offer |

Both directions land in the same `DealRequest` table, distinguished only by
`initiated_by`. One state machine serves both — see `09_deal_lifecycle.md`.

---

## 9. Viva questions

**Q. How does the marketplace filtering work?**
Column-level filters run in SQL so only relevant rows are fetched. The grade
filter runs in Python because "B or better" is a ranking over text where
alphabetical order is wrong; `grade_rank()` maps A→3, B→2, C→1.

**Q. What is the value score?**
Quality per rupee: the AI quality score scaled by the ratio of the recommended
price to the asking price, with bonuses for certification and organic. It exposes
cases where a Grade A lot is poorer value than a well-priced Grade B lot.

**Q. Why is the ratio clamped?**
So one absurdly cheap or expensive listing cannot dominate the ranking.

**Q. When are the farmer's contact details revealed?**
Only after a deal is accepted. Earlier exposure would let buyers scrape contacts
and take the trade off-platform, which removes the platform's reason to exist.

**Q. Why show "near misses" on a requirement?**
An empty result tells the buyer nothing. Six near misses tell him his grade,
price or certificate condition is too tight.

**Q. How are farmers notified of a new requirement?**
Every farmer with that crop currently listed gets a notification; a set
comprehension deduplicates, and the batch is capped at 50. A background queue is
the right answer at scale.

**Q. How do you prevent duplicate requests?**
Before creating one, the view checks for an existing pending request from the
same buyer on the same lot and redirects to it instead.

**Q. Why can only four lots be compared?**
Five columns do not fit legibly on a laptop screen. The checkboxes disable
themselves at four.
