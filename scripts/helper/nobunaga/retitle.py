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
"""Show Nobunaga's Ambition Online under its English or its Japanese name.

The same two places as the PlayOnline titles (see playonline/retitle.py),
neither of which the game reads:

    the browser entry   `icon.sys` in the attribute area: `title0` and
                        `title1`. Shown by HDD-OSD and the Sony browser.
    `/res/info.sys`     `title`, `genre` and `note`. Shown by PSBBN's game
                        list. Koei's installer copies it from the disc.

The installer sets English when the English translation goes on and puts
Koei's Japanese back when it comes off, so the name always matches the
language the game is in. The Japanese text is the disc's own
(INST/RES/HDDICON.SYS and INST/RES/INFO.SYS), byte for byte.

This reuses playonline's field rewrite, attribute-area and PFS helpers and
never changes them.

    python3 -m nobunaga.retitle DRIVE english|japanese            # dry run
    python3 -m nobunaga.retitle DRIVE english|japanese --write
"""
import argparse
import re
import os
import sys

from playonline import apa, attrarea, drive
from playonline import retitle as polretitle
from playonline.lib import polfill, polnetdump, polpfsread

PARTITION = "PP.SLPM-65197.KOEI.NOBUON"

_NOTE_EN = "\\n".join([
    "A new life unfolds in a virtual Sengoku world!",
    "　",
    "The sixteenth century, the Warring States era.",
    "　",
    "Countless powers hold their ground and vie",
    "for supremacy on battlefield after battlefield.",
    "The low overthrow the high, houses fight to endure,",
    "and the ambitious rise in the world.",
    "　",
    "To survive the turmoil of the Sengoku era,",
    "countless dramas begin right here.",
    "　",
    "In an age of swirling chaos,",
    "the world of \"Nobunaga\"",
    "now lives again on the network.",
    "　",
    "That world",
    "will become your new reason to live,",
    "the stage for another life.",
])

_NOTE_JA = "\\n".join([
    "仮想戦国世界で展開する新たなる人生！",
    "　",
    "時は十六世紀の戦国時代",
    "　",
    "幾多の勢力が割拠し、数多の戦場にて、その覇権を争う",
    "下剋上、家名存続、立身出世",
    "　",
    "激動の戦国乱世を生き抜くために",
    "数々のドラマは、今ここからはじまる",
    "　",
    "混沌渦巻く嵐の時代",
    "あの『信長』の世界が",
    "今、ネットワーク空間で蘇る",
    "　",
    "その世界は、",
    "あなたの新たな生き甲斐になる",
    "もう一つの人生の舞台",
])

NAMES = {
    "english": {
        "icon": {"title0": "Nobunaga's Ambition Online",
                 "title1": "~Hiryu no Sho~"},
        "info": {"title": "Nobunaga's Ambition Online ~Hiryu no Sho~",
                 "genre": "Online RPG",
                 "note": _NOTE_EN},
    },
    "japanese": {
        "icon": {"title0": "信長の野望Online",
                 "title1": "～飛龍の章～"},
        "info": {"title": "信長の野望 Online ～飛龍の章～",
                 "genre": "オンラインＲＰＧ",
                 "note": _NOTE_JA},
    },
}

def set_fields(text, fields):
    """(new text, [keys changed]). Line endings and separators are kept."""
    new_text, changed, _last = polretitle.set_fields(text, fields)
    return new_text, changed


def with_uninstall_lines(text):
    """(text, added). Stock HDD-OSD lists an entry as "Corrupted Data" when its
    icon.sys has no uninstallmes0..2 lines (PCSX2 + HDD-OSD rig, 2026-10-08);
    every retail area carries them, empty or not. PSBBN does not care, which is
    why areas written without them looked fine on PSBBN drives."""
    if re.search(r"(?m)^uninstallmes0\s*=", text):
        return text, False
    eol = "\r\n" if "\r\n" in text else "\n"
    eq = " = " if re.search(r"(?m)^title0 = ", text) else "="
    if text and not text.endswith("\n"):
        text += eol
    text += "".join("uninstallmes%d%s%s" % (i, eq, eol) for i in range(3))
    return text, True


def area_with(area, fields):
    """(new area, [keys changed]). The slots stay where they are."""
    s = attrarea.slots(area)
    new_text, changed = set_fields(s[1][2].decode("utf-8"), fields)
    new_text, added = with_uninstall_lines(new_text)
    if added:
        changed = changed + ["uninstallmes0-2"]
    if not changed:
        return area, []
    same_icon = (s[2][0], s[2][1]) == (s[3][0], s[3][1])
    new = attrarea.build_area(s[0][2], new_text.encode("utf-8"), s[2][2],
                              None if same_icon else s[3][2],
                              icon_off=s[2][0],
                              copy_off=None if same_icon else s[3][0])
    # Rebuilding can only shrink the area; keep the old length so no stale
    # icon bytes are left past a shorter area's end.
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


def state(image):
    """english or japanese, by the browser entry's title0 (the installer keeps
    it in step with the text), or absent without a Nobunaga partition."""
    found = apa.find_partition(image, PARTITION)
    if found is None:
        return "absent"
    area = attrarea.read_area(image, found[0])
    title = ((attrarea.title0_of(area) if area else None) or "").strip()
    return "english" if title == NAMES["english"]["icon"]["title0"] else "japanese"


def retitle(image, language, write=False):
    """[lines] describing the change, or None without a Nobunaga partition."""
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
    ap.add_argument("language", choices=sorted(NAMES) + ["state"],
                    help="`state` prints english, japanese or absent and stops")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if args.language == "state":
        print(state(args.drive))
        return 0
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
