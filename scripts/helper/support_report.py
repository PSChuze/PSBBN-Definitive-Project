#!/usr/bin/env python3
#
# Support report for the PSBBN Definitive Project
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
"""One zip a player can send when a game does not boot (HDD Games option 6).

Collects, without writing to the drive:
  hwaudit.txt / hwaudit.json  the drive report (nobunaga/tools/hwaudit.py)
  trace-<partition>.bin       the first sector of each game's /trace.bin, the
                              boot record the loader's atadpatch wrote during
                              the last boot (armed by debug text Y). The
                              sector is copied whether or not it was written;
                              trace-decode.py tells the two apart.
  logs/                       the toolkit's own logs
  info.txt                    date, toolkit version, console model, drive

The drive is opened read-only. The caller flushes the block device first.

  support_report.py --device /dev/sdX --helper scripts/helper --logs logs
                    --out DIR [--model SCPH-xxxxx]
prints the zip's path on success.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import zipfile


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--device", required=True)
    ap.add_argument("--helper", required=True, help="scripts/helper")
    ap.add_argument("--logs", required=True, help="the toolkit's logs folder")
    ap.add_argument("--out", required=True, help="folder the zip goes to")
    ap.add_argument("--model", default="", help="console model the player typed")
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    work = tempfile.mkdtemp(prefix="support-report-")
    files = {}                                  # name in the zip -> local path
    notes = []

    # 1. hwaudit (read-only). A failure is noted, not fatal: the traces and
    # logs are still worth sending.
    hw = os.path.join(args.helper, "nobunaga", "tools", "hwaudit.py")
    hj = os.path.join(work, "hwaudit.json")
    rc, text = run([sys.executable, hw, args.device, "--helper", args.helper, "--json", hj])
    with open(os.path.join(work, "hwaudit.txt"), "w") as f:
        f.write(text)
    files["hwaudit.txt"] = os.path.join(work, "hwaudit.txt")
    if rc == 0 and os.path.exists(hj):
        files["hwaudit.json"] = hj
    else:
        notes.append("hwaudit exit %d" % rc)

    # 2. each game's boot record, at the LBA hwaudit found for /trace.bin.
    games = {}
    if "hwaudit.json" in files:
        try:
            games = json.load(open(hj)).get("games", {})
        except ValueError as exc:
            notes.append("hwaudit.json unreadable: %s" % exc)
    with open(args.device, "rb") as dev:
        for name, g in sorted(games.items()):
            lba = (g.get("trace_bin") or {}).get("lba")
            if not lba:
                continue
            dev.seek(lba * 512)
            blk = dev.read(512)
            p = os.path.join(work, "trace-%s.bin" % name)
            with open(p, "wb") as f:
                f.write(blk)
            files[os.path.basename(p)] = p
            notes.append("trace %s: LBA %d" % (name, lba))

    # 3. the toolkit's logs.
    if os.path.isdir(args.logs):
        for n in sorted(os.listdir(args.logs)):
            p = os.path.join(args.logs, n)
            if os.path.isfile(p):
                files["logs/" + n] = p

    # 4. info.txt
    _, ver = run(["git", "-C", os.path.dirname(os.path.dirname(os.path.abspath(args.helper))),
                  "rev-parse", "--short", "HEAD"])
    _, drive = run(["lsblk", "-dn", "-o", "NAME,SIZE,MODEL,SERIAL", args.device])
    with open(os.path.join(work, "info.txt"), "w") as f:
        f.write("date: %s\n" % stamp)
        f.write("toolkit: %s\n" % ver.strip())
        f.write("console model: %s\n" % (args.model or "(not given)"))
        f.write("drive: %s\n" % drive.strip())
        for n in notes:
            f.write("%s\n" % n)
    files["info.txt"] = os.path.join(work, "info.txt")

    os.makedirs(args.out, exist_ok=True)
    zpath = os.path.join(args.out, "support-report-%s.zip" % stamp)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, p in files.items():
            z.write(p, arc)
    print(zpath)
    return 0


if __name__ == "__main__":
    sys.exit(main())
