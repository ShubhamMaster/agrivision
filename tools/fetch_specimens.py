"""
AgriVision — one-time specimen photo fetcher.

Downloads real photographed produce specimens into  assets/specimens/<Crop>/
so that seed.py can compose realistic lot photographs **offline**.

    python tools/fetch_specimens.py            # fetch anything missing
    python tools/fetch_specimens.py --force    # re-fetch everything

Source
------
Fruits-360 (Horea Muresan et al.), a public dataset of produce photographed on
a turntable against a white background, mirrored on GitHub:

    https://github.com/Horea94/Fruit-Images-Dataset

Each class holds several hundred 100x100 JPEGs of the same specimens from
different angles, so a lot composed from them shows genuine photographic
colour, texture and blemishes rather than drawn shapes.

The images are only the *source material*: app/photo_lot.py cuts each specimen
off its white background and scatters many of them into a crate scene, which is
what the farmer and buyer actually see.

Licence: the dataset is published under CC BY-SA 4.0. It is used here for an
academic project; keep the attribution in docs/ and in this file.

Crops with no photographic match
--------------------------------
Wheat, Rice, Soybean, Cotton and Sugarcane are bulk grain/fibre crops with no
class in the dataset. They keep the procedural renderer, which suits them —
a grain heap really is a mass of thousands of near-identical units.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import ssl
import sys
import urllib.parse
import urllib.request

BASE = "https://raw.githubusercontent.com/Horea94/Fruit-Images-Dataset/master/Training"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(PROJECT_ROOT, "assets", "specimens")

# AgriVision crop  ->  [(dataset class, filename pattern, how many to take), ...]
# Several classes per crop gives natural specimen-to-specimen variation.
CROP_SOURCES = {
    "Grapes": [
        ("Grape White", "{n}_100.jpg", 26),       # green — Thompson/Sonaka
        ("Grape White 4", "{n}_100.jpg", 14),
        ("Grape Blue", "{n}_100.jpg", 10),
    ],
    "Pomegranate": [
        ("Pomegranate", "{n}_100.jpg", 42),
    ],
    "Mango": [
        ("Mango", "r_{n}_100.jpg", 28),
        ("Mango Red", "r_{n}_100.jpg", 14),
    ],
    "Banana": [
        ("Banana", "{n}_100.jpg", 30),
        ("Banana Lady Finger", "{n}_100.jpg", 12),
    ],
    "Tomato": [
        ("Tomato 1", "{n}_100.jpg", 16),
        ("Tomato 3", "{n}_100.jpg", 16),
        ("Tomato 4", "{n}_100.jpg", 12),
    ],
    "Onion": [
        ("Onion Red", "r_{n}_100.jpg", 26),
        ("Onion White", "{n}_100.jpg", 16),
    ],
    "Potato": [
        ("Potato Red", "{n}_100.jpg", 20),
        ("Potato White", "r_{n}_100.jpg", 14),
        ("Potato Red Washed", "{n}_100.jpg", 10),
    ],
    "Maize": [
        ("Corn", "{n}_100.jpg", 26),
        ("Corn Husk", "r_{n}_100.jpg", 14),
    ],
    # The dataset has no chilli class. Red capsicum is the closest available
    # produce — the same genus (Capsicum annuum) and the right colour for a
    # red-chilli lot. Green bell peppers are deliberately excluded: they read
    # as capsicum rather than chilli and would contradict the listing.
    # This substitution is noted in docs/12_photography_pipeline.md.
    "Chilli": [
        ("Pepper Red", "r_{n}_100.jpg", 40),
    ],
}

# Spread the indices so the specimens are photographed from different angles
# rather than 40 near-identical frames of one rotation.
STRIDE = 7

_ctx = ssl.create_default_context(
    cafile="/root/.ccr/ca-bundle.crt"
    if os.path.exists("/root/.ccr/ca-bundle.crt") else None
)
_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"https": _proxy} if _proxy else {}),
    urllib.request.HTTPSHandler(context=_ctx),
)


def fetch_one(url: str, dest: str) -> bool:
    try:
        with _opener.open(urllib.request.Request(url), timeout=20) as r:
            data = r.read()
        if len(data) < 500:          # an error page or an empty placeholder
            return False
        with open(dest, "wb") as fh:
            fh.write(data)
        return True
    except Exception:
        return False


def fetch_crop(crop: str, sources: list, force: bool) -> int:
    out_dir = os.path.join(OUT_ROOT, crop)
    os.makedirs(out_dir, exist_ok=True)

    if not force:
        existing = [f for f in os.listdir(out_dir) if f.endswith(".jpg")]
        if len(existing) >= 20:
            print(f"  {crop:14s} {len(existing):3d} specimens already cached")
            return len(existing)

    jobs = []
    for cls, pattern, count in sources:
        q = urllib.parse.quote(cls)
        slug = cls.lower().replace(" ", "-")
        for i in range(count):
            n = i * STRIDE
            url = f"{BASE}/{q}/{pattern.format(n=n)}"
            dest = os.path.join(out_dir, f"{slug}_{n:03d}.jpg")
            jobs.append((url, dest))

    got = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(fetch_one, u, d): d for u, d in jobs}
        for fut in concurrent.futures.as_completed(futures):
            if fut.result():
                got += 1

    print(f"  {crop:14s} {got:3d} specimens fetched")
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even if specimens are already cached")
    args = ap.parse_args()

    os.makedirs(OUT_ROOT, exist_ok=True)
    print("\nFetching real produce specimens into assets/specimens/")
    print("=" * 58)

    total = 0
    for crop, sources in CROP_SOURCES.items():
        total += fetch_crop(crop, sources, args.force)

    print("=" * 58)
    print(f"{total} specimen photographs cached in {OUT_ROOT}")
    print("These are committed with the project, so seed.py runs offline.\n")

    if total < 100:
        print("WARNING: very few specimens were fetched. Check network access.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
