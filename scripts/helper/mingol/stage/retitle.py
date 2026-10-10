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


def icon_from_drive(image):
    """The game's real HDD-OSD icon (data/menu/suzuki00.ico) read back from the
    partition's own INSTALL/ICON.XB (or MENU/ICON.XB), or None when it is not
    there (an old kit install) or cannot be decoded. Read-only.

    The disc ships no loose game icon: it is packed in those "xe" containers
    (mingol.stage.disc_icon does the same from the disc), and both are copied
    to the partition, so an already-installed drive carries them."""
    from playonline.lib import pfsupdate
    from . import xbcodec, ICON_ENTRY, ICON_CONTAINERS
    try:
        with pfsupdate.Installed(image, PARTITION) as inst:
            lower = {rel.lower(): rel for rel in inst.files}
            for rel in ICON_CONTAINERS:
                key = lower.get(rel.lower())
                if key is None:
                    continue
                blob = inst.read(key)
                if blob is None:
                    continue
                try:
                    items = xbcodec.decode_all(blob)
                except Exception:                     # noqa: BLE001 - try the next container
                    continue
                for path, data in items:
                    name = path.replace(b"\\", b"/").split(b"/")[-1].lower()
                    if name == ICON_ENTRY and data[:4] == b"\x00\x00\x01\x00" and len(data) > 0x100:
                        return data
    except Exception:                                 # noqa: BLE001 - read-only, best effort
        return None
    return None


def repair_area(area, icon):
    """(new area, [changes]). Adds the uninstallmes0..2 lines when they are
    missing (as nobunaga.retitle.area_with does) and, when `icon` is given and
    differs from the area's, sets the browser icon to it. The title and look
    lines are left exactly as they are."""
    from nobunaga.retitle import with_uninstall_lines
    from playonline import attrarea
    s = attrarea.slots(area)
    text, added = with_uninstall_lines(s[1][2].decode("utf-8"))
    changes = ["uninstallmes0-2"] if added else []
    if icon and icon != s[2][2]:
        changes.append("icon")
    if not changes:
        return area, []
    want_icon = icon if (icon and "icon" in changes) else s[2][2]
    same_icon = (s[2][0], s[2][1]) == (s[3][0], s[3][1])
    new = attrarea.build_area(s[0][2], text.encode("utf-8"), want_icon,
                              None if same_icon else s[3][2],
                              icon_off=s[2][0],
                              copy_off=None if same_icon else s[3][0])
    # Rebuilding with the same or a smaller icon can only shrink the area; keep
    # the old length so no stale bytes are left past a shorter area's end. A
    # larger icon (the real one replacing the network one) grows it, which
    # write_area allows up to the PFS superblock.
    if len(new) < len(area):
        new += b"\0" * (len(area) - len(new))
    return new, changes


NAMES = {
    "english": {"title": "Everybody's Golf Online",
                "genre": "Sports",
                "note": "This is Everybody's Golf Online."},
    "japanese": {"title": "みんなのＧＯＬＦ オンライン",
                 "genre": "スポーツ",
                 "note": "みんなのＧＯＬＦ オンラインです。"},
}


def retitle(image, language, write=False):
    """Lines describing what happened to the browser entry and /res/info.sys, or
    None without the Minna partition."""
    from nobunaga.retitle import info_with
    from playonline import attrarea, drive
    try:
        lba, sectors = apa.find_partition(image, PARTITION)
    except KeyError:
        return None
    lines = []
    # The HOSDMenu browser entry (icon.sys in the attribute area). Two repairs,
    # both in place and leaving the title and look as write.py set them:
    #   - uninstallmes0..2: an install written before build_attr carried them
    #     has none, which stock HDD-OSD lists as "Corrupted Data" (pop'n and
    #     Nobunaga retitle repair the same field the same way);
    #   - the icon: an install written before the icon fix carried the shared
    #     network-settings icon (CNF/SYS_NET.ICO) instead of the game's own.
    #     The real one (data/menu/suzuki00.ico) is read back from the
    #     partition's own INSTALL/ICON.XB and put in its place. In the normal
    #     install flow write.py has already rewritten the attribute area from
    #     the rebuilt attr.bin, so this finds the icon current and does nothing.
    area = attrarea.read_area(image, lba)
    icon = icon_from_drive(image)
    if area is None:
        lines.append("browser entry: none")
    else:
        new, changed = repair_area(area, icon)
        if not changed:
            lines.append("browser entry: already complete")
        elif not write:
            lines.append("browser entry: would set %s" % ", ".join(changed))
        else:
            drive.write_area(image, lba, new, write=True, backup=False)
            if attrarea.read_area(image, lba)[:len(new)] != new:
                raise SystemExit(
                    "browser entry: readback after the write does not match")
            lines.append("browser entry: set %s" % ", ".join(changed))
    with open(image, "r+b" if write else "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        lines.append(info_with(f, size, lba, sectors, NAMES[language], write))
        if write:
            f.flush()
            os.fsync(f.fileno())
    return lines


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive")
    ap.add_argument("language", choices=sorted(NAMES))
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    lines = retitle(a.drive, a.language, a.write)
    if lines is None:
        print("no %s partition on this drive" % PARTITION)
        return 1
    print("%s (%s)" % (PARTITION, a.language))
    for line in lines:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
