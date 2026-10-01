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
"""Say which Viewer a drive has and which console its loader is zoned for.

A drive holds one Viewer, and its partition name says which: the US one is
`PP.SCUS-97269.1000.POLVIEWER`, the Japanese one `PP.SLPS-20200.1000.POLVIEWER`.
The Viewer boots through `/dnasload.elf` on that partition, a KELF, and a
KELF's header carries the MagicGate region mask at +0x1C: 0x01 opens on a
Japanese console, 0x02 on a US one, and the all-regions loader sets every bit.
Both answers are already on the drive, so a later run of the installer does
not have to ask for them again.

    python3 -m playonline.driveinfo DRIVE
    viewer=us
    console=us

A line is left out when the drive cannot answer it: no Viewer, two Viewers,
or a loader whose mask is none of the three.
"""
import argparse
import sys

from . import apa, titles
from .lib import polfill, polnetdump, polpfsread

LOADER = b"dnasload.elf"
MASK_AT = 0x1C
CONSOLES = {0x01: "jp", 0x02: "us", 0xFF: "all"}


def viewers(image):
    """{region: partition name} for each Viewer partition on the drive."""
    names = {p.ident for p in apa.partitions(image)}
    out = {}
    for key in ("viewer-us", "viewer-jp"):
        part = titles.TITLES[key].partition
        if part in names:
            out[key.split("-")[1]] = part
    return out


def loader_console(image, partition):
    """The console region the installed loader opens on, or None."""
    lba, sectors = apa.find_partition(image, partition)
    with open(image, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        part, root = polpfsread.mount(f, lba, sectors,
                                      polnetdump.sub_partitions(f, size).get(lba))
        if part is None:
            return None
        for name, inode, sub, _flags in polfill.read_dir_full(part, root):
            if name == LOADER:
                ino = polfill.read_inode(part, inode, sub)
                head = polfill.read_content(part, ino)[:MASK_AT + 4] if ino["ok"] else b""
                if len(head) < MASK_AT + 1:
                    return None
                return CONSOLES.get(head[MASK_AT])
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive")
    args = ap.parse_args()
    found = viewers(args.drive)
    if len(found) != 1:
        return 0
    (region, partition), = found.items()
    print("viewer=%s" % region)
    console = loader_console(args.drive, partition)
    if console:
        print("console=%s" % console)
    return 0


if __name__ == "__main__":
    sys.exit(main())
