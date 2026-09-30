#!/usr/bin/env python3
#
# PlayOnline installer for the PSBBN Definitive Project
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
"""Talk to a PlayOnline patch server the way the Viewer's updater does.

The service listens on 53000 plus the title number (FFXI 53001, Tetra Master
53002, the Viewer 54000). Every message is a frame:

    +0   u32 total length
    +4   u32 checksum, the first 4 bytes of MD5(frame[8:]) little-endian
    +8   "POLP"
    +12  u32 command

and the four commands used here are

    7 -> 8   version check: region, product, the drive's patch.ver
             -> status and the latest version
    1 -> 2   the patch list, compressed (see `slc_decompress`)
    3 -> 4   a range of one file, named by the path the list gives it
    anything else, or a request for something the server lacks -> 5

A console tags each request with its region: "PS2" (Japan) or "P2U" (US).
The community server paces replies to those tags for the PS2's network
stack. This client asks as "PS2+" / "P2U+", which that server answers from
the same files without pacing. A server that does not know the mark answers
5, and `Client` then asks again with the plain tag.

The patch list is a sequence of blocks:

    file image/ffxi/ROM/0/0.DAT {
    <version> <size> <byte-sum> <md5[:4]> <blob path> <blob size> [...]
    }

one row per version that changed the file, ended by a line `end`. The byte
sum is the file's bytes added as signed 8-bit values; the MD5 column is the
first four bytes of the file's MD5 read as a signed little-endian integer.
"""
import array
import hashlib
import socket
import struct
import zlib

try:
    import numpy as _np
except ImportError:          # the toolkit's Python may not have it
    _np = None

DEFAULT_PORT_BASE = 53000
VIEWER_PORT = 54000
TOOL_MARK = "+"
CHUNK = 1 << 20            # the server sends up to 2 MiB per frame


class Rejected(Exception):
    """The server answered 5: it has no such bundle or file."""


def cksum(buf):
    return int.from_bytes(hashlib.md5(bytes(buf[8:])).digest()[:4], "little")


def frame(cmd, payload, total_len=None):
    b = bytearray(16)
    b[8:12] = b"POLP"
    struct.pack_into("<I", b, 12, cmd)
    b += payload
    struct.pack_into("<I", b, 0, total_len if total_len is not None else len(b))
    struct.pack_into("<I", b, 4, cksum(b))
    return bytes(b)


def field(text):
    """A region or product code as its fixed 4-byte field."""
    raw = text.encode("ascii")
    if len(raw) > 4:
        raise ValueError("%r does not fit a 4-byte field" % text)
    return raw.ljust(4, b"\0")


def port_for(product):
    """The service port for a product number ("0001" -> 53001)."""
    return VIEWER_PORT if product == "1000" else DEFAULT_PORT_BASE + int(product)


# --- the compressed containers ------------------------------------------------

def _lzss(stream, nbits):
    """Method 2: bit-LZSS, least significant bit first.

    A 0 flag bit is followed by an 8-bit literal; a 1 by a 16-bit distance and
    an 8-bit length. `nbits` is exactly how many stream bits to consume.
    """
    out = bytearray()
    acc = have = used = i = 0
    n = len(stream)
    while used + 9 <= nbits:
        while have < 25 and i < n:
            acc |= stream[i] << have
            have += 8
            i += 1
        if not acc & 1:
            out.append((acc >> 1) & 0xFF)
            acc >>= 9
            have -= 9
            used += 9
            continue
        if used + 25 > nbits:
            break
        dist = (acc >> 1) & 0xFFFF
        length = (acc >> 17) & 0xFF
        acc >>= 25
        have -= 25
        used += 25
        if dist < 1 or dist > len(out):
            break
        start = len(out) - dist
        if length <= dist:
            out += out[start:start + length]
        else:
            for _ in range(length):
                out.append(out[-dist])
    return bytes(out)


def slc_decompress(blob):
    """A served file or list -> its bytes.

    The first byte is the method: 1 stored, 2 bit-LZSS (the patch list),
    3 zlib (every file).
    """
    method = blob[0]
    if method == 3:
        return zlib.decompress(blob[1:])
    if method == 2:
        return _lzss(blob[5:], struct.unpack_from("<I", blob, 1)[0])
    if method == 1:
        return bytes(blob[1:])
    raise ValueError("unknown container method 0x%02x" % method)


def signed_bytesum(raw):
    """The list's byte-sum column: every byte added as a signed int8."""
    if _np is not None:
        return int(_np.frombuffer(raw, dtype=_np.int8).sum(dtype=_np.int64))
    a = array.array("b")
    a.frombytes(raw)
    return sum(a)


def md5_4(raw):
    """The list's MD5 column, as an unsigned 32-bit value."""
    return struct.unpack("<I", hashlib.md5(raw).digest()[:4])[0]


# --- the patch list -----------------------------------------------------------

def version_key(v):
    """Versions are YYYYMMDD_X and compare as text. The Viewer lowercases the
    letter when it copies a row (`20260913_m`), so compare without case."""
    return v.lower()


class Row(object):
    __slots__ = ("version", "size", "bytesum", "md5", "blob", "blob_size", "line")

    def __init__(self, line):
        p = line.split()
        if len(p) < 6:
            raise ValueError("short row: %r" % line)
        self.version = p[0]
        self.size = int(p[1])
        self.bytesum = int(p[2])
        self.md5 = int(p[3]) & 0xFFFFFFFF
        rest = p[4:]
        # A blob path can hold spaces, so anchor on the token that ends it.
        at = next((k for k, t in enumerate(rest) if t.endswith(".slc")), None)
        if at is None or at + 1 >= len(rest):
            raise ValueError("no Direct blob in row: %r" % line)
        self.blob = " ".join(rest[:at + 1])
        self.blob_size = int(rest[at + 1])
        self.line = line

    def check(self, raw):
        """None when `raw` is this row's file, else what disagrees."""
        if len(raw) != self.size:
            return "%d bytes, the list says %d" % (len(raw), self.size)
        if signed_bytesum(raw) != self.bytesum:
            return "byte-sum disagrees with the list"
        if md5_4(raw) != self.md5:
            return "MD5 disagrees with the list"
        return None


class Block(object):
    """One file's block: its path, its rows, and the lines as served."""

    def __init__(self, path):
        self.path = path
        self.rows = []
        self.lines = []

    def newest(self, ceiling=None):
        """The row with the highest version, no higher than `ceiling`."""
        rows = [r for r in self.rows
                if ceiling is None or version_key(r.version) <= version_key(ceiling)]
        return max(rows, key=lambda r: version_key(r.version)) if rows else None


def parse_list(text):
    """Blocks in list order. `text` is the decompressed list as str."""
    blocks, cur = [], None
    for line in text.splitlines():
        if line.startswith("file ") and line.endswith(" {"):
            cur = Block(line[5:-2])
            blocks.append(cur)
        elif line.strip() == "}":
            cur = None
        elif cur is not None and line.strip():
            cur.lines.append(line)
            cur.rows.append(Row(line))
    return blocks


def work_list(blocks):
    """The updater's `patch2.cfg` for these blocks.

    The Viewer keeps, beside `patch.cfg` (the list exactly as served), the
    blocks of the files its last update fetched, in list order, with the
    letter of each row's version lowercased. Square Enix's 2016 FFXI
    partition holds 957 such blocks, every one identical to its block in
    `patch.cfg`, and every file at its last row's size.
    """
    out = []
    for b in blocks:
        rows = []
        for line in b.lines:
            ver, sep, rest = line.partition(" ")
            rows.append(ver.lower() + sep + rest)
        out.append("file %s {\n%s\n}\n\n" % (b.path, "\n".join(rows)))
    return ("".join(out) + "\nend\n\n").encode("latin-1")


# --- the connection -----------------------------------------------------------

class Client(object):
    """One connection to a title's patch service."""

    def __init__(self, host, port, region, product, timeout=60, tool=True):
        self.host, self.port = host, port
        self.region, self.product = region, product
        self.timeout = timeout
        self.tool = tool
        self.sock = None

    @property
    def tag(self):
        return self.region + (TOOL_MARK if self.tool else "")

    def _connect(self):
        if self.sock is None:
            self.sock = socket.create_connection((self.host, self.port), self.timeout)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def rpc(self, pkt):
        self._connect()
        self.sock.sendall(pkt)
        buf = bytearray()
        want = 16
        while len(buf) < want:
            c = self.sock.recv(max(65536, want - len(buf)))
            if not c:
                self.close()
                raise IOError("the server closed the connection")
            buf += c
            if len(buf) >= 4:
                want = max(16, struct.unpack_from("<I", buf, 0)[0])
        pkt = bytes(buf[:want])
        if pkt[8:12] != b"POLP" or struct.unpack_from("<I", pkt, 4)[0] != cksum(pkt):
            self.close()
            raise IOError("a damaged reply")
        cmd = struct.unpack_from("<I", pkt, 12)[0]
        if cmd == 5:
            raise Rejected()
        return cmd, pkt

    def _tagged(self, build):
        """Send with the tool mark; if refused, once more without it."""
        try:
            return build(self.tag)
        except Rejected:
            if not self.tool:
                raise
        self.tool = False
        self.close()
        return build(self.tag)

    def version(self, have):
        """(status, latest) for a drive at version `have`."""
        def ask(tag):
            body = bytearray(0x48)
            body[0:4] = field(tag)
            body[4:8] = field(self.product)
            body[8:8 + len(have)] = have.encode("ascii")
            return self.rpc(frame(7, bytes(body)))
        cmd, pkt = self._tagged(ask)
        if cmd != 8:
            raise IOError("version check answered with command %d" % cmd)
        status = pkt[0x18:pkt.index(b"\0", 0x18)].decode("latin-1")
        blen = struct.unpack_from("<I", pkt, 0x58)[0]
        latest = pkt[0x5c:0x5c + blen].split(b"\0")[0].decode("latin-1")
        return status, latest

    def patch_list(self):
        """The decompressed list, as bytes."""
        def ask(tag):
            # The Viewer sends 24 as the length of this frame.
            return self.rpc(frame(1, field(tag) + field(self.product), total_len=24))
        cmd, pkt = self._tagged(ask)
        if cmd != 2:
            raise IOError("list request answered with command %d" % cmd)
        return slc_decompress(pkt[16:])

    def fetch(self, path, size):
        """A whole blob, by ranged reads."""
        out = bytearray()
        name = path.encode("latin-1")
        while len(out) < size:
            ask = min(CHUNK, size - len(out))
            body = struct.pack("<II", len(out), ask) + field(self.tag) \
                + field(self.product) + struct.pack("<I", len(name) + 1) + name + b"\0"
            cmd, pkt = self.rpc(frame(3, body))
            if cmd != 4:
                raise IOError("%s: answered with command %d" % (path, cmd))
            plen = struct.unpack_from("<I", pkt, 0x18)[0]
            data = pkt[0x1c + plen:]
            if not data:
                raise IOError("%s: an empty range at %d" % (path, len(out)))
            out += data
        if len(out) != size:
            raise IOError("%s: %d bytes, the list says %d" % (path, len(out), size))
        return bytes(out)
