"""
AgriVision — calibration check for the grading hue bands.

    python tools/check_hue_bands.py

Measures the actual hue distribution of each crop's cached specimen photographs
and reports how much of it falls inside the `hue_bands` declared for that crop
in CROP_CATALOGUE (app/ai/pricing.py).

Why this exists
---------------
The hue bands drive 34% of the quality score. They were first written against
drawn stand-ins and several were simply wrong for real produce — maize kernels
measure around hue 45, but the original band stopped at 40, so genuine corn
scored 22% in-band and was marked down for being the correct colour.

Run this after adding a crop or re-fetching specimens. A crop sitting below
about 70% in-band is miscalibrated, not poor-quality produce.

Note the scale: OpenCV packs hue into 0-179, not 0-359, so halve any hue value
quoted from a colour picker before putting it in a band.
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai.grading import _segment_produce          # noqa: E402
from app.ai.pricing import crop_info                 # noqa: E402
from app.photo_lot import available_crops, _variety_groups   # noqa: E402

GOOD, WARN = 70.0, 50.0


def main():
    crops = available_crops()
    if not crops:
        print("No cached specimens. Run: python tools/fetch_specimens.py")
        return 1

    print("\nHue band calibration against real specimen photographs")
    print("=" * 76)
    print(f"{'crop':13s} {'p5':>4s} {'med':>4s} {'p95':>4s}  {'in-band':>8s}  declared bands")
    print("-" * 76)

    problems = []
    for crop in crops:
        hues = []
        for files in _variety_groups(crop).values():
            for f in files[:10]:
                img = cv2.imread(f)
                if img is None:
                    continue
                hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
                mask, _ = _segment_produce(hsv, crop)
                sel = mask > 0
                if sel.sum() > 200:
                    hues.append(hsv[..., 0][sel].astype(float))
        if not hues:
            continue

        h = np.concatenate(hues)
        bands = crop_info(crop)["hue_bands"]
        inside = np.zeros(h.shape, bool)
        for lo, hi in bands:
            inside |= (h >= lo) & (h <= hi)
        pct = float(inside.mean()) * 100

        flag = " " if pct >= GOOD else ("!" if pct >= WARN else "X")
        print(f"{crop:13s} {np.percentile(h, 5):4.0f} {np.median(h):4.0f} "
              f"{np.percentile(h, 95):4.0f}  {pct:6.0f}% {flag}  {bands}")
        if pct < GOOD:
            problems.append((crop, pct))

    print("=" * 76)
    if problems:
        print("Miscalibrated (widen hue_bands in app/ai/pricing.py):")
        for crop, pct in problems:
            print(f"  {crop}: only {pct:.0f}% of real pixels fall inside the band")
    else:
        print("All crops are well inside their declared bands.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
