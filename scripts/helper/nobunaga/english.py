#!/usr/bin/env python3
#
# Nobunaga's Ambition Online installer for the PSBBN Definitive Project
# Copyright (C) 2026 PrettyOpenLobby
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Put the English of a Nobunaga translation pack into a staged game tree.

HippaulInstaller's playonline/games/nobunaga/english.py (the pack reader,
the CSTR and STRDAT builders and the CRC32TBL.BIN re-listing), unchanged;
its browser-name code is left out, because the toolkit's nobunaga.retitle
already sets the name.

The game's interface text lives in three plaintext data files that the
install copies out of the disc's INSTIMG/NOBUON.LWZ into the partition root:

    UIMSG.BIN    menus, dialogs and system messages ("CSTR" string tables)
    WDMMSG.BIN   world and chat messages (the same format)
    STRDAT.BIN   fixed-width name tables: items, skills, traits, provinces ...

A pack (download.py fetches the latest from openlobby.fyi) holds only our
English: each row carries a short hash of the Japanese it replaces, and the
Japanese itself is read off the disc. Each file is rebuilt from the disc's
own copy at the same size, then re-listed in CRC32TBL.BIN, which the game
checks. Nothing is changed unless every file is the one the pack was made
for.

    python3 -m nobunaga.english TREE PACK      # rebuild TREE's text in English
"""
import hashlib
import json
import os
import re
import struct
import sys
import zipfile
import zlib

CRC_TABLE = "CRC32TBL.BIN"


class Refused(SystemExit):
    """The disc's text is not what the English was made for."""


def jp_hash(raw):
    """The short hash a table row carries for the Japanese (cp932 bytes) it replaces."""
    return hashlib.sha1(raw).hexdigest()[:12]


# ---- the translation pack ------------------------------------------------

#: The newest pack format this code reads.
FORMAT = 1
MANIFEST = "manifest.json"
PACK_HEADER = "id\thash\ten"
#: The kinds of text file this code can rebuild.
KINDS = ("cstr", "strdat")
#: A bound on any one file in a pack, far above the real ones (about 1 MB).
MAX_FILE = 32 * 1024 * 1024

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
_ESC = re.compile(r"\\(\\|n|t|x[0-9a-fA-F]{2})")


def unesc(s):
    """Undo the text escapes: \\\\ \\n \\t and \\xNN."""
    def one(m):
        c = m.group(1)
        if c == "\\":
            return "\\"
        if c == "n":
            return "\n"
        if c == "t":
            return "\t"
        return chr(int(c[1:], 16))
    return _ESC.sub(one, s)


def rows(text):
    """[(id, jp hash, English)] from one of a pack's text files."""
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r") != PACK_HEADER:
        raise Refused("a text file in the pack does not start with %r" % PACK_HEADER)
    out = []
    for n, line in enumerate(lines[1:], 2):
        line = line.rstrip("\r")
        if not line:
            continue
        p = line.split("\t")
        if len(p) != 3:
            raise Refused("line %d of a text file in the pack has %d fields, not 3"
                          % (n, len(p)))
        out.append((p[0], p[1], unesc(p[2])))
    return out


def _reader(path):
    """(read(name) -> bytes, zip or None) for a pack given as a zip or a folder."""
    if os.path.isdir(path):
        def read(name):
            full = os.path.join(path, *name.split("/"))
            if not os.path.isfile(full):
                raise Refused("the pack has no %s" % name)
            if os.path.getsize(full) > MAX_FILE:
                raise Refused("%s in the pack is too large" % name)
            return _read(full)
        return read, None
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise Refused("%s is not a translation pack: %s" % (path, e))

    def read(name):
        try:
            info = z.getinfo(name)
        except KeyError:
            raise Refused("the pack has no %s" % name)
        if info.file_size > MAX_FILE:
            raise Refused("%s in the pack is too large" % name)
        return z.read(info)
    return read, z


def load_pack(path):
    """The pack at `path`, checked.

    Returns {"format", "version", "date", "text": {target: (kind,
    original sha1, rows)}}, or raises Refused saying why it cannot be used.
    """
    read, z = _reader(path)
    try:
        try:
            man = json.loads(read(MANIFEST).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise Refused("the pack's %s is not JSON" % MANIFEST)
        if not isinstance(man, dict):
            raise Refused("the pack's %s is not a JSON object" % MANIFEST)
        fmt = man.get("format")
        if not isinstance(fmt, int) or isinstance(fmt, bool) or fmt < 1:
            raise Refused("the pack has no usable format number")
        if fmt > FORMAT:
            raise Refused("the pack is format %d and this installer reads up to %d; "
                          "a newer installer is needed" % (fmt, FORMAT))
        if man.get("game") != "nobunaga":
            raise Refused("the pack is for %r, not Nobunaga" % (man.get("game"),))
        files = man.get("files")
        text = man.get("text")
        if not isinstance(files, dict) or not isinstance(text, dict) or not text:
            raise Refused("the pack's manifest lists no files or no text")
        out = {}
        for target, ent in sorted(text.items()):
            if not _NAME.match(target) or "/" in target or target.upper() == CRC_TABLE:
                raise Refused("the pack names a target %r" % (target,))
            if not isinstance(ent, dict):
                raise Refused("the pack's entry for %s is not an object" % target)
            name, kind, sha1 = ent.get("file"), ent.get("kind"), ent.get("original_sha1")
            if kind not in KINDS:
                raise Refused("the pack's %s is of kind %r, which this installer "
                              "cannot build" % (target, kind))
            if not isinstance(sha1, str) or not _SHA1.match(sha1):
                raise Refused("the pack's %s has no usable original_sha1" % target)
            want = files.get(name) if isinstance(name, str) else None
            if not isinstance(want, dict) or not _NAME.match(name):
                raise Refused("the pack's %s names a file it does not list" % target)
            data = read(name)
            if len(data) != want.get("size") or \
                    hashlib.sha256(data).hexdigest() != str(want.get("sha256", "")).lower():
                raise Refused("%s in the pack does not match its manifest" % name)
            try:
                body = data.decode("utf-8")
            except UnicodeDecodeError:
                raise Refused("%s in the pack is not UTF-8" % name)
            out[target] = (kind, sha1, rows(body))
        return {"format": fmt, "version": str(man.get("version", "?")),
                "date": str(man.get("date", "?")), "text": out}
    finally:
        if z is not None:
            z.close()


# ---- CSTR string tables (UIMSG.BIN, WDMMSG.BIN) --------------------------

def cstr_parse(d):
    """The blocks of a CSTR file, each with its fixed slot size."""
    blocks = []
    o = 0
    while o < len(d) and d[o:o + 4] == b"CSTR":
        _magic, ng, ns, ps = struct.unpack_from("<4sIII", d, o)
        groups = [struct.unpack_from("<HH", d, o + 0x30 + 4 * i) for i in range(ng)]
        offs = struct.unpack_from("<%dI" % ns, d, o + 0x30 + 4 * ng)
        base = o + 0x30 + 4 * ng + 4 * ns
        pool = d[base:base + ps]
        strs = [pool[x:pool.index(b"\0", x)] for x in offs]
        end = base + ps
        nxt = (end + 0x1ff) & ~0x1ff
        while nxt < len(d) and d[nxt:nxt + 4] != b"CSTR" and not d[nxt:nxt + 0x200].strip(b"\0"):
            nxt += 0x200
        if d[end:nxt].strip(b"\0"):
            raise Refused("CSTR block at %#x: padding is not zero" % o)
        blocks.append({"hdr": d[o:o + 0x30], "groups": groups, "strs": strs,
                       "slot": nxt - o})
        o = nxt
    if o != len(d) or not blocks:
        raise Refused("not a CSTR string table (stops at %#x of %#x)" % (o, len(d)))
    return blocks


def cstr_ids(blocks):
    """(message id "block.group.index", block, string index), in file order."""
    for b, blk in enumerate(blocks):
        for g, (first, cnt) in enumerate(blk["groups"]):
            for k in range(cnt):
                yield "%d.%d.%d" % (b, g, k), b, first + k


def cstr_pack(blk, strs):
    """One block's bytes: header, groups, offsets, then each distinct string once."""
    pool = bytearray()
    where = {}
    offs = []
    for s in strs:
        if s not in where:
            where[s] = len(pool)
            pool += s + b"\0"
        offs.append(where[s])
    hdr = bytearray(blk["hdr"])
    struct.pack_into("<4sIII", hdr, 0, b"CSTR", len(blk["groups"]), len(strs), len(pool))
    return (bytes(hdr) + b"".join(struct.pack("<HH", *g) for g in blk["groups"])
            + struct.pack("<%dI" % len(strs), *offs) + bytes(pool))


def cstr_build(data, table, name):
    """`data` (the disc's CSTR file) with the English of `table` put in."""
    blocks = cstr_parse(data)
    at = {sid: (b, i) for sid, b, i in cstr_ids(blocks)}
    lines = []
    for sid, h, en in table:
        if sid not in at:
            raise Refused("%s has no message %s" % (name, sid))
        b, i = at[sid]
        raw = blocks[b]["strs"][i]
        if jp_hash(raw) != h:
            raise Refused("%s message %s is not the Japanese the English was made for"
                          % (name, sid))
        lines.append((b, i, raw, en))
    # A line without English of its own takes that of the first line with
    # the same Japanese, so each distinct line is translated once.
    first = {}
    for _b, _i, raw, en in lines:
        if en and raw not in first:
            first[raw] = en
    strs = [list(blk["strs"]) for blk in blocks]
    changed = 0
    for b, i, raw, en in lines:
        text = en or first.get(raw)
        if text:
            strs[b][i] = text.encode("cp932")
            changed += 1
    out = bytearray()
    for b, blk in enumerate(blocks):
        body = cstr_pack(blk, strs[b])
        if len(body) > blk["slot"]:
            raise Refused("%s block %d: the English is %d bytes, the game reads %d"
                          % (name, b, len(body), blk["slot"]))
        out += body + b"\0" * (blk["slot"] - len(body))
    return bytes(out), changed


# ---- STRDAT.BIN name tables ----------------------------------------------

# Section 0 (item names) is stored scrambled: bit i of each plain byte moves
# to bit P[i], with P chosen by the byte's index in the record mod 3. Zero
# bytes stay zero.
_PERM = [(6, 4, 0, 2, 7, 3, 1, 5), (2, 1, 6, 5, 4, 0, 3, 7), (3, 5, 7, 0, 1, 6, 4, 2)]


def _perm_table(p):
    t = bytearray(256)
    for v in range(256):
        o = 0
        for i in range(8):
            if v >> i & 1:
                o |= 1 << p[i]
        t[v] = o
    return bytes(t)


_DEC = [_perm_table(p) for p in _PERM]                      # stored -> plain
_ENC = [bytes(t.index(v) for v in range(256)) for t in _DEC]  # plain -> stored


def strdat_build(data, table):
    """`data` (the disc's STRDAT.BIN) with the English of `table` put in."""
    d = bytearray(data)
    n = struct.unpack_from("<I", d, 0)[0]
    base = 4 + 12 * n
    secs = [struct.unpack_from("<III", d, 4 + 12 * i) for i in range(n)]
    changed = 0
    for sid, h, en in table:
        try:
            i, j = (int(x) for x in sid.split("."))
            off, count, width = secs[i]
        except (ValueError, IndexError):
            raise Refused("STRDAT.BIN has no name %s" % sid)
        if j >= count:
            raise Refused("STRDAT.BIN has no name %s" % sid)
        at = base + off + j * width
        rec = bytes(d[at:at + width])
        if i == 0:
            rec = bytes(_DEC[k % 3][c] for k, c in enumerate(rec))
        if jp_hash(rec.split(b"\0")[0]) != h:
            raise Refused("STRDAT.BIN name %s is not the Japanese the English was made for" % sid)
        if not en:
            continue
        b = en.encode("cp932")
        limit = width if i == 0 else width - 1
        if len(b) > limit:
            raise Refused("STRDAT.BIN name %s: %r is %d bytes, the record holds %d"
                          % (sid, en, len(b), limit))
        rec = b + b"\0" * (width - len(b))
        if i == 0:
            rec = bytes(_ENC[k % 3][c] for k, c in enumerate(rec))
        d[at:at + width] = rec
        changed += 1
    return bytes(d), changed


# ---- CRC32TBL.BIN --------------------------------------------------------

def crc_relist(table, files):
    """CRC32TBL.BIN (u32 count, then {u32 crc32, name NUL}) with each of
    `files` ({name: (old bytes, new bytes)}) re-listed. Each entry must hold
    the old file's checksum first."""
    n = struct.unpack_from("<I", table, 0)[0]
    ents = []
    p = 4
    while p < len(table):
        crc = struct.unpack_from("<I", table, p)[0]
        e = table.index(b"\0", p + 4)
        ents.append([crc, table[p + 4:e]])
        p = e + 1
    if len(ents) != n:
        raise Refused("%s lists %d files, its count says %d" % (CRC_TABLE, len(ents), n))
    for name, (old, new) in sorted(files.items()):
        hit = [e for e in ents if e[1] == name.upper().encode("ascii")]
        if len(hit) != 1:
            raise Refused("%s does not list %s once" % (CRC_TABLE, name))
        if hit[0][0] != zlib.crc32(old):
            raise Refused("%s's entry for %s is not the disc file's checksum" % (CRC_TABLE, name))
        hit[0][0] = zlib.crc32(new)
    return struct.pack("<I", n) + b"".join(struct.pack("<I", c) + nm + b"\0" for c, nm in ents)


# ---- putting it together -------------------------------------------------

def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def translate_text(tree, pack):
    """Rebuild the pack's text files in `tree` in English and re-list them in
    CRC32TBL.BIN. Returns {name: strings replaced}. Writes nothing unless
    every step succeeds."""
    old, new, counts = {}, {}, {}
    for name, (kind, sha1, table) in sorted(pack["text"].items()):
        path = os.path.join(tree, name)
        if not os.path.isfile(path):
            raise Refused("the tree has no %s" % name)
        old[name] = _read(path)
        if hashlib.sha1(old[name]).hexdigest() != sha1:
            raise Refused("%s is not the one the pack was made for (the Hiryuu no "
                          "Shou disc's)" % name)
        if kind == "cstr":
            new[name], counts[name] = cstr_build(old[name], table, name)
        else:
            new[name], counts[name] = strdat_build(old[name], table)
        if len(new[name]) != len(old[name]):
            raise Refused("%s changed size (%d to %d)" % (name, len(old[name]), len(new[name])))
    tpath = os.path.join(tree, CRC_TABLE)
    crcs = crc_relist(_read(tpath), {n: (old[n], new[n]) for n in new})
    for name in sorted(new):
        _write(os.path.join(tree, name), new[name])
    _write(tpath, crcs)
    return counts


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip().splitlines()[-1].strip())
    tree, path = sys.argv[1], sys.argv[2]
    pack = load_pack(path)
    counts = translate_text(tree, pack)
    print("translation pack %s (%s): %s" % (
        pack["version"], pack["date"],
        ", ".join("%s %d" % (n, c) for n, c in sorted(counts.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
