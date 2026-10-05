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
"""Read a DNAS2 disc-form container offline.

Only the container bytes and the public keystore are needed:

  sec        = r7 content[0x20:0x24] (LE u32) + 0x200
  r2         = record at sec-0x100 (slot 2): section count, then disc sizes
  per section, at `cursor`:
    r15      = record at cursor (slot 15): the disc-outer key
    inner    = record at cursor+0x80 (any slot; 6 or 10): the inner key
    r3       = record at cursor+0x100 (slot 3): v1, v2, D9
    r11      = record at cursor+0x180 (slot 11): decrypts H1 at cursor+0x280
    payload  = cursor+0x300, disc_size-0x400 bytes, RC6-CBC under r15;
               its last 16 bytes read "4571cd4f3dce5a9b"
    inner    = RC6-CBC-dec of the payload's v1 bytes before that tail
    module   = inner[D9 : D9+v2]
    cursor  += 0x300 + (disc_size-0x400) + 0x100

Minna no Golf Online uses it for two things: checking that each disc
container decrypts to its plaintext twin in ZZBIN/, and, when the Nobunaga
disc is given as the second disc, taking the IOP reboot image out of that
disc's AUTH/BIN/SLPM_651.97 for its SYSMEM module (see ioprp).
"""
import struct

from . import dnas2, rc6

_H1_TAG = b"a5713c8bdbe8d420"
_TAIL_TAG = b"4571cd4f3dce5a9b"


class DiscDecryptError(Exception):
    pass


def _unrec(blob, off, slot):
    ks = dnas2.keys()
    return dnas2.unrecord(blob[off:off + 128], ks[slot][1], ks[slot][2])


def _unrec_any(blob, off):
    ks = dnas2.keys()
    for slot in ks:
        r = dnas2.unrecord(blob[off:off + 128], ks[slot][1], ks[slot][2])
        if r is not None:
            return slot, r
    return None, None


def _decrypt_section(enc, cursor, disc_size, tag=False):
    """One section's module; with tag=True also the 16-byte trailer after it."""
    r15 = _unrec(enc, cursor, 15)
    if r15 is None:
        raise DiscDecryptError("r15 did not RSA-verify at %#x" % cursor)
    _, inner_rec = _unrec_any(enc, cursor + 0x80)
    if inner_rec is None:
        raise DiscDecryptError("no keystore slot verifies at %#x (inner key)" % (cursor + 0x80))
    r3 = _unrec(enc, cursor + 0x100, 3)
    if r3 is None:
        raise DiscDecryptError("r3 (sizes) did not verify at %#x" % (cursor + 0x100))
    r11 = _unrec(enc, cursor + 0x180, 11)
    if r11 is None:
        raise DiscDecryptError("r11 (session) did not verify at %#x" % (cursor + 0x180))
    h1 = rc6.cbc(enc[cursor + 0x280:cursor + 0x300], r11[0][:16], r11[0][16:32], True)
    if h1[10:26] != _H1_TAG:
        raise DiscDecryptError("H1 tag mismatch at %#x" % cursor)
    v1, v2 = struct.unpack("<II", r3[0][:8])
    d9 = r3[0][9] * 16
    payload = enc[cursor + 0x300:cursor + 0x300 + disc_size - 0x400]
    d1 = rc6.cbc(payload, r15[0][:16], r15[0][16:32], True)
    if d1[-16:] != _TAIL_TAG:
        raise DiscDecryptError("disc-outer tail tag mismatch at %#x" % cursor)
    v1a = (v1 + 15) & ~0xf
    inner_off = len(d1) - v1a - 0x10
    if inner_off < 0:
        raise DiscDecryptError("v1 %d does not fit the payload at %#x" % (v1a, cursor))
    inner = rc6.cbc(d1[inner_off:inner_off + v1a], inner_rec[0][:16], inner_rec[0][16:32], True)
    return inner[d9:d9 + v2 + (16 if tag else 0)]


def sections(enc):
    """Yield (index, cursor, disc_size, v1, v2, d9) per section, without decrypting."""
    r7 = _unrec(enc, 0, 7)
    if r7 is None:
        raise DiscDecryptError("r7 did not verify at 0")
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200
    r2 = _unrec(enc, sec - 0x100, 2)
    if r2 is None:
        raise DiscDecryptError("r2 did not verify at %#x" % (sec - 0x100))
    body = r2[0]
    count = int.from_bytes(body[:4], "little")
    disc_sizes = [int.from_bytes(body[4 + i * 4:8 + i * 4], "little") for i in range(count)]
    cursor = sec
    for i, ds in enumerate(disc_sizes):
        r3 = _unrec(enc, cursor + 0x100, 3)
        v1, v2 = struct.unpack("<II", r3[0][:8])
        yield i, cursor, ds, v1, v2, r3[0][9] * 16
        cursor += 0x300 + (ds - 0x400) + 0x100
