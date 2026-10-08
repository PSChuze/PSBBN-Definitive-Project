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
"""Show Minna no Golf Online in PSBBN's game list under the name of its language.

The browser entry (icon.sys in the attribute area, shown by HDD-OSD and the
Sony browser) is the stage's: attr.bin carries "Everybody's Golf Online" for
an English install and the disc's name for a Japanese one, and
mingol.stage.write puts it on. PSBBN's game list reads `/res/info.sys`
instead (`title`, `genre`, `note`). This installer does not make that file,
but a partition from the retail installer or the older kit-based one has it,
and the in-place update keeps it as one of the partition's own files. This
sets its three fields to match the language; the other fields, and the
jacket art beside it, stay. The Japanese text is the retail installer's,
byte for byte. A partition without the file is left as it is.

    python3 -m mingol.stage.retitle DRIVE english|japanese            # dry run
    python3 -m mingol.stage.retitle DRIVE english|japanese --write

Reuses nobunaga.retitle's info.sys rewrite (playonline's PFS and field
helpers underneath) and never changes them.
"""
import argparse
import os
import sys

from playonline import apa

PARTITION = "PP.SCPS-15049..APPLICATION"

NAMES = {
    "english": {"title": "Everybody's Golf Online",
                "genre": "Sports",
                "note": "This is Everybody's Golf Online."},
    "japanese": {"title": "みんなのＧＯＬＦ オンライン",
                 "genre": "スポーツ",
                 "note": "みんなのＧＯＬＦ オンラインです。"},
}


def retitle(image, language, write=False):
    """A line describing what happened to /res/info.sys, or None without the
    Minna partition."""
    from nobunaga.retitle import info_with
    try:
        lba, sectors = apa.find_partition(image, PARTITION)
    except KeyError:
        return None
    with open(image, "r+b" if write else "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        line = info_with(f, size, lba, sectors, NAMES[language], write)
        if write:
            f.flush()
            os.fsync(f.fileno())
    return line


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive")
    ap.add_argument("language", choices=sorted(NAMES))
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    line = retitle(a.drive, a.language, a.write)
    if line is None:
        print("no %s partition on this drive" % PARTITION)
        return 1
    print("%s (%s): %s" % (PARTITION, a.language, line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
