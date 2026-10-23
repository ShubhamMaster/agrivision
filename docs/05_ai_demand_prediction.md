# 05 · AI module 3 — demand prediction and price trends

**Section goal:** tell a farmer whether to sell now or wait, and tell a buyer
whether to buy now or hold.

**File:** `app/ai/demand.py` (~330 lines)

---

## 1. Four public functions

| Function | Question answered | Used by |
|---|---|---|
| `price_trend()` | How has this crop moved recently? | charts, lot pages |
| `demand_index()` | Is demand strong right now? | pricing engine, dashboards |
| `forecast()` | Where is the price heading? | insights report |
| `top_demand_crops()` | Which crops should I focus on? | both dashboards |

---

## 2. `price_trend()` — weekly aggregation

Daily mandi prices are too noisy to plot: 180 points of sawtooth. The function
buckets them into weeks.

```python
wk = r.record_date - timedelta(days=r.record_date.weekday())   # Monday of that week
buckets.setdefault(wk, []).append(r)
```

`weekday()` returns 0 for Monday, so subtracting it snaps any date to that week's
Monday — a one-line weekly bucketing with no library needed.

Each bucket yields the mean modal price, the week's low and high, and total
arrivals. The function also returns the period average, the period low and high,
the percentage change from first to last week, and a direction label
(`rising` / `falling` / `flat`, with a ±3% dead zone so noise is not reported as
a trend).

Like the pricing engine it falls back district → state → national and reports the
scope it used.

---

## 3. `demand_index()` — the core of the module

Four independent signals, each mapped to −1…+1, then weighted:

```python
WEIGHTS = {
    "price_momentum":  0.38,
    "supply_pressure": 0.24,
    "season":          0.18,
    "platform_pull":   0.20,
}
index = 50 + 50 * Σ(weight_i × signal_i)        # 0-100, 50 is neutral
```

### Signal 1 — price momentum (38%)

```python
recent = mean(last 30 days)
base   = mean(the 90 days before that)
pm = (recent - base) / base
signal = clip(pm / 0.18)        # ±18% saturates the signal
```

Rising prices mean demand is outstripping supply. This carries the most weight
because price is the market's own summary of everything else.

Comparing a short recent window against a longer baseline is standard momentum
analysis: it detects a change in regime rather than day-to-day noise.

### Signal 2 — supply pressure (24%)

```python
sp = (base_arrivals - recent_arrivals) / base_arrivals      # note: inverted
```

Arrivals are the quantity reaching the mandi each day. **Falling arrivals with
firm prices mean supply is tightening**, which is good for the seller — hence the
inversion.

This signal is what distinguishes a genuine demand surge from a supply collapse.
Price rising *and* arrivals rising means real demand growth; price rising while
arrivals fall means scarcity. Both support the farmer's price today, but they
have very different implications next month.

### Signal 3 — season (18%)

Reuses `season_factor()` from the pricing module, normalised:

```python
signal = clip((s_factor - 1) / 0.12)
```

Sharing the function keeps the two modules consistent — the season cannot be a
glut in one screen and a peak in another.

### Signal 4 — marketplace pull (20%)

```python
wanted  = open Requirement rows for this crop in this state
offered = available Crop rows for this crop in this state
pull = (wanted - offered) / (wanted + offered)
```

**This is AgriVision's own proprietary signal** and the most interesting one in
the project. Mandi data is public; this is not. If eight buyers want grapes and
only two lots are listed, demand is strong *on this platform* regardless of what
the mandi says — and that is the market the farmer is actually selling into.

It is also a genuine network effect: the more the platform is used, the better
this signal becomes.

### Combining and labelling

```python
index ≥ 72 → "Strong demand"     (success / green)
index ≥ 58 → "Firm demand"       (success)
index ≥ 43 → "Balanced market"   (secondary / grey)
index ≥ 30 → "Soft demand"       (warning / amber)
else       → "Weak demand"       (danger / red)
```

Each call also returns a `drivers` list — one entry per signal with its value, a
sentence of explanation, and whether it is positive — plus an `advice` string in
plain language:

> "Demand for Grapes is soft. If you have storage, waiting a few weeks may pay;
> otherwise price competitively to move the lot."

The number alone is not actionable. The advice sentence is what a farmer reads.

---

## 4. `forecast()` — six weeks ahead

### Step 1 — least-squares line through the weekly means

```python
slope = (n·Σxy − Σx·Σy) / (n·Σxx − (Σx)²)
intercept = (Σy − slope·Σx) / n
```

Implemented by hand in `_least_squares()` rather than importing NumPy's
`polyfit`, because it is eight lines and the examiner can read it.

### Step 2 — apply a continuous seasonal curve

```python
def _smooth_season(crop_name, day):
    peak_doy = mean(peak_months) → day of year
    return 1 + 0.10 * cos(2π (doy − peak_doy) / 365)
```

Note this is **not** the step-function `season_factor()` used for pricing. A step
function holds every week inside one month at the same value, which makes a
six-week forecast print the same rupee figure four times and look broken. The
cosine varies every day while peaking in the same months.

The two functions coexist deliberately: the step version gives the farmer one
crisp reason for his price, the smooth version gives the chart a believable
curve.

### Step 3 — damping

```python
damp = 1.0 - 0.06 * k                       # k = weeks ahead
value = trend_value * season * damp + period_average * (1 - damp)
```

The further out the projection, the more it is pulled back toward the period
average. This encodes **mean reversion** — commodity prices do not trend forever
— and it is also intellectual honesty: a naive linear extrapolation six weeks out
would be confidently wrong.

The band widens with the crop's volatility, and the returned note says plainly:

> "Confidence narrows the further out you look — treat week 5-6 as indicative."

---

## 5. `top_demand_crops()`

Runs `demand_index()` for every catalogue crop in the given region and sorts
descending. It drives the "Demand in Nashik" panel on the farmer dashboard and
the whole `/insights/` ranking page.

For a farmer deciding what to *plant*, this is the most valuable screen in the
application.

---

## 6. The data behind it

Everything reads `price_records`, which `seed.py` fills with ~41,000 rows —
14 crops × 4 districts × 730 days — generated with a realistic model:

```
price(t) = base × seasonal(t) × trend(t) × shock(t) × noise
```

where `seasonal` is a cosine peaking in the crop's lean months, `trend` is a slow
multi-year drift, `shock` is an occasional market event that decays
geometrically, and arrivals move inversely to price. That inverse relationship is
what gives the supply-pressure signal something real to detect.

**Replacing it with real data** (strongly recommended for the final report):
Agmarknet (`agmarknet.gov.in`) publishes daily mandi prices, and data.gov.in
offers the same as an API. Write a loader that inserts `PriceRecord` rows — every
model in this module then works unchanged on real figures. The seed exists so the
project runs on day one, not because synthetic data is preferred.

---

## 7. The chart pipeline

```
insights/crop_report.html
   <canvas id="trendChart" data-url="/insights/api/trend?crop=Grapes&…">
        │
        ▼  fetch()
/insights/api/trend  →  { history: [...], forecast: [...], summary: {...} }
        │
        ▼
app/static/js/app.js → initTrendChart() → Chart.js line chart
```

The forecast series is padded with nulls so it starts where the history ends,
producing one continuous line that changes to a dashed amber segment at the
boundary. A second canvas renders weekly arrivals as bars.

---

## 8. Viva questions

**Q. How do you predict demand?**
A 0–100 index fusing four signals: price momentum (38%), supply pressure from
mandi arrivals (24%), the crop's seasonal calendar (18%) and the platform's own
requirement-versus-listing balance (20%). 50 is neutral; above 70 is a seller's
market.

**Q. Why those weights?**
Price momentum is the market's own summary of everything, so it leads. Supply
pressure is the next most direct physical signal. The platform signal is
weighted meaningfully because it describes the market the user is actually
trading in. Season is a known pattern already partly reflected in the other
three, so it is weighted lowest.

**Q. Why are falling arrivals a positive signal?**
Arrivals are supply. Less supply with firm prices means scarcity, which supports
the seller's price.

**Q. What is the marketplace-pull signal?**
The ratio of open buyer requirements to available listings for that crop on
AgriVision itself. It is proprietary — not available from mandi data — and it
improves as the platform grows.

**Q. How does the forecast work?**
A least-squares line through the last ~20 weekly means, multiplied by a
continuous seasonal cosine, then damped 6% per week toward the period average to
encode mean reversion.

**Q. Why two different seasonal functions?**
The pricing engine needs one crisp reason per month ("March is a glut month,
−12%"), so it uses a step function. A week-by-week forecast with a step function
projects identical values inside a month and looks broken, so the forecast uses
a smooth cosine.

**Q. How accurate is the forecast?**
Weeks 1–2 are reasonable because the trend is still recent. By weeks 5–6 it is
indicative only, which is why the damping pulls it to the average and the UI says
so. It cannot predict shocks — weather, an export ban, a policy change.

**Q. Where does the price data come from?**
The seed generates two years of realistic daily data so the project runs
immediately. For production, Agmarknet and data.gov.in publish real daily mandi
prices; a loader writing `PriceRecord` rows is the only change needed.
