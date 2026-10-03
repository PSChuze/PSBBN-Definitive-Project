#!/usr/bin/env python3
#
# pop'n Puzzle Dama Online installer for the PSBBN Definitive Project
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
"""Show pop'n Puzzle Dama Online under its English or its Japanese name.

The same two places as the PlayOnline titles (see playonline/retitle.py),
neither of which the game reads:

    the browser entry   `icon.sys` in the attribute area: `title0` and
                        `title1`. Shown by HDD-OSD and the Sony browser.
    `/res/info.sys`     `title`, `genre` and `note`. Shown by PSBBN's game
                        list. The disc-form INFO.SYS at BN_RES/INFO.SYS is
                        copied to res/info.sys by the pop'n installer.

The installer sets English by default (there is no English translation of
the game yet; the Latin browser title is a convenience for the drive's
gallery). Passing --language japanese restores the disc's own text.

This reuses playonline's field rewrite, attribute-area and PFS helpers and
never changes them.

    python3 -m popn.retitle DRIVE english|japanese            # dry run
    python3 -m popn.retitle DRIVE english|japanese --write
"""
import argparse
import os
import sys

from playonline import apa, attrarea, drive
from playonline import retitle as polretitle
from playonline.lib import polfill, polnetdump, polpfsread

PARTITION = "PP.BLJA-00010"

NAMES = {
    "english": {
        "icon": {"title0": "pop'n Puzzle Dama Online",
                 "title1": ""},
        "info": {"title": "pop'n Puzzle Dama Online",
                 "genre": "Puzzle",
                 "note": ""},
    },
    "japanese": {
        # The disc's own strings, verbatim from BN_RES/INFO.SYS.
        "icon": {"title0": "pop'n対戦ぱずるだま",
                 "title1": "ONLINE"},
        "info": {"title": "pop'n対戦ぱずるだまONLINE",
                 "genre": "PUZZLE",
                 "note": ""},
    },
}

def set_fields(text, fields):
    """(new text, [keys changed]). Line endings and separators are kept."""
    new_text, changed, _last = polretitle.set_fields(text, fields)
    return new_text, changed


def area_with(area, fields):
    """(new area, [keys changed]). The slots stay where they are."""
    s = attrarea.slots(area)
    new_text, changed = set_fields(s[1][2].decode("utf-8"), fields)
    if not changed:
        return area, []
    same_icon = (s[2][0], s[2][1]) == (s[3][0], s[3][1])
    new = attrarea.build_area(s[0][2], new_text.encode("utf-8"), s[2][2],
                              None if same_icon else s[3][2],
                              icon_off=s[2][0],
                              copy_off=None if same_icon else s[3][0])
    return new + b"\0" * (len(area) - len(new)), changed


def info_with(f, size, lba, sectors, fields, write):
    """Text describing what happened to /res/info.sys."""
    subs = polnetdump.sub_partitions(f, size).get(lba)
    part, root = polpfsread.mount(f, lba, sectors, subs)
    if part is None:
        return "info.sys: the partition did not mount"
    found = polretitle._find(part, root, polretitle.INFO_PATH)
    if found is None:
        return "info.sys: none on this partition"
    zone, sub, ino = found
    old = polfill.read_content(part, ino)
    try:
        text = old.decode("utf-8")
    except UnicodeDecodeError:
        return "info.sys: not UTF-8, left alone"
    new_text, changed = set_fields(text, fields)
    if not changed:
        return "info.sys: already set"
    new = new_text.encode("utf-8")
    if not write:
        return "info.sys: would set %s" % ", ".join(changed)
    polretitle._replace(part, zone, sub, ino, new)
    again = polfill.read_inode(part, zone, sub)
    if polfill.read_content(part, again) != new or not again["ok"]:
        raise SystemExit("info.sys: readback after the write does not match")
    return "info.sys: set %s (%d -> %d B, read back identical)" % (
        ", ".join(changed), len(old), len(new))


def retitle(image, language, write=False):
    """[lines] describing the change, or None without a pop'n partition."""
    found = apa.find_partition(image, PARTITION)
    if found is None:
        return None
    lba, sectors = found
    names = NAMES[language]
    lines = []
    area = attrarea.read_area(image, lba)
    if area is None:
        lines.append("browser entry: none")
    else:
        new, changed = area_with(area, names["icon"])
        if not changed:
            lines.append("browser entry: already set")
        elif not write:
            lines.append("browser entry: would set %s" % ", ".join(changed))
        else:
            drive.write_area(image, lba, new, write=True, backup=False)
            if attrarea.read_area(image, lba)[:len(new)] != new:
                raise SystemExit("browser entry: readback after the write does not match")
            lines.append("browser entry: set %s" % ", ".join(changed))
    with open(image, "r+b" if write else "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        lines.append(info_with(f, size, lba, sectors, names["info"], write))
        if write:
            f.flush()
            os.fsync(f.fileno())
    return lines


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive")
    ap.add_argument("language", choices=sorted(NAMES))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    lines = retitle(args.drive, args.language, args.write)
    if lines is None:
        print("no %s partition on this drive" % PARTITION)
        return 1
    print("%s (%s)" % (PARTITION, args.language))
    for line in lines:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
