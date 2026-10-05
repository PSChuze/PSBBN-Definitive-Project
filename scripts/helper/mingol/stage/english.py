#
# Minna no Golf Online installer for the PSBBN Definitive Project
# Copyright (C) 2026 PrettyOpenLobby
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Minna no Golf Online's English text, applied to the player's own disc.

Unlike Nobunaga (whose interface text lives in separate CSTR/STRDAT data
files), Minna's UI text is compiled into the game's plaintext code overlays
`ZZBIN/*.BIN`, as NUL-terminated Shift-JIS strings in zero-padded slots. The
install already decrypts those overlays off the player's disc (disc_dec:
ZZENC/ZZBIN/*.BIN -> plaintext) and later seals each to the drive
(disc_to_drive). This module is the step between: it overwrites the Japanese
in each plaintext overlay with our English, and the stage seals the English
overlays (disc_to_drive.build_drive_form_patched) instead of the disc's.
No repacking - English (1 byte/char ASCII) fits inside the Japanese byte slot.

The English is not part of the installer. It comes in a translation pack
(only OUR English; the Japanese it replaces is Clap Hanz's and is read off the
player's disc). Each row carries a short hash of the Japanese it replaces, and
nothing is changed unless every overlay is the one the pack was made for.

The pack is a zip (or the folder it unpacks to) with a manifest.json:

    {"format": 1, "game": "mingol", "version": "2026.10.04",
     "date": "2026-10-04",
     "files": {"text/menu.tsv": {"size": N, "sha256": "..."}, ...},
     "text": {"ZZBIN/MENU.BIN": {"file": "text/menu.tsv", "kind": "overlay",
                                 "original_sha1": "..."}, ...}}

A text file is a header line `id <TAB> hash <TAB> en`, then one row per line:
`id` is the string's byte offset in the overlay (hex, e.g. 0x3b4e0); `hash` is
the first 12 hex digits of the SHA-1 of the Japanese slot bytes in cp932; `en`
is the English as final overlay bytes, escaped \\\\ \\n \\t \\xNN (the inline
markup byte 0x07 becomes \\x07, so a colour toggle reads "\\x07]"). The slot
size is taken from the overlay itself (the string plus its zero padding), so
the English plus a NUL must fit it. packaging/build_mingol_pack.py makes packs.

Protocol-coupled strings (login field names like &LOGIN=, host names, paths,
PSaccountLib XML element names, the software-keyboard IME dictionary) are not
in the pack on purpose; translating them would break login or input.
"""
import hashlib
import json
import os
import re
import zipfile

FORMAT = 1
MANIFEST = "manifest.json"
PACK_HEADER = "id\thash\ten"
KINDS = ("overlay",)
MAX_FILE = 32 * 1024 * 1024

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
_TARGET = re.compile(r"^ZZBIN/[A-Z0-9_]+\.BIN$")
_ESC = re.compile(r"\\(\\|n|t|x[0-9a-fA-F]{2})")
_OFF = re.compile(r"^0x[0-9a-fA-F]+$")


class Refused(SystemExit):
    """The disc's overlays are not what the English was made for."""


def jp_hash(raw):
    """The short hash a row carries for the Japanese slot bytes (cp932) it replaces."""
    return hashlib.sha1(raw).hexdigest()[:12]


def esc(b):
    """Escape final overlay bytes as \\\\ \\n \\t \\xNN (printable ASCII kept)."""
    out = []
    for c in b:
        if c == 0x5c:
            out.append("\\\\")
        elif c == 0x0a:
            out.append("\\n")
        elif c == 0x09:
            out.append("\\t")
        elif 0x20 <= c <= 0x7e:
            out.append(chr(c))
        else:
            out.append("\\x%02x" % c)
    return "".join(out)


def unesc(s):
    """Undo esc(): -> bytes."""
    out = bytearray()
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            n = s[i + 1:i + 2]
            if n == "\\":
                out.append(0x5c); i += 2
            elif n == "n":
                out.append(0x0a); i += 2
            elif n == "t":
                out.append(0x09); i += 2
            elif n == "x":
                out.append(int(s[i + 2:i + 4], 16)); i += 4
            else:
                raise Refused("bad escape in pack text: %r" % s[i:i + 2])
        else:
            out += ch.encode("cp932")
            i += 1
    return bytes(out)


def rows(text):
    """[(offset int, jp hash, en bytes)] from one of a pack's text files."""
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
            raise Refused("line %d of a text file has %d fields, not 3" % (n, len(p)))
        if not _OFF.match(p[0]) or not re.match(r"^[0-9a-f]{12}$", p[1]):
            raise Refused("line %d of a text file has a bad id or hash" % n)
        out.append((int(p[0], 16), p[1], unesc(p[2])))
    return out


def _reader(path):
    if os.path.isdir(path):
        def read(name):
            full = os.path.join(path, *name.split("/"))
            if not os.path.isfile(full):
                raise Refused("the pack has no %s" % name)
            if os.path.getsize(full) > MAX_FILE:
                raise Refused("%s in the pack is too large" % name)
            with open(full, "rb") as f:
                return f.read()
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
    """The pack at `path`, checked. Returns {"format","version","date",
    "text": {target: (kind, original sha1, rows)}} or raises Refused."""
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
        if man.get("game") != "mingol":
            raise Refused("the pack is for %r, not Minna" % (man.get("game"),))
        files = man.get("files")
        text = man.get("text")
        if not isinstance(files, dict) or not isinstance(text, dict) or not text:
            raise Refused("the pack's manifest lists no files or no text")
        out = {}
        for target, ent in sorted(text.items()):
            if not _TARGET.match(target):
                raise Refused("the pack names a target %r" % (target,))
            if not isinstance(ent, dict):
                raise Refused("the pack's entry for %s is not an object" % target)
            name, kind, sha1 = ent.get("file"), ent.get("kind"), ent.get("original_sha1")
            if kind not in KINDS:
                raise Refused("the pack's %s is of kind %r, unsupported" % (target, kind))
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


def slot(d, off):
    """(raw jp bytes without NUL, slot size incl. zero padding) at `off`."""
    end = d.index(b"\0", off)
    j = end
    while j < len(d) and d[j] == 0:
        j += 1
    return bytes(d[off:end]), j - off


def overlay_build(data, table, name):
    """`data` (the disc's plaintext overlay) with the English of `table` in place."""
    d = bytearray(data)
    changed = 0
    for off, h, en in table:
        if off >= len(d) or 0 not in d[off:]:
            raise Refused("%s has no string at %#x" % (name, off))
        raw, size = slot(d, off)
        if jp_hash(raw) != h:
            raise Refused("%s string at %#x is not the Japanese the English was made for"
                          % (name, off))
        if len(en) + 1 > size:
            raise Refused("%s string at %#x: the English is %d bytes, the slot holds %d"
                          % (name, off, len(en) + 1, size))
        for k in range(size):
            d[off + k] = 0
        d[off:off + len(en)] = en
        changed += 1
    return bytes(d), changed


def translated(disc_root, pack):
    """({target: English overlay bytes}, {target: strings replaced}) for the
    overlays under `disc_root` (which holds ZZBIN/*.BIN); writes nothing.
    Refused unless every overlay checks out."""
    new, counts = {}, {}
    for target, (kind, sha1, table) in sorted(pack["text"].items()):
        path = os.path.join(disc_root, *target.split("/"))
        if not os.path.isfile(path):
            raise Refused("the disc tree has no %s" % target)
        with open(path, "rb") as f:
            old = f.read()
        if hashlib.sha1(old).hexdigest() != sha1:
            raise Refused("%s is not the one the pack was made for (the SCPS-15049 disc's)"
                          % target)
        new[target], counts[target] = overlay_build(old, table, target)
        if len(new[target]) != len(old):
            raise Refused("%s changed size" % target)
    return new, counts


def translate_overlays(disc_root, pack):
    """Rewrite each overlay named by the pack, in place under `disc_root`
    (which holds ZZBIN/*.BIN). Returns {target: strings replaced}. Writes
    nothing unless every overlay checks out."""
    new, counts = translated(disc_root, pack)
    for target in sorted(new):
        with open(os.path.join(disc_root, *target.split("/")), "wb") as f:
            f.write(new[target])
    return counts


# The containers whose payload hash is in an RSA-signed record: a changed byte
# makes dnas.bin refuse them (-102), so no pack may name them.
SIGNED = ("ZZBIN/EDAUTH.BIN", "ZZBIN/INSTALL.BIN", "ZZBIN/MOVIE.BIN", "ZZBIN/SYSTEM.BIN")


def apply(root, man, translate=False, pack_path=None, local=None):
    """The stage step's language pass: {overlay file name: English plaintext}
    for the sealer, empty when the game stays Japanese.

    With `pack_path` (a local pack, zip or folder) the English goes in or the
    stage stops. With only `translate` the latest pack is downloaded; if that
    cannot be done, or the pack does not fit the disc, the install stays
    Japanese and a note says why; `local` names a folder of packs to fall back
    on (download.latest). Nothing under `root` is changed.
    """
    if not (pack_path or translate):
        return {}
    if pack_path:
        src, why = pack_path, None
    else:
        from . import download
        src, why = download.latest(local=local)
    if src is None:
        man.note("--translate: no translation pack (%s); the game stays Japanese" % why)
        return {}
    try:
        pack = load_pack(src)
        bad = sorted(t for t in pack["text"] if t in SIGNED)
        if bad:
            raise Refused("it changes %s, whose signed hash cannot be redone"
                          % ", ".join(bad))
        new, counts = translated(root, pack)
    except Refused as e:
        if pack_path:
            raise SystemExit("translation pack %s: %s" % (pack_path, e))
        man.note("--translate: the translation pack cannot be used (%s); "
                 "the game stays Japanese" % e)
        return {}
    man.note("--translate: translation pack %s (%s) fits this disc: %s; "
             "SYSTEM.BIN's text is not in it (its container is signed)"
             % (pack["version"], pack["date"],
                ", ".join("%s (%d strings)" % (t.split("/")[-1], n)
                          for t, n in sorted(counts.items()))))
    return dict((t.split("/")[-1], data) for t, data in new.items())
