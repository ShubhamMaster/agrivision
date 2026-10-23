# 13 · Multilingual support and the onboarding guide

**Section goal:** how English, Marathi and Hindi are served from one codebase,
and how a new user is shown what to do without being trapped in a tutorial.

**Files:** `app/i18n.py`, `tools/check_translations.py`,
`app/routes/main.py` (language + guide routes), `app/templates/main/guide.html`

---

## Part 1 — Multilingual support

### 1. Why this matters here

The platform's whole argument is that a farmer should not need an intermediary
to reach a buyer. A farmer in Niphad who reads Marathi and not English still
needs one — the person who can read the screen for him. An English-only
interface quietly rebuilds the dependency the project exists to remove.

Marathi is the state language, Hindi covers traders and buyers from outside
Maharashtra, and English is what institutional buyers and exporters use.

### 2. Why a Python dictionary and not Flask-Babel

The textbook answer is Flask-Babel with gettext `.po` / `.mo` catalogues. It
was deliberately not used, for three reasons:

1. **`.mo` files are compiled artefacts.** They need `pybabel compile` after
   every edit, and a stale or missing `.mo` silently falls back to English —
   a confusing failure for anyone else running the project.
2. **AgriVision must run with no network and no build step.** Plain Python
   dictionaries are imported like any other module.
3. **Adding a string is one line in two dictionaries**, which someone
   maintaining this can do without learning gettext tooling.

Be honest about the trade-off in a viva: **for a production deployment with
professional translators, Flask-Babel is the right tool**, because `.po` is the
format translation agencies work in, and it handles plural forms properly.
This project's scale does not need either.

### 3. The key is the English text

```python
t("Marketplace")   # → "बाजारपेठ" in Marathi, "बाज़ार" in Hindi
```

Using the English source string as the dictionary key, rather than an
identifier like `nav.marketplace`, has one decisive advantage: **a missing
translation renders as readable English**, not as a raw key. A half-translated
page is still usable.

Interpolation goes through `str.format`:

```python
t("{n} lots available", n=14)
```

`t()` never raises — a bad placeholder returns the unformatted string, because
a template should not 500 over a translation.

### 4. How the language is chosen

`get_locale()` resolves in priority order:

1. `?lang=` on the request — lets a link force a language
2. the session — what the user last chose
3. the signed-in user's saved `language` column
4. the browser's `Accept-Language` header
5. English

The result is cached on Flask's `g` for the request, so a page rendering
hundreds of strings resolves the locale once.

Saving the choice on the `users` row is what makes it follow a farmer from his
phone to a borrowed laptop.

### 5. Registering the helpers — a real bug worth knowing

The helpers are registered as **Jinja globals**, not through a context
processor:

```python
app.jinja_env.globals.update(t=t, crop_name=crop_name, ...)
```

The first attempt used a context processor, and every page 500'd with
`'t' is undefined`. The reason: **context processors do not reach inside
imported macros.** `{% from "macros.html" import crop_card %}` gets a bare
context unless it is imported `with context` — and the macros are exactly where
most of the repeated UI text lives. Jinja globals are visible everywhere,
including macros.

### 6. What gets translated, and what does not

| Translated | Left as-is |
|---|---|
| All interface text — navigation, labels, buttons, headings, empty states | Farmer and buyer names |
| **Crop names** — stored in English, shown translated via `crop_name()` | Variety names (Thompson Seedless, Bhagwa) — proper nouns |
| Status words (`available`, `pending`) via the `\| tr` filter | District and market names |
| Relative times ("3 days ago") via the `ago` filter | Free-text descriptions farmers typed |
| Units ("quintal") | Certificate numbers, GST numbers |

Crop names matter most: द्राक्ष, कांदा and डाळिंब are what a farmer actually
calls his crop. The English value stays in the database and in form `value`
attributes, so filtering and matching are unaffected — only the label changes.

### 7. The fonts

IBM Plex Sans has no Devanagari coverage, so Noto Sans Devanagari is bundled
alongside it and declared with a `unicode-range`:

```css
@font-face {
  font-family: "Noto Sans Devanagari Var";
  src: url("../vendor/fonts/noto-sans-devanagari-...woff2") format("woff2-variations");
  unicode-range: U+0900-097F, ...;
}
```

The `unicode-range` means **an English-only visitor never downloads the 119 KB
Devanagari font** — the browser fetches it only when Devanagari actually
appears on the page.

Devanagari also needs more vertical room than Latin: matras above and below the
headline stroke collide at the line heights that suit Plex. The fix is scoped
to the language so the English pages are untouched:

```css
html[lang="mr"] body, html[lang="hi"] body { line-height: 1.68; font-size: .96rem; }
html[lang="mr"] .av-card-title { -webkit-line-clamp: 2; }   /* Devanagari runs longer */
```

### 8. The two coverage tools

```bash
python tools/check_translations.py       # summary
python tools/check_translations.py -v    # every unwrapped string, by template
```

It reports **two different things**, and both matter:

| Coverage | Question | Where it is measured |
|---|---|---|
| **Catalogue** | of the strings passed to `t()`, how many have Marathi and Hindi? | `app/i18n.py` → `coverage()` |
| **Template** | of the user-visible text, how much goes through `t()` at all? | the scanner in the tool |

The second is the one that is easy to miss. A string nobody wrapped is never
*missing* from the catalogue — it is simply always English, and a report that
only checks the catalogue will happily say "100% translated" while half the
screen is in English. That was the real state of this project before the
wrapping pass: the catalogue was complete at 315 strings, but only about 38%
of the interface actually passed through `t()`.

Current state:

```
catalogue : 705 / 705 in both Marathi and Hindi
templates : ~91% of user-visible strings pass through t()
```

The remaining ~9% is deliberate and should stay in English:

- the worked price formula in `about.html` (it is code, shown as code);
- the demo account credentials on the login page;
- proper nouns — district names, variety names, company names;
- `AgriVision`, `OCMR`, `APEDA`, `GrapeNet`, and the other authority acronyms.

### 8a. Whitespace-insensitive keys

Templates wrap text where it sits, so the same sentence arrives with whatever
indentation the HTML happened to have. `_key()` collapses runs of whitespace
before lookup, so this:

```jinja
{{ t("Up to 5 photos,
      JPG or PNG.") }}
```

and the same sentence on one line are the same catalogue entry. Without it the
catalogue would need an entry per indentation level, and re-indenting a
template would silently drop a translation.

### 8b. Interpolation, not concatenation

A sentence with a value in the middle must be **one** `t()` call with a
placeholder, never several fragments glued together:

```jinja
{# wrong — word order is frozen to English, and the fragments are unreadable
   to a translator #}
{{ t("This offer is") }} {{ amount }}{{ t("per quintal below the asking price") }}

{# right #}
{{ t("This offer is {amount} per quintal below the asking price.", amount=amount|rupee) }}
```

Marathi and Hindi put the verb last, so a fragment-by-fragment translation
produces word salad. `t()` takes `**kwargs` and runs `str.format`, and it falls
back to the unformatted English rather than raising if a placeholder is wrong —
a template should never 500 because of a translation.

### 9. Adding a language

1. Add it to `LANGUAGES` in `app/i18n.py`.
2. Add a dictionary (copy the Marathi one and translate the values).
3. Register it in `CATALOGUES`.
4. If it needs a different script, bundle the font and add a `@font-face` with
   the right `unicode-range`.
5. Run `python tools/check_translations.py` until it reports complete.

No template changes are needed — the switcher is built from `LANGUAGES`.

---

## Part 2 — The onboarding guide

### 10. What it is

A **single screen**, shown once immediately after registration, with four steps
specific to the role that just registered. Not a multi-step wizard, not a
tooltip tour.

| Farmer sees | Buyer sees |
|---|---|
| Photograph your crop | Post what you need |
| Let the AI grade and price it | Filter on grade, not on guesswork |
| Upload your certificate | Check the fair price band |
| Answer buyers directly | Compare, then buy direct |

### 11. Three design decisions

**One screen, not a wizard.** A farmer opening this on a phone wants to see the
whole thing and get on with listing a crop, not click "Next" four times. The
numbering is kept because the steps are a genuine sequence — do this, then
this — so the numbers carry information rather than decorating the page.

**Skip is a first-class choice.** An experienced user should not have to read a
guide to reach their dashboard, so Skip sits next to the primary button rather
than hidden in a corner. Because the guide stays reachable from the profile
menu afterwards, skipping costs nothing — which is what makes it safe to offer
prominently.

**Finishing lands on the action, not the dashboard.** The primary button sends
a farmer to the crop form and a buyer to the marketplace. A guide that ends by
dropping you somewhere unrelated wastes the attention it just asked for.
Skipping goes to the dashboard, because someone skipping has said they do not
want to be steered.

### 12. How it is wired

```
POST /auth/register/<role>
   └── account created, logged in
          └── redirect  /guide           (not the dashboard)

GET  /guide
   └── FARMER_STEPS or BUYER_STEPS by role
   └── first_run = not current_user.onboarding_seen

POST /guide/done
   ├── onboarding_seen = True            (either way — never forced again)
   ├── skip pressed  → /<role>/dashboard
   └── otherwise     → /farmer/crops/new  or  /buyer/browse
```

Two columns were added to `users`:

```python
language        = db.Column(db.String(5), default="en")
onboarding_seen = db.Column(db.Boolean, default=False)
```

`db.create_all()` never alters an existing table, so after pulling these
changes the database has to be rebuilt — `python seed.py` does that.

The step text lives in `FARMER_STEPS` / `BUYER_STEPS` in `app/routes/main.py`
as plain data and is rendered through `t()`, so it is fully translated along
with everything else. Editing a step means editing one dictionary entry and
adding its translations.

### 13. Tests

The suite covers both features — 75 checks, up from 59:

| Language | Onboarding |
|---|---|
| Marathi and Hindi render Devanagari | registration redirects to the guide |
| `<html lang>` follows the choice | a farmer sees farmer steps, a buyer buyer steps |
| switching back to English works | the guide is unseen until dismissed |
| an unknown code is refused safely | skipping marks it seen and goes to the dashboard |
| **the switcher cannot redirect off-site** | finishing goes to the matching action |
| the choice is saved on the account | the guide stays reachable afterwards |

The open-redirect test matters: `?next=` on the language switch is exactly the
kind of parameter that becomes a phishing vector if it is not checked to be a
path on this site.

---

## 14. Viva questions

**Q. How is multilingual support implemented?**
A dictionary per language in `app/i18n.py`, keyed on the English source text,
with a `t()` helper registered as a Jinja global. The language is resolved from
the query string, session, user record, or browser header, and cached per
request.

**Q. Why not Flask-Babel?**
It needs a compile step for `.mo` files, which conflicts with the requirement
to run with no build step and no network, and a stale `.mo` fails silently. For
a production deployment with professional translators, Flask-Babel would be the
right choice, because `.po` is the format they work in.

**Q. Why key on English text rather than identifiers?**
A missing translation then renders as readable English instead of a raw key, so
a half-translated page is still usable.

**Q. What happens if a string has no translation?**
It falls back to English. `tools/check_translations.py` exists precisely
because that failure is silent — it reports coverage, currently 100% for both
languages across 268 strings.

**Q. Why are the helpers Jinja globals rather than a context processor?**
Context processors do not reach inside imported macros, and the macros hold
most of the repeated UI text. Using a context processor made every page fail
with `'t' is undefined`.

**Q. Are crop names translated?**
Yes. They are stored in English in the database and translated on display by
`crop_name()`, so filtering and matching are unaffected — only the label
changes. That matters because द्राक्ष is what the farmer actually calls it.

**Q. How is the Devanagari font handled?**
Noto Sans Devanagari is bundled for offline use and declared with a
`unicode-range`, so an English-only visitor never downloads it. Line height and
title clamping are adjusted under `html[lang="mr"]` because Devanagari needs
more vertical room than Latin.

**Q. Why is the onboarding one screen with a skip button?**
Because a farmer on a phone wants the whole thing at once, and an experienced
user should not have to read a guide to reach their dashboard. The guide stays
in the profile menu, which is what makes skipping safe to offer up front.

**Q. What stops the guide reappearing forever?**
`onboarding_seen` is set on the user record when the guide is finished *or*
skipped.
