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

# The text face. POPN_TEX_FONT overrides; else a bold font bundled next to this
# file (DejaVuSans-Bold.ttf, so the install renders the same on any OS without a
# Windows/proprietary font); else fall back to the old Comic Sans path for dev.
def _default_font():
    env = os.environ.get("POPN_TEX_FONT")
    if env and os.path.isfile(env):
        return env
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DejaVuSans-Bold.ttf")
    if os.path.isfile(here):
        return here
    return '/c/Windows/Fonts/comicbd.ttf'

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

    def do_erase(x0, y0, x1, y1, cx=None, flat=None):
        for y in range(y0, y1):
            bg = flat if flat is not None else gp(cx, y)
            for x in range(x0, x1):
                stp(x, y, bg)

    def sample_ink(cx, ty, maxw, align):
        # ink = extreme gray in a small band near where text will go that
        # contrasts most with the local bg
        y0 = max(0, ty-2); y1 = min(W, ty+20)
        xs = range(max(0, cx-maxw//2), min(W, cx+maxw//2)) if align == 'c' else range(cx, min(W, cx+maxw))
        vals = [gray(gp(x, y)) for y in range(y0, y1) for x in xs]
        if not vals:
            return 30
        lo, hi = min(vals), max(vals)
        # bg ~ median; ink ~ whichever extreme is farther from bg
        import statistics
        bg = statistics.median(vals)
        return lo if (bg-lo) >= (hi-bg) else hi

    def draw_text(text, cx, ty, maxw=250, ink=None, align='c', fs=15):
        tmpd = ImageDraw.Draw(Image.new('L', (1, 1)))
        while fs > 8:
            f = ImageFont.truetype(font, fs); bb = tmpd.textbbox((0, 0), text, font=f)
            if bb[2]-bb[0] <= maxw:
                break
            fs -= 1
        f = ImageFont.truetype(font, fs); bb = tmpd.textbbox((0, 0), text, font=f)
        tw = bb[2]-bb[0]
        tx = (cx-tw//2-bb[0]) if align == 'c' else (cx-bb[0])
        if ink is None:
            ink = sample_ink(cx, ty, maxw, align)
        tmp = Image.new('L', (W, 28), 0); ImageDraw.Draw(tmp).text((tx, 0-bb[1]), text, fill=255, font=f)
        m = tmp.load()
        for yy in range(28):
            y = ty+yy
            if 0 <= y < W:
                for x in range(W):
                    a = m[x, yy]
                    if a:
                        stp(x, y, inv[int(gray(gp(x, y))*(1-a/255)+ink*(a/255))])

    for e in edits:
        if 'erase' in e:
            flat = e.get('flat')
            if 'flatg' in e:                      # flat fill by gray value
                flat = inv[e['flatg']]
            do_erase(*e['erase'], cx=e.get('cx'), flat=flat)
        if 'text' in e:
            draw_text(e['text'], e['cx'], e['ty'], e.get('maxw', 250),
                      e.get('ink'), e.get('align', 'c'), e.get('fs', 15))

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
