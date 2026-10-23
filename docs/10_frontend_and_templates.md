# 10 · Frontend — templates, styling and JavaScript

**Section goal:** how the interface is built, and where to change it.

**Files:** 27 templates in `app/templates/`, `app/static/css/style.css` (~190
lines), `app/static/js/app.js` (~250 lines).

---

## 1. Template inheritance

Every page extends one base:

```
base.html                     navbar, flash messages, footer, asset links
   ├── main/        home, about, notifications
   ├── auth/        register_choice, register, login, profile
   ├── farmer/      dashboard, crops, crop_form, crop_detail,
   │                certificate_upload, certificate_report, requirements
   ├── buyer/       dashboard, browse, crop_detail, compare,
   │                requirements, requirement_form, requirement_detail
   ├── deals/       inbox, detail
   ├── insights/    overview, crop_report
   ├── errors/      403, 404, error
   └── partials/    macros.html   (not a page — a component library)
```

A child template fills blocks:

```jinja
{% extends "base.html" %}
{% block title %}Farmer dashboard{% endblock %}
{% block content %} … {% endblock %}
```

The navbar in `base.html` adapts to the role, so there is one navbar, not three:

```jinja
{% if current_user.is_authenticated and current_user.is_farmer %}
   My Crops · Buyer Requirements
{% elif current_user.is_authenticated and current_user.is_buyer %}
   Marketplace · My Requirements
{% endif %}
```

`current_user` is available in templates because Flask-Login injects it — no view
has to pass it.

---

## 2. The macro library

`partials/macros.html` holds eight reusable components:

| Macro | Renders |
|---|---|
| `grade_badge(grade, score)` | the coloured A/B/C pill |
| `cert_badge(crop)` | verified / pending / rejected certificate pill |
| `stat(icon, label, value, colour)` | a dashboard statistic tile |
| `crop_card(crop, href, …)` | a marketplace card |
| `price_band(band, asking)` | the gradient band with the position marker |
| `demand_meter(d)` | the demand gauge |
| `deal_badge(deal)` | the deal status pill |
| `empty(icon, title, text, …)` | the empty-state block |

Imported where needed:

```jinja
{% from "partials/macros.html" import crop_card, grade_badge %}
```

The payoff: the grade badge appears on eleven screens. Changing its colour or
adding a tooltip is one edit, and no screen can drift out of step with the
others.

---

## 3. Three bugs worth knowing about

### `&amp;` rendering literally

```jinja
{{ metric('Unit size &amp; consistency', …) }}     ✗ prints "Unit size &amp; consistency"
{{ metric('Unit size & consistency', …) }}         ✓ prints "Unit size & consistency"
```

Jinja autoescapes the value of a `{{ }}` expression, so an entity written inside
a **string literal** gets escaped a second time and the `&` becomes visible. In
plain HTML text outside `{{ }}`, `&amp;` is correct. Both appear in this project
and both are right in their own context.

### Indian number formatting

Python's `{:,}` gives `1,756,300`. Indian grouping is `17,56,300` — 2-2-3 from
the right. Hence the hand-written `rupee` filter in `app/__init__.py`.

### Bootstrap submit buttons

`<button class="btn btn-success">` inside a form submits by default, but it has
no `type="submit"` attribute, so the CSS selector `button[type="submit"]` does
not match it. This cost a debugging round in the screenshot tooling and is worth
knowing if you write browser tests.

---

## 4. Styling

`style.css` defines the palette once:

```css
:root {
  --av-green: #1f6b3b;        /* deep field green */
  --av-green-dark: #154d2a;
  --av-amber: #f0a500;        /* harvest amber */
  --av-soil: #6b4f3a;
  --av-ink: #1d2b24;
}
```

Changing the whole site's colour scheme is five lines.

Bootstrap 5 does the layout; the custom CSS adds the things Bootstrap has no
component for:

**The price band** — a gradient track with an absolutely positioned marker:

```css
.av-band-fill   { background: linear-gradient(90deg, #cfe9d8, var(--av-green), #cfe9d8); }
.av-band-marker { position: absolute; width: 4px; height: 22px; background: #d6336c; }
```

```jinja
{% set pos = ((asking - band.min) / (band.max - band.min) * 100) %}
<div class="av-band-marker" style="left: {{ [[pos, 0]|max, 100]|min }}%"></div>
```

The nested `max`/`min` clamp keeps the marker inside the track when the asking
price is outside the band.

**The demand gauge**, **quality metric bars**, **chat bubbles** (`.av-msg-mine`
right-aligned green, `.av-msg-theirs` left-aligned white), and a sticky
`position: sticky; top: 86px` sidebar so the price panel stays visible while
scrolling a long lot page.

The footer is pinned to the bottom with flexbox on `body`, so short pages do not
leave it floating mid-screen.

---

## 5. JavaScript — five features, no framework

`app.js` is plain ES6 with five independent initialisers, each of which returns
immediately if its element is absent:

```javascript
function initPriceHelper() {
  const box = document.getElementById("priceHelper");
  if (!box) return;            // not on this page
  ...
}
```

That pattern means one script file can be loaded on every page without errors.

| Function | What it does |
|---|---|
| `initPriceHelper()` | POSTs to `/farmer/api/price-suggestion`, renders the band and factors, gives live feedback as the farmer types |
| `initPhotoPreview()` | shows thumbnails before upload via `URL.createObjectURL` |
| `initCompareTray()` | collects checked lot ids, shows the fixed bar, builds `?id=1&id=3`, disables extras past four |
| `initTrendChart()` | fetches `/insights/api/trend` and draws the history + forecast line and the arrivals bars |
| `initChatScroll()` | scrolls the chat to the newest message |

**Why no React or Vue?** Server-rendered Jinja with a few hundred lines of
vanilla JS does everything this application needs. A build step, a bundler and a
node_modules tree would add setup friction for a reviewer and buy nothing here.
The one genuinely dynamic screen — the price helper — is 80 lines of `fetch`.

### The forecast chart trick

```javascript
const pad = new Array(hist.length - 1).fill(null);
const fc  = pad.concat([hist[hist.length - 1]], forecastPrices);
```

Padding the forecast series with nulls makes it start exactly where the history
ends, so the two datasets join into one continuous line that changes to a dashed
amber segment at the boundary.

---

## 6. Offline operation

Bootstrap, Bootstrap Icons and Chart.js are **bundled** in
`app/static/vendor/`, not loaded from a CDN:

```
app/static/vendor/
├── css/bootstrap.min.css
├── css/bootstrap-icons.min.css
├── css/fonts/bootstrap-icons.woff2     ← must sit next to its stylesheet
└── js/bootstrap.bundle.min.js
    js/chart.umd.min.js
```

The reason is practical: a project demo must not fail because the college Wi-Fi
is down or the CDN is blocked.

Note the font location. `bootstrap-icons.min.css` references `./fonts/…`
*relative to itself*, so the font files must live in `css/fonts/`, not a sibling
`fonts/` folder. Getting this wrong produces a page where every icon is an
invisible box — it was a real bug during the build, caught by watching for 404s
in the browser console.

---

## 7. Responsive behaviour

Bootstrap's grid handles it: `col-lg-8` / `col-lg-4` becomes full width below
992 px, the navbar collapses to a hamburger, and `table-responsive` makes wide
tables scroll horizontally instead of breaking the layout. Tested at 1440 px.

---

## 8. Accessibility and polish

- Every form control has a `<label>`.
- Icons are decorative and always accompanied by text.
- Flash messages are `role="alert"` and dismissible.
- Destructive actions use `onsubmit="return confirm(…)"`.
- Empty states explain what to do next and link to the action, instead of showing
  a blank panel.

---

## 9. Where to change what

| You want to… | Edit |
|---|---|
| Change the colour scheme | the `:root` block in `style.css` |
| Change the navbar or footer | `base.html` |
| Change how a grade badge looks everywhere | `partials/macros.html` |
| Change the money format | the `rupee` filter in `app/__init__.py` |
| Change the chart | `initTrendChart()` in `app.js` |
| Add a page | a template + a route in the right blueprint |

---

## 10. Viva questions

**Q. How is the UI structured?**
Jinja2 template inheritance: one `base.html` with the navbar, flash area and
footer; every page fills its blocks. Shared components live as macros in
`partials/macros.html` and are imported where needed.

**Q. Why macros instead of copying the markup?**
The grade badge appears on eleven screens. As a macro it is one definition, so
the screens cannot drift apart and a change is a single edit.

**Q. Why no frontend framework?**
The application is server-rendered and needs dynamic behaviour on exactly one
screen. Vanilla JS does it in 250 lines with no build step, no bundler and
nothing for a reviewer to install.

**Q. Why are Bootstrap and Chart.js bundled rather than from a CDN?**
So the application runs with no internet connection. A demo should not depend on
the venue's Wi-Fi.

**Q. Why did the icons initially fail to load?**
`bootstrap-icons.min.css` references its font files relative to itself, so they
must live in `css/fonts/`. They were in a sibling folder, producing 404s and
blank icon boxes.

**Q. Why is there a custom rupee filter?**
Indian digit grouping is 2-2-3 from the right (₹17,56,300), which Python's `{:,}`
cannot produce.

**Q. What does the price band marker show?**
Where the farmer's asking price sits inside the AI fair band, positioned by a
percentage computed in the template and clamped to the track.
