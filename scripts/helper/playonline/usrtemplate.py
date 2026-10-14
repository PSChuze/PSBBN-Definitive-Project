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
"""Give an installed Viewer the `usr/` files Square Enix's installer copies in.

The disc carries a template, `default/usr/`, and Square Enix's installer
copies it to `usr/` on the new partition. It holds `usr/all/url/` (cert.db,
rdthosts.bin and cache/dcfat0.bin), the Viewer's download cache. The Viewer
never makes that directory itself. Without it the Viewer cannot download:
page music (`<bgsound>` with an http source) stops the page at about 144 KB,
and a wallpaper download never finishes. Pages themselves still load, so
nothing else shows it.

Installs made before this module have an empty `usr/all/`. For every file in
the partition's own `default/usr/` that `usr/` lacks, this stages a copy of
that file and writes the pfsshell commands that put it, making the missing
directories first. A file already in `usr/` is never touched: the Viewer
writes there (the cache index, its settings).

    python3 -m playonline.usrtemplate DRIVE --title viewer-us --work DIR --out cmds
    sudo pfsshell < cmds
    python3 -m playonline.usrtemplate DRIVE --title viewer-us --work DIR --verify

Exit status 3 means nothing is missing.
"""
import argparse
import os
import sys

from . import pfsput, titles
from .update import Drive

TEMPLATE = ("default", "usr")


def missing(drive):
    """[(template path tuple, usr path tuple)] for each template file `usr/` lacks."""
    out = []
    for path in sorted(drive.files):
        if path[:2] != TEMPLATE:
            continue
        dest = path[1:]
        if dest not in drive.files:
            out.append((path, dest))
    return out


def stage(drive, pairs, work):
    for src, dest in pairs:
        p = os.path.join(work, *dest)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(drive.read("/".join(src)) or b"")


def commands(drive, pairs, work):
    q = pfsput.quote
    out = ["device %s" % drive.image, "mount %s" % drive.title.partition]
    want = set()
    for _src, dest in pairs:
        for k in range(1, len(dest)):
            want.add(dest[:k])
    for d in sorted(want - drive.dirs):          # sorted, so a parent comes first
        out.append("cd /%s" % "/".join(d[:-1]) if len(d) > 1 else "cd /")
        out.append("mkdir %s" % q(d[-1]))
    by_dir = {}
    for _src, dest in pairs:
        by_dir.setdefault(dest[:-1], []).append(dest[-1])
    for d in sorted(by_dir):
        out.append("cd /%s" % "/".join(d))
        out.append("lcd %s" % q(pfsput.host_path(os.path.join(work, *d))))
        for name in by_dir[d]:
            out.append("put %s" % q(name))
    return out + ["umount", "exit"]


def verify(drive, work):
    """[problems]: each staged file against the partition."""
    bad = []
    for dirpath, _dirs, names in os.walk(work):
        for name in names:
            rel = os.path.relpath(os.path.join(dirpath, name), work).split(os.sep)
            want = open(os.path.join(dirpath, name), "rb").read()
            got = drive.read("/".join(rel))
            if got != want:
                bad.append("/%s: %s" % ("/".join(rel), "missing" if got is None
                                        else "%d bytes, expected %d" % (len(got), len(want))))
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive", help="device path or drive image")
    ap.add_argument("--title", required=True)
    ap.add_argument("--work", required=True, help="where the copies are staged")
    ap.add_argument("--out", help="write the pfsshell commands here")
    ap.add_argument("--verify", action="store_true",
                    help="after pfsshell ran: compare the partition with --work")
    args = ap.parse_args()
    title = titles.TITLES.get(args.title)
    if title is None:
        sys.exit("unknown title %r" % args.title)
    drive = Drive(args.drive, title)
    try:
        if args.verify:
            bad = verify(drive, args.work)
            for line in bad:
                print("  " + line)
            print("%s: %s" % (title.partition, "%d problem(s)" % len(bad) if bad
                              else "every template file is in usr/"))
            return 1 if bad else 0
        pairs = missing(drive)
        if not pairs:
            print("%s: usr/ has every file of the template" % title.partition)
            return 3
        print("%s: %d file(s) of default/usr/ are missing from usr/:"
              % (title.partition, len(pairs)))
        for _src, dest in pairs:
            print("  /" + "/".join(dest))
        stage(drive, pairs, args.work)
        cmds = commands(drive, pairs, args.work)
        text = "\n".join(cmds) + "\n"
        if args.out:
            with open(args.out, "w") as f:
                f.write(text)
        else:
            sys.stdout.write(text)
        return 0
    finally:
        drive.close()


if __name__ == "__main__":
    sys.exit(main())
