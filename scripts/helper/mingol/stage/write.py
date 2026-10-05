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
"""Write a staged Minna no Golf Online partition onto a PS2 drive (or image).

    python -m mingol.stage.write DEVICE --stage DIR --hddid FILE
        [--pfsshell CMD] [--keeplist <OPL>/protect-parts.list] [--write]

DIR is what `python -m mingol.stage` wrote. The steps, as the kit-based
mingolinstall.py did them:

  1. check     the partition is not there yet, and the drive's own __net record
               decodes with this HDD ID to the four the stage sealed with (the
               record is read, never written: it is the one PlayOnline shares).
  2. mkpart    PP.SCPS-15049..APPLICATION, 1536 MiB PFS (pfsshell shapes it as a
               1 GiB main + one 512 MiB sub, the retail layout), then put tree/.
  3. password  rpwd = fpwd = apa_password(id, "MM21") on the main header (the
               boot ELF mounts hdd0:PP.SCPS-15049..APPLICATION,MM21). Then clear
               the APA journal pfsshell leaves behind (it holds the pre-password
               header).
  4. attr      the attribute area (browser icon + boot block) at main + 0x1000.
  5. protect   add the partition to the PSBBN keep-list (protect-parts.list) so a
               PSBBN game add never deletes it, when --keeplist is given.

Dry run unless --write.
"""
import argparse
import json
import os
import shlex
import struct
import subprocess
import sys

from playonline.lib import polhdd, polrecord

SECTOR = 512
PARTITION = "PP.SCPS-15049..APPLICATION"
PASSWORD = b"MM21"
PART_MIB = 1536
ATTR_OFF = 0x1000
NET_RECORD_OFF = 0x201800


def partitions(device):
    from playonline.lib.polnetdump import partitions as walk
    with open(device, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        return list(walk(f, size))


def find_partition(device, name):
    for start, length, _ptype, pname in partitions(device):
        if pname == name:
            return start, length
    return None


def net_four(device, hddid):
    """Decode the drive's own __net DNAS record (partition +0x201800) with its HDD ID.
    polrecord's reply[84..99] is HDD ID bytes 0x50..0x60 (the ATA reply sits at +4)."""
    net = find_partition(device, "__net")
    if not net:
        raise SystemExit("no __net partition on %s" % device)
    with open(device, "rb") as f:
        f.seek(net[0] * SECTOR + NET_RECORD_OFF)
        rec = f.read(32)
    if not any(rec):
        raise SystemExit("the __net DNAS record is empty: this drive has never been "
                         "provisioned (run the PlayOnline step first)")
    dec = bytes(polrecord.decode(rec, polrecord.derive_key(hddid[0x50:0x60])))
    if any(dec[12:20]):
        raise SystemExit("the __net record does not decode with this HDD ID (%s): "
                         "wrong playonline.hddid?" % dec[:20].hex())
    return dec[:4]


def _quote(name):
    return '"%s"' % name if " " in name else name


def emit_dir(out, host_dir):
    entries = sorted(os.scandir(host_dir), key=lambda e: e.name)
    files = [e for e in entries if e.is_file()]
    if files:
        out.append("lcd %s" % _quote(host_dir.replace("\\", "/")))
        out += ["put %s" % _quote(e.name) for e in files]
    for e in entries:
        if e.is_dir():
            out += ["mkdir %s" % _quote(e.name), "cd %s" % _quote(e.name)]
            emit_dir(out, e.path)
            out.append("cd ..")


def pfsshell_script(device, staged):
    out = ["device %s" % device,
           "mkpart %s %dM PFS" % (PARTITION, PART_MIB), "mount %s" % PARTITION]
    emit_dir(out, staged)
    return "\n".join(out + ["umount", "exit", ""])


def set_password(device, lba):
    """rpwd = fpwd = apa_password(id, MM21) on the main header, checksum refreshed."""
    pw = polhdd.apa_password(PARTITION, PASSWORD)
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR)
        h = bytearray(f.read(1024))
        if h[0x10:0x30].split(b"\0")[0].decode("latin-1") != PARTITION:
            raise SystemExit("header at LBA %d is not %s" % (lba, PARTITION))
        h[0x30:0x38] = pw
        h[0x38:0x40] = pw
        struct.pack_into("<I", h, 0, polhdd.checksum(bytes(h)))
        f.seek(lba * SECTOR)
        f.write(h)
    return pw


def clear_journal(device, backup):
    """pfsshell leaves its APA journal behind (MBR-area sectors 6-7, 10-15), holding our
    header as it was BEFORE set_password. A stale journal stops HDD-OSD booting, and a
    replay would drop the password. Same sectors as PlayOnline poljournal.py --clear;
    8-9 are left alone."""
    with open(device, "r+b") as f:
        with open(backup, "wb") as b:
            b.write(f.read(SECTOR * 16))
        for s in (6, 7, 10, 11, 12, 13, 14, 15):
            f.seek(s * SECTOR)
            f.write(bytes(SECTOR))


def write_attr(device, lba, attr):
    with open(attr, "rb") as f:
        area = f.read()
    if area[:9] != b"PS2ICON3D":
        raise SystemExit("attr file has no PS2ICON3D magic")
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        f.write(area)


def protect(keeplist):
    """The installer owns its keep-list entry: append once, never rewrite other lines."""
    lines = []
    if os.path.exists(keeplist):
        with open(keeplist, encoding="utf-8") as f:
            lines = f.read().splitlines()
    if PARTITION in lines:
        return False
    ends_nl = True
    if lines:
        with open(keeplist, "rb") as f:
            ends_nl = f.read().endswith(b"\n")
    with open(keeplist, "a", encoding="utf-8", newline="\n") as f:
        if not ends_nl:
            f.write("\n")
        f.write(PARTITION + "\n")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("device")
    ap.add_argument("--stage", required=True, help="the folder `python -m mingol.stage` wrote")
    ap.add_argument("--hddid", required=True, help="the drive's 512-byte identity")
    ap.add_argument("--pfsshell", default="pfsshell",
                    help="pfsshell command line (a path with spaces is quoted as one word)")
    ap.add_argument("--keeplist", help="<OPL>/protect-parts.list on the exFAT partition")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)

    stage = os.path.abspath(a.stage)
    with open(os.path.join(stage, "game.json")) as f:
        game = json.load(f)
    tree = os.path.join(stage, "tree")
    attr = os.path.join(stage, "attr.bin")
    for p in (tree, attr, os.path.join(tree, "dnasload.elf")):
        if not os.path.exists(p):
            raise SystemExit("the stage is incomplete: no %s" % p)
    if game.get("partition") != PARTITION:
        raise SystemExit("the stage is for %s, not %s" % (game.get("partition"), PARTITION))

    with open(a.hddid, "rb") as f:
        hddid = f.read()
    if len(hddid) != 512 or hddid[:32] != b"Sony Computer Entertainment Inc.":
        raise SystemExit("%s does not look like a PS2 HDD ID" % a.hddid)
    if find_partition(a.device, PARTITION):
        raise SystemExit("%s already exists on %s: remove it first (reinstall is not "
                         "in-place)" % (PARTITION, a.device))
    four = net_four(a.device, hddid)
    if four.hex() != game.get("four"):
        raise SystemExit("the stage was sealed with four %s but %s's __net record holds %s"
                         % (game.get("four"), a.device, four.hex()))
    print("== target %s, four %s" % (a.device, four.hex()))

    script = pfsshell_script(a.device, tree)
    with open(stage.rstrip("/\\") + ".pfsshell.txt", "w", newline="\n") as f:
        f.write(script)
    print("== pfsshell script: %d commands (saved next to the stage dir)" % script.count("\n"))
    if not a.write:
        print(script[:600] + ("..." if len(script) > 600 else ""))
        print("== dry run: nothing written (pass --write)")
        return 0

    cmd = [a.pfsshell] if os.path.isfile(a.pfsshell) else shlex.split(a.pfsshell)
    subprocess.run(cmd, input=script, text=True, check=True)
    part = find_partition(a.device, PARTITION)
    if not part:
        raise SystemExit("pfsshell finished but %s is not in the APA table" % PARTITION)
    pw = set_password(a.device, part[0])
    print("== password set on LBA %d (%s)" % (part[0], pw.hex()))
    jb = stage.rstrip("/\\") + ".journal-backup.bin"
    clear_journal(a.device, jb)
    print("== APA journal cleared (sectors 0-15 backed up to %s)" % jb)
    write_attr(a.device, part[0], attr)
    print("== attr written at LBA %d + 0x1000" % part[0])
    if a.keeplist:
        print("== keep-list: %s" % ("added" if protect(a.keeplist) else "already listed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
