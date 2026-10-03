#!/usr/bin/env python3
"""Reusable pop'n IMAGE.DAT texture text editor.

Loads a texture substream, unswizzles, applies a list of edits (erase a region by
reconstructing its per-row background from a clean column, then draw English text
blended toward a sampled ink level), re-swizzles, re-compresses, and splices the
result back into IMAGE.DAT in place (zero-padded to the original slot) so every
other byte is unchanged.

Edits are declared as dicts:
  {"erase":(x0,y0,x1,y1), "cx":<clean column x>}          # reconstruct bg
  {"erase":(x0,y0,x1,y1), "flat":<index>}                 # flat fill
  {"text":"English", "cx":<center x>, "ty":<top y>, "maxw":W,
   "ink":<gray 0-255 or None=auto>, "align":"c"|"l", "fs":<max font px>}

See edit_texture(). Depends on pnimage.py (same dir).
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pnimage import decompress, unswizzle8, swizzle8, compress
from PIL import Image, ImageDraw, ImageFont

# The text face. All 18 screens are rendered with Comic Neue Bold (ComicNeue-
# Bold.ttf, SIL OFL - a free rounded Comic-Sans-alike that matches pop'n's look and
# is safe to ship in the public toolkit repo). The layout auto-fits each string to
# its box, so the exact face only needs to be a rounded bold. Resolution:
# POPN_TEX_FONT override -> a font bundled next to this file (ComicNeue, then
# DejaVuSans-Bold) -> a system comicbd (dev fallback, works under WSL /mnt/c too).
def _default_font():
    env = os.environ.get("POPN_TEX_FONT")
    if env and os.path.isfile(env):
        return env
    d = os.path.dirname(os.path.abspath(__file__))
    for name in ("ComicNeue-Bold.ttf", "DejaVuSans-Bold.ttf", "comicbd.ttf"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    for p in ("/mnt/c/Windows/Fonts/comicbd.ttf", "/c/Windows/Fonts/comicbd.ttf",
              r"C:\Windows\Fonts\comicbd.ttf"):
        if os.path.isfile(p):
            return p
    return "ComicNeue-Bold.ttf"

FONT = _default_font()
W = 512


def edit_texture(src_dat, out_dat, fo, slot_end, edits, font=FONT, preview_png=None):
    d = bytearray(open(src_dat, 'rb').read())
    out, size, cons = decompress(d, fo)
    assert d[fo+4:fo+8] == b'\xa1\x02\x02\x80', "not a big texture at %#x" % fo
    clut = out[0x10:0x410]
    un = bytearray(unswizzle8(bytearray(out[0x410:0x410+W*W]), W, W))
    inv = [min(range(256), key=lambda idx: abs(clut[idx*4]-v)) for v in range(256)]
    gray = lambda idx: clut[idx*4]
    gp = lambda x, y: un[y*W+x]
    stp = lambda x, y, i: un.__setitem__(y*W+x, i)

    def find_clean_col(x0, y0, x1, y1):
        # a column just outside the text with low vertical variance = real bg
        # (same per-row gradient as the text region); copying it is natural AND
        # compresses like the original (real pixels, not a synthesized gradient).
        # It must match the panel's own bg level (sampled from the rows just
        # above/below the band) so we never copy the black border beyond a panel.
        ref = sorted(gray(gp(x, y))
                     for y in (max(0, y0 - 2), max(0, y0 - 1),
                               min(W - 1, y1), min(W - 1, y1 + 1))
                     for x in range(x0, x1))
        exp = ref[len(ref) // 2] if ref else 128
        for cx in (list(range(x1 + 2, min(W, x1 + 48))) +
                   list(range(x0 - 2, max(-1, x0 - 48), -1))):
            vals = [gray(gp(cx, y)) for y in range(y0, y1)]
            if vals and max(vals) - min(vals) < 60 and abs(sum(vals) / len(vals) - exp) < 45:
                return cx
        return None

    def do_erase(x0, y0, x1, y1, cx=None, flat=None, interp=False):
        if interp:
            cc = find_clean_col(x0, y0, x1, y1)
            if cc is not None:                     # copy real bg column (per row)
                for y in range(y0, y1):
                    v = gp(cc, y)
                    for x in range(x0, x1):
                        stp(x, y, v)
                return
            # else fall through to synthesized vertical interpolation
            # reconstruct the background by interpolating, per column, between the
            # clean rows just above and just below the band (preserves vertical
            # gradients and avoids flat rectangles); horizontal variation is kept
            # because each column uses its own endpoints.
            # Used only when no clean bg column exists (full-width text on a
            # horizontally-uniform panel): synthesize ONE smooth vertical gradient
            # from the median bg just above/below the band and apply it uniformly
            # across x (per-column would streak from any text in the ref rows).
            def med(rows):
                s = sorted(gray(gp(x, yy)) for yy in rows for x in range(x0, x1))
                return s[len(s) // 2] if s else 128
            m = 2; q = 3
            tv = med(range(max(0, y0 - m), max(1, y0)))
            bv = med(range(min(W - 1, y1), min(W, y1 + m)))
            h = y1 - y0
            for yi, y in enumerate(range(y0, y1)):
                t = (yi + 1) / (h + 1)
                idx = inv[max(0, min(255, int(round((tv * (1 - t) + bv * t) / q)) * q))]
                for x in range(x0, x1):
                    stp(x, y, idx)
            return
        for y in range(y0, y1):
            bg = flat if flat is not None else gp(cx, y)
            for x in range(x0, x1):
                stp(x, y, bg)

    def draw_text(text, cx, ty, maxw=250, align='c', fs=15,
                  fill=250, outline=30, sw=2):
        # white fill + dark outline, matching the game's beveled bold font.
        tmpd = ImageDraw.Draw(Image.new('L', (1, 1)))
        while fs > 8:
            f = ImageFont.truetype(font, fs)
            bb = tmpd.textbbox((0, 0), text, font=f, stroke_width=sw)
            if bb[2] - bb[0] <= maxw:
                break
            fs -= 1
        f = ImageFont.truetype(font, fs)
        bb = tmpd.textbbox((0, 0), text, font=f, stroke_width=sw)
        tw = bb[2] - bb[0]
        tx = (cx - tw // 2 - bb[0]) if align == 'c' else (cx - bb[0])
        PAD = sw + 3
        H = fs + 2 * PAD + 6
        tmp = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((tx, PAD - bb[1]), text, font=f,
                                 fill=(fill, fill, fill, 255), stroke_width=sw,
                                 stroke_fill=(outline, outline, outline, 255))
        px = tmp.load()
        for yy in range(H):
            y = ty - PAD + yy
            if 0 <= y < W:
                for x in range(W):
                    r, g, b, a = px[x, yy]
                    if a:
                        v = gray(gp(x, y)) * (1 - a / 255) + r * (a / 255)
                        stp(x, y, inv[int(v)])

    for e in edits:
        if 'erase' in e:
            flat = e.get('flat')
            if 'flatg' in e:                      # flat fill by gray value
                flat = inv[e['flatg']]
            do_erase(*e['erase'], cx=e.get('cx'), flat=flat,
                     interp=e.get('interp', False))
        if 'text' in e:
            fill = e.get('fill', e.get('ink', 250))   # 'ink' kept as a fill alias
            draw_text(e['text'], e['cx'], e['ty'], e.get('maxw', 250),
                      e.get('align', 'c'), e.get('fs', 15),
                      fill=fill, outline=e.get('outline', 30), sw=e.get('sw', 2))

    if preview_png:
        Image.frombytes('L', (W, W), bytes(gray(un[i]) for i in range(W*W))).save(preview_png)

    new_dec = out[:0x410] + swizzle8(bytes(un), W, W) + out[0x410+W*W:]
    comp = compress(new_dec)
    slot = slot_end - fo
    if len(comp) > slot:
        raise SystemExit("re-encoded %d > slot %d for texture @%#x" % (len(comp), slot, fo))
    d[fo:fo+len(comp)] = comp
    for i in range(fo+len(comp), slot_end):
        d[i] = 0
    open(out_dat, 'wb').write(d)
    return len(comp), slot
