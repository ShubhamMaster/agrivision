# 04 · AI module 2 — price recommendation engine

**Section goal:** answer "what should I ask for this lot?" with a number the
farmer can defend, and show him exactly how it was reached.

**File:** `app/ai/pricing.py` (~300 lines)

---

## 1. The model

```
price = regional_base_price
        × grade_factor        quality assessed by the CV model
        × season_factor       where we are in that crop's calendar
        × demand_factor       the demand index from app/ai/demand.py
        × premium_factor      organic / verified certificate
```

A **multiplicative** model is used rather than an additive one because every
factor is naturally a percentage. "Grade A is worth 18% more" holds whether the
crop sells at ₹1,500 or ₹9,500 a quintal; "+₹800 for Grade A" does not.

Worked example (seeded Nashik grapes):

```
Nashik median, last 45 days        ₹6,350
  × 0.993  quality   Grade B, score 58/100        −0.7%
  × 1.05   season    approaching lean supply      +5.0%
  × 0.979  demand    index 39/100, soft           −2.1%
  × 1.08   premium   verified certificate         +8.0%
  ────────────────────────────────────────────────────
  = ₹6,690 recommended,  band ₹5,490 – ₹7,900
```

---

## 2. The crop catalogue

`CROP_CATALOGUE` is the single source of truth for all 14 crops and is imported
by **three** modules — pricing, grading and demand.

```python
"Grapes": {
    "base_price": 5800,              # fallback reference, ₹/quintal
    "volatility": 0.18,              # typical ± swing → band width
    "peak_months": [6, 7, 8, 9],     # lean supply, prices high
    "glut_months": [2, 3, 4],        # harvest flood, prices low
    "hue_bands": [(32, 85), (118, 165)],   # used by grading.py
    "min_sat": 35,                         # used by grading.py
    "certificate": True,             # needs a quality certificate to trade
    "unit_note": "Export lots usually 20-100 quintal",
},
```

Volatility is the honest part of the design. Tomato is 0.38 and wheat is 0.09,
because tomato genuinely swings ±38% and wheat is anchored near its MSP. The band
width follows from the crop's real behaviour rather than a flat ±10% for
everything.

---

## 3. Stage 1 — the regional base price

```python
def regional_base_price(crop_name, state, district, days=45):
    attempts = [
        (district, state, f"{district} mandi data (last {days} days)"),
        (None,     state, f"{state} state average"),
        (None,     None,  "all-India average"),
    ]
    for dist, st, label in attempts:
        prices = [r.modal_price for r in query...]
        if len(prices) >= 3:
            return median(prices), label
    return catalogue_base_price, "catalogue reference price (no mandi data yet)"
```

Three design decisions worth defending:

**District first.** Onion in Lasalgaon and onion in Solapur are different prices.
A national average would be useless to the farmer standing in Niphad.

**Median, not mean.** A single data-entry error of ₹60,000 would drag a mean
badly; the median ignores it. Mandi data is noisy and this is cheap insurance.

**Graceful degradation.** District → state → national → catalogue. The function
*always* returns a usable number, and it always returns a label saying which
level it fell back to. That label is shown to the user — "Source: Nashik mandi
data (last 45 days)" — so the number is never anonymous.

**Why 45 days?** Long enough to smooth daily noise, short enough to track the
current market. 7 days is jumpy; 180 days is stale.

---

## 4. Stage 2 — the grade factor

```python
GRADE_FACTORS = {"A": 1.18, "B": 1.00, "C": 0.82}

g_factor = GRADE_FACTORS[grade]
if quality_score is not None:
    g_factor *= 1 + (quality_score - 65.0) / 1000.0     # ±3.5% smoothing
g_factor = max(0.70, min(1.30, g_factor))
```

Grade B is the reference (×1.00); A is worth 18% more, C 18% less.

The smoothing term matters. Without it, a lot scoring 75.9 and one scoring 76.1
would be priced 18% apart — a cliff edge the farmer would rightly call unfair.
The term nudges the factor by up to ±3.5% based on where inside the grade the lot
sits, so the price curve is continuous while the grade label stays discrete.

The clamp to [0.70, 1.30] stops any future change to the formula from producing
an absurd multiplier.

---

## 5. Stage 3 — the season factor

```python
if month in peak_months:  return 1.12, "lean-supply month (+12%)"
if month in glut_months:  return 0.88, "peak-harvest season (-12%)"
if adjacent to a peak:    return 1.05, "approaching the lean-supply window (+5%)"
if adjacent to a glut:    return 0.95, "close to the harvest-flood window (-5%)"
return 1.00, "normal season"
```

Agricultural prices are strongly seasonal: everyone harvests at once, the market
floods, the price collapses. Four months later the same crop is scarce and dear.

The function returns **a factor and a sentence**. The sentence goes straight into
the UI, which is why the farmer sees "March is peak-harvest season for grapes —
supply glut (−12%)" instead of a bare number. Every factor in this module returns
its own explanation for the same reason.

The adjacent-month cases avoid a hard jump between a peak month and a normal one.

---

## 6. Stage 4 — the demand factor

```python
di = demand_index(crop_name, state, district)        # 0-100, 50 is neutral
d_factor = 1 + (di["index"] - 50) / 550.0            # → roughly 0.91 … 1.09
```

The demand index is computed in `app/ai/demand.py` (documented in `05_…`). The
divisor 550 caps the demand effect at about ±9%, deliberately **smaller** than
the grade effect (±18%). Quality is a fact about the lot; demand is an estimate
from noisy market data, so it is given less authority.

The whole call is wrapped in `try/except`: if demand cannot be computed the
factor falls back to 1.0 and pricing still works. No single sub-model can take
the engine down.

---

## 7. Stage 5 — premiums

```python
if organic:   p_factor *= 1.15     # +15%
if certified: p_factor *= 1.08     # +8%
```

Both are market realities: organic produce commands a premium, and a verified
residue certificate is what makes a lot exportable at all. Note that the
certificate premium is applied **only after verification succeeds** — the
farmer's claim alone earns nothing, which is what gives the verification step its
value.

---

## 8. The band

```python
spread = volatility * (0.75 if grade == "A" else 1.0 if grade == "B" else 1.15)
min = recommended * (1 - spread)
max = recommended * (1 + spread)
```

The band is **narrower for Grade A and wider for Grade C**. A premium lot has a
well-established market price; a poor lot's value depends much more on who is
buying and how desperate they are. The band width honestly reflects that
uncertainty.

All prices are rounded to the nearest ₹10 — nobody quotes ₹6,687.43 a quintal.

---

## 9. The output

```python
{
  "recommended": 6690,
  "min": 5490, "max": 7900,
  "base": 6350,
  "source": "Nashik mandi data (last 45 days)",
  "factors": [
     {"name": "Quality grade",  "multiplier": 0.993, "effect": "-0.7%",
      "note": "Grade B (score 58/100)"},
     {"name": "Season",         "multiplier": 1.05,  "effect": "+5.0%",
      "note": "Approaching the lean-supply window for Grapes (+5%)"},
     {"name": "Market demand",  "multiplier": 0.979, "effect": "-2.1%",
      "note": "Demand index 39/100 — Soft demand"},
     {"name": "Premiums",       "multiplier": 1.08,  "effect": "+8.0%",
      "note": "verified certificate +8%"}
  ],
  "volatility_pct": 18.0,
  "explanation": "Starting from Nashik mandi data at ₹6,350/quintal. …"
}
```

**Every factor carries its own effect and reason.** This is the design decision
that makes the module usable: the UI renders the list directly, so the farmer
sees the full derivation and can argue with any line of it.

---

## 10. `evaluate_asking_price()` — the feedback loop

```python
if asking < band["min"]:
    "Your price is ₹X below the fair band. You may be under-selling…"
elif asking > band["max"]:
    "Your price is ₹X above the fair band. Buyers may skip this listing…"
else:
    "Your price sits inside the AI-recommended fair band. Good pricing."
```

Note that the farmer is **never prevented** from setting his own price. He knows
things the model does not — a standing relationship with a buyer, an urgent need
for cash, exceptional sweetness in this year's crop. The system advises; he
decides. Anything else would replace one authority with another.

The same comparison is shown to the **buyer** on the lot page, from the opposite
side: "asking price is above the AI fair band — there is room to negotiate."
Showing both parties the same number is what makes it a fair marketplace rather
than a farmer's tool or a buyer's tool.

---

## 11. Where it is called

| Caller | Purpose |
|---|---|
| `routes/farmer.py` → `_reprice()` | store the band on the crop when it is created, edited, re-graded or certified |
| `routes/farmer.py` → `api_price_suggestion` | the live AJAX helper on the listing form |
| `routes/buyer.py` → `crop_detail` | fairness read-out for the buyer |
| `routes/buyer.py` → `compare` | the value score |
| `routes/insights.py` → `crop_report` | "fair price today (Grade B)" |
| `seed.py` | setting realistic demo prices and requirement ranges |

### The live helper

While the farmer is still filling the form — before anything is saved — the page
POSTs to `/farmer/api/price-suggestion` and renders the suggestion beside the
form. `app/static/js/app.js` then compares whatever he types against the band in
real time. This is the feature farmers notice first.

---

## 12. Viva questions

**Q. How is the suggested price computed?**
A regional base price (median modal price of the last 45 days in the farmer's
district) multiplied by four factors: grade, season, demand and premiums. Each
factor returns both a multiplier and a sentence explaining it.

**Q. Why multiplicative rather than additive?**
Every factor is naturally proportional. "Grade A is worth 18% more" is true at
₹1,500 and at ₹9,500; a fixed rupee bonus is not.

**Q. Why the median and not the mean?**
Mandi data contains entry errors. One wrong figure moves the mean badly; the
median ignores it.

**Q. What if there is no price data for that district?**
It falls back to the state, then to the national average, then to the catalogue
reference price — and it tells the user which level it used.

**Q. Why does the band width differ by crop?**
It comes from each crop's historical volatility: tomato ±38%, wheat ±9%. A single
flat percentage would be dishonest for both.

**Q. Why is the band narrower for Grade A?**
Premium produce has a well-established price. Low-grade produce varies much more
with the buyer, so the band widens to reflect genuine uncertainty.

**Q. Why is the demand effect capped lower than the grade effect?**
Grade is a measurement of the lot; demand is an inference from noisy market data.
The less reliable signal is given less authority — ±9% against ±18%.

**Q. Can the farmer ignore the suggestion?**
Yes, completely. He sets his own price and the system just tells him where it
sits relative to the band. He has private information the model does not.

**Q. How does the certificate premium work?**
A verified certificate adds 8%, applied only after the OCMR pipeline returns
`verified`. An unverified claim earns nothing.
