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
   "wht": 180, "drk": 80, "dil": 2,    # glyph-mask thresholds / dilation
   "align": "c"|"l", "fill": 250, "outline": 28, "sw": 2}

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


def _inpaint(G, mask):
    """Rebuild masked pixels from their surroundings. OpenCV Telea when available,
    otherwise a numpy Jacobi diffusion (masked pixel <- mean of known neighbours),
    which reconstructs smooth panel gradients well enough for these backgrounds."""
    if _HAVE_CV2:
        return cv2.inpaint(G, (mask * 255).astype(np.uint8), 4, cv2.INPAINT_TELEA)
    out = G.astype(np.float32)
    known = ~mask.astype(bool)
    # seed unknown pixels with the global known mean so edges converge faster
    out[~known] = out[known].mean() if known.any() else 128.0
    for _ in range(220):
        up = np.roll(out, 1, 0); dn = np.roll(out, -1, 0)
        lf = np.roll(out, 1, 1); rt = np.roll(out, -1, 1)
        avg = (up + dn + lf + rt) * 0.25
        out = np.where(known, out, avg)
    return np.clip(out, 0, 255).astype(np.uint8)


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


def _draw_lines(G, e):
    clip = e["clip"]; x0, y0, x1, y1 = clip
    lines = e.get("lines") or []
    if not lines:
        return G
    align = e.get("align", "c"); fill = e.get("fill", 250)
    outline = e.get("outline", 28); sw = e.get("sw", 2)
    ty0 = e["ty0"]; lh = e.get("lh", 22); fs0 = e.get("fs", 14)
    img = Image.fromarray(G, "L").convert("RGBA"); dr = ImageDraw.Draw(img)
    for i, tx in enumerate(lines):
        fs = fs0; f = ImageFont.truetype(FONT, fs)
        bb = dr.textbbox((0, 0), tx, font=f, stroke_width=sw); w = bb[2] - bb[0]
        while w > (x1 - x0 - 8) and fs > 8:
            fs -= 1; f = ImageFont.truetype(FONT, fs)
            bb = dr.textbbox((0, 0), tx, font=f, stroke_width=sw); w = bb[2] - bb[0]
        px = ((x0 + x1) // 2 - w // 2 - bb[0]) if align == "c" else (x0 - bb[0])
        dr.text((px, ty0 + i * lh), tx, font=f, fill=(fill, fill, fill, 255),
                stroke_width=sw, stroke_fill=(outline, outline, outline, 255))
    arr = np.array(img.convert("L"))
    out = G.copy(); out[y0:y1, x0:x1] = arr[y0:y1, x0:x1]
    return out


def apply_edits(G, edits):
    """Apply edits to a (512,512) uint8 grayscale image in place-ish; returns the
    new image. Each edit removes its Japanese text (bg) then draws English, all
    confined to its clip."""
    for e in edits:
        clip = e["clip"]; x0, y0, x1, y1 = clip
        bg = e.get("bg", "inpaint")
        mask = _glyph_mask(G, clip, e.get("wht", 180), e.get("drk", 80),
                           e.get("dil", 2), e.get("hat", 40), e.get("kk", 9))
        if bg == "inpaint":
            G = _inpaint(G, mask)
        elif bg == "flat":
            # fill the glyph mask with the panel's own background level (median of
            # the non-text pixels in the clip). Clean on a ~uniform panel; no box,
            # no inpaint smear. Best when the element background is roughly solid.
            x0, y0, x1, y1 = clip
            sub = G[y0:y1, x0:x1]
            subm = mask[y0:y1, x0:x1]
            bgpx = sub[~subm]
            val = int(np.median(bgpx)) if bgpx.size else 0
            G = G.copy(); G[mask] = val
        else:
            val = 0 if bg == "black" else int(bg)
            G = G.copy(); G[mask] = val
        G = _draw_lines(G, e)
    return G


def edit_texture(src_dat, out_dat, fo, slot_end, edits, preview_png=None):
    """Decode the big texture at `fo`, apply `edits`, re-encode and splice back in
    place (zero-padded to the original slot). Asserts atlas-safety: no pixel
    outside the union of edit clips may change. Returns (compressed_len, slot)."""
    d = bytearray(open(src_dat, "rb").read())
    assert d[fo + 4:fo + 8] == b"\xa1\x02\x02\x80", "not a big texture at %#x" % fo
    out, size, cons = decompress(d, fo)
    clut = out[0x10:0x410]
    gclut = [clut[i * 4] for i in range(256)]
    inv = [min(range(256), key=lambda idx: abs(gclut[idx] - v)) for v in range(256)]
    un = bytearray(unswizzle8(bytearray(out[0x410:0x410 + W * W]), W, W))
    G = np.array([gclut[un[i]] for i in range(W * W)], dtype=np.uint8).reshape(W, W)
    orig = G.copy()

    G = apply_edits(G, edits)

    # atlas-safety: changes must lie inside the union of clips
    allowed = np.zeros((W, W), bool)
    for e in edits:
        x0, y0, x1, y1 = e["clip"]; allowed[y0:y1, x0:x1] = True
    leaked = int(((G != orig) & ~allowed).sum())
    if leaked:
        raise SystemExit("atlas-safety: %d px changed outside clips @%#x" % (leaked, fo))

    if preview_png:
        Image.fromarray(G, "L").save(preview_png)

    un2 = bytes(inv[int(v)] for v in G.flatten())
    new_dec = out[:0x410] + swizzle8(un2, W, W) + out[0x410 + W * W:]
    comp = compress(new_dec)
    slot = slot_end - fo
    if len(comp) > slot:
        raise SystemExit("re-encoded %d > slot %d for texture @%#x" % (len(comp), slot, fo))
    d[fo:fo + len(comp)] = comp
    for i in range(fo + len(comp), slot_end):
        d[i] = 0
    open(out_dat, "wb").write(d)
    return len(comp), slot
