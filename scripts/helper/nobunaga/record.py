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
r"""Keep the `__net` record safe across Koei's installer.

There is one per-drive record, at `__net` + 0x201800, outside any
filesystem. The PlayOnline step writes one there, and every keyed PlayOnline
module on the drive (FFXI's in every mode) decrypts through it. Installed
Nobunaga drives carry their record at the same offset: it is Sony's DNAS2
record, shared by every DNAS title on a drive, which is why it lives in a
system partition.

What Koei's installer does when it finds a record already there is not
known. If it keeps it, both titles share it and nothing needs doing. If it
writes its own, the PlayOnline modules keyed through the old one stop
decrypting. So the record is saved before the console install and compared
afterwards, and it can be put back. Putting it back favours PlayOnline over
Nobunaga, so it is only ever done when asked.

The first save on a drive is kept as `BEFORE` and never overwritten, so a
later run cannot replace the pre-install record with a post-install one.

    python3 -m nobunaga.record DRIVE --save DIR
    python3 -m nobunaga.record DRIVE --compare DIR [--hddid FILE]   exit 0 ok, 3 broken
    python3 -m nobunaga.record DRIVE --restore DIR --write

--compare exits 0 (no action needed) when the record is byte-identical to the
BEFORE snapshot, or when it changed but still decodes under an HDD ID the drive
is served (the loaders', or the given --hddid): a record that still decodes is
healthy and the keyed PlayOnline titles still start, whatever the bytes are. It
exits 3 only when the record changed and decodes under none of those IDs, which
is the case that can keep FFXI from starting; the record can then be restored.
"""
import argparse
import hashlib
import json
import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playonline import netpart                               # noqa: E402

RECORD_OFFSET = netpart.RECORD_OFFSET
LENGTH = 512                    # the sector holding the 20-byte record
BEFORE = "net-record-before-nobunaga.json"


def read(path):
    """(lba, bytes) of the record sector, or None when there is no __net."""
    found = netpart.present(path)
    if not found:
        return None
    lba = found[0]
    with open(path, "rb") as f:
        f.seek(lba * 512 + RECORD_OFFSET)
        return lba, f.read(LENGTH)


def _entry(lba, data):
    return {"net_lba": lba, "offset": RECORD_OFFSET,
            "sha256": hashlib.sha256(data).hexdigest(),
            "record": data.hex(),
            "saved": time.strftime("%Y-%m-%d %H:%M:%S")}


def save(path, folder):
    cur = read(path)
    if cur is None:
        return "no __net partition: nothing to save"
    os.makedirs(folder, exist_ok=True)
    entry = _entry(*cur)
    stamped = os.path.join(folder, "net-record-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    with open(stamped, "w") as f:
        json.dump(entry, f, indent=1)
    before = os.path.join(folder, BEFORE)
    if not os.path.exists(before):
        with open(before, "w") as f:
            json.dump(entry, f, indent=1)
        return "saved %s (kept as %s)" % (stamped, BEFORE)
    return "saved %s (%s already kept from an earlier run)" % (stamped, BEFORE)


def load_before(folder):
    with open(os.path.join(folder, BEFORE)) as f:
        entry = json.load(f)
    return entry["net_lba"], bytes.fromhex(entry["record"])


def served_ids(path, hddid_file=None):
    """[(label, 512-byte block)] HDD IDs to test the record against: the given
    file, and every ID a loader on the drive serves. Strictly read-only."""
    blocks = []
    if hddid_file and os.path.exists(hddid_file):
        try:
            with open(hddid_file, "rb") as f:
                blk = f.read(512)
            if len(blk) == 512:
                blocks.append(("playonline.hddid", blk))
        except OSError:
            pass
    try:
        from playonline.hddid import served_on_drive
        for name, blk in served_on_drive(path):
            blocks.append(("the loader in %s" % name, blk))
    except Exception:                               # noqa: BLE001 - diagnostics only
        pass
    return blocks


def decodes_under_served(path, hddid_file=None):
    """(ok, label, four_hex): does the current record decode under any HDD ID
    the drive is served? A record that decodes is one keyed PlayOnline titles
    can still read, so it is healthy whatever its bytes are."""
    cur = read(path)
    if cur is None:
        return False, None, None
    rec = cur[1]
    if not any(rec[:32]):
        return False, None, None
    from playonline.lib import polrecord
    for label, blk in served_ids(path, hddid_file):
        dec = bytes(polrecord.decode(rec[:32], polrecord.derive_key(blk[0x50:0x60])))
        if not any(dec[12:20]):                     # a good decode has zeros here
            return True, label, dec[:4].hex()
    return False, None, None


def compare(path, folder, hddid_file=None):
    """(state, text): state is 'same', 'healthy' or 'broken'.

    'same'     the record is byte-identical to the BEFORE snapshot.
    'healthy'  the record changed but still decodes under an ID the drive is
               served, so keyed PlayOnline titles still start: no action needed.
    'broken'   the record changed and decodes under none of the served IDs (or
               none is known), the case that can keep FFXI from starting.
    """
    lba, want = load_before(folder)
    cur = read(path)
    if cur is None:
        return "broken", "__net is gone"
    if cur[0] != lba:
        return "broken", "__net has moved (LBA %d, was %d)" % (cur[0], lba)
    if cur[1] == want:
        return "same", "the __net record is unchanged"
    ok, label, four = decodes_under_served(path, hddid_file)
    if ok:
        return "healthy", ("the __net record changed since %s but still decodes under the "
                           "drive's served ID (%s, four %s): keyed PlayOnline titles still "
                           "start, so no action is needed" % (BEFORE, label, four))
    if not served_ids(path, hddid_file):
        return "broken", ("the __net record has changed since %s and no served HDD ID is "
                          "known here to check whether it still decodes" % BEFORE)
    return "broken", ("the __net record has changed since %s and decodes under none of the "
                      "HDD IDs the drive is served: keyed PlayOnline titles (FFXI among "
                      "them) may no longer start" % BEFORE)


def restore(path, folder, write=False):
    lba, want = load_before(folder)
    cur = read(path)
    if cur is None or cur[0] != lba:
        raise SystemExit("__net is not where it was when the record was saved; not writing")
    if cur[1] == want:
        return "the __net record is already the saved one"
    if not write:
        return "would put back the record saved in %s  (plan only)" % BEFORE
    with open(path, "r+b") as f:
        f.seek(lba * 512 + RECORD_OFFSET)
        f.write(want)
        f.flush()
        os.fsync(f.fileno())
    if read(path)[1] != want:
        raise SystemExit("the record did not read back as written")
    return "put back the record saved in %s" % BEFORE


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save", metavar="DIR")
    g.add_argument("--compare", metavar="DIR")
    g.add_argument("--restore", metavar="DIR")
    ap.add_argument("--hddid", help="with --compare: an HDD ID file to also test "
                                    "the record against (the loaders' IDs are always tried)")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if args.save:
        print(save(args.drive, args.save))
    elif args.compare:
        state, text = compare(args.drive, args.compare, args.hddid)
        print(text)
        sys.exit(0 if state in ("same", "healthy") else 3)
    else:
        print(restore(args.drive, args.restore, args.write))


if __name__ == "__main__":
    main()
