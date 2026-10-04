#!/usr/bin/env python3
"""pntexnat.py - natural, atlas-safe pop'n IMAGE.DAT text editor (redesign).

The first texture editor (pntexedit.py) erased a loose rectangle to a flat/gradient
fill and drew text on top. On real PS2 hardware that read as "a colored box with
text", and worse, a box that reached past the owning UI element overwrote pixels a
SHARED atlas draws elsewhere (the AUTOLOAD dialog box clipped the title/lobby cat
sprite). This editor fixes both:

  * NATURAL: only the Japanese glyph pixels are removed (a threshold mask of the
    white fill + dark outline), and the real panel background behind them is
    rebuilt by inpainting (OpenCV Telea if present, else a numpy diffusion fill).
    Backgrounds that are a flat colour (text floating on black/transparent) are
    just refilled with that colour. English is then drawn in the game's own
    white-fill + dark-outline bold style. No rectangle, no gradient box.
  * ATLAS-SAFE: every edit carries a `clip` rect = the owning element's own
    bounds; nothing is ever written outside it, and edit_texture() asserts that
    the finished image differs from the source ONLY inside the union of clips.
    So a sprite sharing the 512x512 sheet can never be touched.

An edit is a dict:
  {"clip": (x0,y0,x1,y1),              # the element's own bounds (hard limit)
   "lines": ["English line", ...],     # text to draw, one per line
   "ty0": <top y of first line>, "lh": <line height>, "fs": <max font px>,
   "bg": "inpaint" | "black" | <int gray>,   # how to rebuild behind the JP text
                                       # (also "outlined", "rows", "key", "flat", and
                                       # "copy" + "src": (dx, dy): clip <- twin region)
   "wht": 180, "drk": 80, "dil": 2,    # glyph-mask thresholds / dilation
   "align": "c"|"l", "fill": 250, "outline": 28, "sw": 2}   # fill/outline: grey or (r,g,b)

Only `clip` is required; a text-less edit (no "lines") just erases. See
edit_texture(). Depends on pnimage.py (same dir), Pillow and numpy; OpenCV is
used when importable but is optional.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pnimage import decompress, unswizzle8, swizzle8, compress
from PIL import Image, ImageDraw, ImageFont
import numpy as np

try:
    import cv2
    _HAVE_CV2 = True
except Exception:
    _HAVE_CV2 = False

W = 512


def _default_font():
    env = os.environ.get("POPN_TEX_FONT")
    if env and os.path.isfile(env):
        return env
    d = os.path.dirname(os.path.abspath(__file__))
    for name in ("ComicNeue-Bold.ttf", "DejaVuSans-Bold.ttf", "comicbd.ttf"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return "ComicNeue-Bold.ttf"


FONT = _default_font()


def _dilate(mask, it):
    # binary dilation with a 3x3 cross, numpy-only (keeps cv2 optional)
    m = mask.astype(bool)
    for _ in range(it):
        d = m.copy()
        d[1:, :] |= m[:-1, :]; d[:-1, :] |= m[1:, :]
        d[:, 1:] |= m[:, :-1]; d[:, :-1] |= m[:, 1:]
        m = d
    return m


def _diffuse(ch, mask):
    """numpy Jacobi diffusion for one channel: masked pixel <- mean of neighbours."""
    out = ch.astype(np.float32)
    known = ~mask.astype(bool)
    out[~known] = out[known].mean() if known.any() else 128.0
    for _ in range(220):
        up = np.roll(out, 1, 0); dn = np.roll(out, -1, 0)
        lf = np.roll(out, 1, 1); rt = np.roll(out, -1, 1)
        out = np.where(known, out, (up + dn + lf + rt) * 0.25)
    return np.clip(out, 0, 255).astype(np.uint8)


def _inpaint(img, mask):
    """Rebuild masked pixels of an RGB image from their surroundings. OpenCV Telea
    when available, otherwise a per-channel numpy diffusion. Only masked pixels
    change."""
    if _HAVE_CV2:
        return cv2.inpaint(img, (mask * 255).astype(np.uint8), 4, cv2.INPAINT_TELEA)
    return np.stack([_diffuse(img[:, :, c], mask) for c in range(3)], axis=2)


def _lum(img):
    """Luminance of an RGB image (the glyph detector works on this, not on one
    channel: the textures' palettes are full colour, not a grey ramp)."""
    f = img.astype(np.float32)
    return np.clip(0.299 * f[:, :, 0] + 0.587 * f[:, :, 1] + 0.114 * f[:, :, 2],
                   0, 255).astype(np.uint8)


def _glyph_mask(G, clip, wht, drk, dil, hat=40, kk=9):
    """Mark the Japanese glyph pixels inside the clip. With OpenCV we use a
    morphological top-hat (bright text on a darker panel) + black-hat (dark text
    on a lighter panel), which finds the text whatever the local background level
    is - including text floating on black - without ever flagging the background
    itself. Without OpenCV we fall back to fixed white/dark thresholds."""
    x0, y0, x1, y1 = clip
    sub = G[y0:y1, x0:x1]
    if _HAVE_CV2 and hat:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk))
        th = cv2.morphologyEx(sub, cv2.MORPH_TOPHAT, k)
        bh = cv2.morphologyEx(sub, cv2.MORPH_BLACKHAT, k)
        m = (th > hat) | (bh > hat)
    else:
        m = (sub > wht) | (sub < drk)
    full = np.zeros((W, W), bool)
    full[y0:y1, x0:x1] = m
    full = _dilate(full, dil)
    keep = np.zeros((W, W), bool); keep[y0:y1, x0:x1] = True
    return full & keep


def _rgb(c):
    """A text colour: a grey level (int) or an (r, g, b) tuple."""
    return tuple(int(v) for v in c) if isinstance(c, (tuple, list)) else (int(c),) * 3


def _text(dr, xy, tx, f, fill, sw, outline, bold=0):
    """dr.text, plus optional faux bold: the line is drawn `bold` more times, each 1 px
    further right (outlines first, then all fills), so strokes get `bold` px thicker
    and the outline stays around the union. bold=0 is exactly dr.text."""
    if not bold:
        dr.text(xy, tx, font=f, fill=fill, stroke_width=sw, stroke_fill=outline)
        return
    x, y = xy
    for k in range(bold + 1):
        dr.text((x + k, y), tx, font=f, fill=outline, stroke_width=sw, stroke_fill=outline)
    for k in range(bold + 1):
        dr.text((x + k, y), tx, font=f, fill=fill)


def _draw_lines(G, e):
    """Draw the English lines onto an RGB image, confined to the clip."""
    clip = e["clip"]; x0, y0, x1, y1 = clip
    lines = e.get("lines") or []
    if not lines:
        return G
    align = e.get("align", "c"); fill = e.get("fill", 250)
    outline = e.get("outline", 28); sw = e.get("sw", 2)
    ty0 = e["ty0"]; lh = e.get("lh", 22); fs0 = e.get("fs", 14)
    img = Image.fromarray(G, "RGB"); dr = ImageDraw.Draw(img)
    if not e.get("aa", e.get("bg") != "key"):
        # aliased glyphs (no edge blending): for text over a TRANSPARENT entry, where
        # an antialiased edge would blend with its black RGB and map to a dark halo.
        # Default for bg="key": the key colour is hidden at draw time but edge blends
        # toward it are opaque (live test: a muddy brown fringe on the room HELP line)
        dr.fontmode = "1"
    margin = e.get("margin", 8)
    bold = e.get("bold", 0)          # optional faux bold (px), see _text
    for i, tx in enumerate(lines):
        fs = fs0; f = ImageFont.truetype(FONT, fs)
        bb = dr.textbbox((0, 0), tx, font=f, stroke_width=sw); w = bb[2] - bb[0] + bold
        avail = x1 - x0 - margin
        if e.get("squeeze") and w > avail:
            # keep the full height and compress the line horizontally to fit, the
            # way game UIs fit long words in narrow plates (a smaller font would
            # shrink the height too and look weak next to the original glyphs)
            hgt = bb[3] - bb[1]
            layer = Image.new("RGBA", (w + 2, hgt + 2), (0, 0, 0, 0))
            _text(ImageDraw.Draw(layer), (1 - bb[0], 1 - bb[1]), tx, f, _rgb(fill) + (255,),
                  sw, _rgb(outline) + (255,), bold)
            layer = layer.resize((avail, hgt + 2), Image.LANCZOS)
            px = (x0 + x1) // 2 - avail // 2 if align == "c" else x0
            img.paste(layer, (px, ty0 + i * lh + bb[1] - 1), layer)
            continue
        while w > avail and fs > 8:
            fs -= 1; f = ImageFont.truetype(FONT, fs)
            bb = dr.textbbox((0, 0), tx, font=f, stroke_width=sw); w = bb[2] - bb[0] + bold
        px = ((x0 + x1) // 2 - w // 2 - bb[0]) if align == "c" else (x0 - bb[0])
        _text(dr, (px, ty0 + i * lh), tx, f, _rgb(fill), sw, _rgb(outline), bold)
    arr = np.array(img)
    out = G.copy(); out[y0:y1, x0:x1] = arr[y0:y1, x0:x1]
    return out


def _patch_fill(G, force, idx, pal, e):
    """bg="patch": exemplar / block-match fill for text on a NON-periodic panel art
    (bubbles, bands, a 2-px dither), where inpaint smooths and a row copy streaks.

    The glyph mask is built for the whole `region` (the panel's sprite rect) from the
    ORIGINAL texture: cream fill (min channel > wht) grown `dil` px, plus optional
    `twins` masks (see below). The masked pixels inside the clip are cut into
    `chunk` x `chunk` tiles, filled outside-in. For each tile, every offset (dx, dy)
    with both even (keeps the dither phase) whose shifted bbox + `ring` px lies
    entirely on clean region pixels is scored: mean RGB SSD on the tile's known ring
    (clean pixels and tiles already filled) + `lam` * |dy|. The best source's ORIGINAL
    palette indices are copied into the tile's masked pixels (forced, so indices stay
    original). Tiles with no valid source fall back to a local inpaint."""
    rx0, ry0, rx1, ry1 = e["region"]
    x0, y0, x1, y1 = e["clip"]
    wht, dil = e.get("wht", 215), e.get("dil", 3)
    ring, chunk, lam = e.get("ring", 3), e.get("chunk", 10), e.get("lam", 4.0)
    maxdy = e.get("maxdy", 64)
    orig = pal[idx][:, :, :3].astype(np.int32)
    inreg = np.zeros((W, W), bool); inreg[ry0:ry1, rx0:rx1] = True
    cream = (orig.min(axis=2) > wht) & inreg
    gmask = np.zeros((W, W), bool)
    # extra glyph masks borrowed from TWIN sprites (e.g. a highlighted copy of the label
    # elsewhere on the sheet, whose bold white fill + dark outline is a crisp superset
    # of the soft label's glyph): each {"src": rect, "to": (x, y), "wht", "drk", "dil"}
    oL = (0.299 * orig[:, :, 0] + 0.587 * orig[:, :, 1] + 0.114 * orig[:, :, 2])
    # A twin on ANOTHER sheet is given as "bits" instead: rows of "#"/"." (its mask
    # precomputed from that sheet).
    for t in e.get("twins", ()):
        tx, ty = t["to"]
        if "bits" in t:
            sub = np.array([[c == "#" for c in r] for r in t["bits"]], bool)
        else:
            sx0, sy0, sx1, sy1 = t["src"]
            sub = (orig[sy0:sy1, sx0:sx1].min(axis=2) > t.get("wht", 200)) |                 (oL[sy0:sy1, sx0:sx1] < t.get("drk", 120))
        m = np.zeros((W, W), bool); m[ty:ty + sub.shape[0], tx:tx + sub.shape[1]] = sub
        gmask |= _dilate(m, t.get("dil", 1)) & inreg
    if e.get("twins") and e.get("cream_near_twins", True):
        # cream only counts as glyph near a twin mask: a pale part of the panel itself
        # (e.g. its near-white bottom) stays a valid, clean source
        cream &= _dilate(gmask, dil + 2)
    gmask |= _dilate(cream, dil) & inreg
    clean = inreg & ~gmask
    # summed-area table of NOT-clean, to test a rect for cleanliness in O(1)
    bad = np.pad((~clean).astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def rect_clean(ax0, ay0, ax1, ay1):
        if ax0 < 0 or ay0 < 0 or ax1 > W or ay1 > W:
            return False
        return bad[ay1, ax1] - bad[ay0, ax1] - bad[ay1, ax0] + bad[ay0, ax0] == 0

    inclip = np.zeros((W, W), bool); inclip[y0:y1, x0:x1] = True
    tgt = gmask & inclip
    if not tgt.any():
        return G
    G = G.copy()
    cur = G.astype(np.int32)
    known = clean | ~inreg                       # ring pixels we may compare against
    known &= ~tgt
    # tiles of `chunk` x `chunk` over the masked pixels, filled outside-in (onion
    # peel: tiles nearest the clean surroundings first), each compared on its known
    # ring, which includes tiles filled before it, so the fill propagates coherently
    ys_all, xs_all = np.nonzero(tgt)
    tiles = {}
    for yy, xx in zip(ys_all, xs_all):
        tiles.setdefault(((yy - y0) // chunk, (xx - x0) // chunk), []).append((yy, xx))
    if _HAVE_CV2:
        dist = cv2.distanceTransform(tgt.astype(np.uint8), cv2.DIST_L2, 3)
    else:
        dist = np.zeros((W, W), np.float32)
    order = sorted(tiles.values(), key=lambda pts: min(dist[p] for p in pts))
    left = np.zeros((W, W), bool)
    for pts in order:
        ys = np.array([p[0] for p in pts]); xs = np.array([p[1] for p in pts])
        bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        ox0, oy0, ox1, oy1 = bx0 - ring, by0 - ring, bx1 + ring, by1 + ring
        if ox0 < 0 or oy0 < 0 or ox1 > W or oy1 > W:
            left[ys, xs] = True; continue
        win = np.zeros((oy1 - oy0, ox1 - ox0), bool)
        win[ys - oy0, xs - ox0] = True
        ringm = ~win & known[oy0:oy1, ox0:ox1]
        if not ringm.any():
            left[ys, xs] = True; continue
        tref = cur[oy0:oy1, ox0:ox1][ringm]
        best = None
        for dy in range(-maxdy, maxdy + 1, 2):
            if oy0 + dy < ry0 or oy1 + dy > ry1:
                continue
            for dx in range(rx0 - ox0 + ((ox0 - rx0) % 2), rx1 - ox1 + 1, 2):
                if (dx == 0 and dy == 0) or                         not rect_clean(ox0 + dx, oy0 + dy, ox1 + dx, oy1 + dy):
                    continue
                sv = orig[oy0 + dy:oy1 + dy, ox0 + dx:ox1 + dx][ringm]
                score = ((sv - tref) ** 2).sum(axis=1).mean() + lam * abs(dy)
                if best is None or score < best[0]:
                    best = (score, dx, dy)
        if best is None:
            left[ys, xs] = True; continue
        _, dx, dy = best
        src = idx[ys + dy, xs + dx]
        force[ys, xs] = src
        G[ys, xs] = pal[src, :3]
        cur[ys, xs] = pal[src, :3]
        known[ys, xs] = True
    if left.any():
        G[y0:y1, x0:x1] = _inpaint(np.ascontiguousarray(G[y0:y1, x0:x1]), left[y0:y1, x0:x1])
    return G


def apply_edits(G, edits, idx=None, pal=None):
    """Apply edits to a (512,512,3) uint8 RGB image. Each edit removes its Japanese
    text (bg) then draws English, all confined to its clip. Returns (image, force):
    `force` is a (512,512) int array of palette indices to write as-is (-1 = map the
    pixel's colour to the nearest palette entry instead)."""
    force = np.full((W, W), -1, np.int32)
    for e in edits:
        clip = e["clip"]; x0, y0, x1, y1 = clip
        bg = e.get("bg", "inpaint")
        mask = _glyph_mask(_lum(G), clip, e.get("wht", 180), e.get("drk", 80),
                           e.get("dil", 2), e.get("hat", 40), e.get("kk", 9))
        if bg == "outlined" and idx is not None and pal is not None:
            # White letters with a DARK OUTLINE on a busy plate (pop'n's buttons:
            # cream/striped/gradient). The letters are exactly: dark pixels touching
            # white ones, plus white pixels touching dark ones (a pale plate area on
            # its own has no dark outline, so it is left alone). Only those small
            # holes are inpainted from the surrounding plate.
            inclip = np.zeros((W, W), bool); inclip[y0:y1, x0:x1] = True
            L = _lum(G)
            white = (G.min(axis=2) > e.get("wht", 200)) & inclip
            dark = (L < e.get("drk", 90)) & inclip
            r = e.get("reach", 2)
            mask = (dark & _dilate(white, r)) | (white & _dilate(dark, r))
            mask = _dilate(mask, e.get("dil", 1)) & inclip
            if e.get("local"):
                # inpaint from inside the clip only: an element next to a black atlas
                # gap would otherwise pull that black in as dark blotches
                G = G.copy()
                G[y0:y1, x0:x1] = _inpaint(np.ascontiguousarray(G[y0:y1, x0:x1]),
                                           mask[y0:y1, x0:x1])
            else:
                G = _inpaint(G, mask)
        elif bg == "rows" and idx is not None and pal is not None:
            # Text on a BUTTON PLATE (a gradient that only varies top to bottom). The
            # text is the near-white fill (all channels high, so a bright peach plate
            # is not mistaken for it) plus the dark outline/antialiasing around it.
            # Each masked pixel copies the ORIGINAL INDEX of the nearest unmasked pixel
            # in the same row: the plate's gradient continues exactly, and the indices
            # are ones the plate already uses, so a palette-cycling hover animation
            # still animates the whole button.
            inclip = np.zeros((W, W), bool); inclip[y0:y1, x0:x1] = True
            white = (G.min(axis=2) > e.get("wht", 215)) & inclip
            near = _dilate(white, e.get("dil", 3)) & inclip
            dark = (_lum(G) < e.get("drk", 90)) & _dilate(white, e.get("dil", 3) + 2) & inclip
            mask = _dilate(near | dark, 1) & inclip
            G = G.copy()
            # Copy along the plate's pattern direction: (1, 0) = rows (a top-to-bottom
            # gradient), (1, -1) = the diagonal stripes on pop'n's button plates. Walk
            # both ways from each masked pixel to the nearest unmasked pixel in the
            # clip; fall back to the row if the diagonal leaves the clip first.
            dx, dy = e.get("dir", (1, 0))
            # opt-in (2026-10-04, splotch probe): src="cur" copies the CURRENT index
            # (after earlier edits, e.g. a twin-plate copy) instead of the original;
            # blend="dither" picks between the two ends found along the direction with
            # an ordered (Bayer 4x4) dither weighted by distance, so a plate that drifts
            # along the stripe (a gradient) blends without a seam while every pixel
            # still gets an index the plate itself uses.
            srcidx = np.where(force >= 0, force, idx) if e.get("src") == "cur" else idx
            dither = e.get("blend") == "dither"
            for y, x in zip(*np.nonzero(mask)):
                src = None
                for ddx, ddy in ((dx, dy), (1, 0)):
                    best = None; ends = []
                    for sgn in (1, -1):
                        cx, cy = x, y
                        for step in range(1, W):
                            cx += sgn * ddx; cy += sgn * ddy
                            if not (x0 <= cx < x1 and y0 <= cy < y1):
                                break
                            if not mask[cy, cx]:
                                ends.append((step, srcidx[cy, cx]))
                                if best is None or step < best[0]:
                                    best = (step, srcidx[cy, cx])
                                break
                    if best is not None:
                        src = best[1]
                        if dither and len(ends) == 2:
                            (sa, ia), (sb, ib) = ends
                            src = ib if _BAYER4[y % 4][x % 4] < sa / float(sa + sb) else ia
                        break
                if src is None:
                    continue                      # nothing to copy from: leave it
                force[y, x] = src
                G[y, x] = pal[src, :3]
        elif bg == "key" and idx is not None and pal is not None:
            # Text on a flat KEY colour (e.g. the salmon behind message sprites, which
            # the game hides at draw time). The key is the clip's most common index;
            # the text is every non-key pixel within a few px of the white fill (fill +
            # outline + antialiasing). Refill exactly those with the key index. Far
            # more precise than the morphology mask on dense text.
            # key = most common MID-TONE index: on text-dense strips the white fill or
            # dark outline can outnumber the background, so exclude both
            L = _lum(G)
            sub_i = idx[y0:y1, x0:x1].astype(np.int64)
            sub_l = L[y0:y1, x0:x1]
            mid = sub_i[(sub_l >= 60) & (sub_l <= e.get("wht", 190))]
            key = int(np.bincount(mid if mid.size else sub_i.ravel()).argmax())
            if "key" in e:
                # explicit key index (e.g. 0 = the transparent entry behind text that
                # floats on nothing; with wht=-1, dil=0 the whole clip is wiped to it)
                key = int(e["key"])
            inclip = np.zeros((W, W), bool); inclip[y0:y1, x0:x1] = True
            white = (L > e.get("wht", 190)) & inclip
            mask = _dilate(white, e.get("dil", 3)) & inclip & (idx != key)
            G = G.copy(); G[mask] = pal[key, :3]; force[mask] = key
        elif bg == "copy" and idx is not None and pal is not None:
            # Rebuild the WHOLE clip from a same-sized region `src`=(dx, dy) away, as it
            # is now (after earlier edits). For a sprite whose glyphs cover nearly all of
            # its plate (nothing left to inpaint from) next to a twin plate. Only the
            # clip is written; the source is only read.
            dx, dy = e["src"]
            sy0, sy1, sx0, sx1 = y0 + dy, y1 + dy, x0 + dx, x1 + dx
            assert 0 <= sx0 and sx1 <= W and 0 <= sy0 and sy1 <= W, "copy src off-sheet"
            s_rgb = G[sy0:sy1, sx0:sx1].copy()
            s_frc = force[sy0:sy1, sx0:sx1].copy()
            s_idx = idx[sy0:sy1, sx0:sx1]
            same = (pal[s_idx][:, :, :3] == s_rgb).all(axis=2)
            G = G.copy(); G[y0:y1, x0:x1] = s_rgb
            # s_idx is uint8: widen it before mixing in -1 (NumPy 2 no longer upcasts
            # a uint8 array for an out-of-range Python int; same values on NumPy 1)
            force[y0:y1, x0:x1] = np.where(s_frc >= 0, s_frc,
                                           np.where(same, s_idx.astype(np.int32), -1))
        elif bg == "patch" and idx is not None and pal is not None:
            G = _patch_fill(G, force, idx, pal, e)
        elif bg == "lerp" and idx is not None and pal is not None:
            # Like bg="rows" with dir (1, 0), but each masked run in a row is filled
            # with a linear blend from its left neighbour's colour to its right one's
            # (nearest palette entry the clip already uses): a left-to-right plate
            # gradient continues without the hard seam a nearest-copy leaves mid-run.
            inclip = np.zeros((W, W), bool); inclip[y0:y1, x0:x1] = True
            white = (G.min(axis=2) > e.get("wht", 254)) & inclip
            mask = _dilate(white, 1) & inclip
            local = np.unique(idx[y0:y1, x0:x1]); local = local[pal[local, 3] > 0]
            if e.get("local") == "ring":
                # opt-in: only indices of the clip's UNMASKED pixels (the plate itself),
                # never the JP glyph's own entries under the mask: those do not take
                # part in the plate's palette-cycling hover animation
                cur = np.where(force >= 0, force, idx)[y0:y1, x0:x1][~mask[y0:y1, x0:x1]]
                local = np.unique(cur); local = local[pal[local, 3] > 0]
            G = G.copy()
            for y in range(y0, y1):
                xs = np.nonzero(mask[y, x0:x1])[0] + x0
                if not xs.size:
                    continue
                runs = np.split(xs, np.nonzero(np.diff(xs) > 1)[0] + 1)
                for run in runs:
                    a, b = run[0] - 1, run[-1] + 1
                    ca = G[y, a].astype(np.float32) if a >= x0 else None
                    cb = G[y, b].astype(np.float32) if b < x1 else None
                    if ca is None and cb is None:
                        continue
                    ca = cb if ca is None else ca; cb = ca if cb is None else cb
                    t = (run - a) / float(b - a)
                    px = np.clip(ca[None, :] * (1 - t[:, None]) + cb[None, :] * t[:, None], 0, 255).astype(np.uint8)
                    G[y, run] = px
                    force[y, run] = _nearest_index(px, pal, local)
        elif bg == "pattern" and idx is not None and pal is not None:
            # Repaint the WHOLE clip from `rows`: one list of (r, g, b) per clip row,
            # repeated along x (a dithered band = 2 colours). For a highlight tile that
            # is a crop of a panel on ANOTHER sheet (no src to copy). Each colour is
            # written as the nearest visible palette entry.
            rows = e["rows"]
            assert len(rows) == y1 - y0, "pattern needs one row per clip row"
            local = np.nonzero(pal[:, 3] > 0)[0]
            G = G.copy()
            for r, pat in enumerate(rows):
                px = np.array([pat[(x - x0) % len(pat)] for x in range(x0, x1)], np.uint8)
                G[y0 + r, x0:x1] = px
                force[y0 + r, x0:x1] = _nearest_index(px, pal, local)
        elif bg == "inpaint":
            G = _inpaint(G, mask)
            if e.get("local") == "ring" and idx is not None and pal is not None and mask.any():
                # opt-in (2026-10-04): write the inpainted pixels as the nearest of the
                # indices the clip's UNMASKED pixels use (the art around the text), not
                # any palette entry: no foreign entry that a palette animation skips
                ring = np.where(force >= 0, force, idx)[y0:y1, x0:x1][~mask[y0:y1, x0:x1]]
                ring = np.unique(ring); ring = ring[pal[ring, 3] > 0]
                if ring.size:
                    force[mask] = _nearest_index(G[mask], pal, ring)
                    G[mask] = pal[force[mask], :3]
        elif bg == "flat":
            # fill the glyph mask with the panel's own background. With the palette
            # known, use the panel's most common ORIGINAL INDEX exactly: some sheets'
            # sprite backgrounds are swapped or keyed at draw time, so a lookalike
            # entry would show. Clean on a ~uniform panel; no box, no inpaint smear.
            subm = mask[y0:y1, x0:x1]
            G = G.copy()
            if idx is not None and pal is not None and (~subm).any():
                mode = int(np.bincount(idx[y0:y1, x0:x1][~subm].astype(np.int64)).argmax())
                G[mask] = pal[mode, :3]
                force[mask] = mode
            else:
                bgpx = G[y0:y1, x0:x1][~subm]
                G[mask] = np.median(bgpx, axis=0).astype(np.uint8) if len(bgpx) else 0
        else:
            v = 0 if bg == "black" else int(bg)
            G = G.copy(); G[mask] = (v, v, v)
        before = G
        G = _draw_lines(G, e)
        txt = (G != before).any(axis=2)
        if idx is not None and pal is not None and txt.any():
            # Draw the English only with palette entries this element ALREADY used
            # (its plate, the old text's fill and outline). Some sheets animate by
            # cycling palette entries (button hover); a lookalike entry from elsewhere
            # in the palette would not animate with the rest of the element.
            # "local_rect": take the allowed entries from a wider rect instead (e.g. a
            # whole panel), so sibling labels map to the SAME text colours
            lx0, ly0, lx1, ly1 = e.get("local_rect", clip)
            local = np.unique(idx[ly0:ly1, lx0:lx1])
            local = local[pal[local, 3] > 0]
            if not local.size:
                force[txt] = -1
            elif e.get("ramp", RAMP):
                force[txt] = _ramp_map(G, before, txt, e, force, idx, pal, local)
            else:
                force[txt] = _nearest_index(G[txt], pal, local)
        else:
            force[txt] = -1                         # colour-match it later
    return G, force


_BAYER4 = [[(v + 0.5) / 16.0 for v in r] for r in ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))]


# Ramp-constrained text colours (2026-10-04, default on; an edit opts out with
# "ramp": False, and POPN_TEX_RAMP=0 turns it off globally for A/B builds).
# An antialiased text pixel is a blend of two colours it lies between: fill<->outline,
# outline<->the plate under it, or fill<->plate. Mapping it to the plain nearest
# palette entry picks whatever is closest in RGB, often a neutral grey or an olive
# that is NOT on that blend (cream text on a green plate came out speckled grey).
# _ramp_map finds the segment the pixel lies on and only accepts palette entries
# within max(RAMP_TOL, RAMP_FRAC x the ramp's length) of that segment (its two end
# indices always qualify; a long white->near-black ramp tolerates warm/cool greys,
# a short pale->green one does not tolerate a neutral grey), then picks
# the one nearest along the ramp. Pixels far from every segment (resampling ringing,
# overlapping lines) keep the old nearest-entry mapping.
RAMP = os.environ.get("POPN_TEX_RAMP", "1") != "0"
RAMP_TOL = 7.0
RAMP_FRAC = 0.04


def _ramp_map(G, before, txt, e, force, idx, pal, local):
    """Palette index for every `txt` pixel of G (drawn text), constrained to the colour
    ramp it lies on. `before` is the image just before the text was drawn (the plate),
    `force`/`idx` give the plate's index there, `local` the allowed palette entries."""
    tol = float(e.get("ramp_tol", RAMP_TOL)); frac = float(e.get("ramp_frac", RAMP_FRAC))
    P = G[txt].astype(np.float32)
    n = len(P)
    F = np.array(_rgb(e.get("fill", 250)), np.float32)
    O = np.array(_rgb(e.get("outline", 28)), np.float32)
    lrgb = pal[local, :3].astype(np.float32)
    near = lambda c: int(local[((lrgb - c) ** 2).sum(1).argmin()])
    fi, oi = near(F), near(O)
    # the plate under each pixel: its current index when that index shows exactly the
    # colour drawn over, else the nearest local entry
    Bc = before[txt].astype(np.float32)
    cur = np.where(force >= 0, force, idx)[txt].astype(np.int64)
    ok = (pal[cur, :3].astype(np.float32) == Bc).all(1)
    bi = cur.copy()
    if (~ok).any():
        bi[~ok] = _nearest_index(before[txt][~ok], pal, local)
    # three segments per pixel: (start colour, end colour, start index, end index)
    A = np.stack([np.broadcast_to(F, (n, 3)), np.broadcast_to(O, (n, 3)),
                  np.broadcast_to(F, (n, 3))])
    Z = np.stack([np.broadcast_to(O, (n, 3)), Bc, Bc])
    IA = np.stack([np.full(n, fi), np.full(n, oi), np.full(n, fi)])
    IZ = np.stack([np.full(n, oi), bi, bi])
    D = Z - A
    L2 = np.maximum((D * D).sum(2), 1e-6)
    t = np.clip(((P[None] - A) * D).sum(2) / L2, 0.0, 1.0)
    dist = np.sqrt((((A + t[..., None] * D) - P[None]) ** 2).sum(2))
    s = dist.argmin(0)                                  # the segment each pixel is on
    r = np.arange(n)
    tp, ia, iz = t[s, r], IA[s, r], IZ[s, r]
    dmin = dist[s, r]
    out = np.where(tp < 0.5, ia, iz).astype(np.int64)  # endpoint fallback
    # The pixel's position t along its ramp comes from the colours actually drawn;
    # candidates are judged against the ramp between the two END ENTRIES' palette
    # colours (a fill/outline given as a grey level can map to a tinted entry, and
    # the in-between entries then lie on the tinted ramp, not the grey one).
    a = pal[ia, :3].astype(np.float32)
    d = pal[iz, :3].astype(np.float32) - a
    l2 = np.maximum((d * d).sum(1), 1e-6)
    # interior candidates: local entries close to the pixel's own segment
    for i in range(0, n, 2048):
        sl = slice(i, i + 2048)
        tc = ((lrgb[None] - a[sl, None]) * d[sl, None]).sum(2) / l2[sl, None]
        pc = a[sl, None] + np.clip(tc, 0, 1)[..., None] * d[sl, None]
        dc = np.sqrt(((pc - lrgb[None]) ** 2).sum(2))
        L = np.sqrt(l2[sl])[:, None]
        okc = (dc <= np.minimum(np.maximum(tol, frac * L), 0.25 * L + 1.0)) & (tc > 0.0) & (tc < 1.0)
        cost = np.where(okc, (L * (tc - tp[sl, None])) ** 2 + dc ** 2, np.inf)
        # the two endpoints as candidates at t = 0 / 1
        c0 = (L[:, 0] * tp[sl]) ** 2
        c1 = (L[:, 0] * (1.0 - tp[sl])) ** 2
        k = cost.argmin(1)
        best = cost[np.arange(len(k)), k]
        o = np.where(c0 <= c1, ia[sl], iz[sl])
        ce = np.minimum(c0, c1)
        o = np.where(best < ce, local[k], o)
        out[sl] = o
    # far from every ramp (resampling ringing, overlapping lines): plain nearest entry
    far = dmin > max(3.0 * tol, 24.0)
    if far.any():
        out[far] = _nearest_index(G[txt][far], pal, local)
    return out


def _nearest_index(pixels, pal, cand):
    """Palette index (among `cand`) nearest in RGB to each pixel, in chunks."""
    prgb = pal[cand, :3].astype(np.int32)
    out = np.empty(len(pixels), np.int64)
    for i in range(0, len(pixels), 4096):
        p = pixels[i:i + 4096].astype(np.int32)
        d = ((p[:, None, :] - prgb[None, :, :]) ** 2).sum(2)
        out[i:i + 4096] = cand[d.argmin(1)]
    return out


def _compress_exact(data, tries=512):
    """Same token set and match finder as pnimage.compress, but an EXACT-cost optimal
    parse: literal runs are costed as 1 header byte + n literals (n <= 32) instead of the
    amortised 33/32 per byte, and every match / RLE / zero-run length up to the longest
    is considered, not only the longest. 1-2% smaller on dense sheets (the manual page
    0x5631f0 and the BGM title sheet 0x15c6a60 overflow their slots with the standard
    coder even unedited). Used by edit_texture only as an overflow fallback."""
    import struct
    data = bytes(data); n = len(data)
    if n == 0:
        return struct.pack('<I', 0) + b'\x7f\xff'
    HSIZE = 1 << 16
    head = [-1] * HSIZE; prev = [-1] * n
    mlen = bytearray(n); mdist = [0] * n; run = bytearray(n)
    for i in range(n):
        m = min(33, n - i); r = 1; bi = data[i]
        while r < m and data[i + r] == bi:
            r += 1
        run[i] = r
        if i + 2 < n:
            hv = ((data[i] << 7) ^ (data[i + 1] << 4) ^ data[i + 2]) & (HSIZE - 1)
            j = head[hv]; ws = i - 1024; bl = 0; bd = 0; t = tries
            while j >= 0 and j >= ws and t > 0:
                t -= 1
                if data[j + bl] == data[i + bl]:
                    l = 0
                    while l < m and data[j + l] == data[i + l]:
                        l += 1
                    if l > bl:
                        bl = l; bd = i - j
                        if l == m:
                            break
                j = prev[j]
            if bl == 33 and bd == 1:                 # (33, dist 1) would encode 7fff END
                bl = 32
            mlen[i] = bl; mdist[i] = bd
            prev[i] = head[hv]; head[hv] = i
    f = [0] * (n + 1); kind = bytearray(n); klen = [0] * n
    for i in range(n - 1, -1, -1):
        best = 1 << 60; bk = 0; bln = 1
        for L in range(1, min(32, n - i) + 1):          # literal run: 1 + L bytes
            c = L + 1 + f[i + L]
            if c < best:
                best = c; bk = 0; bln = L
        for L in range(2, mlen[i] + 1):                  # match: 2 bytes
            c = 2 + f[i + L]
            if c < best:
                best = c; bk = 1; bln = L
        if data[i] != 0:
            for L in range(2, run[i] + 1):               # byte RLE: 2 bytes
                c = 2 + f[i + L]
                if c < best:
                    best = c; bk = 2; bln = L
        else:
            z = 1
            while i + z < n and data[i + z] == 0 and z < 0x11f:
                z += 1
            for L in range(1, min(z, 31) + 1):           # short zero run: 1 byte
                c = 1 + f[i + L]
                if c < best:
                    best = c; bk = 3; bln = L
            for L in range(32, z + 1):                   # long zero run: 2 bytes
                c = 2 + f[i + L]
                if c < best:
                    best = c; bk = 3; bln = L
            cnt = 0                                      # zero-interleave: 1 + cnt bytes
            while cnt < 32 and i + 2 * cnt + 1 < n and data[i + 2 * cnt] == 0:
                cnt += 1
                c = 1 + cnt + f[i + 2 * cnt]
                if c < best:
                    best = c; bk = 4; bln = 2 * cnt
        f[i] = best; kind[i] = bk; klen[i] = bln
    out = bytearray(struct.pack('<I', n)); i = 0
    while i < n:
        k = kind[i]; L = klen[i]
        if k == 0:
            out.append(0x80 | (L - 1)); out += data[i:i + L]
        elif k == 1:
            V = (~(mdist[i] - 1)) & 0x3ff
            out.append((((L - 2) & 0x1f) << 2) | ((V >> 8) & 3)); out.append(V & 0xff)
        elif k == 2:
            out.append(0xc0 | (L - 2)); out.append(data[i])
        elif k == 4:
            out.append(0xa0 | (L // 2 - 1))
            for q in range(L // 2):
                out.append(data[i + 2 * q + 1])
        elif L <= 31:
            out.append(0xe0 | (L - 1))
        else:
            out.append(0xff); out.append(L - 0x20)
        i += L
    out += bytes([0x7f, 0xff])
    assert decompress(bytes(out) + b"\0" * 8, 0)[0] == data, "exact coder round-trip"
    return bytes(out)


def edit_texture(src_dat, out_dat, fo, slot_end, edits, preview_png=None):
    """Decode the big texture at `fo`, apply `edits`, re-encode and splice back in
    place (zero-padded to the original slot). Asserts atlas-safety: no pixel
    outside the union of edit clips may change. Returns (compressed_len, slot)."""
    d = bytearray(open(src_dat, "rb").read())
    assert d[fo + 4:fo + 8] == b"\xa1\x02\x02\x80", "not a big texture at %#x" % fo
    out, size, cons = decompress(d, fo)
    # Slot guard: between this stream's end and slot_end there must only be the
    # stream's own few tail bytes and zero padding. Some textures are followed by
    # non-texture data (sprite/layout tables) before the next texture; padding over it
    # breaks that whole screen (seen: black login screen). Refuse such a slot.
    tail = bytes(d[fo + cons:slot_end])
    nz = len(tail) - tail.count(0)
    if nz > 8:
        first = next(k for k, b in enumerate(tail) if b)
        raise SystemExit("slot overrun @%#x: %d non-zero bytes of other data between the "
                         "stream end %#x and slot_end %#x (first at %#x); use slot_end <= %#x"
                         % (fo, nz, fo + cons, slot_end, fo + cons + first, fo + cons + first))
    # The CLUT is 256 x RGBA in FULL COLOUR (not a grey ramp). Work on the real
    # colours, and keep the original palette index of every pixel the edits did not
    # change: re-quantising the whole sheet through one channel collapses distinct
    # colours (greens with R=0 onto the transparent black entry).
    pal = np.frombuffer(bytes(out[0x10:0x410]), np.uint8).reshape(256, 4)
    idx = np.frombuffer(bytes(unswizzle8(bytearray(out[0x410:0x410 + W * W]), W, W)),
                        np.uint8).reshape(W, W)
    orig_rgb = pal[idx][:, :, :3].copy()

    rgb, force = apply_edits(orig_rgb.copy(), edits, idx, pal)

    changed = (rgb != orig_rgb).any(axis=2)
    new_idx = idx.copy()
    if changed.any():
        visible = np.nonzero(pal[:, 3] > 0)[0]
        new_idx[changed] = _nearest_index(rgb[changed], pal, visible)
    new_idx[force >= 0] = force[force >= 0]

    # atlas-safety, on the INDEX array (what is actually written): no index may
    # change outside the union of clips
    allowed = np.zeros((W, W), bool)
    for e in edits:
        x0, y0, x1, y1 = e["clip"]; allowed[y0:y1, x0:x1] = True
    leaked = int(((new_idx != idx) & ~allowed).sum())
    if leaked:
        raise SystemExit("atlas-safety: %d px changed outside clips @%#x" % (leaked, fo))

    if preview_png:
        Image.fromarray(pal[new_idx][:, :, :3], "RGB").save(preview_png)

    un2 = new_idx.astype(np.uint8).tobytes()
    new_dec = out[:0x410] + swizzle8(un2, W, W) + out[0x410 + W * W:]
    comp = compress(new_dec)
    slot = slot_end - fo
    if len(comp) > slot:
        # additive fallback (2026-10-04, options_menus): only when the standard coder
        # overflows, try the exact-cost parse; textures that already fit are unchanged
        comp2 = _compress_exact(new_dec)
        if len(comp2) < len(comp):
            comp = comp2
    if len(comp) > slot:
        raise SystemExit("re-encoded %d > slot %d for texture @%#x" % (len(comp), slot, fo))
    d[fo:fo + len(comp)] = comp
    for i in range(fo + len(comp), slot_end):
        d[i] = 0
    open(out_dat, "wb").write(d)
    return len(comp), slot
