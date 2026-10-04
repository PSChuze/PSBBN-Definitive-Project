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
    for i, tx in enumerate(lines):
        fs = fs0; f = ImageFont.truetype(FONT, fs)
        bb = dr.textbbox((0, 0), tx, font=f, stroke_width=sw); w = bb[2] - bb[0]
        while w > (x1 - x0 - 8) and fs > 8:
            fs -= 1; f = ImageFont.truetype(FONT, fs)
            bb = dr.textbbox((0, 0), tx, font=f, stroke_width=sw); w = bb[2] - bb[0]
        px = ((x0 + x1) // 2 - w // 2 - bb[0]) if align == "c" else (x0 - bb[0])
        dr.text((px, ty0 + i * lh), tx, font=f, fill=(fill, fill, fill),
                stroke_width=sw, stroke_fill=(outline, outline, outline))
    arr = np.array(img)
    out = G.copy(); out[y0:y1, x0:x1] = arr[y0:y1, x0:x1]
    return out


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
        if bg == "key" and idx is not None and pal is not None:
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
            inclip = np.zeros((W, W), bool); inclip[y0:y1, x0:x1] = True
            white = (L > e.get("wht", 190)) & inclip
            mask = _dilate(white, e.get("dil", 3)) & inclip & (idx != key)
            G = G.copy(); G[mask] = pal[key, :3]; force[mask] = key
        elif bg == "inpaint":
            G = _inpaint(G, mask)
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
        force[(G != before).any(axis=2)] = -1      # drawn English: colour-match it
    return G, force


def _nearest_index(pixels, pal, cand):
    """Palette index (among `cand`) nearest in RGB to each pixel, in chunks."""
    prgb = pal[cand, :3].astype(np.int32)
    out = np.empty(len(pixels), np.int64)
    for i in range(0, len(pixels), 4096):
        p = pixels[i:i + 4096].astype(np.int32)
        d = ((p[:, None, :] - prgb[None, :, :]) ** 2).sum(2)
        out[i:i + 4096] = cand[d.argmin(1)]
    return out


def edit_texture(src_dat, out_dat, fo, slot_end, edits, preview_png=None):
    """Decode the big texture at `fo`, apply `edits`, re-encode and splice back in
    place (zero-padded to the original slot). Asserts atlas-safety: no pixel
    outside the union of edit clips may change. Returns (compressed_len, slot)."""
    d = bytearray(open(src_dat, "rb").read())
    assert d[fo + 4:fo + 8] == b"\xa1\x02\x02\x80", "not a big texture at %#x" % fo
    out, size, cons = decompress(d, fo)
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
        raise SystemExit("re-encoded %d > slot %d for texture @%#x" % (len(comp), slot, fo))
    d[fo:fo + len(comp)] = comp
    for i in range(fo + len(comp), slot_end):
        d[i] = 0
    open(out_dat, "wb").write(d)
    return len(comp), slot
