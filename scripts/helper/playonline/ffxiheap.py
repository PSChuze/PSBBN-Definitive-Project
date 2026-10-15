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
r"""Give FFXI's 2016 PS2 boot module more room for heavy cutscenes.

The 2016 client splits the EE's 32 MB into two fixed heap pools and runs out of
both in the later storyline cutscenes (A Crystalline Prophecy's opening in Lower
Jeuno, ASA 1, the RoV city scenes): the Viewer then shows "An error occurred.
Please reset your console." with the code 449a64. Retail PS2 players hit the same
wall. This module changes the plain boot module `ffxi_pol.pex` that a
plaintext-Viewer drive runs, in three places:

  * On PCSX2 with "Enable 128MB RAM (Dev Console)" the pools are laid out over
    the extra memory (pool A to 0x1FF4000, pool B 0x2000000-0x7E00000). The new
    layout is chosen only when the main thread's stack sits above 0x7E00000,
    which PCSX2 does only in that mode, so a real console and PCSX2 without the
    option get the retail layout. The out-of-memory path no longer takes the
    dev-kit `break` that a 128 MB machine would otherwise reach.
  * A 512 KB buffer the module only uses for Japanese text input becomes reserve
    space below pool B when the game runs in another language.
  * The light effect around walking characters checks the object it is about to
    call into; a stale one (freed by the cache and reused) is skipped for that
    frame instead of crashing the console. Seen in A Journey Begins (324) and
    A Crystalline Prophecy (10094).

Measured 2026-10-15 on PCSX2: 10094 plays to the end with 128 MB; at 32 MB it
passes the light effect and still runs out of memory later.

The patch is our own code only: byte runs written at fixed offsets into the
decompressed module, applied only when the module is byte for byte the retail
2016 one and checked against the expected result. Any other module (the 2008
build, a module already patched) is returned unchanged.

Where the runs go (virtual addresses; the module loads at 0x280000):

    0x2802A0  pool setup calls the new layout code
    0x2816A4  out-of-memory path: branch past the dev-kit `break`
    0x28D598  new code, in newlib's powf error wrapper, which nothing calls
    0x337F04  light effect size method: check the object at +0xC4 first
    0x337F90  light effect draw method: the same check
"""
import hashlib

#: The decompressed 2016 ffxi_pol.pex (3,655,040 bytes), and the result.
RETAIL_SHA1 = "9f2f72e5a7a9a44efad1b02f576c703e134f18f7"
PATCHED_SHA1 = "877f36b09176d24ad6598bd1910ce86c3b93ae72"
SIZE = 3655040
NAME = "ffxi_pol.pex"
#: Where a title partition holds it.
PATH = "image/ffxi/prog/ps2/ffxi_pol.pex"

#: (offset into the module, bytes written there). The module loads at 0x280000.
RUNS = (
    (0x0002A0,  # VA 0x2802A0, 16 bytes
     "66350a0c000000000900001000000000"),
    (0x0016A4,  # VA 0x2816A4, 4 bytes
     "04000010"),
    (0x00D598,  # VA 0x28D598, 440 bytes
     "e0ffbd270000bfff0800b1ff25880000e007013c2b883d007c00043c00228434"
     "2001053c03002012000000008301053c001ea534c0040a0c000000009c01043c"
     "002284340002023c03002012000000000002043ce007023c2310440000804224"
     "e4040a0c00c045246600013cf821228c11004010000000006a00083c30f40835"
     "7200093c20f429356000013ca0c52a8c000000ad040000ad080009ad0c0000ad"
     "00800b3c000020ad04002bad08002aad0c0028ad0c0049ad0000bfdf0800b1df"
     "0800e0032000bd271b0080101000013c2b088100180020140008013c2b088100"
     "150020100300813013002014000000000000998c2800013c2b0821030e002014"
     "6000013c2b0821030b0020100300213309002014000000001800218f06002010"
     "000000001400398f0300201300000000080020030000000000e00c0825100000"
     "1b0080101000013c2b088100180020140008013c2b0881001500201003008130"
     "13002014000000000000998c2800013c2b0821030e0020146000013c2b082103"
     "0b0020100300213309002014000000001800218f06002010000000001400398f"
     "03002013000000000800200300000000d6df0c0800008044"),
    (0x0B7F04,  # VA 0x337F04, 16 bytes
     "b6350a0cc400848c0000000000000000"),
    (0x0B7F90,  # VA 0x337F90, 16 bytes
     "98350a0cc400448e0000000000000000"),)


def is_boot_module(what):
    """True for a name of FFXI's boot module or a container of it
    (`ffxi_pol.pex`, `ffxi_pol.pex.enc`, `ffxi_pol.pex.enc.tmp2`, with or without a path)."""
    return what.replace("\\", "/").rsplit("/", 1)[-1].startswith(NAME)


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


def state(plain):
    """'retail', 'patched' or 'other' for a decompressed boot module."""
    if len(plain) != SIZE:
        return "other"
    digest = _sha1(plain)
    return {RETAIL_SHA1: "retail", PATCHED_SHA1: "patched"}.get(digest, "other")


def apply(plain):
    """The patched module for the retail one; anything else unchanged."""
    if state(plain) != "retail":
        return plain
    out = bytearray(plain)
    for off, hexdata in RUNS:
        data = bytes.fromhex(hexdata)
        out[off:off + len(data)] = data
    out = bytes(out)
    if _sha1(out) != PATCHED_SHA1:
        raise SystemExit("ffxiheap: the patched boot module does not match its "
                         "expected hash; nothing was written")
    return out
