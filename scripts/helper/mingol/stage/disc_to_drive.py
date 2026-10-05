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
"""Seal a disc-form DNAS2 container to a drive: what the retail installer writes.

Minna no Golf Online's ZZENC/ZZBIN/*.BIN use the same container family as
pop'n (DNAS 2.80) and Nobunaga: one section each, at 0x240. The drive form
built here decrypts (dnasdec) to the disc's plaintext ZZBIN overlay, byte
for byte, and differs from a retail install only in the arbitrary K1-block
plaintext and the outer layer's padding in front of the inner region, which
the retail installer fills with random bytes.

The drive form keeps every RSA-signed record of the disc form and replaces the
two encrypted parts with ones keyed to the target drive (its ATA material and
the __net four):

    [0:sec]        r7, r21, r2, copied
    sec+0x000      the inner-key record (disc sec+0x80; type 6, or 10 in MAIN.BIN)
    sec+0x080      RC6-encrypt(blk, K1), K1 = derive_k1(ata32, four)
    sec+0x100      r3 (sizes), copied
    sec+0x180      r11 (session), copied
    sec+0x200      the static record (type 14, or 4 in MAIN.BIN), copied
    sec+0x280      H1, copied
    sec+0x300      RC6-encrypt(outer, K2), K2 = derive_k2(blk, ata32, four)
    then           r28, copied (no r20 in the drive form)

`blk` is any 128 bytes: the game decrypts it with K1 only to derive K2. Zeros
make the output reproducible. `outer` is zeros with the disc's inner-encoded
region at [d10 : d10+v1] and the tag DRIVE_TAIL_TAG in its last 16 bytes,
which the game checks after decrypting (zeros there make it retry forever).

`build_drive_form_patched` seals a changed module instead of the disc's: the
inner layer is decrypted with the inner-key record's key, the module at
[d9 : d9+v2] replaced, and the inner layer encrypted again. The module length
v2 is in the signed r3 record, so a replacement must be exactly v2 bytes. Only
modules with no signed hash of their payload can be changed this way (the
English overlays); EDAUTH, INSTALL, MOVIE and SYSTEM carry one and stay stock.
"""
import struct

from . import dnas2, dnaskey, rc6

BLK_ZERO = b"\x00" * 128
DRIVE_TAIL_TAG = b"cfe9b0068e5c24d4"


class DriveBuildError(Exception):
    pass


def _first_verifying(enc, off):
    ks = dnas2.keys()
    for slot in ks:
        if dnas2.unrecord(enc[off:off + 128], ks[slot][1], ks[slot][2]) is not None:
            return slot
    return None


def _disc_section(enc, cursor, disc_size):
    """The pieces of one disc-form section the drive form reuses."""
    ks = dnas2.keys()
    r15 = dnas2.unrecord(enc[cursor:cursor + 128], ks[15][1], ks[15][2])
    if r15 is None:
        raise DriveBuildError("r15 missing at %#x" % cursor)
    slot = _first_verifying(enc, cursor + 0x80)
    if slot is None:
        raise DriveBuildError("no inner-key record verifies at %#x" % (cursor + 0x80))
    inner_key = dnas2.unrecord(enc[cursor + 0x80:cursor + 0x100],
                               ks[slot][1], ks[slot][2])[0][:32]
    r3 = dnas2.unrecord(enc[cursor + 0x100:cursor + 0x180], ks[3][1], ks[3][2])
    r11 = dnas2.unrecord(enc[cursor + 0x180:cursor + 0x200], ks[11][1], ks[11][2])
    if r3 is None or r11 is None:
        raise DriveBuildError("r3 or r11 missing at %#x" % cursor)
    h1 = rc6.cbc(enc[cursor + 0x280:cursor + 0x300], r11[0][:16], r11[0][16:32], True)
    if h1[10:26] != b"a5713c8bdbe8d420":
        raise DriveBuildError("H1 tag mismatch at %#x" % cursor)

    v1, v2 = struct.unpack("<II", r3[0][:8])
    d9 = r3[0][9] * 16
    d10 = r3[0][10] * 16
    if v1 & 0xF:
        raise DriveBuildError("v1 %#x is not 16-aligned" % v1)
    start = cursor + 0x300
    d1 = rc6.cbc(enc[start:start + disc_size - 0x400], r15[0][:16], r15[0][16:32], True)
    if d1[-16:] != b"4571cd4f3dce5a9b":
        raise DriveBuildError("disc-layer tail tag mismatch at %#x" % cursor)
    v1a = (v1 + 15) & ~0xF
    inner_off = len(d1) - v1a - 0x10
    return dict(
        v1=v1, v2=v2, d9=d9, d10=d10, inner_key=inner_key,
        inner_raw=enc[cursor + 0x80:cursor + 0x100],
        r3_raw=enc[cursor + 0x100:cursor + 0x180],
        r11_raw=enc[cursor + 0x180:cursor + 0x200],
        static_raw=enc[cursor + 0x200:cursor + 0x280],
        h1_raw=enc[cursor + 0x280:cursor + 0x300],
        inner_encoded=d1[inner_off:inner_off + v1],
    )


def _repatched(s, index, patcher):
    """The section's inner-encoded region, with the patcher's module in it."""
    if patcher is None:
        return s["inner_encoded"]
    key, d9, v2 = s["inner_key"], s["d9"], s["v2"]
    inner = bytearray(rc6.cbc(s["inner_encoded"], key[:16], key[16:32], True))
    module = bytes(inner[d9:d9 + v2])
    new = patcher(index, module)
    if new is None or new == module:
        return s["inner_encoded"]
    if len(new) != v2:
        raise DriveBuildError("the module of section %d is %d bytes, it must stay %d "
                              "(its length is signed)" % (index, len(new), v2))
    inner[d9:d9 + v2] = new
    return rc6.cbc(bytes(inner), key[:16], key[16:32], False)


def build_drive_form(enc, ata32, four, blk_plain=BLK_ZERO):
    """The drive-form bytes of disc-form container `enc` for drive (ata32, four)."""
    return build_drive_form_patched(enc, ata32, four, None, blk_plain)


def build_drive_form_patched(enc, ata32, four, patcher, blk_plain=BLK_ZERO):
    """As build_drive_form, with `patcher(section_index, module)` returning the
    module to seal (the same bytes, or None, for no change; else exactly as long)."""
    if len(blk_plain) != 128:
        raise DriveBuildError("blk_plain must be exactly 128 bytes")
    ks = dnas2.keys()
    k1 = dnaskey.derive_k1(ata32, four)
    k2 = dnaskey.derive_k2(blk_plain, ata32, four)
    blk_ct = rc6.cbc(blk_plain, k1[:16], k1[16:32], False)

    r7 = dnas2.unrecord(enc[:128], ks[7][1], ks[7][2])
    if r7 is None:
        raise DriveBuildError("r7 does not verify at 0")
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200
    r2 = dnas2.unrecord(enc[sec - 0x100:sec - 0x80], ks[2][1], ks[2][2])
    if r2 is None:
        raise DriveBuildError("r2 does not verify at %#x" % (sec - 0x100))
    body = r2[0]
    count = int.from_bytes(body[:4], "little")
    disc_sizes = [int.from_bytes(body[4 + i * 4:8 + i * 4], "little") for i in range(count)]

    out = bytearray(enc[:sec])
    cursor = sec
    for index, size in enumerate(disc_sizes):
        s = _disc_section(enc, cursor, size)
        v1, d10 = s["v1"], s["d10"]
        extent = d10 + v1 + ((0x10 - (v1 & 0xF)) & 0xF) + 0x10
        outer = bytearray(extent)
        outer[d10:d10 + v1] = _repatched(s, index, patcher)
        outer[extent - 16:extent] = DRIVE_TAIL_TAG
        out += s["inner_raw"]
        out += blk_ct
        out += s["r3_raw"]
        out += s["r11_raw"]
        out += s["static_raw"]
        out += s["h1_raw"]
        out += rc6.cbc(bytes(outer), k2[:16], k2[16:32], False)
        payload_end = cursor + 0x300 + (size - 0x400)
        out += enc[payload_end + 0x80:payload_end + 0x100]     # r28 (r20 dropped)
        cursor = payload_end + 0x100
    return bytes(out)
