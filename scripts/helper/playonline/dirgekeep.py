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
"""Keep a copy of Dirge of Cerberus's partition while it moves to a larger one.

Earlier versions of this package installed Dirge without the two movie
containers beside KEL.DAT on its disc (see dirgedata.py), in a 4096 MiB
partition. With the containers the title needs 8192 MiB, and a partition
cannot grow, so a refresh of such a drive removes the partition and makes it
again. This module holds what the old partition had while that happens.

`needs` exits 0 when the drive's Dirge partition lacks a file of the staged
tree and is smaller than the title needs, and 3 when it does not (a refresh
then writes the files in place as for any title).

`keep` copies every file on the partition into `DIR/tree`, its updates and
settings among them, reads the copy back against the partition, then adds
the files of the staged tree the partition does not have. A file the
partition already has is kept as the partition has it. Last it writes
`DIR/.complete` beside the tree, which the installer checks before it removes the partition and
which tells a later run that the folder holds the whole title.

    python3 -m playonline.dirgekeep needs DRIVE --src STAGED
    python3 -m playonline.dirgekeep keep DRIVE --src STAGED --out DIR
    python3 -m playonline.dirgekeep check DIR
"""
import argparse
import json
import os
import shutil
import sys

from . import apa, titles, update
from .lib import polfill

KEY = "dirge-jp"
MARKER = ".complete"
CHUNK = 64 << 20
SECTOR = 512


def _staged_files(src):
    out = {}
    for dirpath, _dirs, names in os.walk(src):
        for n in names:
            host = os.path.join(dirpath, n)
            rel = os.path.relpath(host, src).replace(os.sep, "/")
            out[rel] = host
    return out


def _copy_from_drive(drive, ino, dst):
    """Write the file at inode `ino` to `dst`, a chunk at a time."""
    part = drive.part
    left = ino["size"]
    with open(dst, "wb") as out:
        for number, sub, count in ino["runs_full"]:
            if not left:
                break
            at = part.zone_sector(number, sub) * SECTOR
            run = min(count * part.zone_size, left)
            done = 0
            while done < run:
                k = min(CHUNK, run - done)
                part.f.seek(at + done)
                data = part.f.read(k)
                if len(data) != k:
                    raise SystemExit("the drive ended inside a file")
                out.write(data)
                done += k
            left -= run
    if left:
        raise SystemExit("%s: the partition's runs end %d B short" % (dst, left))


def needs(drive_path, src):
    title = titles.TITLES[KEY]
    drive = update.Drive(drive_path, title)
    try:
        have = set("/".join(k) for k in drive.files)
        # pfsshell splits a partition past the drive's ceiling into a main and
        # sub-partitions, so the volume is the main plus every sub.
        sizes = dict((p.lba, p.sectors) for p in apa.partitions(drive_path))
        sectors = drive.sectors + sum(sizes.get(lba, 0)
                                      for lba in (drive.subs or {}).values())
        mib = sectors // 2048
    finally:
        drive.close()
    missing = [rel for rel in _staged_files(src) if rel not in have]
    return missing, mib, title.need_mib


def keep(drive_path, src, out):
    """Copy the partition into `out`/tree and add the staged files it lacks."""
    title = titles.TITLES[KEY]
    if os.path.exists(os.path.join(out, MARKER)):
        raise SystemExit("%s already holds a complete copy; it is used as it is" % out)
    shutil.rmtree(out, ignore_errors=True)
    root = out
    out = os.path.join(root, "tree")
    os.makedirs(out)
    drive = update.Drive(drive_path, title)
    copied = total = 0
    try:
        for d in sorted(drive.dirs):
            os.makedirs(os.path.join(out, *d), exist_ok=True)
        for path, ino in sorted(drive.files.items()):
            dst = os.path.join(out, *path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _copy_from_drive(drive, ino, dst)
            copied += 1
            total += ino["size"]
        # Read the copy back against the partition before anything relies on it.
        for path, ino in drive.files.items():
            dst = os.path.join(out, *path)
            if os.path.getsize(dst) != ino["size"] or \
                    not polfill.content_matches(drive.part, ino, dst):
                raise SystemExit("/%s did not copy back the same" % "/".join(path))
    finally:
        drive.close()
    added = []
    for rel, host in sorted(_staged_files(src).items()):
        dst = os.path.join(out, *rel.split("/"))
        if os.path.exists(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(host, dst)
        added.append(rel)
    with open(os.path.join(root, MARKER), "w") as f:
        json.dump({"title": KEY, "partition": title.partition, "copied": copied,
                   "bytes": total, "added": added}, f, indent=1)
    return copied, total, added


def check(out):
    """The marker's contents when `out` holds a complete copy, else None."""
    try:
        with open(os.path.join(out, MARKER)) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("needs")
    p.add_argument("drive")
    p.add_argument("--src", required=True)
    p = sub.add_parser("keep")
    p.add_argument("drive")
    p.add_argument("--src", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("check")
    p.add_argument("out")
    args = ap.parse_args()

    if args.cmd == "needs":
        missing, mib, need = needs(args.drive, args.src)
        print("Dirge's partition: %d MiB, the title needs %d MiB; %d staged file(s) "
              "not on it%s" % (mib, need, len(missing),
                               (": " + ", ".join(missing[:6])) if missing else ""))
        return 0 if missing and mib < need else 3
    if args.cmd == "keep":
        copied, total, added = keep(args.drive, args.src, args.out)
        print("kept %d file(s), %.1f MiB, from the partition; added %d from the disc: %s"
              % (copied, total / 1048576.0, len(added), ", ".join(added) or "none"))
        return 0
    got = check(args.out)
    if got is None:
        print("%s does not hold a complete copy" % args.out)
        return 3
    print("%s holds %d file(s) from %s" % (args.out, got["copied"], got["partition"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
