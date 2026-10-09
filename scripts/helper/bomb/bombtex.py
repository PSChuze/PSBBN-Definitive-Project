"""bombtex - the UI textures in Net de Bomberman's FILES.BIN: list, dump, and redraw them in English.

Read-only on every input; writes only the output paths you give it.

Texture record (inside a FILES.BIN chunk payload, see bombtext.py for the container), 0x20 bytes:
    u8 bpp (4 / 8 / 32) | u8 psm | u16 clut entries | u16 w | u16 h | u32 pixel bytes
    | u32 clut offset | u32 pixel offset | 12 bytes 0          (offsets from the payload start)
    psm low nibble 3/4 = 16-bit CLUT entries (RGBA5551, bit 15 = opaque), 0x13/0x14 = 32-bit
    (RGBA, alpha 0x80 = opaque). 8bpp CLUTs are stored in the GS CSM1 order (entries 8..15 and
    16..23 of every 32 swapped). 4bpp pixels: low nibble = left pixel. Pixels are linear rows.
    The game draws sprites from these sheets by rectangle, so an edit must stay inside the
    rectangle of the element it replaces.

Edits never touch a CLUT: every pixel the edit does not change keeps its original index, and a
changed pixel takes the nearest colour among the indices the texture already uses. apply()
refuses to write if any index outside an edit's clip changed. Identical copies of a texture
(the same sheet in several entries) are found by content hash and all patched.

Spec (JSON, translation/images.en.json): {"styles": {name: {edit keys}}, "textures": [item, ...]}
    (a bare list of items also works). item:
    {"tex": "<chunk id>_<record offset>", "sha": "<sha1 prefix of clut+pixels>", "note": "...",
     "edits": [edit, ...]}
    edit keys:
      clip  [x0, y0, x1, y1]      the only pixels this edit may change (x1/y1 exclusive)
      bg    "rows"  each row refilled by interpolating the pixels just left/right of the clip
            "cols"  same per column, from the pixels just above/below
            "copy"  fill from the same-size block at clip + src [dx, dy] (repeating patterns)
            "rowmode" each row refilled with that row's most common index inside the clip
                    (vertical-gradient button faces); "colmode" the same per column;
                    mode_x [a, b] takes the modes from those columns instead, and lo/hi drop
                    pixels outside that luma range (text ink) from the count
            "bestcol" every column replaced by one column of the clip: src_x if given, else the
                    most typical column (fewest light pixels and row-mode mismatches)
            "tile"  repeating pattern: each row rebuilt from the period-px strip just left of the
                    clip (src_l) and just right of it (src_r), blended across the clip; keys
                    period (default 12), src_l, src_r; src_tex = read the strips from another
                    texture (same layout) when this one has no clean columns
            "flat"  the most common index on the clip border
            "mode"  the most common index inside the clip
            "inpaint" (default) only the glyph pixels are removed and filled from around them
            "keep"  draw over the original (for adding text to an empty area)
            <int>   that palette index (pixel value)
      mask  for "inpaint": "dark" (luma below lo), "light" (luma above hi), "ink" (far from the
            local background, default), "all" (whole clip); lo / hi / dil tune it
      text  English, "\n" splits lines; omitted = erase only
      font  Medium | Bold | ExtraBold | Black (M PLUS Rounded 1c, translation/fonts)
      size  px; shrinks to fit the box when "fit" is true (default)
      box   [x0, y0, x1, y1] layout box (default = clip); align left|center|right,
            valign top|middle|bottom; lh line height (default size * 1.15); wrap true = wrap
            words to the box width
      fill  [r, g, b] or {"grad": [[r,g,b] top, [r,g,b] bottom]}
      outline [r, g, b]; ow outline width px (0 = none); shadow [dx, dy, [r,g,b]]
      spans  rich text instead of text: list of lines, each a list of [text, [r,g,b]] runs
      dx/dy  nudge the drawn text
      style  name of a preset in "styles"; the edit's own keys win

Usage:
    python bombtex.py list  <FILES.BIN>                         # unique textures, one per line
    python bombtex.py dump  <FILES.BIN> <outdir> [name ...]     # PNG per unique texture
    python bombtex.py apply <FILES.BIN> <spec.json> <out FILES.BIN> [--preview DIR]
    python bombtex.py grid  <FILES.BIN> <name> <out.png> [--scale N]   # authoring aid
    python bombtex.py mkpatch <stock FILES.BIN> <patched FILES.BIN> <out .btp>
    python bombtex.py patch   <FILES.BIN> <.btp> <out FILES.BIN>        # stdlib only

.btp (what the installer ships, so it needs no numpy / fonts / OpenCV and the result is the same
on every machine): zlib of  "BTP1" | u32 runs | 20-byte sha1 of the stock bytes of every run,
concatenated | runs of {u32 offset, u32 length, new bytes}. patch() refuses a FILES.BIN whose
bytes under the runs are not the stock ones. The runs only cover texture pixels, so the message
rebuild (bombtext msg-build) can run before or after.
"""

import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIRS = [os.path.join(HERE, "..", "translation", "fonts"),
             os.path.join(HERE, "translation", "fonts"),
             os.path.join(HERE, "fonts")]


# ------------------------------------------------------------------ container

def entries(d):
    out = []
    for i in range(0, 0x8000, 8):
        s, n = struct.unpack_from("<II", d, i)
        if s == 0 and n == 0:
            break
        out.append((s * 0x800, n))
    return out


def chunks(d):
    """(entry, chunk id, payload offset, payload size) for every chunk."""
    for ei, (p, n) in enumerate(entries(d)):
        end = p + n
        while p + 16 <= end:
            cid, sz, real, _ = struct.unpack_from("<IIII", d, p)
            if cid == 0xFFFFFFFF:
                break
            yield ei, cid, p + 16, sz
            p += 16 + sz


class Tex:
    __slots__ = ("entry", "cid", "base", "rec", "bpp", "psm", "ncl", "w", "h", "size", "co", "po")

    def __init__(self, **k):
        for a, v in k.items():
            setattr(self, a, v)

    @property
    def name(self):
        return "%03x_%05x" % (self.cid, self.rec)

    @property
    def es(self):
        return 4 if self.psm & 0x10 else 2

    @property
    def ncolors(self):
        return 1 << self.bpp


def scan(d):
    """Every texture record. The record test is strict enough that chunk data does not pass it."""
    import numpy as np
    out = []
    for ei, cid, base, sz in chunks(d):
        n4 = (sz - 0x20) // 4
        if n4 <= 0:
            continue
        w32 = np.zeros(n4 + 8, dtype="<u4")
        avail = min(n4 + 8, (len(d) - base) // 4)
        w32[:avail] = np.frombuffer(d, dtype="<u4", count=avail, offset=base)
        w0, w1, w2, w3, w4 = (w32[k:k + n4].astype(np.int64) for k in range(5))
        bpp, psm, ncl = w0 & 0xFF, (w0 >> 8) & 0xFF, w0 >> 16
        w, h = w1 & 0xFFFF, w1 >> 16
        o = np.arange(n4, dtype=np.int64) * 4
        ok = ((bpp == 4) | (bpp == 8)) & np.isin(psm & 0x0F, (3, 4)) & ((psm & 0xE0) == 0)
        ok &= (w > 0) & (w <= 1024) & (h > 0) & (h <= 1024) & (w2 == w * h * bpp // 8)
        ok &= ((ncl == 16) | (ncl == 256)) & (w4 >= o + 0x20) & (w4 + w2 <= sz)
        es = np.where(psm & 0x10, 4, 2)
        cl = (1 << bpp) * es
        ok &= (w3 + cl <= sz) & ~((w3 < w4) & (w4 < w3 + cl))
        for i in np.nonzero(ok)[0]:
            out.append(Tex(entry=ei, cid=cid, base=base, rec=int(o[i]), bpp=int(bpp[i]), psm=int(psm[i]),
                           ncl=int(ncl[i]), w=int(w[i]), h=int(h[i]), size=int(w2[i]), co=int(w3[i]),
                           po=int(w4[i])))
    return out


def csm(i):
    return (i & ~0x18) | ((i & 8) << 1) | ((i & 16) >> 1)


def palette(d, t):
    """RGBA (0..255) for each PIXEL VALUE."""
    n = t.ncolors
    a0 = t.base + t.co
    if t.es == 4:
        raw = [tuple(d[a0 + 4 * i:a0 + 4 * i + 4]) for i in range(n)]
        raw = [(r, g, b, min(255, a * 2)) for r, g, b, a in raw]
    else:
        raw = []
        for i in range(n):
            v = struct.unpack_from("<H", d, a0 + 2 * i)[0]
            raw.append(((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31,
                        ((v >> 10) & 31) * 255 // 31, 255 if v >> 15 else 0))
    if t.bpp == 8:
        raw = [raw[csm(i)] for i in range(256)]
    return raw


def get_indices(d, t):
    import numpy as np
    px = np.frombuffer(bytes(d[t.base + t.po:t.base + t.po + t.size]), dtype=np.uint8)
    if t.bpp == 4:
        px = np.stack([px & 15, px >> 4], axis=1).reshape(-1)
    return px.reshape(t.h, t.w).copy()


def put_indices(buf, t, idx):
    import numpy as np
    flat = idx.astype(np.uint8).reshape(-1)
    if t.bpp == 4:
        flat = (flat[0::2] & 15) | ((flat[1::2] & 15) << 4)
    buf[t.base + t.po:t.base + t.po + t.size] = flat.astype(np.uint8).tobytes()


def content_sha(d, t):
    h = hashlib.sha1()
    h.update(bytes(d[t.base + t.co:t.base + t.co + t.ncolors * t.es]))
    h.update(bytes(d[t.base + t.po:t.base + t.po + t.size]))
    return h.hexdigest()


def unique(d, texs=None):
    """{sha: [Tex, ...]} with the first-seen copy first."""
    groups = {}
    for t in texs if texs is not None else scan(d):
        groups.setdefault(content_sha(d, t), []).append(t)
    return groups


def to_image(d, t, idx=None):
    from PIL import Image
    import numpy as np
    pal = np.array(palette(d, t), dtype=np.uint8)
    if idx is None:
        idx = get_indices(d, t)
    return Image.fromarray(pal[idx], "RGBA")


# ------------------------------------------------------------------ rendering

_fonts = {}


def font(name, size):
    from PIL import ImageFont
    k = (name, size)
    if k not in _fonts:
        for fd in FONT_DIRS:
            p = os.path.join(fd, "MPLUSRounded1c-%s.ttf" % name)
            if os.path.exists(p):
                _fonts[k] = ImageFont.truetype(p, size)
                break
        else:
            raise SystemExit("font MPLUSRounded1c-%s.ttf not found in %s" % (name, FONT_DIRS))
    return _fonts[k]


def _luma(a):
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def _dilate(m, r):
    import numpy as np
    if r <= 0:
        return m
    out = m.copy()
    h, w = m.shape
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r * r + r:
                continue
            ys, yd = (slice(dy, h), slice(0, h - dy)) if dy >= 0 else (slice(0, h + dy), slice(-dy, h))
            xs, xd = (slice(dx, w), slice(0, w - dx)) if dx >= 0 else (slice(0, w + dx), slice(-dx, w))
            out[yd, xd] |= m[ys, xs]
    return out


def _inpaint(rgba, mask):
    """Fill mask pixels from their surroundings. OpenCV TELEA when present, else diffusion."""
    import numpy as np
    try:
        import cv2
        rgb = np.ascontiguousarray(rgba[..., :3])
        m8 = mask.astype(np.uint8) * 255
        out = rgba.copy()
        out[..., :3] = cv2.inpaint(rgb, m8, 3, cv2.INPAINT_TELEA)
        a = np.ascontiguousarray(rgba[..., 3])
        out[..., 3] = cv2.inpaint(a, m8, 3, cv2.INPAINT_TELEA)
        return out
    except ImportError:
        pass
    img = rgba.astype(np.float32)
    known = ~mask
    # seed holes with the mean of known pixels, then Jacobi-relax
    if known.any():
        img[mask] = img[known].mean(axis=0)
    for _ in range(400):
        p = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode="edge")
        avg = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]) / 4
        img[mask] = avg[mask]
    return np.clip(img + 0.5, 0, 255).astype(np.uint8)


def _layout(lines_spec, e, box):
    """Pick a size that fits; return (font size, [(line runs, width)], line height)."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    fname = e.get("font", "Black")
    size = int(e.get("size", 16))
    ow = int(e.get("ow", 0))
    dr = ImageDraw.Draw(Image.new("L", (1, 1)))
    minsize = int(e.get("minsize", 7))
    while True:
        f = font(fname, size)
        lh = e.get("lh")
        lh = int(lh * size / e.get("size", size)) if lh else int(round(size * 1.15))
        lines = []
        for runs in lines_spec:
            if e.get("wrap") and len(runs) == 1:
                txt, col = runs[0]
                words = txt.split(" ")
                cur = ""
                for wd in words:
                    t2 = (cur + " " + wd) if cur else wd
                    if dr.textlength(t2, font=f) + 2 * ow <= bw or not cur:
                        cur = t2
                    else:
                        lines.append([[cur, col]])
                        cur = wd
                lines.append([[cur, col]])
            else:
                lines.append(runs)
        widths = [sum(dr.textlength(t, font=f) for t, _ in r) + 2 * ow for r in lines]
        th = lh * (len(lines) - 1) + size + 2 * ow
        if (max(widths) <= bw and th <= bh + 2) or not e.get("fit", True) or size <= minsize:
            return size, list(zip(lines, widths)), lh
        size -= 1


def render_text(rgba, e):
    """Draw the edit's text onto rgba (H, W, 4 uint8) in place."""
    import numpy as np
    from PIL import Image, ImageDraw
    if "spans" in e:
        lines_spec = [[[t, tuple(c)] for t, c in line] for line in e["spans"]]
    elif e.get("text"):
        fill = e.get("fill", [255, 255, 255])
        lines_spec = [[[ln, None if isinstance(fill, dict) else tuple(fill)]]
                      for ln in e["text"].split("\n")]
    else:
        return
    box = e.get("box", e["clip"])
    size, lines, lh = _layout(lines_spec, e, box)
    f = font(e.get("font", "Black"), size)
    ow = int(e.get("ow", 0))
    x0, y0, x1, y1 = box
    th = lh * (len(lines) - 1) + size
    va = e.get("valign", "middle")
    asc, desc = f.getmetrics()
    # place by the cap/x-height band rather than the full em so the text sits visually centred
    ty = {"top": y0 + ow, "bottom": y1 - th - ow}.get(va, y0 + (y1 - y0 - th) / 2.0)
    ty += e.get("dy", 0) - (asc - size) * 0.5 - size * 0.08
    H, W = rgba.shape[:2]
    canvas = Image.fromarray(rgba, "RGBA")
    al = e.get("align", "center")
    sh = e.get("shadow")
    for li, (runs, width) in enumerate(lines):
        if al == "left":
            tx = x0 + ow
        elif al == "right":
            tx = x1 - width + ow
        else:
            tx = x0 + (x1 - x0 - width) / 2.0 + ow
        tx += e.get("dx", 0)
        y = ty + li * lh
        for txt, col in runs:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            if sh:
                d.text((tx + sh[0], y + sh[1]), txt, font=f, fill=tuple(sh[2]) + (255,),
                       stroke_width=ow, stroke_fill=tuple(sh[2]) + (255,))
            if ow:
                d.text((tx, y), txt, font=f, fill=tuple(e["outline"]) + (255,),
                       stroke_width=ow, stroke_fill=tuple(e["outline"]) + (255,))
            fill = e.get("fill", [255, 255, 255])
            if col is None and isinstance(fill, dict):
                m = Image.new("L", (W, H), 0)
                ImageDraw.Draw(m).text((tx, y), txt, font=f, fill=255)
                top, bot = np.array(fill["grad"][0], float), np.array(fill["grad"][1], float)
                bb = m.getbbox() or (0, 0, W, H)
                g = np.zeros((H, W, 4), np.uint8)
                span = max(1, bb[3] - bb[1] - 1)
                for yy in range(H):
                    t = min(1.0, max(0.0, (yy - bb[1]) / span))
                    g[yy, :, :3] = (top * (1 - t) + bot * t).astype(np.uint8)
                g[..., 3] = np.array(m)
                layer = Image.alpha_composite(layer, Image.fromarray(g, "RGBA"))
            else:
                c = tuple(col if col is not None else fill)
                d.text((tx, y), txt, font=f, fill=c + (255,))
            canvas = Image.alpha_composite(canvas, layer)
            tx += d.textlength(txt, font=f)
    rgba[...] = np.array(canvas)


def edit_texture(d, t, edits):
    """New index array for texture t after the edits; asserts nothing outside the clips moved."""
    import numpy as np
    pal = np.array(palette(d, t), dtype=np.int32)
    idx0 = get_indices(d, t)
    used = np.unique(idx0)
    cand = pal[used]
    rgba = pal[idx0].astype(np.uint8)
    out = rgba.copy()
    allowed = np.zeros(idx0.shape, bool)
    forced = np.full(idx0.shape, -1, np.int32)   # exact index for flat / copied fills
    for e in edits:
        x0, y0, x1, y1 = e["clip"]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(t.w, x1), min(t.h, y1)
        allowed[y0:y1, x0:x1] = True
        reg = out[y0:y1, x0:x1]
        bg = e.get("bg", "inpaint")
        if bg == "rows":
            l = out[y0:y1, max(0, x0 - 1)].astype(float)
            r = out[y0:y1, min(t.w - 1, x1)].astype(float)
            ww = x1 - x0
            for i in range(ww):
                a = (i + 1) / (ww + 1)
                reg[:, i] = (l * (1 - a) + r * a + 0.5).astype(np.uint8)
        elif bg == "cols":
            u = out[max(0, y0 - 1), x0:x1].astype(float)
            b = out[min(t.h - 1, y1), x0:x1].astype(float)
            hh = y1 - y0
            for i in range(hh):
                a = (i + 1) / (hh + 1)
                reg[i, :] = (u * (1 - a) + b * a + 0.5).astype(np.uint8)
        elif bg == "copy":
            dx, dy = e["src"]
            reg[...] = rgba[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
            forced[y0:y1, x0:x1] = idx0[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
        elif bg == "bestcol":
            if "src_x" in e:
                sx = e["src_x"]
            else:
                # the most typical column: light pixels count against it, and so does every
                # row where it differs from that row's most common index
                sub = idx0[y0:y1, x0:x1]
                lu = _luma(rgba[y0:y1, x0:x1].astype(float))
                mode = np.array([np.bincount(r).argmax() for r in sub])
                score = (lu > e.get("hi", 170)).sum(axis=0) * 2 + (sub != mode[:, None]).sum(axis=0)
                sx = x0 + int(score.argmin())
            col = idx0[y0:y1, sx]
            reg[...] = pal[col][:, None, :]
            forced[y0:y1, x0:x1] = col[:, None]
        elif bg == "tile":
            P = int(e.get("period", 12))
            sl = int(e.get("src_l", x0 - P))
            sr = int(e.get("src_r", x1))
            srcimg = rgba
            if e.get("src_tex"):
                st = _TEXCACHE[e["src_tex"]]
                srcimg = np.array(palette(d, st), dtype=np.int32)[get_indices(d, st)]
            L = srcimg[y0:y1, sl:sl + P].astype(float)
            R = srcimg[y0:y1, sr:sr + P].astype(float)
            ww = x1 - x0
            for i in range(ww):
                x = x0 + i
                a = (i + 0.5) / ww
                reg[:, i] = (L[:, (x - sl) % P] * (1 - a) + R[:, (x - sr) % P] * a + 0.5).astype(np.uint8)
        elif bg in ("rowmode", "colmode"):
            mx0, mx1 = e.get("mode_x", (x0, x1))
            sub = idx0[y0:y1, x0:x1]
            src = idx0[y0:y1, mx0:mx1]
            lum = _luma(rgba[y0:y1, mx0:mx1].astype(float))
            if bg == "colmode":
                sub, src, lum = sub.T, src.T, lum.T
            fill = np.empty_like(sub)
            for i, line in enumerate(src):
                keep = line[(lum[i] < e.get("hi", 256)) & (lum[i] > e.get("lo", -1))]
                vals, cnts = np.unique(keep if len(keep) else line, return_counts=True)
                fill[i] = vals[cnts.argmax()]
            if bg == "colmode":
                fill = fill.T
            reg[...] = pal[fill]
            forced[y0:y1, x0:x1] = fill
        elif bg in ("flat", "mode") or isinstance(bg, int):
            if bg == "mode":
                vals, cnts = np.unique(idx0[y0:y1, x0:x1], return_counts=True)
                bi = int(vals[cnts.argmax()])
            elif bg == "flat":
                ring = np.concatenate([idx0[y0, x0:x1], idx0[y1 - 1, x0:x1],
                                       idx0[y0:y1, x0], idx0[y0:y1, x1 - 1]])
                vals, cnts = np.unique(ring, return_counts=True)
                bi = int(vals[cnts.argmax()])
            else:
                bi = bg
            reg[...] = pal[bi]
            forced[y0:y1, x0:x1] = bi
        elif bg == "inpaint":
            sub = rgba[y0:y1, x0:x1].astype(float)
            lu = _luma(sub)
            mode = e.get("mask", "ink")
            if mode == "dark":
                m = lu < e.get("lo", 150)
            elif mode == "light":
                m = lu > e.get("hi", 200)
            elif mode == "all":
                m = np.ones(lu.shape, bool)
            else:
                # far from the median colour of the clip border
                ring = np.concatenate([sub[0], sub[-1], sub[:, 0], sub[:, -1]])
                med = np.median(ring, axis=0)
                m = np.abs(sub - med)[..., :3].sum(axis=2) > e.get("thr", 90)
            m = _dilate(m, int(e.get("dil", 1)))
            # pad the region so the inpaint sees context, then cut back to the clip
            px = int(e.get("ctx", 6))
            X0, Y0 = max(0, x0 - px), max(0, y0 - px)
            X1, Y1 = min(t.w, x1 + px), min(t.h, y1 + px)
            big = out[Y0:Y1, X0:X1].copy()
            bm = np.zeros(big.shape[:2], bool)
            bm[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = m
            filled = _inpaint(big, bm)
            reg[...] = filled[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0]
        # "keep": draw over what is there
        render_text(out, e)
    # back to indices: unchanged pixels keep their index; forced pixels take theirs unless text
    # covered them; others take the nearest used colour
    new = idx0.copy()
    changed = np.any(out != rgba, axis=2) & allowed
    fm = forced >= 0
    fm &= np.all(out == pal[np.where(fm, forced, 0)].astype(np.uint8), axis=2)
    new[fm] = forced[fm]
    changed &= ~fm
    ys, xs = np.nonzero(changed)
    if len(ys):
        px = out[ys, xs].astype(np.int32)
        wgt = np.array([1, 1, 1, 2])
        dist = (((px[:, None, :] - cand[None, :, :]) ** 2) * wgt).sum(axis=2)
        new[ys, xs] = used[dist.argmin(axis=1)]
    leak = int(((new != idx0) & ~allowed).sum())
    if leak:
        raise SystemExit("%s: %d pixels changed outside the clips" % (t.name, leak))
    return new


# ------------------------------------------------------------------ commands

def load_spec(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def expand(spec):
    """Items with every edit's style preset merged in."""
    if isinstance(spec, list):
        return spec
    styles = spec.get("styles", {})
    out = []
    for item in spec["textures"]:
        eds = []
        for e in item.get("edits", []):
            m = dict(styles.get(e["style"], {})) if "style" in e else {}
            m.update(e)
            eds.append(m)
        out.append(dict(item, edits=eds))
    return out


_TEXCACHE = {}


def apply(d, spec, preview=None):
    """Return a patched copy of FILES.BIN bytes."""
    spec = expand(spec)
    buf = bytearray(d)
    groups = unique(d)
    _TEXCACHE.clear()
    for ts in groups.values():
        for t in ts:
            _TEXCACHE[t.name] = t
    by_name = {}
    for sha, ts in groups.items():
        for t in ts:
            by_name[t.name] = (sha, t)
    done = 0
    for item in spec:
        if not item.get("edits"):
            continue
        if item["tex"] not in by_name:
            raise SystemExit("texture %s not found" % item["tex"])
        sha, t = by_name[item["tex"]]
        if item.get("sha") and not sha.startswith(item["sha"]):
            raise SystemExit("texture %s: content differs from the spec (sha %s)" % (t.name, sha[:12]))
        new = edit_texture(d, t, item["edits"])
        for c in groups[sha]:
            put_indices(buf, c, new)
            done += 1
        if preview:
            os.makedirs(preview, exist_ok=True)
            from PIL import Image
            a, b = to_image(d, t), to_image(d, t, new)
            w, h = a.size
            im = Image.new("RGBA", (w, h * 2 + 4), (255, 0, 255, 255))
            im.paste(a, (0, 0))
            im.paste(b, (0, h + 4))
            im.save(os.path.join(preview, t.name + ".png"))
    return bytes(buf), done


def make_patch(stock, new, gap=16):
    import zlib
    if len(stock) != len(new):
        raise SystemExit("sizes differ")
    runs = []
    i, n = 0, len(stock)
    mv_a, mv_b = memoryview(stock), memoryview(new)
    blk = 4096
    while i < n:
        j = min(n, i + blk)
        if mv_a[i:j] == mv_b[i:j]:
            i = j
            continue
        for k in range(i, j):
            if stock[k] != new[k]:
                if runs and k - runs[-1][1] <= gap:
                    runs[-1][1] = k + 1
                else:
                    runs.append([k, k + 1])
        i = j
    h = hashlib.sha1()
    body = bytearray()
    for a, b in runs:
        h.update(stock[a:b])
        body += struct.pack("<II", a, b - a) + new[a:b]
    out = b"BTP1" + struct.pack("<I", len(runs)) + h.digest() + bytes(body)
    return zlib.compress(out, 9), len(runs), sum(b - a for a, b in runs)


def apply_patch(data, btp):
    import zlib
    raw = zlib.decompress(btp)
    if raw[:4] != b"BTP1":
        raise SystemExit("not a bombtex patch")
    nruns, = struct.unpack_from("<I", raw, 4)
    want = raw[8:28]
    p = 28
    runs = []
    for _ in range(nruns):
        a, ln = struct.unpack_from("<II", raw, p)
        runs.append((a, raw[p + 8:p + 8 + ln]))
        p += 8 + ln
    h = hashlib.sha1()
    for a, b in runs:
        h.update(data[a:a + len(b)])
    if h.digest() != want:
        raise SystemExit("FILES.BIN texture bytes are not the stock ones; patch not applied")
    out = bytearray(data)
    for a, b in runs:
        out[a:a + len(b)] = b
    return bytes(out)


def cmd_list(path):
    d = open(path, "rb").read()
    for sha, ts in unique(d).items():
        t = ts[0]
        print("%s\t%s\t%dx%d\t%dbpp\t%s" % (t.name, sha[:12], t.w, t.h, t.bpp,
                                            ",".join(c.name for c in ts[1:])))


def cmd_dump(path, outdir, names):
    d = open(path, "rb").read()
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for sha, ts in unique(d).items():
        t = ts[0]
        if names and t.name not in names:
            continue
        to_image(d, t).save(os.path.join(outdir, "%s_%dx%d.png" % (t.name, t.w, t.h)))
        n += 1
    print("%d textures" % n)


def cmd_grid(path, name, out, scale=2):
    from PIL import Image, ImageDraw
    d = open(path, "rb").read()
    t = [x for x in scan(d) if x.name == name][0]
    im = to_image(d, t)
    bg = Image.new("RGBA", im.size, (255, 0, 255, 255))
    im = Image.alpha_composite(bg, im).resize((t.w * scale, t.h * scale), Image.NEAREST)
    dr = ImageDraw.Draw(im)
    for x in range(0, t.w, 8):
        c = (0, 255, 0, 255) if x % 40 == 0 else (0, 120, 0, 255)
        dr.line([(x * scale, 0), (x * scale, t.h * scale)], fill=c if x % 40 == 0 else (0, 90, 0, 90))
        if x % 40 == 0:
            dr.text((x * scale + 1, 0), str(x), fill=(255, 255, 0, 255))
    for y in range(0, t.h, 8):
        c = (0, 255, 0, 255) if y % 40 == 0 else (0, 90, 0, 90)
        dr.line([(0, y * scale), (t.w * scale, y * scale)], fill=c)
        if y % 40 == 0:
            dr.text((0, y * scale + 1), str(y), fill=(255, 255, 0, 255))
    im.save(out)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "list":
        cmd_list(argv[2])
    elif cmd == "dump":
        cmd_dump(argv[2], argv[3], set(argv[4:]))
    elif cmd == "grid":
        sc = int(argv[argv.index("--scale") + 1]) if "--scale" in argv else 2
        cmd_grid(argv[2], argv[3], argv[4], sc)
    elif cmd == "mkpatch":
        btp, nr, nb = make_patch(open(argv[2], "rb").read(), open(argv[3], "rb").read())
        with open(argv[4], "wb") as f:
            f.write(btp)
        print("%d runs, %d bytes changed, %d bytes compressed -> %s" % (nr, nb, len(btp), argv[4]))
    elif cmd == "patch":
        out = apply_patch(open(argv[2], "rb").read(), open(argv[3], "rb").read())
        with open(argv[4], "wb") as f:
            f.write(out)
        print("patched -> %s" % argv[4])
    elif cmd == "apply":
        prev = argv[argv.index("--preview") + 1] if "--preview" in argv else None
        d = open(argv[2], "rb").read()
        out, n = apply(d, load_spec(argv[3]), prev)
        with open(argv[4], "wb") as f:
            f.write(out)
        print("%d texture copies patched -> %s" % (n, argv[4]))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
