#!/usr/bin/env python3
#
# Nobunaga's Ambition Online installer for the PSBBN Definitive Project
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
r"""Place Nobunaga's DNAS boot gate in `__net` WITHOUT disturbing PlayOnline.

`__net` holds two DNAS2 records, in two different sectors, outside its
filesystem:

    + 0x201800   the 20-byte per-drive record every keyed title decrypts
                 through (FFXI, the PlayOnline Viewer, ...). SHARED. Managed by
                 record.py; this tool NEVER touches it.
    + 0x202000   `access_flag25`, 1024 bytes, the record the game reads at boot
                 (LBA 0x41010) to check the HDD<->console binding. It is keyed
                 to the console i.Link ID, not the HDD ID, so one known-good
                 record works on every drive AS LONG AS the boot loader serves
                 that same i.Link (the psbb spoof in dnasload; see
                 nobunaga-ilink-binding). PlayOnline does not use this sector.

Grafting a whole `__net` from a reference drive (the old mkdrive.py path) would
overwrite + 0x201800 and break every PlayOnline title on the drive. This tool
writes ONLY the + 0x202000 record, so Nobunaga gains its boot gate and the
shared record is left exactly as PlayOnline wrote it. The two sectors are
0x800 apart (4 sectors), so the write cannot reach + 0x201800.

The record shipped here is the psbb console's (0700001ad5910c10, the i.Link the
dnasload spoof serves). Minting a per-console record instead needs the
access_flag25 plaintext format, which is not recovered yet; until then this
record plus the spoof is the boot path. It is Sony DNAS2 identity data, not
Koei game code.

    python3 -m nobunaga.accessflag DRIVE --check            # what is there now
    python3 -m nobunaga.accessflag DRIVE --save DIR         # back up + 0x202000
    python3 -m nobunaga.accessflag DRIVE --write [--save DIR]
"""
import argparse
import hashlib
import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playonline import netpart                               # noqa: E402

AF25_OFFSET = 0x202000                 # inside __net, outside its filesystem
LENGTH = 1024                          # the 2-sector access_flag25 record
RECORD_OFFSET = netpart.RECORD_OFFSET  # 0x201800, the shared record - never touched here
_BLOB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "data", "access_flag25.psbb.bin")


def psbb_record():
    with open(_BLOB, "rb") as f:
        rec = f.read()
    if len(rec) != LENGTH:
        raise SystemExit("bundled access_flag25 is %d B, expected %d" % (len(rec), LENGTH))
    return rec


def _net_lba(image):
    found = netpart.present(image)
    if not found:
        raise SystemExit("no __net partition on %s (run the PlayOnline __net step first)" % image)
    return found[0]


def read(image):
    """(lba, 1024-byte current record)."""
    lba = _net_lba(image)
    with open(image, "rb") as f:
        f.seek(lba * 512 + AF25_OFFSET)
        return lba, f.read(LENGTH)


def check(image):
    lba, cur = read(image)
    want = psbb_record()
    nz = sum(1 for b in cur if b)
    state = ("matches the shipped psbb record" if cur == want
             else "empty/zero (no gate installed)" if nz == 0
             else "present but DIFFERENT from the shipped record")
    print("__net LBA %d, access_flag25 at +0x%x:" % (lba, AF25_OFFSET))
    print("  current sha256 %s (%d/%d nonzero) - %s"
          % (hashlib.sha256(cur).hexdigest()[:16], nz, LENGTH, state))
    print("  shipped sha256 %s" % hashlib.sha256(want).hexdigest()[:16])
    return cur == want


def save(image, folder):
    lba, cur = read(image)
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, "access_flag25-before-%s.bin" % time.strftime("%Y%m%d-%H%M%S"))
    with open(out, "wb") as f:
        f.write(cur)
    return "backed up the current access_flag25 (%d B) to %s" % (len(cur), out)


def write(image, folder=None):
    """Write the psbb access_flag25 at +0x202000. Backs up first when folder is given.

    Guards: refuses if there is no __net; verifies the shared record at
    +0x201800 is byte-identical before and after, so a bug can never cost
    PlayOnline its record."""
    lba = _net_lba(image)
    want = psbb_record()
    with open(image, "rb") as f:
        f.seek(lba * 512 + RECORD_OFFSET)
        shared_before = f.read(512)
        f.seek(lba * 512 + AF25_OFFSET)
        cur = f.read(LENGTH)
    if folder:
        print(save(image, folder))
    if cur == want:
        return "access_flag25 already matches the shipped record; nothing to do"
    with open(image, "r+b") as f:
        f.seek(lba * 512 + AF25_OFFSET)
        f.write(want)
        f.flush()
        os.fsync(f.fileno())
        f.seek(lba * 512 + AF25_OFFSET)
        back = f.read(LENGTH)
        f.seek(lba * 512 + RECORD_OFFSET)
        shared_after = f.read(512)
    if back != want:
        raise SystemExit("access_flag25 did not read back as written")
    if shared_after != shared_before:
        raise SystemExit("PANIC: the shared +0x201800 record changed - aborting (should be impossible)")
    return "wrote the psbb access_flag25 at +0x%x; the shared +0x201800 record is untouched" % AF25_OFFSET


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--save", metavar="DIR")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if args.write:
        print(write(args.drive, args.save))
    elif args.save:
        print(save(args.drive, args.save))
    else:
        sys.exit(0 if check(args.drive) else 3)


if __name__ == "__main__":
    main()
