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
"""The drive's ATA material, and reading a drive-form container back.

    fp    = DES-ECB-encrypt(STAT_2ACE20, key STAT_2ACDF8)       (4 blocks)
    snap  = HDD ID [0x40:0x48] + [0x50:0x60] + 8 zero bytes
    ata32 = 3DES-EDE-CBC-encrypt(snap, keys fp[0:8)/fp[8:16)/fp[16:24),
                                 IV fp[24:32))

`dnaskey.derive_k1(ata32, four)` then gives the key a drive-form container
section is sealed with. `decrypt` undoes `disc_to_drive.build_drive_form`
the way the game does, so the stage step can check every container it
writes against the disc's plaintext overlay before the tree is used:

    blk    = RC6-CBC-decrypt(sec+0x80, K1)
    K2     = dnaskey.derive_k2(blk, ata32, four)
    outer  = RC6-CBC-decrypt(the payload extent, K2)
    inner  = RC6-CBC-decrypt(outer[d10 : d10+v1], the static record)
    module = inner[d9 : d9+v2]
"""
import struct

from Crypto.Cipher import DES

from . import dnas2, dnaskey, rc6
from .dnasconsts import STAT_2ACDF8, STAT_2ACE20

H1_TAG = b"a5713c8bdbe8d420"
DRIVE_TAIL_TAG = b"cfe9b0068e5c24d4"


def ede3(k1, k2, k3, blk):
    """One 3DES-EDE block, three single-DES keys."""
    d1 = DES.new(k1, DES.MODE_ECB)
    d2 = DES.new(k2, DES.MODE_ECB)
    d3 = DES.new(k3, DES.MODE_ECB)
    return d3.encrypt(d2.decrypt(d1.encrypt(blk)))


def cbc3(k1, k2, k3, iv, data):
    """3DES-EDE in CBC mode over whole 8-byte blocks."""
    prev = iv
    out = bytearray()
    for i in range(0, len(data), 8):
        c = ede3(k1, k2, k3, bytes(x ^ y for x, y in zip(data[i:i + 8], prev)))
        out += c
        prev = c
    return bytes(out)


_d = DES.new(STAT_2ACDF8, DES.MODE_ECB)
FP = b"".join(_d.encrypt(STAT_2ACE20[i:i + 8]) for i in range(0, 32, 8))


def ata_material(identify):
    """ata32 for a 512-byte HDD ID block."""
    snap = identify[0x40:0x48] + identify[0x50:0x60] + bytes(8)
    return cbc3(FP[0:8], FP[8:16], FP[16:24], FP[24:32], snap)


class DriveDecryptError(ValueError):
    pass


def _unrec(blob, off, slot):
    ks = dnas2.keys()
    r = dnas2.unrecord(blob[off:off + 128], ks[slot][1], ks[slot][2])
    return r[0] if r else None


def decrypt(blob, ata32, four):
    """The modules of a drive-form container, one per section, as the game reads them."""
    r7 = _unrec(blob, 0, 7)
    if r7 is None:
        raise DriveDecryptError("not a DNAS2 container (no type-7 record)")
    sec = int.from_bytes(r7[0x20:0x24], "little") + 0x200
    k1 = dnaskey.derive_k1(ata32, four)
    modules = []
    while sec + 0x300 < len(blob):
        sess = _unrec(blob, sec + 0x180, 11)
        if sess is None:
            raise DriveDecryptError("no session record at %#x" % (sec + 0x180))
        h1 = rc6.cbc(blob[sec + 0x280:sec + 0x300], sess[:16], sess[16:32], True)
        if h1[10:26] != H1_TAG:
            raise DriveDecryptError("H1 tag mismatch at %#x" % sec)
        sizes = _unrec(blob, sec + 0x100, h1[4]) or _unrec(blob, sec + 0x100, 3)
        if sizes is None:
            raise DriveDecryptError("no sizes record at %#x" % (sec + 0x100))
        stat = None
        for t in (h1[8], 6, 14, 10):
            stat = _unrec(blob, sec, t)
            if stat is not None:
                break
        if stat is None:
            raise DriveDecryptError("no static record at %#x" % sec)
        v1, v2 = struct.unpack("<II", sizes[:8])
        d9, d10 = sizes[9] * 16, sizes[10] * 16
        extent = d10 + v1 + ((0x10 - (v1 & 0xF)) & 0xF) + 0x10
        blk = rc6.cbc(blob[sec + 0x80:sec + 0x100], k1[:16], k1[16:32], True)
        k2 = dnaskey.derive_k2(blk, ata32, four)
        outer = rc6.cbc(blob[sec + 0x300:sec + 0x300 + extent], k2[:16], k2[16:32], True)
        if outer[-16:] != DRIVE_TAIL_TAG:
            raise DriveDecryptError("drive tail tag mismatch at %#x: wrong drive "
                                    "identity or four?" % sec)
        inner = rc6.cbc(outer[d10:d10 + v1], stat[:16], stat[16:32], True)
        modules.append(inner[d9:d9 + v2])
        sec = sec + 0x300 + extent + 0x80
    return modules
