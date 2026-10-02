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
r"""What a drive needs before the pop'n installer can run on it. Read-only.

The pop'n install is a single 128 MiB PFS partition:

    PP.BLJA-00010    128 MiB   (fpwd/rpwd = POPNPUZZ)

No sub-partitions, no companion PC partition. `PIECES` is that list. The
installer places the partition inside the APA chain's free space, aligned to
its own size (as APA requires).

On an APA-Jail drive that free space can run past the PS2 region into the
exFAT partition holding the user's games (see playonline/jail.py), and the
console does not know about the boundary. So the free space counted here is
only what lies inside the PS2 region. That is what it is safe to give the
installer, and Nobunaga's check.py established the same rule.

The launcher also reads /etc/bnnetwork/netcnf000.dat on hdd0:__sysconf. That
is keyed to the console, so only the console can write it (through PSBBN's
own network settings). This step only reports whether the file is there.

    python3 -m popn.check DRIVE
    python3 -m popn.check DRIVE --plain      key=value lines for the shell
"""
import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playonline import apa, jail, netpart                  # noqa: E402

GAME_PART = "PP.BLJA-00010"
PIECES = {
    GAME_PART: (128,),
}
SYSTEM_PARTS = ("__system", "__sysconf", "__common")
NETCNF = "/etc/bnnetwork/netcnf000.dat"


def free_in_region(path):
    """[(lba, sectors)] of free space inside the PS2's region, largest first.

    Same rule as helper/nobunaga/check.py: type-0 free entries plus the tail
    span after the last partition, all clipped to the APA-Jail boundary.
    """
    region = jail.apa_region(path)
    if region is not None:
        lo, hi = region[0], region[0] + region[1]
    else:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            lo, hi = 0, min(f.tell() // 512, 1 << 28)
    spans = [(p.lba, p.lba + p.sectors) for p in apa.free_entries(path)]
    parts = apa.partitions(path)
    if parts:
        spans.append((max(p.lba + p.sectors for p in parts), hi))
    out = []
    for start, end in spans:
        start, end = max(start, lo), min(end, hi)
        if end > start:
            out.append((start, end - start))
    out.sort(key=lambda e: e[1], reverse=True)
    return out


def fits(free, pieces_mib):
    """True if every piece finds an aligned slot, largest piece first."""
    spans = [(lba, lba + sectors) for lba, sectors in free]
    for piece in sorted(pieces_mib, reverse=True):
        size = piece * 2048
        for i, (start, end) in enumerate(spans):
            at = (start + size - 1) // size * size
            if at + size <= end:
                spans[i:i + 1] = [s for s in ((start, at), (at + size, end))
                                  if s[1] > s[0]]
                break
        else:
            return False
    return True


def sysconf_netcnf(path):
    """True, False, or None when __sysconf cannot be read."""
    from playonline.lib import polpfsread
    try:
        lba, sectors = apa.find_partition(path, "__sysconf")
        with open(path, "rb") as f:
            part, ino = polpfsread.mount(f, lba, sectors)
            if part is None:
                return None
            items = []
            polpfsread.walk(part, ino, "/", 0, items, [])
    except (KeyError, IOError, OSError, ValueError):
        return None
    return any(item[0].lower() == NETCNF for item in items)


def inspect(path):
    parts = apa.partitions(path)
    names = {p.ident for p in parts if not p.is_sub}
    info = {}
    info["system"] = all(n in names for n in SYSTEM_PARTS)
    installed = [n for n in PIECES if n in names]
    info["installed"] = installed
    # Every other title partition. On a drive with the PlayOnline titles or
    # Nobunaga on it these are what must come through the pop'n step untouched.
    info["others"] = sorted(n for n in names
                            if n[:3] in ("PP.", "PC.") and n not in PIECES)
    need = [piece for n in PIECES if n not in names for piece in PIECES[n]]
    free = free_in_region(path)
    info["need_mib"] = sum(need)
    info["free_mib"] = sum(s for _l, s in free) // 2048
    info["largest_mib"] = (free[0][1] // 2048) if free else 0
    info["fits"] = fits(free, need)
    info["jailed"] = jail.apa_region(path) is not None

    # __net status is reported (Nobunaga and PlayOnline rely on it), but the
    # pop'n step itself does not touch it: pop'n's installer writes no bytes
    # to __net, so a drive without __net records is still installable.
    net = netpart.present(path)
    if not net:
        info["net"] = "absent"
        info["record"] = "absent"
    else:
        checks = {name: ok for name, ok, _d in netpart.verify(path)}
        info["net"] = "ok" if checks.get("__net passwords") else "passwords"
        info["record"] = "present" if checks.get("__net record") else "absent"
    info["netcnf"] = {True: "present", False: "absent",
                      None: "unknown"}[sysconf_netcnf(path)]
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive")
    ap.add_argument("--plain", action="store_true")
    args = ap.parse_args()
    info = inspect(args.drive)

    if args.plain:
        print("system=%d" % info["system"])
        print("installed=%s" % ",".join(info["installed"]))
        print("others=%s" % ",".join(info["others"]))
        for key in ("need_mib", "free_mib", "largest_mib"):
            print("%s=%d" % (key, info[key]))
        print("fits=%d" % info["fits"])
        print("jailed=%d" % info["jailed"])
        for key in ("net", "record", "netcnf"):
            print("%s=%s" % (key, info[key]))
        return

    print("  PS2 system partitions   %s" % ("present" if info["system"] else "MISSING"))
    print("  pop'n partition         %s" % (", ".join(info["installed"]) or "none yet"))
    print("  other titles            %s" % (", ".join(info["others"]) or "none"))
    print("  free in the PS2 region  %d MiB (largest run %d MiB)%s"
          % (info["free_mib"], info["largest_mib"],
             ", APA-Jail boundary applied" if info["jailed"] else ""))
    if info["need_mib"]:
        print("  the install needs       %d MiB: %s"
              % (info["need_mib"], "fits" if info["fits"] else "DOES NOT FIT"))
    print("  __net                   %s, record %s" % (info["net"], info["record"]))
    print("  network settings        %s (%s on __sysconf)" % (info["netcnf"], NETCNF))


if __name__ == "__main__":
    main()
