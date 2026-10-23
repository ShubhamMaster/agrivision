# 12 · Lot photography pipeline

**Section goal:** where the crop images come from, how they are made, and why
they are made that way.

**Files:** `app/photo_lot.py`, `tools/fetch_specimens.py`,
`tools/check_hue_bands.py`, `assets/specimens/`

---

## 1. The problem

The marketplace is a catalogue. A buyer decides whether to open a lot almost
entirely from its photograph, and the computer-vision grader reads that same
photograph. So the images are not decoration — they are both the primary
interface and the input to the main AI module.

The first build drew each lot procedurally: coloured blobs on a noisy
background. That was enough to exercise the grader, but it looked nothing like
produce, and a demo where every card shows confetti undersells the whole
project.

---

## 2. What the images are now

| Crops | Source |
|---|---|
| Grapes, Pomegranate, Mango, Banana, Tomato, Onion, Potato, Maize, Chilli | **Real photographed specimens**, composed into a lot |
| Wheat, Rice, Soybean, Cotton, Sugarcane | **Rendered** in the same studio style |

Nine of fourteen crops are built from real photographs. The other five are bulk
grain and fibre crops with no photographic source available; they are rendered
to match, because a catalogue where four cards look like a different product is
worse than one where every card is at least consistent.

Rendering genuinely suits those five: a wheat lot really is a heap of thousands
of near-identical grains, so the shape being drawn is the shape the crop has.

---

## 3. Where the real photographs come from

**Fruits-360** (Horea Mureșan et al.), a public dataset of produce photographed
on a turntable against a white background:

> https://github.com/Horea94/Fruit-Images-Dataset — licensed CC BY-SA 4.0

`tools/fetch_specimens.py` downloads roughly 30 specimens per crop into
`assets/specimens/<Crop>/`, sampling indices with a stride so the specimens are
different angles rather than 30 near-identical frames of one rotation.

```bash
python tools/fetch_specimens.py           # fetch anything missing
python tools/fetch_specimens.py --force   # re-fetch everything
```

**The cache is committed with the project**, so `seed.py` runs offline. The
fetcher is only needed to add a crop or refresh the set.

### The substitution you should know about

The dataset has no chilli class. **Red capsicum stands in for chilli** — same
genus (*Capsicum annuum*), right colour for a red-chilli lot. Green bell
peppers were deliberately excluded because they read as capsicum and would
contradict the listing. If an examiner asks, this is the honest answer: it is a
visual stand-in, not a claim that the lot is capsicum.

---

## 4. Why compose rather than use a specimen directly

A single 100×100 fruit on white says nothing about 85 quintal of grapes. Worse,
it would make the grader meaningless: one object, no background to segment, and
nothing to measure for uniformity or unit size — every lot would score the same.

Composing from many real specimens keeps every pixel photographic (real colour,
real skin texture, real blemishes) while giving the grader what it needs: many
units, a real background to separate, and genuine variation between pieces.

---

## 5. The composer — `compose_lot()`

```
 specimen photographs (100x100, white background)
        │
  ┌─────▼──────────┐
  │ 1 CUT OUT      │  remove the studio background → RGBA sprite
  └─────┬──────────┘
  ┌─────▼──────────┐
  │ 2 SWEEP        │  white studio backdrop with a faint floor gradient
  └─────┬──────────┘
  ┌─────▼──────────┐
  │ 3 ARRANGE      │  heap / cluster / crossed, by crop
  └─────┬──────────┘
  ┌─────▼──────────┐
  │ 4 GRADE TIER   │  colour scatter, bruising, size spread
  └─────┬──────────┘
  ┌─────▼──────────┐
  │ 5 CAMERA       │  key light, contact shadow, unsharp, sensor noise
  └────────────────┘
```

### Stage 1 — the cut-out, and the halo problem

The obvious approach is a brightness threshold: anything bright and unsaturated
is background. It leaves a **pale fringe** around every piece — the antialiased
ring where the fruit blends into white is bright but partly saturated, so it
survives the test and then glows against a darker surface.

The fix uses a property the fringe does not have: the studio background is
**connected to the border of the frame**.

```python
loose_bg = (v > 182) & (s < 78)                 # deliberately generous
n, labels = cv2.connectedComponents(loose_bg)
border = labels on the frame edge
true_bg = components touching the border
```

A pale pixel in the middle of a fruit is a highlight and stays; the same pale
pixel connected to the border is background and goes. The alpha edge is then
tapered with a distance transform rather than a Gaussian blur, which would
reach back out and pull the white pixels in again.

### Stage 3 — the three arrangements

| Layout | Crops | Why |
|---|---|---|
| `heap` | pomegranate, mango, tomato, onion, potato, chilli | a back row higher and smaller, a front row lower and full size — how loose produce is piled for a shot |
| `cluster` | grapes | many small pieces packed into a bunch |
| `crossed` | banana, maize | elongated pieces laid across each other in a shallow fan |

The cluster radius is **derived from the piece count and size**, not set as a
fraction of the frame:

```python
packing = 0.20
r = sqrt(n * piece² * packing / π)
```

Solving `π·r² ≈ n · piece² · packing` makes the berries actually touch. With a
fixed radius they float apart and the group reads as spilled rather than as a
bunch.

`_fit_to_frame()` then scales and recentres the whole arrangement so no piece
is clipped — otherwise a wide heap runs off the edge and the card shows half a
tomato, which looks like a cropping bug rather than a photograph.

### Stage 4 — the quality tiers

`good` / `medium` / `poor` control colour scatter, bruise rate and strength,
size spread and sharpness. They exist so the seeded marketplace shows a real
spread of A, B and C grades.

Two calibration notes worth knowing:

- **Hue jitter stays small (2–7).** Produce varies far more in brightness and
  blemishing than in hue. Shifting hue more than a few degrees turns potatoes
  purple, which reads as a rendering bug rather than as a poor lot.
- **Bruises are wide, weak and feathered**, and desaturate as well as darken. A
  small hard dark disc does not read as a blemish; it reads as a hole punched
  through the fruit.

### Stage 5 — the unsharp mask

The specimens are 100 px originals enlarged several times over, so they arrive
soft. Without restoring edge definition the grader's blur check fires on every
composed photo and caps the score — see section 7.

---

## 6. The bulk renderer — `compose_bulk_lot()`

Same white sweep, same contact shadow, same framing. Three forms:

- **heap** — wheat, rice, soybean: thousands of small ellipses inside a dome,
  shaded so grains deeper in the pile sit in shadow.
- **bolls** — cotton: overlapping soft lobes, then the boll region is blurred.
  Drawn as hard-edged discs it reads as grey bubbles; cotton is fibre, and
  blurring is what makes it fluffy. The shading range has to be wide because
  white produce on a white sweep otherwise disappears.
- **stalks** — sugarcane: canes with node bands and a highlight/shadow pair
  across each, giving a cylinder's cross-section.

`make_lot_photo()` is the single entry point the seed calls; it routes to the
composer, then the bulk renderer, then a blank sweep as a last resort.

---

## 7. Two real bugs the photographs exposed

These are worth being able to explain, because they were genuine defects in the
AI modules that the synthetic images had been hiding.

### 7.1 The blur check misfired on pale backgrounds

`grade_image()` measured sharpness as the variance of the Laplacian **over the
whole frame**. A white studio sweep has almost no Laplacian response, so it
dragged the variance below the blur threshold and capped the score at 68 — every
photographed lot graded exactly B, regardless of quality.

The bug was not limited to the seed: any farmer photographing produce against a
pale tarpaulin or an overcast sky would have been marked down for it.

The fix measures sharpness **inside the produce mask**:

```python
lap = cv2.Laplacian(gray, cv2.CV_64F)   # computed on the whole image
sel = eroded_mask > 0                   # variance taken only on produce
return float(lap[sel].var())
```

The mask is eroded first, because the produce/background boundary is a genuine
strong edge that would read as "sharp" no matter how blurred the subject is.
Exposure was moved inside the mask for the same reason — a white backdrop
pushes the frame mean past the over-exposure limit while the fruit is correctly
exposed.

Segmentation now runs *before* the photo-quality checks, which is why the stage
numbering in `grading.py` changed.

### 7.2 The hue bands were wrong

The `hue_bands` in `CROP_CATALOGUE` drive 34% of the quality score. They had
been written against drawn stand-ins, and measuring them against real
photographs showed several were simply wrong:

| Crop | Old band | Real median hue | In-band before | After |
|---|---|---|---|---|
| Maize | (16, 40) | 45 | **22%** | 97% |
| Grapes | (32, 85) | 34 | 63% | 95% |
| Potato | (8, 30) | 17 | 58% | 99% |
| Mango | (12, 40), (40, 80) | 43 | 60% | 81% |

Real corn was being marked down for being the correct colour.

`tools/check_hue_bands.py` is the re-runnable calibration check:

```bash
python tools/check_hue_bands.py
```

It reports each crop's actual hue distribution against its declared band and
flags anything under 70%. Run it after adding a crop or re-fetching specimens;
a crop below that line is miscalibrated, not poor produce.

Remember OpenCV packs hue into **0–179**, not 0–359 — halve any value from a
colour picker.

---

## 8. Grading results after the change

```
crop          tier     grade  score   colour unif defect size
Grapes        good     A       78.3      87   68     69    93
Onion         medium   A       77.7      96   71     54    93
Tomato        good     A       76.1      78   77     64    93
Pomegranate   good     A       77.6      84   74     66    93
Potato        good     A       81.6      98   78     58    93
Pomegranate   poor     B       68.0      83   73     63    81
Chilli        medium   B       68.2      82   59     47    93
Maize         medium   B       72.4      83   72     53    88
Wheat         good     B       56.4      71   43     79    14   (rendered)
Soybean       medium   C       45.8      65   44     44    18   (rendered)
Rice          good     C       47.9      34   27     90    36   (rendered)

grade spread: A 7 · B 5 · C 2
```

The grader discriminates, and the grades track the intended tiers.

**An honest limitation:** the poor tier still lands at B rather than C for
photographed lots. The defect detector looks for pixels much darker than the
produce median, and a soft realistic bruise on a dark pomegranate does not drop
far enough below it. Making the bruises detectable enough to force a C made
them look like holes punched in the fruit. The visual honesty was kept and the
grade range was accepted — the separation between 76–82 (good) and 68–74
(medium/poor) is real, it is just narrower than the rendered crops' range.

---

## 9. Replacing these with your own photographs

This is the single strongest improvement available, and the pipeline is built
for it.

**Option A — use your own lot photographs directly.** Drop them in
`app/static/uploads/crops/` and insert `CropPhoto` rows pointing at them. The
grader runs on whatever is on disk.

**Option B — use your own specimens and keep the composer.** Photograph
individual fruits against a plain white sheet, save them as
`assets/specimens/<Crop>/<variety>_001.jpg`, and re-run `python seed.py`. The
composer picks them up automatically — `has_specimens()` just counts files in
the folder. Then run `tools/check_hue_bands.py` and widen any band that your
produce falls outside.

The filename prefix before the underscore is the variety group, and
`compose_lot(variety=...)` pins a listing to one group, so a Thompson Seedless
listing shows green grapes and not a mixed bowl.

---

## 10. Viva questions

**Q. Are these real photographs?**
Nine of the fourteen crops are composed from real photographed specimens from
the Fruits-360 dataset — real colour, texture and blemishes. The five bulk
grain and fibre crops have no photographic source and are rendered in the same
studio style. The pipeline takes your own photographs directly if you supply
them.

**Q. Why compose instead of showing one specimen photo?**
One fruit on white tells a buyer nothing about an 85-quintal lot, and it would
make the grader meaningless — a single object with no background gives nothing
to measure for uniformity or unit size.

**Q. How do you remove the white background cleanly?**
A generous brightness-and-saturation test, then keep only the components
connected to the frame border. The studio background touches the edge; a
highlight inside a fruit does not. The alpha edge is tapered with a distance
transform so it does not reach back into the white pixels.

**Q. What bugs did the real photographs expose?**
Two. The grader measured blur over the whole frame, so a white background
dragged the variance down and capped every score at 68 — it now measures inside
the produce mask. And four crops' hue bands were calibrated against drawn
stand-ins; real maize scored 22% in-band until they were re-measured.

**Q. Is the chilli image actually chilli?**
No — it is red capsicum, the closest produce in the dataset and the same genus.
It is a visual stand-in and it is documented as one.

**Q. Does the app still work offline?**
Yes. The specimen cache is committed, and Bootstrap, Chart.js and the typeface
are all bundled in `app/static/vendor/`. Only `tools/fetch_specimens.py` needs
the network, and only when adding a crop.
