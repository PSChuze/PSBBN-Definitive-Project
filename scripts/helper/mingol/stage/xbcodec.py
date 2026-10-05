#!/usr/bin/env python3
#
# HippaulInstaller - PlayOnline for the PlayStation 2
# Copyright (C) 2026 PrettyOpenLobby
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""xe (.XB) container + codec for Minna no Golf Online.

LZ stage reverse-engineered from SYSTEM.BIN's decompressor at EE 0x1948ec
(func(dst, src, size)): a tag-byte LZ, low bits pick the element:

  tag & 3 == 0   literal run   n = (tag >> 2) + 1               (1..64 bytes)
  tag & 1 == 1   short copy    v = tag | b1<<8                  2 bytes
                               len = ((v >> 1) & 7) + 3         (3..10)
                               dist = v >> 4                    (1..4095)
  tag & 3 == 2   long copy     v = tag | b1<<8 | b2<<16         3 bytes
                               len = ((v >> 2) & 0x3ff) + 3     (3..1026)
                               dist = v >> 12                   (1..4095)

Copies read from dst - dist, byte by byte (overlap allowed). Decoding stops
when `size` output bytes have been produced.
"""
import struct


def lz_decode(src, size, pos=0):
    out = bytearray()
    i = pos
    n = len(src)
    while len(out) < size:
        if i >= n:
            raise ValueError("LZ input exhausted at out=%d/%d" % (len(out), size))
        t = src[i]; i += 1
        if t & 3 == 0:
            k = (t >> 2) + 1
            out += src[i:i + k]; i += k
        elif t & 1:
            v = t | (src[i] << 8); i += 1
            ln = ((v >> 1) & 7) + 3; d = v >> 4
            s = len(out) - d
            for j in range(ln):
                out.append(out[s + j])
        else:
            v = t | (src[i] << 8) | (src[i + 1] << 16); i += 2
            ln = ((v >> 2) & 0x3ff) + 3; d = v >> 12
            s = len(out) - d
            for j in range(ln):
                out.append(out[s + j])
    return bytes(out[:size]), i - pos


def parse(d):
    """Single-entry header -> dict (fields after the name block)."""
    if d[:4] != b'xe\x00\x01':
        raise ValueError("not an xe container")
    count, A, B, C = struct.unpack_from('<IIII', d, 4)
    plen = d[0x18]
    path = d[0x1a:0x1a + plen]
    f = (0x1a + plen + 1 + 3) & ~3
    return dict(count=count, A=A, B=B, C=C, plen=plen, hash=d[0x19],
                path=path, fields=f)


# ---- Huffman stage ----------------------------------------------------------
# Entry fields: [u32 payload_len][u32 coded_len]. coded_len == 0 -> payload is
# stored raw right after. Otherwise: a canonical Huffman table (u8 maxlen, then
# for each length 1..maxlen: u8 count + that many symbols in code order) and an
# LSB-first bitstream that decodes to payload_len bytes.
# Payload: [u32 unc_size][u32 payload_len][LZ stream].

# Exact emulation of SYSTEM.BIN's Huffman stage: table builder at EE 0x1946f0,
# decoder at 0x1947f0 (called through the [size][flag] wrapper at 0x194a00).
#  - table: u8 maxlen, then per length L=1..maxlen: u8 count + count symbols.
#    Canonical codes, but the counter only advances while L < 11, so every
#    length-11 symbol shares one code: length 11 is an ESCAPE.
#  - lookup: 10-bit table indexed by the bit-reversed code (stream is LSB-first).
#  - decode: refill 16-bit LE words while fewer than 16 bits are buffered.
#    hit with len < 11 -> emit sym, drop len bits.
#    hit with len >= 11 -> drop 10 bits, then the next 8 raw bits are the byte.
#  - the bitstream starts 2-byte aligned after the table.
ESC = 11


def huff_table(d, p):
    maxlen = d[p]; p += 1
    table = [None] * 1024
    code = 0
    for L in range(1, maxlen + 1):
        count = d[p]; p += 1
        for _ in range(count):
            rev = 0
            c = code
            for _ in range(L):
                rev = (rev << 1) | (c & 1); c >>= 1
            sym = d[p]; p += 1
            idx = rev
            while idx < 1024:
                table[idx] = (L, sym)
                idx += 1 << L
            if L < ESC:
                code += 1
        code <<= 1
    if p & 1:
        p += 1
    return table, p


def huff_decode(d, p, nout, table):
    out = bytearray()
    buf = 0
    nb = 0
    while len(out) < nout:
        if nb < 16:
            buf |= (d[p] | (d[p + 1] << 8)) << nb; p += 2; nb += 16
        ent = table[buf & 0x3ff]
        if ent is None:
            raise ValueError("invalid Huffman code at out=%d" % len(out))
        L, sym = ent
        if L < ESC:
            out.append(sym); buf >>= L; nb -= L
        else:
            buf >>= 10; nb -= 10
            if nb < 16:
                buf |= (d[p] | (d[p + 1] << 8)) << nb; p += 2; nb += 16
            out.append(buf & 0xff); buf >>= 8; nb -= 8
    return bytes(out)


def entry_payload(d, f):
    """Return the raw payload ([unc][len][LZ...]) of the entry whose fields are at f.
    Mirrors the wrapper at EE 0x194a00: [size][flag]; flag 0 = stored."""
    plen, clen = struct.unpack_from('<II', d, f)
    if clen == 0:
        return d[f + 8:f + 8 + plen]
    table, p = huff_table(d, f + 8)
    # the 16-bit refill may read a word past the end, as it does on the console
    return huff_decode(bytes(d) + b'\0' * 8, p, plen, table)


# ---- generic (multi-entry) container --------------------------------------
# [xe 00 01][u32 count]
# count x [u32 file_size][u32 key]
# [u32 names_size][u32 names_flag]  -- same wrapper: flag 0 = stored, else LZ
#   (names_flag = compressed length), then the name block
# name records: [u8 len][u8 hash][path bytes][NUL]
# then per entry, 4-aligned: [u32 payload_len][u32 coded_len][...]

def _entry_span(d, p):
    """Byte length of the encoded entry at p ([f0][f1] + body)."""
    f0, f1 = struct.unpack_from('<II', d, p)
    if f1 == 0:
        return 8 + f0
    _, q = huff_table(d, p + 8)
    return (q - p) + f1


def parse_all(d):
    if d[:4] != b'xe\x00\x01':
        raise ValueError("not an xe container")
    count = struct.unpack_from('<I', d, 4)[0]
    table = [struct.unpack_from('<II', d, 8 + 8 * i) for i in range(count)]
    w = 8 + 8 * count
    nsize, nflag = struct.unpack_from('<II', d, w)
    nstart = w + 8
    if nflag == 0:
        names = d[nstart:nstart + nsize]
        nend = nstart + nsize
    else:
        # flag is only tested for non-zero; the block ends where the LZ stops
        names, used = lz_decode(d, nsize, nstart)
        nend = nstart + used
    recs, q = [], 0
    for _ in range(count):
        ln, h = names[q], names[q + 1]
        recs.append((names[q + 2:q + 2 + ln], h))
        q += ln + 3
    p = (nend + 3) & ~3
    entries = []
    for i in range(count):
        span = _entry_span(d, p)
        entries.append(dict(size=table[i][0], key=table[i][1], path=recs[i][0],
                            hash=recs[i][1], off=p, span=span))
        p = (p + span + 3) & ~3
    return dict(count=count, names_wrap=(nsize, nflag), entries=entries, end=p)


def decode_all(d):
    """-> [(path, file bytes)] for every entry."""
    info = parse_all(d)
    out = []
    for e in info['entries']:
        out.append((e['path'], unwrap_payload(entry_payload(d, e['off']))))
    return out


# ---- encoder ---------------------------------------------------------------

def lz_encode(data, max_chain=1024, lazy=False):
    """LZ in the 0x1948f0 format (hash chains on 3-byte prefixes). lazy=True
    defers a match by one byte when the next position has a longer one."""
    if lazy:
        return _lz_encode_lazy(data, max_chain)
    return _lz_encode_greedy(data, max_chain)


def _lz_encode_lazy(data, max_chain):
    n = len(data)
    out = bytearray()
    lit = bytearray()
    head = {}
    prev = [-1] * n

    def flush():
        i = 0
        while i < len(lit):
            k = min(64, len(lit) - i)
            out.append((k - 1) << 2)
            out.extend(lit[i:i + k])
            i += k
        lit.clear()

    def insert(i):
        if i + 2 < n:
            key = data[i:i + 3]
            prev[i] = head.get(key, -1)
            head[key] = i

    def best_at(i):
        bl = bd = 0
        if i + 2 < n:
            j = head.get(data[i:i + 3], -1)
            chain = 0
            maxlen = min(1026, n - i)
            while j >= 0 and chain < max_chain:
                dist = i - j
                if dist > 4095:
                    break
                if data[j + bl] == data[i + bl] if bl < maxlen else False:
                    l = 0
                    while l < maxlen and data[j + l] == data[i + l]:
                        l += 1
                    if l > bl:
                        bl, bd = l, dist
                        if l == maxlen:
                            break
                j = prev[j]; chain += 1
        return bl, bd

    def cost(l, d):
        return 2 if l <= 10 else 3

    i = 0
    while i < n:
        bl, bd = best_at(i)
        if bl >= 3:
            insert(i)
            nl, nd = best_at(i + 1) if i + 1 < n else (0, 0)
            if nl > bl + 1:          # a literal now buys a clearly longer match
                lit.append(data[i]); i += 1
                continue
            flush()
            if bl <= 10:
                v = 1 | ((bl - 3) << 1) | (bd << 4)
                out += bytes((v & 0xff, v >> 8))
            else:
                v = 2 | ((bl - 3) << 2) | (bd << 12)
                out += bytes((v & 0xff, (v >> 8) & 0xff, v >> 16))
            for k in range(1, bl):
                insert(i + k)
            i += bl
        else:
            lit.append(data[i]); insert(i); i += 1
    flush()
    return bytes(out)


def _lz_encode_greedy(data, max_chain=64):
    """Greedy LZ in the 0x1948f0 format (hash chains on 3-byte prefixes)."""
    n = len(data)
    out = bytearray()
    lit = bytearray()
    head = {}
    prev = [-1] * n

    def flush():
        i = 0
        while i < len(lit):
            k = min(64, len(lit) - i)
            out.append((k - 1) << 2)
            out.extend(lit[i:i + k])
            i += k
        lit.clear()

    def insert(i):
        if i + 2 < n:
            key = data[i:i + 3]
            prev[i] = head.get(key, -1)
            head[key] = i

    i = 0
    while i < n:
        best_len = 0; best_d = 0
        if i + 2 < n:
            j = head.get(data[i:i + 3], -1)
            chain = 0
            maxlen = min(1026, n - i)
            while j >= 0 and chain < max_chain:
                dist = i - j
                if dist > 4095:
                    break
                l = 3
                while l < maxlen and data[j + l] == data[i + l]:
                    l += 1
                if l > best_len:
                    best_len, best_d = l, dist
                    if l == maxlen:
                        break
                j = prev[j]; chain += 1
        if best_len >= 3:
            flush()
            if best_len <= 10:
                v = 1 | ((best_len - 3) << 1) | (best_d << 4)
                out += bytes((v & 0xff, v >> 8))
            else:
                v = 2 | ((best_len - 3) << 2) | (best_d << 12)
                out += bytes((v & 0xff, (v >> 8) & 0xff, v >> 16))
            for k in range(best_len):
                insert(i + k)
            i += best_len
        else:
            lit.append(data[i])
            insert(i)
            i += 1
    flush()
    return bytes(out)


def _limited_lengths(freq, limit=10):
    """Package-merge: optimal code lengths <= limit for symbols with freq > 0."""
    syms = [s for s in range(256) if freq[s]]
    if len(syms) == 1:
        return {syms[0]: 1}
    leaves = sorted((freq[s], (s,)) for s in syms)
    packages = list(leaves)
    for _ in range(limit - 1):
        merged = []
        for k in range(0, len(packages) - 1, 2):
            a, b = packages[k], packages[k + 1]
            merged.append((a[0] + b[0], a[1] + b[1]))
        packages = sorted(leaves + merged)
    lengths = {s: 0 for s in syms}
    for _, ss in packages[:2 * len(syms) - 2]:
        for s in ss:
            lengths[s] += 1
    return lengths


def huff_encode(payload):
    """-> (table bytes incl. 2-byte alignment pad, bitstream bytes)."""
    freq = [0] * 256
    for b in payload:
        freq[b] += 1
    lengths = _limited_lengths(freq, 10)
    maxlen = max(lengths.values())
    by_len = {L: sorted(s for s, l in lengths.items() if l == L) for L in range(1, maxlen + 1)}
    table = bytearray([maxlen])
    codes = {}
    code = 0
    for L in range(1, maxlen + 1):
        syms = by_len[L]
        table.append(len(syms))
        table += bytes(syms)
        for s in syms:
            codes[s] = (code, L); code += 1
        code <<= 1
    bits = bytearray()
    acc = 0; nb = 0
    for b in payload:
        c, L = codes[b]
        for k in range(L - 1, -1, -1):  # code MSB first into an LSB-first stream
            acc |= ((c >> k) & 1) << nb; nb += 1
            if nb == 8:
                bits.append(acc); acc = 0; nb = 0
    if nb:
        bits.append(acc)
    if len(bits) & 1:
        bits.append(0)
    return bytes(table), bytes(bits)


def encode_entry(newfile, huffman=True):
    """-> encoded entry bytes ([f0][f1] + body). Entries start 4-aligned, so
    the bitstream's 2-byte alignment depends only on the table length."""
    lz = lz_encode(newfile)
    if len(lz) < len(newfile):
        payload = struct.pack('<II', len(newfile), len(lz) + 8) + lz
    else:
        payload = struct.pack('<II', len(newfile), 0) + bytes(newfile)
    stored = struct.pack('<II', len(payload), 0) + payload
    if not huffman:
        return stored
    table, bits = huff_encode(payload)
    tabpad = table + (b'\0' if len(table) & 1 else b'')
    coded = struct.pack('<II', len(payload), len(bits)) + tabpad + bits
    return coded if len(coded) < len(stored) else stored


def build_all(orig, repl, huffman=True):
    """Rebuild container `orig`, replacing entries whose inner path is a key of
    `repl` ({path bytes: new file bytes}). Untouched entries and the names
    block are copied verbatim; sizes are updated and every entry's key is
    rewritten as its file offset / 4 (the loader seeks to entries by key)."""
    info = parse_all(orig)
    ents = info['entries']
    out = bytearray(orig[:ents[0]['off']])
    used = set()
    for i, e in enumerate(ents):
        if e['path'] in repl:
            new = repl[e['path']]
            body = encode_entry(new, huffman)
            struct.pack_into('<I', out, 8 + 8 * i, len(new))
            used.add(e['path'])
        else:
            body = orig[e['off']:e['off'] + e['span']]
        if i:
            out += b'\0' * ((-len(out)) & 3)
        struct.pack_into('<I', out, 8 + 8 * i + 4, len(out) // 4)  # key = offset/4
        out += body
    missing = set(repl) - used
    if missing:
        raise KeyError("no such entries: %r" % sorted(missing))
    return bytes(out)


def build_single(orig, newfile, huffman=True):
    """Replace the only entry of a single-entry .XB."""
    path = parse_all(orig)['entries'][0]['path']
    return build_all(orig, {path: newfile}, huffman)


def unwrap_payload(pl):
    """Level-2 wrapper: [u32 unc][u32 flag] -> file bytes (flag 0 = stored)."""
    unc, flag = struct.unpack_from('<II', pl, 0)
    if flag == 0:
        return bytes(pl[8:8 + unc])
    out, _ = lz_decode(pl, unc, 8)
    return out


def decode_single(d):
    """Decode a single-entry .XB -> (inner path, file bytes)."""
    e = parse(d)
    return e['path'], unwrap_payload(entry_payload(d, e['fields']))
