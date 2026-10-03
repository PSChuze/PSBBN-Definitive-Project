#!/usr/bin/env python3
"""pop'n Taisen Puzzle-dama Online - IMAGE.DAT texture codec + container tools.

The menu/login/logo/HELP/disc-check screens are pre-rendered 512x512 8bpp
indexed textures (grayscale-coverage ramp CLUT, tinted at draw time), stored in
IMAGE.DAT, LZ-compressed and GS-swizzled (PSMT8).

Reverse-engineered 2026-10-02 (session 2):
  - Container: 16-aligned blocks, header [0x10, off1, off2, off3] (relative) ->
    sub-streams. Each sub-stream = u32 decompressed_size + LZ token stream.
    Big (texture) streams start `a1 02 02 80` and inflate to 0x40410 bytes =
    0x10 header + 0x400 CLUT (256 x RGBA32) + 0x40000 image (512x512 @ 8bpp).
    Small streams start `e1 80` -> sprite/layout tables.
  - LZ codec = game function @0x123b70 (LZSS + RLE). See decompress().
  - Image bytes are PSMT8-swizzled; unswizzle8()/swizzle8() convert.

Usage:
  python pnimage.py list     <IMAGE.DAT>
  python pnimage.py extract  <IMAGE.DAT> <outdir>      # all textures -> PNG (unswizzled, dark-on-white)
  python pnimage.py rtcodec  <IMAGE.DAT>               # verify compress(decompress)==decode for every stream
"""
import struct, sys, os

# ---------------------------------------------------------------------------
# LZ codec (game @0x123b70): decode(dst,src,size). src points at u32 size.
# ---------------------------------------------------------------------------
def decompress(buf, off):
    """buf[off:] = u32 size + token stream. Returns (out_bytes, declared_size, consumed)."""
    size = struct.unpack_from('<I', buf, off)[0]
    out = bytearray(); p = off + 4; start = p; n = len(buf)
    while len(out) < size:
        t0 = buf[p]; t1 = buf[p + 1] if p + 1 < n else 0
        if ((t0 << 8) | t1) == 0x7fff:
            p += 2; break
        if (t0 & 0x80) == 0:                       # back-reference match
            length = (t0 >> 2) + 2
            dist = ((~(((t0 & 3) << 8) | t1)) & 0x3ff) + 1
            s = len(out) - dist
            for i in range(length):
                out.append(out[s + i])
            p += 2
        elif t0 < 0xa0:                            # literal run
            cnt = (t0 & 0x1f) + 1
            out += buf[p + 1:p + 1 + cnt]; p += cnt + 1
        elif t0 < 0xc0:                            # zero-interleave: (00, lit) x cnt
            cnt = (t0 & 0x1f) + 1
            for i in range(cnt):
                out.append(0); out.append(buf[p + 1 + i])
            p += cnt + 1
        elif t0 < 0xe0:                            # byte RLE
            b = buf[p + 1]; ln = (t0 & 0x1f) + 2
            out += bytes([b]) * ln; p += 2
        elif t0 != 0xff:                           # zero run (short)
            ln = (t0 & 0x1f) + 1
            out += bytes(ln); p += 1
        else:                                      # long zero run
            ln = buf[p + 1] + 0x20
            out += bytes(ln); p += 2
    return bytes(out), size, p - start


def compress(data, tries=512):
    """Encode `data` into a token stream the game decoder reproduces exactly,
    using near-optimal (cost-DP) parsing to match/beat Konami's ratio. Returns
    u32 size + tokens. Tokens: zero-run / long-zero / byte-RLE / match / literal."""
    data = bytes(data)
    n = len(data)
    if n == 0:
        return struct.pack('<I', 0) + b'\x7f\xff'

    # --- forward pass: longest match (dist in 1..1024, len 2..33) per position ---
    HSIZE = 1 << 16
    head = [-1] * HSIZE
    prev = [-1] * n
    mlen = bytearray(n)
    mdist = [0] * n
    run = bytearray(n)
    for i in range(n):
        m = min(33, n - i)
        # same-byte run length (cap 33)
        r = 1
        bi = data[i]
        while r < m and data[i + r] == bi:
            r += 1
        run[i] = r
        if i + 2 < n:
            hv = ((data[i] << 7) ^ (data[i + 1] << 4) ^ data[i + 2]) & (HSIZE - 1)
            j = head[hv]
            wstart = i - 1024
            bl = 0; bd = 0; t = tries
            while j >= 0 and j >= wstart and t > 0:
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
            if bl == 33 and bd == 1:                 # avoid 7fff END collision
                bl = 32
            mlen[i] = bl; mdist[i] = bd
            prev[i] = head[hv]; head[hv] = i

    # --- backward DP: minimal byte cost; choice encodes (kind, length) ---
    INF = float('inf')
    cost = [0] * (n + 1)
    kind = bytearray(n)   # 0 literal, 1 match, 2 rle, 3 zero
    klen = [0] * n
    # costs in 1/32-byte units: literal 33 (1 byte + amortized run header),
    # 1-byte token 32, 2-byte token 64. This makes a len-2 match (64) beat two
    # literals (66), matching Konami's heavy use of short matches.
    for i in range(n - 1, -1, -1):
        best = 33 + cost[i + 1]; bk = 0; bln = 1          # literal
        ml = mlen[i]
        if ml >= 2:
            c = 64 + cost[i + ml]
            if c < best:
                best = c; bk = 1; bln = ml
        if data[i] != 0 and run[i] >= 3:
            c = 64 + cost[i + run[i]]
            if c < best:
                best = c; bk = 2; bln = run[i]
        if data[i] == 0:
            z = 1
            while i + z < n and data[i + z] == 0 and z < 0x11f:
                z += 1
            ts = z if z < 31 else 31                  # short zero-run: 1..31 (1 byte)
            c = 32 + cost[i + ts]
            if c < best:
                best = c; bk = 3; bln = ts
            if z >= 32:                               # long zero-run: 32..0x11f (2 bytes)
                c = 64 + cost[i + z]
                if c < best:
                    best = c; bk = 3; bln = z
            # zero-interleave: output 00,x,00,y,... (zeros at even offsets)
            cnt = 0
            while cnt < 32 and i + 2 * cnt + 1 < n and data[i + 2 * cnt] == 0:
                cnt += 1
            if cnt >= 1:
                c = (1 + cnt) * 32 + cost[i + 2 * cnt]
                if c < best:
                    best = c; bk = 4; bln = 2 * cnt
        cost[i] = best; kind[i] = bk; klen[i] = bln

    # --- forward emit ---
    out = bytearray(struct.pack('<I', n))
    lit = bytearray()
    def flush_lit():
        k = 0
        while k < len(lit):
            chunk = lit[k:k + 32]
            out.append(0x80 | (len(chunk) - 1)); out.extend(chunk); k += 32
        lit.clear()
    i = 0
    while i < n:
        k = kind[i]; L = klen[i]
        if k == 0:
            lit.append(data[i]); i += 1; continue
        flush_lit()
        if k == 1:
            D = mdist[i]
            if L == 33 and D == 1:
                L = 32
            V = (~(D - 1)) & 0x3ff
            out.append((((L - 2) & 0x1f) << 2) | ((V >> 8) & 3)); out.append(V & 0xff)
        elif k == 2:
            out.append(0xc0 | (L - 2)); out.append(data[i])
        elif k == 4:  # zero-interleave: emit cnt odd-position literals
            cnt = L // 2
            out.append(0xa0 | (cnt - 1))
            for q in range(cnt):
                out.append(data[i + 2 * q + 1])
        else:  # zero
            if L <= 31:
                out.append(0xe0 | (L - 1))
            else:
                out.append(0xff); out.append(L - 0x20)
        i += L
    flush_lit()
    out += bytes([0x7f, 0xff])
    return bytes(out)


# ---------------------------------------------------------------------------
# PS2 PSMT8 swizzle
# ---------------------------------------------------------------------------
def unswizzle8(buf, w, h):
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            block_loc = (y & ~0xf) * w + (x & ~0xf) * 2
            swap_sel = (((y + 2) >> 2) & 0x1) * 4
            ypos = (((y & ~3) >> 1) + (y & 1)) & 0x7
            column_loc = ypos * w * 2 + ((x + swap_sel) & 0x7) * 4
            byte_sum = ((y >> 1) & 1) + ((x >> 2) & 2)
            sw = block_loc + column_loc + byte_sum
            out[y * w + x] = buf[sw] if sw < len(buf) else 0
    return bytes(out)


def swizzle8(buf, w, h):
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            block_loc = (y & ~0xf) * w + (x & ~0xf) * 2
            swap_sel = (((y + 2) >> 2) & 0x1) * 4
            ypos = (((y & ~3) >> 1) + (y & 1)) & 0x7
            column_loc = ypos * w * 2 + ((x + swap_sel) & 0x7) * 4
            byte_sum = ((y >> 1) & 1) + ((x >> 2) & 2)
            sw = block_loc + column_loc + byte_sum
            if sw < len(out):
                out[sw] = buf[y * w + x]
    return bytes(out)


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------
def iter_blocks(d):
    n = len(d); off = 0
    while off + 16 <= n:
        w = struct.unpack_from('<4I', d, off)
        if w[0] != 0x10:
            off += 16; continue
        yield off, w
        ends = [x for x in w[1:] if x]
        be = off + (max(ends) if ends else 0x10)
        off = (be + 15) & ~15
        while off < n and struct.unpack_from('<I', d, off)[0] != 0x10:
            off += 16


def iter_substreams(d):
    for bo, w in iter_blocks(d):
        pts = [0x10] + [x for x in w[1:] if x]
        for si in range(len(pts) - 1):
            yield bo, si, bo + pts[si], bo + pts[si + 1]


def main():
    cmd = sys.argv[1]
    if cmd == 'list':
        d = open(sys.argv[2], 'rb').read()
        nb = ntex = nsm = 0
        for bo, w in iter_blocks(d):
            nb += 1
        for bo, si, s, e in iter_substreams(d):
            sig = d[s + 4:s + 8]
            if sig == b'\xa1\x02\x02\x80': ntex += 1
            elif d[s + 4:s + 6] == b'\xe1\x80': nsm += 1
        print(f"blocks={nb} big-textures={ntex} small-streams={nsm}")
    elif cmd == 'rtcodec':
        d = open(sys.argv[2], 'rb').read()
        ok = bad = 0
        for bo, si, s, e in iter_substreams(d):
            try:
                dec, size, cons = decompress(d, s)
            except Exception:
                continue
            re = compress(dec)
            dec2, size2, _ = decompress(re, 0)
            if dec2 == dec:
                ok += 1
            else:
                bad += 1
                if bad <= 5:
                    print(f"  MISMATCH block@{bo:#x} sub{si}")
        print(f"round-trip compress->decompress: ok={ok} bad={bad}")
    elif cmd == 'extract':
        from PIL import Image
        d = open(sys.argv[2], 'rb').read(); outdir = sys.argv[3]
        os.makedirs(outdir, exist_ok=True); k = 0
        for bo, si, s, e in iter_substreams(d):
            if d[s + 4:s + 8] != b'\xa1\x02\x02\x80':
                continue
            dec, size, cons = decompress(d, s)
            clut = dec[0x10:0x410]; img = dec[0x410:0x410 + 512 * 512]
            if len(img) < 512 * 512: img += bytes(512 * 512 - len(img))
            un = unswizzle8(img, 512, 512)
            pix = bytes(255 - clut[b * 4] for b in un)
            Image.frombytes('L', (512, 512), pix).save(f"{outdir}/tex_{k:03d}_blk{bo:x}_s{si}.png")
            k += 1
        print(f"extracted {k} textures to {outdir}")
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
