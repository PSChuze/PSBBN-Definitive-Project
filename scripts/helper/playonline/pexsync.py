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
"""Bring a plaintext Viewer's modules up to the build it has updated to.

In plaintext mode the Viewer runs the plain `/V/<module>.pex` files this
installer wrote, and never opens the `.pex.enc` beside them. The in-Viewer
updater only knows the encrypted form: it downloads each new module, keeps
the download as `<module>.pex.enc.tmp2` and replaces `<module>.pex.enc`. The
plain module is left on the old build. The Viewer then reports the new
version (`version.dat`, `patch.ver`) while it runs the old code. A drive
installed from Vana'diel Collection 2008 and updated to 1.18.15f was found
running 1.18.04's polapp, which still draws the Q&A Search button Square Enix
removed in 1.18.13, and pol.pex has its own update rows, so a partly
refreshed set can fail at sign-in.

The `.tmp2` is the universal form the patch server sent, so it opens with the
disc's keys alone. For every `.tmp2` on the partition this decrypts it,
decompresses the module and compares it with the plain `.pex` beside it; a
module that differs is written through pfsshell, `rm` then `put`, as resync
does. A module with no `.tmp2` was never updated and is left alone, and so is
a partition with no plain modules, which runs the keyed ones.

    python3 -m playonline.pexsync DRIVE --title viewer-us --disc DISC \\
        --work DIR --out cmds
    sudo pfsshell < cmds

Exit status 3 means every module already matches; 4 means a `.tmp2` could not
be read, and that module is reported and left as it is.
"""
import argparse
import os
import sys

from . import apa, discs, pfsput, route, titles
from .resync import drive_view
from .lib import polfill

SUFFIX = ".pex.enc.tmp2"


def plan(image, title, work):
    """(commands, report lines, unreadable count).

    Writes each module that needs replacing under `work`, at its partition
    path, for the commands to `put`."""
    lba, sectors = apa.find_partition(image, title.partition)
    report, out, bad = ["the Viewer's modules, against its own updates:"], [], 0
    with open(image, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        part, files, _dirs = drive_view(f, size, lba, sectors)
        updates = sorted(p for p in files if p[-1].endswith(SUFFIX))
        plain_any = any(p[-1].endswith(".pex") for p in files)
        if not plain_any:
            return [], ["no plain modules on %s: it runs the keyed ones, "
                        "nothing to do" % title.partition], 0
        for path in updates:
            name = path[-1][:-len(SUFFIX)] + ".pex"
            target = path[:-1] + (name,)
            where = "/" + "/".join(target)
            if target not in files:
                report.append("  %-22s no plain module beside its update, left alone" % where)
                continue
            try:
                plain = route.universal_to_plain(polfill.read_content(part, files[path]),
                                                 "/" + "/".join(path))
            except (SystemExit, ValueError) as e:
                bad += 1
                report.append("  %-22s update unreadable, left alone: %s" % (where, e))
                continue
            have = polfill.read_content(part, files[target])
            if have == plain:
                report.append("  %-22s current (%d bytes)" % (where, len(plain)))
                continue
            host = os.path.join(work, *target)
            os.makedirs(os.path.dirname(host), exist_ok=True)
            with open(host, "wb") as h:
                h.write(plain)
            report.append("  %-22s %d -> %d bytes, from its update" % (where, len(have), len(plain)))
            out.append("cd /%s" % "/".join(target[:-1]) if len(target) > 1 else "cd /")
            out.append("lcd %s" % pfsput.quote(pfsput.host_path(os.path.dirname(host))))
            out.append("rm %s" % pfsput.quote(name))
            out.append("put %s" % pfsput.quote(name))
    if not updates:
        report.append("  no module has been updated")
    if out:
        out = ["device %s" % image, "mount %s" % title.partition] + out + ["umount", "exit"]
    return out, report, bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive")
    ap.add_argument("--title", required=True)
    ap.add_argument("--disc", help="the Viewer's disc, for its keys")
    ap.add_argument("--derive-elf", required=True,
                    help="the boot executable the key derivation reads (see route.py)")
    ap.add_argument("--work", required=True, help="where the rebuilt modules are written")
    ap.add_argument("--out", help="write the pfsshell commands here")
    args = ap.parse_args()
    if args.title not in titles.TITLES:
        sys.exit("unknown title %r" % args.title)
    route.use_keys(discs.identify(args.disc) if args.disc else None, args.derive_elf)
    cmds, report, bad = plan(args.drive, titles.TITLES[args.title], args.work)
    for line in report:
        print(line)
    if cmds and args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(cmds) + "\n")
    if bad:
        return 4
    return 0 if cmds else 3


if __name__ == "__main__":
    sys.exit(main())
