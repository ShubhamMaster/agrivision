"""
AgriVision — lot photograph composer.

Turns a folder of individually photographed specimens into an image that looks
like a real lot of produce: dozens of fruits heaped in a crate or spread on a
tarpaulin, lit from one side, with depth, shadow and natural variation.

Why compose instead of using a specimen photo directly
------------------------------------------------------
A single 100x100 fruit on a white background says nothing about 85 quintal of
grapes, and it would make the computer-vision grader meaningless — one object,
no background to segment, and nothing to measure for uniformity or unit size.

Composing from many real specimens keeps every pixel photographic (real colour,
real skin texture, real blemishes) while giving the grader what it needs: many
units, a genuine background to separate, and real variation between pieces.

Visual direction
----------------
Clean studio product photography: a small natural group of produce on a white
sweep, lit from above-left, with a soft contact shadow — the way vegetables are
shot for a catalogue or a seed packet. This reads as a product listing rather
than a snapshot, and it keeps the marketplace cards calm and consistent.

Pipeline
--------
  1. CUT OUT      remove the white studio background from each specimen,
                  producing an RGBA sprite with a clean alpha edge
  2. SWEEP        a white studio backdrop with a faint floor gradient
  3. ARRANGE      stack the specimens into a natural group — a heap, a tight
                  cluster, or crossed elongated pieces, depending on the crop
  4. GRADE TIER   'good' / 'medium' / 'poor' control colour scatter, bruising
                  and size spread, so the CV grader sees a real difference
  5. CAMERA       soft key light, contact shadow, slight blur, sensor noise

The three tiers exist so the seeded marketplace shows a believable spread of
A, B and C grades rather than everything scoring the same.
"""

from __future__ import annotations

import glob
import math
import os
import random

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN_ROOT = os.path.join(PROJECT_ROOT, "assets", "specimens")

# ----------------------------------------------------------------------
# Per-crop staging: how produce of this kind is actually arranged for a shot
# ----------------------------------------------------------------------
#   count      how many pieces are in the group
#   scale      piece size as a fraction of frame width
#   layout     'heap'    — a few pieces stacked, back row then front row
#              'cluster' — many small pieces packed into a rough bunch
#              'crossed' — elongated pieces laid across each other
#   rotate     max rotation in degrees; elongated produce is kept near its
#              natural lie so it looks placed rather than thrown
STAGING = {
    "Grapes":      {"count": (34, 44), "scale": (0.085, 0.100), "layout": "cluster", "rotate": 180},
    # Red capsicum standing in for chilli: round-ish, so it heaps rather than
    # laying flat the way a long chilli would.
    "Chilli":      {"count": (6, 8),   "scale": (0.215, 0.255), "layout": "heap",    "rotate": 180},
    "Pomegranate": {"count": (4, 6),   "scale": (0.270, 0.310), "layout": "heap",    "rotate": 180},
    "Mango":       {"count": (4, 6),   "scale": (0.265, 0.305), "layout": "heap",    "rotate": 28},
    "Tomato":      {"count": (6, 8),   "scale": (0.215, 0.250), "layout": "heap",    "rotate": 180},
    "Onion":       {"count": (5, 7),   "scale": (0.235, 0.275), "layout": "heap",    "rotate": 180},
    "Potato":      {"count": (6, 8),   "scale": (0.225, 0.265), "layout": "heap",    "rotate": 180},
    "Banana":      {"count": (5, 7),   "scale": (0.330, 0.390), "layout": "crossed", "rotate": 26},
    "Maize":       {"count": (4, 6),   "scale": (0.330, 0.390), "layout": "crossed", "rotate": 24},
}

# Quality tier -> how the lot is presented and how sound the produce is.
#
# Hue jitter stays small on purpose. Produce varies far more in brightness and
# in blemishing than in hue, and shifting hue by more than a few degrees turns
# potatoes purple and tomatoes orange — which reads as a rendering bug rather
# than as a poor-quality lot. Tier separation is carried by bruising and by
# size spread instead, which is also what the CV grader actually measures.
#
#   sharpen  how much edge definition to restore. The specimens are 100 px
#            originals enlarged several times over, so they arrive soft; a
#            well-presented lot should come out crisp. A 'poor' lot is left
#            soft on purpose — a blurred photo is itself a quality signal the
#            grader is right to penalise.
TIERS = {
    "good":   {"hue_jitter": 2, "val_jitter": 12, "bruise_rate": 0.05,
               "bruise_strength": (0.20, 0.34), "bruises_per_piece": 1,
               "scale_jitter": 0.10, "blur": 1, "sharpen": 1.15},
    "medium": {"hue_jitter": 4, "val_jitter": 22, "bruise_rate": 0.30,
               "bruise_strength": (0.32, 0.50), "bruises_per_piece": 1,
               "scale_jitter": 0.22, "blur": 1, "sharpen": 0.75},
    "poor":   {"hue_jitter": 7, "val_jitter": 38, "bruise_rate": 0.85,
               "bruise_strength": (0.48, 0.72), "bruises_per_piece": 3,
               "scale_jitter": 0.40, "blur": 5, "sharpen": 0.0},
}


def has_specimens(crop_name: str) -> bool:
    """True when real photographs are cached for this crop."""
    d = os.path.join(SPECIMEN_ROOT, crop_name)
    return os.path.isdir(d) and len(glob.glob(os.path.join(d, "*.jpg"))) >= 8


def available_crops() -> list[str]:
    if not os.path.isdir(SPECIMEN_ROOT):
        return []
    return sorted(c for c in os.listdir(SPECIMEN_ROOT) if has_specimens(c))


# ======================================================================
# 1. CUT OUT — remove the white studio background
# ======================================================================
def _load_sprite(path: str) -> np.ndarray | None:
    """
    Load one specimen and return it as BGRA with the white background removed.

    The dataset photographs each item against near-white, so the subject is
    everything that is *not* bright-and-unsaturated.  The mask is then eroded
    by one pixel and feathered, which removes the pale halo that would
    otherwise ring every piece and give away the composite.
    """
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s, v = hsv[..., 1], hsv[..., 2]

    # --- find the true background, not merely "bright" pixels ------------
    # A global brightness threshold leaves a pale fringe: the antialiased ring
    # where the subject blends into white is bright but partly saturated, so it
    # survives the test and then glows against a darker surface.
    #
    # The studio background has a property the fringe does not: it is
    # connected to the border of the frame. So take a deliberately generous
    # background test, then keep only the components that touch the edge. A
    # pale pixel in the middle of a fruit is a highlight and stays; the same
    # pale pixel connected to the border is background and goes.
    loose_bg = ((v > 182) & (s < 78)).astype(np.uint8)

    n, labels = cv2.connectedComponents(loose_bg, 8)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border.discard(0)
    true_bg = np.isin(labels, list(border)) if border else np.zeros_like(loose_bg, bool)

    mask = (~true_bg).astype(np.uint8) * 255

    # Keep only the largest blob — drops stray specks of shadow or dust.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = (labels == largest).astype(np.uint8) * 255

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.erode(mask, k, iterations=1)
    if int(mask.sum()) < 255 * 300:                  # nothing meaningful left
        return None

    # Taper the alpha over the outermost ~1.5 px using the distance transform.
    # This antialiases the silhouette without reaching back out into the
    # white pixels a plain Gaussian blur would pull in.
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    alpha = np.clip(dist / 1.5, 0, 1.0)
    alpha = (alpha * 255).astype(np.uint8)

    # Crop to the subject's bounding box so scaling is about the fruit, not
    # the empty studio margin around it.
    ys, xs = np.where(mask > 0)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1

    sprite = np.dstack([img, alpha])[y0:y1, x0:x1]
    return sprite


def _variety_groups(crop_name: str) -> dict[str, list[str]]:
    """
    Group the cached specimen files by the source class they came from.

    The filenames carry it: grape-white_014.jpg, grape-blue_007.jpg. This
    matters because a real lot offered for sale is one variety — a crate of
    Thompson Seedless is not half green grapes and half black ones, and corn
    is either husked or it is not. Composing from a single group per image is
    what makes the result look like a graded lot rather than a fruit bowl.
    """
    groups: dict[str, list[str]] = {}
    for f in sorted(glob.glob(os.path.join(SPECIMEN_ROOT, crop_name, "*.jpg"))):
        key = os.path.basename(f).rsplit("_", 1)[0]
        groups.setdefault(key, []).append(f)
    return groups


def varieties(crop_name: str) -> list[str]:
    """Which source varieties are cached for this crop."""
    return sorted(_variety_groups(crop_name).keys())


def _load_sprites(crop_name: str, variety: str | None = None,
                  rng: random.Random | None = None,
                  limit: int = 40) -> list[np.ndarray]:
    rng = rng or random
    groups = _variety_groups(crop_name)
    if not groups:
        return []

    if variety and variety in groups:
        files = list(groups[variety])
    else:
        # Prefer a group with enough specimens to build a varied lot.
        usable = [g for g in groups.values() if len(g) >= 6] or list(groups.values())
        files = list(rng.choice(usable))

    files = list(files)
    rng.shuffle(files)

    out = []
    for f in files[:limit]:
        sp = _load_sprite(f)
        if sp is not None:
            out.append(sp)
    return out


# ======================================================================
# 2. SWEEP — the white studio backdrop
# ======================================================================
def _background(w: int, h: int, rng: random.Random) -> np.ndarray:
    """
    A white studio sweep: not flat #FFFFFF, which looks like a cut-out, but a
    near-white field that falls off very slightly toward the lower corners so
    the produce reads as sitting on a surface.
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = xx / w, yy / h

    # Gentle falloff: brightest a little above centre, dimmer at the base.
    field = 255.0 - 9.0 * ny ** 2 - 4.0 * (nx - 0.5) ** 2 * 2.0
    field = np.clip(field, 238, 255)

    img = np.dstack([field, field, field]).astype(np.uint8)
    noise = np.random.randint(-2, 3, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _contact_shadow(canvas: np.ndarray, cx: int, cy: int,
                    rx: int, ry: int, rng: random.Random) -> None:
    """
    One soft elliptical shadow pooled under the whole group.

    A per-piece cast shadow would look cluttered against white; studio produce
    photography shows a single soft pool where the group meets the surface.
    """
    h, w = canvas.shape[:2]
    layer = np.zeros((h, w), np.float32)
    cv2.ellipse(layer, (cx, cy), (max(4, rx), max(3, ry)), 0, 0, 360, 1.0, -1)

    blur = int(max(rx, ry) * 0.55) | 1
    layer = cv2.GaussianBlur(layer, (blur, blur), 0)
    layer = np.clip(layer * rng.uniform(0.26, 0.34), 0, 1)[..., None]

    tint = np.array([0.74, 0.76, 0.78], np.float32)      # cool grey, not black
    canvas[:] = np.clip(
        canvas.astype(np.float32) * (1 - layer) + canvas.astype(np.float32) * tint * layer,
        0, 255,
    ).astype(np.uint8)


# ======================================================================
# 3. SCATTER — place the specimens
# ======================================================================
def _rotate_scale(sprite: np.ndarray, angle: float, target_w: int) -> np.ndarray:
    h, w = sprite.shape[:2]
    scale = target_w / float(max(w, h))
    new_w, new_h = max(4, int(w * scale)), max(4, int(h * scale))
    sprite = cv2.resize(sprite, (new_w, new_h), interpolation=cv2.INTER_AREA)

    diag = int(math.hypot(new_w, new_h)) + 2
    canvas = np.zeros((diag, diag, 4), np.uint8)
    oy, ox = (diag - new_h) // 2, (diag - new_w) // 2
    canvas[oy:oy + new_h, ox:ox + new_w] = sprite

    m = cv2.getRotationMatrix2D((diag / 2, diag / 2), angle, 1.0)
    return cv2.warpAffine(canvas, m, (diag, diag), flags=cv2.INTER_LINEAR,
                          borderValue=(0, 0, 0, 0))


def _jitter_colour(sprite: np.ndarray, hue_j: int, val_j: int,
                   rng: random.Random) -> np.ndarray:
    """Shift this piece's hue and brightness so the lot is not 40 clones."""
    bgr = sprite[..., :3]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.int16)
    hsv[..., 0] = (hsv[..., 0] + rng.randint(-hue_j, hue_j)) % 180
    hsv[..., 1] = np.clip(hsv[..., 1] * rng.uniform(0.86, 1.14), 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] + rng.randint(-val_j, val_j), 0, 255)
    sprite[..., :3] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return sprite


def _add_bruise(sprite: np.ndarray, rng: random.Random,
                strength_range: tuple[float, float] = (0.30, 0.52)) -> np.ndarray:
    """
    Darken a patch of this piece — a bruise, scab or rot spot.

    Kept shallow and soft on purpose. A small, hard, very dark disc does not
    read as a blemish on the fruit; it reads as a hole punched through it, and
    at a glance the whole lot looks like a rendering fault rather than poor
    produce. Real bruising is a gradual browning, so the patch is wide, weak
    and heavily feathered, and it also desaturates rather than only darkening.
    """
    h, w = sprite.shape[:2]
    solid = sprite[..., 3] > 140
    if not solid.any():
        return sprite

    ys, xs = np.where(solid)
    i = rng.randrange(len(ys))
    cy, cx = int(ys[i]), int(xs[i])
    r = max(3, int(min(h, w) * rng.uniform(0.16, 0.28)))

    patch = np.zeros((h, w), np.uint8)
    cv2.circle(patch, (cx, cy), r, 255, -1)
    cv2.circle(patch, (cx + rng.randint(-r, r) // 2, cy + rng.randint(-r, r) // 2),
               int(r * 0.75), 255, -1)                     # irregular, not a disc

    blur = max(5, (r | 1))
    patch = cv2.GaussianBlur(patch, (blur, blur), 0)
    patch = (patch.astype(np.float32) / 255.0) * solid.astype(np.float32)
    patch = patch[..., None]

    bgr = sprite[..., :3].astype(np.float32)
    grey = bgr.mean(axis=2, keepdims=True)

    # Pull toward a desaturated brown and darken only moderately.
    strength = rng.uniform(*strength_range)
    bruised = bgr * (1 - 0.34 * strength) * 0.88 + grey * (0.34 * strength)
    sprite[..., :3] = np.clip(bgr * (1 - patch * strength) + bruised * (patch * strength),
                              0, 255).astype(np.uint8)
    return sprite


def _paste(canvas: np.ndarray, sprite: np.ndarray, cx: int, cy: int) -> None:
    """Alpha-composite a sprite centred on (cx, cy), clipped at the edges."""
    sh, sw = sprite.shape[:2]
    H, W = canvas.shape[:2]
    x0, y0 = cx - sw // 2, cy - sh // 2
    x1, y1 = x0 + sw, y0 + sh

    sx0, sy0 = max(0, -x0), max(0, -y0)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return

    piece = sprite[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
    alpha = (piece[..., 3:4].astype(np.float32) / 255.0)
    region = canvas[y0:y1, x0:x1].astype(np.float32)
    canvas[y0:y1, x0:x1] = (piece[..., :3] * alpha + region * (1 - alpha)).astype(np.uint8)


# ======================================================================
# ARRANGEMENT — where each piece sits
# ======================================================================
def _layout_heap(n, W, H, piece, rng):
    """
    A few pieces stacked: a back row sitting higher and slightly smaller for
    depth, a front row lower and full size, overlapping it. This is how loose
    produce is piled for a catalogue shot.
    """
    front_n = max(2, int(round(n * 0.6)))
    back_n = max(1, n - front_n)

    cx, base_y = W // 2, int(H * 0.60)
    out = []

    # Rows are spaced at well under one piece width so neighbours actually
    # touch and occlude. Spacing them a full width apart leaves slivers of
    # white between the pieces and the group stops reading as a pile.
    span = piece * 0.66
    start = cx - (back_n - 1) * span / 2
    for i in range(back_n):                              # back row first
        out.append((
            int(start + i * span + rng.uniform(-0.05, 0.05) * piece),
            int(base_y - piece * rng.uniform(0.26, 0.36)),
            rng.uniform(0.86, 0.94),
        ))

    span = piece * 0.70
    start = cx - (front_n - 1) * span / 2
    for i in range(front_n):
        out.append((
            int(start + i * span + rng.uniform(-0.05, 0.05) * piece),
            int(base_y + piece * rng.uniform(0.06, 0.14)),
            rng.uniform(0.97, 1.05),
        ))
    return out


def _layout_cluster(n, W, H, piece, rng):
    """
    Many small pieces packed into a bunch — grapes off the stem.

    The radius is derived from the piece count and size rather than being a
    fixed fraction of the frame: the berries have to actually touch, or the
    group reads as spilled rather than as a bunch. Solving
    pi*rx*ry ~= n * piece^2 * packing gives that directly.
    """
    packing = 0.20                     # <1 because the pieces overlap heavily
    r = math.sqrt(n * piece * piece * packing / math.pi)
    rx, ry = r * 1.18, r * 0.86        # a bunch is wider than it is tall

    cx, cy = W // 2, int(H * 0.50)
    out = []
    for _ in range(n):
        # sqrt keeps the fill even instead of bunching at the centre
        a, rr = rng.uniform(0, 2 * math.pi), math.sqrt(rng.random())
        out.append((int(cx + math.cos(a) * rx * rr),
                    int(cy + math.sin(a) * ry * rr),
                    rng.uniform(0.90, 1.06)))
    out.sort(key=lambda p: p[1])
    return out


def _layout_crossed(n, W, H, piece, rng):
    """
    Elongated produce — bananas, corn cobs — laid across each other in a
    shallow fan.

    Spread is mostly horizontal with only a little vertical stagger: piling
    long items up the frame makes them look stood on end, whereas produce laid
    out for a shot rests flat and overlaps sideways.
    """
    cx, cy = W // 2, int(H * 0.52)
    spread = min(W * 0.26, piece * 0.46 * max(1, n - 1))

    out = []
    for i in range(n):
        t = (i / max(1, n - 1)) - 0.5                    # -0.5 … +0.5
        out.append((int(cx + t * 2 * spread + rng.uniform(-0.02, 0.02) * W),
                    int(cy + t * H * 0.07 + rng.uniform(-0.035, 0.035) * H),
                    rng.uniform(0.94, 1.04)))
    out.sort(key=lambda p: p[1])
    return out


LAYOUTS = {"heap": _layout_heap, "cluster": _layout_cluster, "crossed": _layout_crossed}


def _fit_to_frame(positions, piece_px, W, H, margin=0.07):
    """
    Shrink and recentre the arrangement so no piece is clipped by the frame.

    Without this a wide heap runs off the edge and the card shows half a
    tomato at the border, which looks like a cropping bug rather than a photo.
    The group is scaled about its own centre, so its internal spacing — and so
    the overlap that makes it read as a pile — is preserved.
    """
    half = piece_px * 0.60                      # worst-case half-extent
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)

    left, right = min(xs) - half, max(xs) + half
    top, bottom = min(ys) - half, max(ys) + half

    avail_w, avail_h = W * (1 - 2 * margin), H * (1 - 2 * margin)
    k = min(1.0,
            avail_w / max(1.0, right - left),
            avail_h / max(1.0, bottom - top))

    scaled = [(cx + (x - cx) * k, cy + (y - cy) * k, s) for x, y, s in positions]

    # Recentre what is left, biasing slightly above centre so the contact
    # shadow has room underneath.
    xs = [p[0] for p in scaled]
    ys = [p[1] for p in scaled]
    dx = W / 2 - (min(xs) + max(xs)) / 2
    dy = H * 0.47 - (min(ys) + max(ys)) / 2

    return [(int(x + dx), int(y + dy), s) for x, y, s in scaled], piece_px * k


# ======================================================================
# PUBLIC API
# ======================================================================
def compose_lot(crop_name: str, out_path: str, quality: str = "good",
                size: tuple[int, int] = (900, 650), seed: int | None = None,
                variety: str | None = None) -> str | None:
    """
    Build one lot photograph. Returns the path, or None when no specimens are
    cached for this crop (the caller then falls back to procedural rendering).

    `variety` pins the source group (e.g. "grape-white") so every photo of one
    listing shows the same produce; pass None to let it pick one.
    """
    if not has_specimens(crop_name):
        return None

    rng = random.Random(seed)
    if seed is not None:
        np.random.seed(seed % (2 ** 31))

    tier = TIERS.get(quality, TIERS["medium"])
    stage = STAGING.get(crop_name, {"count": (5, 7), "scale": (0.230, 0.270),
                                    "layout": "heap", "rotate": 180})

    sprites = _load_sprites(crop_name, variety=variety, rng=rng)
    if not sprites:
        return None

    W, H = size
    canvas = _background(W, H, rng)

    n = rng.randint(*stage["count"])
    base_scale = rng.uniform(*stage["scale"])
    piece_px = W * base_scale

    layout = LAYOUTS.get(stage.get("layout", "heap"), _layout_heap)
    positions = layout(n, W, H, piece_px, rng)
    positions, piece_px = _fit_to_frame(positions, piece_px, W, H)

    # One soft shadow pooled under the whole arrangement, sized from the
    # spread of the pieces rather than from the frame.
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    _contact_shadow(
        canvas,
        cx=int(sum(xs) / len(xs)),
        cy=int(max(ys) + piece_px * 0.34),
        rx=int((max(xs) - min(xs)) / 2 + piece_px * 0.52),
        ry=int(piece_px * 0.20),
        rng=rng,
    )

    rot = stage.get("rotate", 180)
    for px, py, smul in positions:
        sprite = sprites[rng.randrange(len(sprites))].copy()

        target = int(piece_px * smul
                     * rng.uniform(1 - tier["scale_jitter"], 1 + tier["scale_jitter"]))
        sprite = _rotate_scale(sprite, rng.uniform(-rot, rot), max(8, target))
        sprite = _jitter_colour(sprite, tier["hue_jitter"], tier["val_jitter"], rng)
        if rng.random() < tier["bruise_rate"]:
            for _ in range(tier.get("bruises_per_piece", 1)):
                sprite = _add_bruise(sprite, rng,
                                     tier.get("bruise_strength", (0.30, 0.52)))

        _paste(canvas, sprite, px, py)

    canvas = _camera(canvas, tier, rng)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out_path


# ======================================================================
# BULK CROPS — wheat, rice, soybean, cotton, sugarcane
# ======================================================================
# These have no photographic source in the specimen dataset, so they are
# rendered. They are rendered to match the photographed crops — the same white
# sweep, the same contact shadow, the same framing — because a marketplace
# where four of fourteen cards look like a different product is worse than one
# where every card is merely consistent.
#
# A grain lot really is a heap of thousands of near-identical units, which is
# why rendering suits it: the shape being drawn is the shape the crop has.
#
#   form    'heap'   a mound of small grains
#           'bolls'  cotton — clusters of soft white fibre
#           'stalks' sugarcane — long canes laid across each other
BULK = {
    "Wheat":     {"form": "heap", "grains": 2600, "grain": (9, 5),
                  "colour": (105, 168, 206), "spread": 14},
    "Rice":      {"form": "heap", "grains": 3000, "grain": (10, 4),
                  "colour": (214, 226, 236), "spread": 9},
    "Soybean":   {"form": "heap", "grains": 1500, "grain": (11, 10),
                  "colour": (122, 176, 208), "spread": 13},
    "Cotton":    {"form": "bolls", "count": (5, 7)},
    "Sugarcane": {"form": "stalks", "count": (5, 7)},
}


def is_bulk(crop_name: str) -> bool:
    return crop_name in BULK


def _shade(colour, factor):
    return tuple(int(max(0, min(255, c * factor))) for c in colour)


def _render_heap(canvas, spec, tier, rng):
    """A mound of grain: thousands of small ellipses inside a dome."""
    H, W = canvas.shape[:2]
    cx, cy = W // 2, int(H * 0.60)
    rx, ry = int(W * 0.30), int(H * 0.20)

    gw, gh = spec["grain"]
    base = spec["colour"]
    spread = spec["spread"] + tier["val_jitter"] // 3

    for _ in range(spec["grains"]):
        a, r = rng.uniform(0, 2 * math.pi), math.sqrt(rng.random())
        gx = cx + math.cos(a) * rx * r
        # Dome profile: the heap is tallest in the middle, so the vertical
        # extent shrinks toward the edges.
        dome = math.sqrt(max(0.0, 1 - (math.cos(a) * r) ** 2))
        gy = cy + math.sin(a) * ry * r * dome - dome * ry * 0.55

        # Light from above-left, and grains deeper in the heap sit in shadow.
        lit = 1.08 - 0.30 * ((gy - (cy - ry)) / max(1.0, 2.0 * ry))
        lit += 0.06 * (1 - r)
        colour = _shade(base, lit * rng.uniform(1 - spread / 255, 1 + spread / 255))

        cv2.ellipse(canvas, (int(gx), int(gy)),
                    (max(1, int(gw * rng.uniform(0.8, 1.2) / 2)),
                     max(1, int(gh * rng.uniform(0.8, 1.2) / 2))),
                    rng.uniform(0, 180), 0, 360, colour, -1, cv2.LINE_AA)

    return cx, cy + int(ry * 0.55), int(rx * 1.05), int(ry * 0.26)


def _render_bolls(canvas, spec, tier, rng):
    """Cotton: soft white fibre bolls with a hint of the dried husk."""
    H, W = canvas.shape[:2]
    n = rng.randint(*spec["count"])
    cx, cy = W // 2, int(H * 0.54)
    piece = int(W * 0.17)
    span = piece * 0.78
    start = cx - (n - 1) * span / 2

    for i in range(n):
        bx = int(start + i * span + rng.uniform(-0.08, 0.08) * piece)
        by = int(cy + rng.uniform(-0.10, 0.10) * H)

        # Dried husk, kept tight behind the boll and close in tone to the
        # fibre. Drawn large and dark it reads as scattered debris rather than
        # as the burr the cotton is sitting in.
        for k in range(5):
            ang = k * 72 + rng.uniform(-14, 14)
            hx = bx + int(math.cos(math.radians(ang)) * piece * 0.30)
            hy = by + int(math.sin(math.radians(ang)) * piece * 0.30)
            cv2.ellipse(canvas, (hx, hy), (int(piece * 0.19), int(piece * 0.09)),
                        ang, 0, 360, _shade((142, 158, 176), rng.uniform(0.92, 1.06)),
                        -1, cv2.LINE_AA)

        # Fibre: overlapping lobes, shaded so the boll has volume. The lobes
        # nearer the lower right sit in shadow; a few bright ones on the upper
        # left catch the key light.
        #
        # The shading range here has to be wide. Cotton is white produce on a
        # white sweep, so with only a few percent of tonal variation the boll
        # dissolves into the background and the card looks empty.
        for _ in range(rng.randint(22, 30)):
            dx, dy = rng.gauss(0, piece * 0.18), rng.gauss(0, piece * 0.16)
            ox, oy = bx + int(dx), by + int(dy)
            rr = int(piece * rng.uniform(0.14, 0.26))

            depth = (dx + dy) / (piece * 0.5)             # -1 (lit) … +1 (shadow)
            tone = 1.0 - 0.14 * max(-1.0, min(1.0, depth))
            cv2.circle(canvas, (ox, oy), rr,
                       _shade((238, 241, 245), tone * rng.uniform(0.98, 1.0)),
                       -1, cv2.LINE_AA)

    # Soften the region the bolls occupy. Drawn as hard-edged discs they read
    # as overlapping grey bubbles; cotton is fibre, and blurring the lobes
    # together is what turns a pile of circles into something fluffy.
    H_, W_ = canvas.shape[:2]
    x0 = max(0, int(start - piece))
    x1 = min(W_, int(start + (n - 1) * span + piece * 1.6))
    y0 = max(0, int(cy - piece * 1.1))
    y1 = min(H_, int(cy + piece * 1.1))
    if x1 - x0 > 8 and y1 - y0 > 8:
        canvas[y0:y1, x0:x1] = cv2.GaussianBlur(canvas[y0:y1, x0:x1], (0, 0), piece * 0.045)

    return cx, cy + int(piece * 0.50), int(span * n * 0.55), int(piece * 0.16)


def _render_stalks(canvas, spec, tier, rng):
    """Sugarcane: long canes laid across each other."""
    H, W = canvas.shape[:2]
    n = rng.randint(*spec["count"])
    cx, cy = W // 2, int(H * 0.52)
    length, thick = int(W * 0.72), int(H * 0.055)

    # Cane is not the saturated green of a leaf — it is a dull olive-tan, often
    # with a purple cast. Each stalk gets its own tone so the group does not
    # read as a flat vector illustration.
    TONES = [(86, 118, 96), (104, 132, 112), (78, 104, 92), (96, 124, 120)]

    for i in range(n):
        t = (i / max(1, n - 1)) - 0.5
        sx = int(cx + t * W * 0.10 + rng.uniform(-0.025, 0.025) * W)
        sy = int(cy + t * H * 0.30 + rng.uniform(-0.02, 0.02) * H)
        ang = rng.uniform(-13, 13)
        ln = int(length * rng.uniform(0.88, 1.0))

        base = _shade(rng.choice(TONES), rng.uniform(0.92, 1.08))
        box = cv2.boxPoints(((sx, sy), (ln, thick), ang)).astype(np.int32)
        cv2.fillConvexPoly(canvas, box, base, cv2.LINE_AA)

        # Nodes: narrow bands, only slightly darker. High contrast here is what
        # made the earlier version look striped rather than grown.
        for k in range(-4, 5):
            nx = sx + int(math.cos(math.radians(ang)) * k * ln * 0.11)
            ny = sy + int(math.sin(math.radians(ang)) * k * ln * 0.11)
            nb = cv2.boxPoints(((nx, ny), (max(2, thick // 4), thick), ang)).astype(np.int32)
            cv2.fillConvexPoly(canvas, nb, _shade(base, 0.90), cv2.LINE_AA)

        # Rounded shading across the cane: a highlight along the top and a
        # shadow along the bottom give it a cylinder's cross-section.
        hl = cv2.boxPoints(((sx - math.sin(math.radians(ang)) * thick * 0.24,
                             sy - math.cos(math.radians(ang)) * thick * 0.24),
                            (ln * 0.98, thick * 0.30), ang)).astype(np.int32)
        cv2.fillConvexPoly(canvas, hl, _shade(base, 1.16), cv2.LINE_AA)

        sh = cv2.boxPoints(((sx + math.sin(math.radians(ang)) * thick * 0.34,
                             sy + math.cos(math.radians(ang)) * thick * 0.34),
                            (ln * 0.98, thick * 0.22), ang)).astype(np.int32)
        cv2.fillConvexPoly(canvas, sh, _shade(base, 0.84), cv2.LINE_AA)

    return cx, cy + int(H * 0.20), int(length * 0.52), int(thick * 0.9)


BULK_RENDERERS = {"heap": _render_heap, "bolls": _render_bolls, "stalks": _render_stalks}


def compose_bulk_lot(crop_name: str, out_path: str, quality: str = "good",
                     size: tuple[int, int] = (900, 650),
                     seed: int | None = None) -> str | None:
    """Render a bulk crop in the same studio style as the photographed ones."""
    spec = BULK.get(crop_name)
    if not spec:
        return None

    rng = random.Random(seed)
    if seed is not None:
        np.random.seed(seed % (2 ** 31))

    tier = TIERS.get(quality, TIERS["medium"])
    W, H = size
    canvas = _background(W, H, rng)

    renderer = BULK_RENDERERS[spec["form"]]
    sx, sy, srx, sry = renderer(canvas, spec, tier, rng)
    _contact_shadow(canvas, sx, sy, srx, sry, rng)

    # Re-draw over the shadow so the produce sits on top of it, not under.
    renderer(canvas, spec, tier, rng)

    canvas = _camera(canvas, tier, rng)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out_path


def make_lot_photo(crop_name: str, out_path: str, quality: str = "good",
                   seed: int | None = None, variety: str | None = None,
                   size: tuple[int, int] = (900, 650)) -> str:
    """
    The single entry point the seed uses.

    Photographed specimens where they exist, a matching studio render for the
    bulk crops that have none.
    """
    made = compose_lot(crop_name, out_path, quality, size, seed, variety)
    if made:
        return made
    made = compose_bulk_lot(crop_name, out_path, quality, size, seed)
    if made:
        return made

    # Last resort for a crop that is neither photographed nor in BULK.
    rng = random.Random(seed)
    canvas = _background(size[0], size[1], rng)
    cv2.imwrite(out_path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out_path


def _camera(img: np.ndarray, tier: dict, rng: random.Random) -> np.ndarray:
    """
    The 'photographed' pass: a soft key light from above-left, slight
    softening, and a little sensor noise.

    Deliberately gentle. A studio sweep has no vignette and almost no falloff —
    the heavy gradient that suits a field snapshot would make the white
    backdrop look dirty and immediately give the composite away.
    """
    h, w = img.shape[:2]

    gx = np.linspace(rng.uniform(1.010, 1.022), rng.uniform(0.982, 0.994), w)
    gy = np.linspace(rng.uniform(1.008, 1.018), rng.uniform(0.984, 0.995), h)
    light = np.outer(gy, gx)[..., None]
    img = np.clip(img.astype(np.float32) * light, 0, 255).astype(np.uint8)

    k = tier.get("blur", 1)
    if k > 1:
        img = cv2.GaussianBlur(img, (k, k), 0)

    # Unsharp mask: restore the edge definition lost when 100 px specimens are
    # enlarged into the frame. Without it even a well-presented lot reads as
    # soft, and the grader's blur check correctly — but unhelpfully — caps the
    # score of every photo the composer produces.
    amount = tier.get("sharpen", 0.0)
    if amount > 0:
        blurred = cv2.GaussianBlur(img, (0, 0), 2.0)
        img = cv2.addWeighted(img, 1 + amount, blurred, -amount, 0)

    noise = np.random.randint(-3, 4, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
