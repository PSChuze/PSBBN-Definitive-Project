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
r"""The disc's FMOD/ATAD.IRX made to work with a drive that is not a genuine Sony one.

The atad of SCPS-15049 (dev9/atad 2.04) asks the drive for Sony's identity
page (ATA 0x8e) inside its own probe, and a drive that refuses it is marked
unusable, so every transfer after that fails: on a console with a non-Sony
drive the game hangs at its first disk access. That probe runs inside atad's
start-up, where the loader's shim cannot reach it, so the module itself is
edited before the loader leaves it resident:

  0x617     the genuine-drive check is skipped
  0xf7c, 0x156c and the export/relocation entries after 0x1c5c
            GetSceId (export 14) and the raw identity command (export 6,
            ATA 0x8e feature 0xec, with export 7 for its result) answer from
            the block below instead of asking the drive
  0x1044    a 0x80-byte identity block, filled with the drive's HDD ID here
            (the loader writes it again at boot)

Only the new bytes are kept; the edits apply to the one known file (SHA-1
checked before), and the result with an empty identity block must come out
as the one proven on the console (2026-10-02: the drive came up and the game
read its install with this module). Real hardware only: under PCSX2 the
disc's own atad works.
"""
import hashlib

STOCK = "271d7864d7c93402d9f8c42c3627f59d1ccebaea"
PROVEN = "d31de146737aebe8f255012ea2f70190f051f335"   # with a zero identity block
ID_AT = 0x1044
ID_LEN = 0x80

# (file offset, new bytes)
PATCHES = (
    (0x000617, "10"),
    (0x000f7c, "2140e0030100110400000000bc00e92720000a2400002b8d04002925"
              "0000abacffff4a25fbff40150400a52460000a240000a0acffff4a25"
              "fdff40150400a52421f800010800e003211000000000000000000000"
              "0000000000000000"),
    (0x00103c, "0800e003211000000000000000000000000000000000000000000000"
              "00000000000000000000000000000000000000000000000000000000"
              "00000000000000000000000000000000000000000000000000000000"
              "00000000000000000000000000000000000000000000000000000000"
              "000000000000000000000000000000000000000000000000"),
    (0x00156c, "21c8e003010011040000000021c0e0032000a88fffff08318e000924"
              "190009150000000001000924c40009afffffca30ec000b2410004b15"
              "000000000e00801000000000ccfa092720000a2400002b8d04002925"
              "00008bacffff4a25fbff40150400842460000a24000080acffff4a25"
              "fdff40150400842421f820030800e00321100000c40000af28ee0927"
              "21f82003080020010000000021c8e00301001104000000002c00e98f"
              "05002011000000002c00e0af21f820030800e0032110000024f4e927"
              "21f82003080020010000000000000000"),
    (0x001c5c, "cc1400006415"),
    (0x001c70, "9c0f"),
    (0x001c80, "9c0f"),
    (0x002a30, "00000000200f000000"),
    (0x002a50, "00000000e80f000000"),
    (0x002b60, "00000000e81400000000000004150000000000000c15000000000000"
              "10150000000000001c15000000"),
)


class PatchError(ValueError):
    pass


def patch(data, hddid):
    """FMOD/ATAD.IRX with the edits, answering with the first 0x80 bytes of `hddid`."""
    if hashlib.sha1(data).hexdigest() != STOCK:
        raise PatchError("FMOD/ATAD.IRX is not the one these edits were made for "
                         "(sha1 %s)" % hashlib.sha1(data).hexdigest())
    if len(hddid) < ID_LEN:
        raise PatchError("the HDD ID is %d bytes" % len(hddid))
    out = bytearray(data)
    for off, new in PATCHES:
        new = bytes.fromhex(new)
        out[off:off + len(new)] = new
    if hashlib.sha1(bytes(out)).hexdigest() != PROVEN:
        raise PatchError("the edited FMOD/ATAD.IRX is not the proven one")
    out[ID_AT:ID_AT + ID_LEN] = hddid[:ID_LEN]
    return bytes(out)
