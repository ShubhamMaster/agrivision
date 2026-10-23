"""
AgriVision — translation coverage audit.

    python tools/check_translations.py          # summary
    python tools/check_translations.py -v       # list every untranslated string

Two different things are called "coverage", and both matter:

  1. CATALOGUE coverage — of the strings passed to t(), how many have a Marathi
     and Hindi entry?  app/i18n.py's coverage() answers that.
  2. TEMPLATE coverage — of the user-visible text in the templates, how much is
     passed through t() at all?  A string nobody wrapped is never missing from
     the catalogue; it is simply always English. That is the blind spot this
     script exists to close.

The scanner is deliberately crude: it strips Jinja tags, HTML tags, script and
style blocks, then reports leftover runs of words. It over-reports (a stray
"q" or a brand name will show up), so treat the output as a worklist rather
than a defect count.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.i18n import HI, MR, coverage          # noqa: E402

TEMPLATE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "templates")

# Text that is not UI copy and should not be translated.
IGNORE = re.compile(
    r"^(?:[\W\d_]+|q|kg|AgriVision|OCMR|APEDA|GrapeNet|NRCG|NPOP|AGMARK|FSSAI"
    r"|JPG|PNG|PDF|GST|AI|UPI|APMC|MSP|ID)$", re.I)

JINJA = re.compile(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", re.S)
SCRIPTY = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
COMMENT = re.compile(r"<!--.*?-->", re.S)
TAG = re.compile(r"<[^>]+>", re.S)
ENTITY = re.compile(r"&[a-z]+;|&#\d+;", re.I)


def visible_text(html: str) -> list[str]:
    s = SCRIPTY.sub(" ", html)
    s = COMMENT.sub(" ", s)
    s = JINJA.sub(" ", s)          # whatever is inside {{ }} is already handled
    s = TAG.sub(" ", s)
    s = ENTITY.sub(" ", s)

    out = []
    for line in s.splitlines():
        for chunk in re.split(r"\s{2,}|[|]", line):
            chunk = chunk.strip(" \t·—–-:,")
            if not chunk or IGNORE.match(chunk):
                continue
            if not re.search(r"[A-Za-z]{2,}", chunk):
                continue
            out.append(re.sub(r"\s+", " ", chunk))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list every unwrapped string, grouped by template")
    args = ap.parse_args()

    # ---- 1. catalogue coverage --------------------------------------
    cov = coverage()
    print("\nCatalogue coverage (strings passed to t() that have translations)")
    print("=" * 70)
    for lang in ("mr", "hi"):
        c = cov[lang]
        print(f"  {lang}: {c['translated']}/{c['total']} translated")
        for m in c["missing"][:10]:
            print(f"      missing: {m}")
    print(f"  catalogue size: {len(MR)} Marathi, {len(HI)} Hindi entries")

    # ---- 2. template coverage ---------------------------------------
    print("\nTemplate coverage (user-visible text actually passed through t())")
    print("=" * 70)

    total_wrapped = total_raw = 0
    per_file = []

    for root, _dirs, files in os.walk(TEMPLATE_ROOT):
        for fn in sorted(files):
            if not fn.endswith(".html"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, TEMPLATE_ROOT)
            html = open(path, encoding="utf-8").read()

            wrapped = len(re.findall(r"\bt\(", html))
            raw = visible_text(html)

            total_wrapped += wrapped
            total_raw += len(raw)
            if raw or wrapped:
                per_file.append((rel, wrapped, raw))

    per_file.sort(key=lambda r: -len(r[2]))

    print(f"  {'template':42s} {'t()':>5s} {'raw':>5s}")
    print("  " + "-" * 56)
    for rel, wrapped, raw in per_file:
        flag = "  <-- worst" if len(raw) >= 20 else ""
        print(f"  {rel:42s} {wrapped:5d} {len(raw):5d}{flag}")

    denom = total_wrapped + total_raw
    pct = (100.0 * total_wrapped / denom) if denom else 100.0
    print("  " + "-" * 56)
    print(f"  {'TOTAL':42s} {total_wrapped:5d} {total_raw:5d}")
    print(f"\n  roughly {pct:.0f}% of user-visible strings go through t()")

    if args.verbose:
        print("\nUnwrapped strings")
        print("=" * 70)
        for rel, _wrapped, raw in per_file:
            if not raw:
                continue
            print(f"\n{rel}")
            for s in dict.fromkeys(raw):
                print(f"    {s}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
