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
"""Read and mint the PS2 HDD ID block that Square Enix's modules are keyed to.

Square Enix's installed modules are keyed to the drive. Both keys come from
two windows of a 512-byte block:

    bulk key    HDDID[0x40:0x48] ++ HDDID[0x50:0x60]
    record key  f(HDDID[0x50:0x60])

The block is not stored in the drive's addressable sectors. A genuine Sony
PS2 drive returns it in response to a proprietary ATA command (0x8e/0xec,
`sceAtaGetSceId`), so it cannot be read back from a drive image. A generic
drive has no such block and the call fails with a zeroed buffer.

The loader shipped with this package carries `atadpatch.irx`, which hooks
loadcore's `RegisterLibraryEntries` and redirects atad export 14 (the call
the Viewer imports) to a function that returns a 512-byte block supplied by
the installer. The ID is therefore an input the installer chooses, like the
`.hddid` file PCSX2 serves, and the modules are transcrypted to match it.
What matters is that the console is served the same block the modules were
built against. A genuine Sony drive works without the shim; any other drive
needs it, so an install always ships it.

    python3 -m playonline.hddid BLOCK.hddid          # parse and show
    python3 -m playonline.hddid BLOCK.hddid --key    # the 24 key bytes
    python3 -m playonline.hddid --mint OUT.hddid [--seed TEXT]
    python3 -m playonline.hddid --recover OUT.hddid --device /dev/sdX

`--recover` is for a drive set up on another machine. The `.hddid` file
stays on the PC that minted it, but every filled loader on the drive carries
the block for its shim to serve, so it can be read back out of
`pfs:/dnasload.elf` (the Viewer's, or any title installed through the same
loader). The Viewer's copy wins when the loaders disagree, since the file
being rebuilt is PlayOnline's.
"""
import argparse
import hashlib
import os
import struct
import sys

MAGIC = b"Sony Computer Entertainment Inc."
SIZE = 512

# Field map per psdevwiki "Security and authentication / HDDID". The two
# windows the Viewer's key derivation reads are 0x40:0x48 and 0x50:0x60.
FIELDS = [
    (0x00, 0x20, "magic", "ascii"),
    (0x20, 0x10, "model", "ascii"),
    (0x30, 0x04, "capacity GB", "ascii"),
    (0x40, 0x04, "serial (u32)", "u32"),
    (0x44, 0x02, "padding", "hex"),
    (0x46, 0x02, "unknown", "hex"),
    (0x48, 0x02, "drive type", "hex"),
    (0x4C, 0x04, "retail 0x01031101 / DEX 0x00031101", "hex"),
    (0x50, 0x10, "encryption block", "hex"),
    (0x60, 0x20, "encryption, further", "hex"),
]


class NotAnHddId(ValueError):
    pass


def load(path):
    with open(path, "rb") as f:
        blk = f.read(SIZE + 1)
    if len(blk) != SIZE:
        raise NotAnHddId("%s is %d bytes, an HDD ID block is %d" % (path, len(blk), SIZE))
    if not blk.startswith(MAGIC):
        raise NotAnHddId("%s does not start %r - first 32 bytes are %r"
                         % (path, MAGIC, blk[:32]))
    return blk


def key_material(blk):
    """The 24 bytes the bulk-key schedule takes, in this order."""
    return blk[0x40:0x48] + blk[0x50:0x60]


def is_zero_material(blk):
    """True when both key windows are zero.

    Zero material is a usable ID, but modules built against it only run
    where the same zeros are served, which on hardware means the shim must
    serve this block.
    """
    return key_material(blk) == b"\0" * 24


def mint(model="SCPH-20400", capacity_gb=40, serial=None, material=None,
         seed=None, retail=True):
    """Make an HDD ID block for a drive that has none.

    Only the 24 key bytes matter: the same bytes must be used to build the
    modules and be served back by the loader's shim. The other fields follow
    the layout of a genuine block.

    `material` is those 24 bytes, `blk[0x40:0x48] + blk[0x50:0x60]`. With
    `seed` they are derived from it, so a rebuild gives the same identity.
    Otherwise they are random and the block must be kept: modules built
    against a lost block cannot be decrypted.
    """
    if material is None:
        if seed is not None:
            digest = hashlib.sha256(seed.encode("utf-8")
                                    if isinstance(seed, str) else seed).digest()
            material = digest[:24]
        else:
            material = os.urandom(24)
    if len(material) != 24:
        raise ValueError("key material is %d bytes, it must be 24" % len(material))

    blk = bytearray(SIZE)
    blk[0:len(MAGIC)] = MAGIC
    blk[0x20:0x20 + len(model)] = model.encode("ascii")[:0x10]
    blk[0x30:0x34] = ("%-4s" % capacity_gb).encode("ascii")[:4]
    blk[0x40:0x48] = material[:8]
    if serial is not None:
        struct.pack_into("<I", blk, 0x40, serial)     # overlaps the first word
    struct.pack_into("<I", blk, 0x4C, 0x01031101 if retail else 0x00031101)
    blk[0x50:0x60] = material[8:24]
    return bytes(blk)


def served_by_shim(blk):
    """What the loader's atad export 14 replacement must return for `blk`.

    The modules are transcrypted against this block and the shim on the
    console must return the same 512 bytes. A mismatch gives no error at run
    time, only modules that decrypt to noise, so the installer stages both
    from one source.
    """
    if len(blk) != SIZE:
        raise NotAnHddId("the shim serves %d bytes, got %d" % (SIZE, len(blk)))
    return blk


LOADER_PATH = "/dnasload.elf"


def served_on_drive(drive):
    """[(partition, block)] for every PP.* partition whose root loader serves
    an HDD ID. Read-only; a partition that does not mount, has no loader, or
    has a loader with no filled header (Square Enix's own, a stock dnasload)
    is skipped."""
    from . import loader
    from .lib import polfill, polnetdump, polpfspatch, polpfsread
    found = []
    with open(drive, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        for start, length, _ptype, name in list(polnetdump.partitions(f, size)):
            if not name.startswith("PP."):
                continue
            try:
                part, root = polpfsread.mount(f, start, length)
                if part is None:
                    continue
                _zone, ino = polpfspatch.find(part, root, LOADER_PATH)
                info = loader.read(polfill.read_content(part, ino))
            except (SystemExit, KeyError, ValueError, IOError, OSError,
                    struct.error):
                continue
            if info["has_hddid"]:
                found.append((name, info["hddid"]))
    return found


def recover(drive):
    """(block, source, notes): the drive's served HDD ID, or block None."""
    from .titles import TITLES
    viewers = {t.partition for t in TITLES.values()
               if t.boot == "pfs:/dnasload.elf"}
    found = served_on_drive(drive)
    if not found:
        return None, None, ["no filled loader on this drive serves an HDD ID"]
    distinct = {blk for _name, blk in found}
    pick = next(((n, b) for n, b in found if n in viewers), found[0])
    notes = ["%s serves %s" % (n, key_material(b).hex()) for n, b in found]
    if len(distinct) > 1:
        if pick[0] not in viewers:
            return None, None, notes + [
                "the loaders on this drive serve %d different IDs and none is "
                "the Viewer's; refusing to guess" % len(distinct)]
        notes.append("the loaders disagree; using the Viewer's (%s)" % pick[0])
    return pick[1], pick[0], notes


def describe(blk):
    lines = []
    for off, ln, name, kind in FIELDS:
        v = blk[off:off + ln]
        if kind == "ascii":
            shown = v.split(b"\0")[0].decode("latin-1").strip()
        elif kind == "u32":
            shown = "0x%08x" % struct.unpack_from("<I", v)[0]
        else:
            shown = v.hex()
        lines.append("  0x%02x %-38s %s" % (off, name, shown))
    lines.append("  key material (24 B): %s" % key_material(blk).hex())
    if is_zero_material(blk):
        lines.append("  [!] zero key material: a build made against this only "
                     "boots where the same zeros are read")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("block", nargs="?", help="a 512-byte .hddid file")
    ap.add_argument("--key", action="store_true", help="print the 24 key bytes only")
    ap.add_argument("--mint", metavar="OUT",
                    help="write a new HDD ID block here instead of reading one")
    ap.add_argument("--seed", help="derive the key material from this, so the "
                                   "same drive identity can be rebuilt")
    ap.add_argument("--recover", metavar="OUT",
                    help="read the HDD ID the drive's installed loaders serve "
                         "and write it here (needs --device)")
    ap.add_argument("--device", help="the PS2 drive for --recover")
    args = ap.parse_args()

    if args.recover:
        if not args.device:
            sys.exit("--recover needs --device")
        if os.path.exists(args.recover):
            sys.exit("%s already exists; not overwriting it" % args.recover)
        blk, source, notes = recover(args.device)
        for n in notes:
            print("  " + n)
        if blk is None:
            sys.exit("could not recover an HDD ID from %s" % args.device)
        d = os.path.dirname(os.path.abspath(args.recover))
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(args.recover, "wb") as f:
            f.write(blk)
        print("recovered the HDD ID from %s -> %s" % (source, args.recover))
        print(describe(blk))
        return
    if args.mint:
        blk = mint(seed=args.seed)
        with open(args.mint, "wb") as f:
            f.write(blk)
        print("wrote %s" % args.mint)
        print(describe(blk))
        if args.seed is None:
            print("  [!] random key material: keep this file. Modules built "
                  "against an HDD ID nobody kept cannot be read back.")
        return
    try:
        blk = load(args.block)
    except NotAnHddId as e:
        sys.exit("%s" % e)
    if args.key:
        print(key_material(blk).hex())
    else:
        print(describe(blk))


if __name__ == "__main__":
    main()
