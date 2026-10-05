#
# HippaulInstaller - PlayOnline for the PlayStation 2
# Copyright (C) 2026 PrettyOpenLobby
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Minna no Golf Online: English menu images, applied to the player's own disc.

Many menu bitmaps inside the .XB asset containers have Japanese baked in. The
pack ships no images: images/recipes.json holds per-image edit operations that
run on the player's own decoded bitmaps, in palette-index space, on the staged
disc tree (after copy_tree, before the partition write).

recipes.json:
  {"targets": {"<disc path of .XB>": {
       "original_sha1": "<sha1 of the disc .XB>",
       "entries": {"<inner path>": {"entry_sha1": "<sha1 of decoded bitmap>",
                                    "ops": [ ... ]}}}},
   "sources": {"<disc path of .XB>": {"original_sha1": ...}}}   (for copy ops)

ops (x0,y0,x1,y1 are pixel rects, top-left origin):
  {"op": "fill",  "rect": [x0,y0,x1,y1], "index": i}
  {"op": "patch", "rect": [x0,y0,x1,y1], "data": base64(zlib(w*h index bytes)),
        "keep": [[x0,y0,x1,y1], ...]}   (optional)
        Our own rendered indices (all 0..255 are colours). Pixels inside a
        "keep" rect are left as they are (original glyphs such as button icons).
  {"op": "copy",  "src": "<xb path>", "entry": "<inner path>", "entry_sha1": ...,
        "from": [x0,y0,x1,y1], "to": [x,y], "remap": {"srcIndex": dstIndex}}
        official art from another bitmap on the same disc.

A target is skipped (stays Japanese) unless every sha1 matches and the rebuilt
container is no larger than the original (the game's load buffers).
"""
import base64
import hashlib
import json
import os
import struct
import zlib

try:
    from . import xbcodec  # same package in the installer
except ImportError:
    import xbcodec


class IndexedBMP:
    """4/8bpp BMP with pixel indices editable; header and palette kept."""

    def __init__(self, data):
        self.raw = bytearray(data)
        if data[:2] != b'BM':
            raise ValueError('not a BMP')
        self.off = struct.unpack_from('<I', data, 10)[0]
        self.w = struct.unpack_from('<i', data, 18)[0]
        h = struct.unpack_from('<i', data, 22)[0]
        self.bottom_up = h > 0
        self.h = abs(h)
        self.bpp = struct.unpack_from('<H', data, 28)[0]
        if self.bpp not in (4, 8):
            raise ValueError('only 4/8bpp')
        ncol = (self.off - 54) // 4
        self.palette = [tuple(data[54 + 4 * i + k] for k in (2, 1, 0)) for i in range(ncol)]
        self.stride = ((self.w * self.bpp + 31) // 32) * 4
        self.px = []
        for y in range(self.h):
            row = self.off + (self.h - 1 - y if self.bottom_up else y) * self.stride
            if self.bpp == 8:
                self.px.append(list(data[row:row + self.w]))
            else:
                r = []
                for x in range(self.w):
                    b = data[row + x // 2]
                    r.append((b >> 4) if x % 2 == 0 else (b & 0x0f))
                self.px.append(r)

    def to_bytes(self):
        out = bytearray(self.raw)
        for y in range(self.h):
            row = self.off + (self.h - 1 - y if self.bottom_up else y) * self.stride
            if self.bpp == 8:
                out[row:row + self.w] = bytes(self.px[y])
            else:
                for x in range(0, self.w, 2):
                    a = self.px[y][x]
                    b = self.px[y][x + 1] if x + 1 < self.w else 0
                    out[row + x // 2] = (a << 4) | b
        return bytes(out)


KEEP = 255


def encode_patch(rows):
    return base64.b64encode(zlib.compress(bytes(v for r in rows for v in r), 9)).decode('ascii')


def _apply_ops(img, ops, sources):
    for op in ops:
        k = op['op']
        if k == 'fill':
            x0, y0, x1, y1 = op['rect']
            for y in range(y0, y1):
                for x in range(x0, x1):
                    img.px[y][x] = op['index']
        elif k == 'patch':
            x0, y0, x1, y1 = op['rect']
            w = x1 - x0
            data = zlib.decompress(base64.b64decode(op['data']))
            if len(data) != w * (y1 - y0):
                raise ValueError('patch size mismatch')
            keep = [tuple(r) for r in op.get('keep', ())]
            for y in range(y0, y1):
                for x in range(x0, x1):
                    if keep and any(a <= x < c and b <= y < d for a, b, c, d in keep):
                        continue
                    img.px[y][x] = data[(y - y0) * w + (x - x0)]
        elif k == 'inpaint':
            _inpaint(img, op['rect'], _unbits(op['mask'], op['rect']), op.get('mode', 'index'),
                     op.get('shifts'), [tuple(r) for r in op.get('avoid', ())])
        elif k == 'overlay':
            _overlay(img, op['rect'], zlib.decompress(base64.b64decode(op['rgba'])),
                     op.get('colours'))
        elif k == 'copy':
            src = sources[(op['src'], op['entry'])]
            x0, y0, x1, y1 = op['from']
            tx, ty = op['to']
            remap = {int(a): b for a, b in op.get('remap', {}).items()}
            for y in range(y0, y1):
                for x in range(x0, x1):
                    v = src.px[y][x]
                    img.px[ty + y - y0][tx + x - x0] = remap.get(v, v)
        else:
            raise ValueError('unknown op %r' % k)


# ---- photographs: install-time inpainting + composited text -------------------
# inpaint {rect, mask}: mask = base64(zlib(packed bits, row-major, MSB first))
#   marking the pixels that held the Japanese text; they are refilled from the
#   player's own surrounding pixels (diffusion inward, then a light 3x3 blur).
# overlay {rect, rgba}: base64(zlib(w*h*4 bytes)) - our rendered English with
#   alpha, blended over the current pixels and snapped to the palette.

def bits_encode(mask_rows):
    out = bytearray()
    acc = n = 0
    for row in mask_rows:
        for v in row:
            acc = (acc << 1) | (1 if v else 0); n += 1
            if n == 8:
                out.append(acc); acc = n = 0
    if n:
        out.append(acc << (8 - n))
    return base64.b64encode(zlib.compress(bytes(out), 9)).decode('ascii')


def _unbits(b64, rect):
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    data = zlib.decompress(base64.b64decode(b64))
    return [[(data[(y * w + x) >> 3] >> (7 - ((y * w + x) & 7))) & 1 for x in range(w)] for y in range(h)]


class _Quant:
    def __init__(self, palette):
        self.pal = palette; self.cache = {}

    def __call__(self, c):
        i = self.cache.get(c)
        if i is None:
            best = None
            for j, p in enumerate(self.pal):
                d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2
                if best is None or d < best[0]:
                    best = (d, j)
            i = self.cache[c] = best[1]
        return i


def _inpaint(img, rect, mask, mode='index', shifts=None, avoid=()):
    if mode == 'shift':
        return _inpaint_shift(img, rect, mask, shifts or [[0, -40], [0, 40], [0, -80], [0, 80]],
                              avoid)
    if mode == 'index':
        return _inpaint_index(img, rect, mask)
    return _inpaint_avg(img, rect, mask)


def _inpaint_shift(img, rect, mask, shifts, avoid=()):
    """Texture fill: each masked pixel copies the pixel at the first offset in
    `shifts` that lies inside the image, outside this op's mask and outside the
    `avoid` rects (absolute; e.g. kept icons); leftovers fall back to index
    propagation."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    src = [row[:] for row in img.px]          # read from the untouched image
    left = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                continue
            for dx, dy in shifts:
                sx, sy = x + dx, y + dy
                inside = 0 <= sx < w and 0 <= sy < h
                ax, ay = x0 + sx, y0 + sy
                if not (0 <= ax < img.w and 0 <= ay < img.h):
                    continue
                if inside and mask[sy][sx]:
                    continue
                if any(a <= ax < c and b <= ay < d for a, b, c, d in avoid):
                    continue
                img.px[y0 + y][x0 + x] = src[ay][ax]
                break
            else:
                left[y][x] = 1
    if any(any(r) for r in left):
        _inpaint_index(img, rect, left)


def _inpaint_index(img, rect, mask):
    """Fill masked pixels by propagating the nearest known pixel's palette index
    inward (onion peeling; ties pick the horizontally nearest, then the
    vertical). Reuses the photo's own index patterns, which keeps the rebuilt
    container small."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    idx = [[img.px[y0 + y][x0 + x] for x in range(w)] for y in range(h)]
    known = [[not mask[y][x] for x in range(w)] for y in range(h)]
    todo = [(x, y) for y in range(h) for x in range(w) if mask[y][x]]
    order = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1))
    while todo:
        upd, rest = [], []
        for x, y in todo:
            for dx, dy in order:
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h and known[yy][xx]:
                    upd.append((x, y, idx[yy][xx])); break
            else:
                rest.append((x, y))
        if not upd:
            break
        for x, y, v in upd:
            idx[y][x] = v; known[y][x] = True
        todo = rest
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                img.px[y0 + y][x0 + x] = idx[y][x]


def _inpaint_avg(img, rect, mask):
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    pal = img.palette
    px = [[list(pal[img.px[y0 + y][x0 + x]]) for x in range(w)] for y in range(h)]
    known = [[not mask[y][x] for x in range(w)] for y in range(h)]
    todo = [(x, y) for y in range(h) for x in range(w) if mask[y][x]]
    nb = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1))
    while todo:
        upd, rest = [], []
        for x, y in todo:
            r = g = b = n = 0
            for dx, dy in nb:
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h and known[yy][xx]:
                    c = px[yy][xx]; r += c[0]; g += c[1]; b += c[2]; n += 1
            if n:
                upd.append((x, y, [r // n, g // n, b // n]))
            else:
                rest.append((x, y))
        if not upd:
            break
        for x, y, c in upd:
            px[y][x] = c; known[y][x] = True
        todo = rest
    q = _Quant(pal)
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                r = g = b = n = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        xx, yy = x + dx, y + dy
                        if 0 <= xx < w and 0 <= yy < h:
                            c = px[yy][xx]; r += c[0]; g += c[1]; b += c[2]; n += 1
                img.px[y0 + y][x0 + x] = q((r // n, g // n, b // n))


def _overlay(img, rect, rgba, colours=None):
    """Blend our text layer over the image. With `colours` (palette indices),
    each blended pixel snaps to the nearest of those indices or the pixel's
    current index - few distinct values, so the container stays small."""
    x0, y0, x1, y1 = rect
    w = x1 - x0
    pal = img.palette
    q = _Quant(pal)
    for y in range(y0, y1):
        for x in range(x0, x1):
            i = ((y - y0) * w + (x - x0)) * 4
            a = rgba[i + 3]
            if a == 0:
                continue
            cur = img.px[y][x]
            c = pal[cur]
            r = (rgba[i] * a + c[0] * (255 - a)) // 255
            g = (rgba[i + 1] * a + c[1] * (255 - a)) // 255
            b = (rgba[i + 2] * a + c[2] * (255 - a)) // 255
            if colours is None:
                img.px[y][x] = q((r, g, b))
            else:
                best = None
                for j in list(colours) + [cur]:
                    p = pal[j]
                    dd = (p[0] - r) ** 2 + (p[1] - g) ** 2 + (p[2] - b) ** 2
                    if best is None or dd < best[0]:
                        best = (dd, j)
                img.px[y][x] = best[1]


def _sha1(b):
    return hashlib.sha1(b).hexdigest()


def apply(tree, recipes, note=print):
    """Rewrite the .XB files named in `recipes` under the staged disc `tree`.
    Returns {xb path: images changed}. Each target is independent: one that
    does not verify is left as it is (Japanese)."""
    def path_of(rel):
        return os.path.join(tree, *rel.split('/'))

    # decode the source bitmaps that copy ops need, verified
    sources = {}
    for rel, info in recipes.get('sources', {}).items():
        p = path_of(rel)
        if not os.path.isfile(p):
            continue
        d = open(p, 'rb').read()
        if _sha1(d) != info['original_sha1']:
            continue
        for path, data in xbcodec.decode_all(d):
            sources[(rel, path.decode('latin1'))] = (_sha1(data), data)

    done = {}
    for rel, tgt in sorted(recipes.get('targets', {}).items()):
        p = path_of(rel)
        if not os.path.isfile(p):
            note('images: %s not in the tree, skipped' % rel)
            continue
        orig = open(p, 'rb').read()
        if _sha1(orig) != tgt['original_sha1']:
            note('images: %s is not the disc copy the recipe was made for, skipped' % rel)
            continue
        try:
            entries = {path.decode('latin1'): data for path, data in xbcodec.decode_all(orig)}
            repl = {}
            for inner, spec in tgt['entries'].items():
                data = entries.get(inner)
                if data is None or _sha1(data) != spec['entry_sha1']:
                    raise ValueError('entry %s does not match' % inner)
                img = IndexedBMP(data)
                need = {}
                for op in spec['ops']:
                    if op['op'] == 'copy':
                        key = (op['src'], op['entry'])
                        if key not in sources or sources[key][0] != op['entry_sha1']:
                            raise ValueError('copy source %s:%s missing' % key)
                        need[key] = IndexedBMP(sources[key][1])
                _apply_ops(img, spec['ops'], need)
                repl[inner.encode('latin1')] = img.to_bytes()
            new = xbcodec.build_all(orig, repl)
            if len(new) > len(orig):
                raise ValueError('rebuilt %d bytes > original %d' % (len(new), len(orig)))
        except Exception as e:
            note('images: %s skipped (%s)' % (rel, e))
            continue
        with open(p, 'wb') as f:
            f.write(new)
        done[rel] = len(tgt['entries'])
    return done


def load_recipes(data):
    r = json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
    if not isinstance(r, dict) or not isinstance(r.get('targets'), dict):
        raise ValueError('recipes.json has no targets')
    return r
