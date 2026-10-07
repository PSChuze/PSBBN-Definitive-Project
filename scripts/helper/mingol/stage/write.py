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

    python -m mingol.stage.write DEVICE --stage DIR --hddid FILE --update [--write]

--update brings a partition this installer made up to a new stage, in place:
the partition, its passwords and its size stay. The stage is compared file by
file with what the partition holds (read with playonline's PFS reader), and
pfsshell rewrites only the files that changed (rm, then put) and puts the new
ones (mkdir as needed); it never runs mkpart or rmpart. Every file only the
partition has, the game's saves and settings, is left as it is, except the
plain overlays an English install puts at the root, which a Japanese stage
drops (they are this installer's, not the game's). Afterwards the MM21
passwords are set again, the APA journal cleared, the attribute area rewritten
if it changed, and the partition read back: every staged file must match and
every kept file must be byte for byte what it was. A partition from the old
kit-based installer (no FMOD/) is refused with exit status 3: reinstall it.

    python -m mingol.stage.write DEVICE --probe

prints what the drive has: absent, old (the kit-based install), english or
japanese (from the browser title).

    python -m mingol.stage.write DEVICE --stage DIR --hddid FILE \
        --reinstall --saves BACKUP_DIR [--write]

--reinstall replaces a partition --update refuses (the old kit-based install)
without losing the game's saves. The files only the partition has, the same
set --update keeps, are copied to BACKUP_DIR and read back there first; then
the partition's passwords are cleared and pfsshell removes it (with its sub),
and the fresh install puts the stage and the saved files together. Last, the
saved files are read back from the new partition. If anything fails after the
removal, BACKUP_DIR still holds them.
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


# ---- the in-place update ---------------------------------------------------

OLD_KIT = 3            # exit status: the partition is the old kit-based install


def plain_overlay_names(tree, inst):
    """The root-level plain overlays an English install puts in (one per
    overlay in the disc's ZZBIN/ but DNAS.BIN): this installer's files, not
    the game's, so a Japanese update removes them. Taken as every *.BIN at
    the root of the stage or the drive whose name is also a sealed container
    under ZZENC/ZZBIN/, or any *.BIN at the root of an English stage."""
    sealed = {p.split("/")[-1].upper() for p in inst.files
              if p.upper().startswith("ZZENC/ZZBIN/") and p.count("/") == 2}
    zz = os.path.join(tree, "ZZENC", "ZZBIN")
    if os.path.isdir(zz):
        sealed |= {n.upper() for n in os.listdir(zz)}
    names = {n for n in sealed if n.endswith(".BIN")}
    names |= {n.upper() for n in os.listdir(tree)
              if n.upper().endswith(".BIN") and os.path.isfile(os.path.join(tree, n))}
    names.discard("DNAS.BIN")
    return names


def save_files(device, tree):
    """{rel: bytes} for the files only the partition has: what --update keeps."""
    from playonline.lib import pfsupdate
    with pfsupdate.Installed(device, PARTITION) as inst:
        ours = plain_overlay_names(tree, inst)
        p = pfsupdate.plan(inst, tree, lambda rel: "/" not in rel and rel.upper() in ours)
        return {rel: inst.read(rel) for rel in p.kept}


def backup_saves(saves, backup):
    """Write the saves under `backup` and read each one back."""
    for rel, data in saves.items():
        dst = os.path.join(backup, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        with open(dst, "rb") as f:
            if f.read() != data:
                raise SystemExit("the copy of %s in %s does not read back" % (rel, backup))


def remove_partition(device, pfsshell):
    """Clear the MM21 passwords (the APA driver refuses to remove a partition
    whose fpwd does not match), then rmpart, which takes the sub with it."""
    part = find_partition(device, PARTITION)
    with open(device, "r+b") as f:
        f.seek(part[0] * SECTOR)
        h = bytearray(f.read(1024))
        h[0x30:0x40] = bytes(16)
        struct.pack_into("<I", h, 0, polhdd.checksum(bytes(h)))
        f.seek(part[0] * SECTOR)
        f.write(h)
    cmd = [pfsshell] if os.path.isfile(pfsshell) else shlex.split(pfsshell)
    subprocess.run(cmd, input="device %s\nrmpart %s\nexit\n" % (device, PARTITION),
                   text=True, check=True)
    if find_partition(device, PARTITION):
        raise SystemExit("pfsshell did not remove %s" % PARTITION)


def read_attr(device, lba, n):
    with open(device, "rb") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        return f.read(n)


def probe(device):
    """absent, old (the kit-based install, no FMOD/), english or japanese."""
    from playonline import attrarea
    from playonline.lib import pfsupdate
    if not find_partition(device, PARTITION):
        return "absent"
    with pfsupdate.Installed(device, PARTITION) as inst:
        if not any(p.startswith("FMOD/") for p in inst.files):
            return "old"
        lba = inst.lba
    area = attrarea.read_area(device, lba)
    title = ((attrarea.title0_of(area) if area else None) or "").strip()
    try:
        title.encode("ascii")
    except UnicodeEncodeError:
        return "japanese"
    return "english" if title else "japanese"


def update(a, stage, tree, attr):
    from playonline.lib import pfsupdate
    with pfsupdate.Installed(a.device, PARTITION) as inst:
        if not any(p.startswith("FMOD/") for p in inst.files):
            print("%s on %s is the old kit-based install (no FMOD/): it cannot be "
                  "updated in place; remove it and install again" % (PARTITION, a.device))
            return OLD_KIT
        lba = inst.lba
        ours = plain_overlay_names(tree, inst)
        plan = pfsupdate.plan(inst, tree, lambda rel: "/" not in rel and rel.upper() in ours)
    with open(attr, "rb") as f:
        want_attr = f.read()
    attr_stale = read_attr(a.device, lba, len(want_attr)) != want_attr
    print("== update %s at LBA %d: %s%s" % (PARTITION, lba, plan.summary(),
                                            ", browser entry changed" if attr_stale else ""))
    for line in plan.lines():
        print(line)
    if plan.empty and not attr_stale:
        print("== the partition is current: nothing to write")
        return 0
    script = pfsupdate.script(a.device, PARTITION, tree, plan)
    with open(stage.rstrip("/\\") + ".update.pfsshell.txt", "w", newline="\n") as f:
        f.write(script)
    if not a.write:
        print(script[:800] + ("..." if len(script) > 800 else ""))
        print("== dry run: nothing written (pass --write)")
        return 0

    if not plan.empty:
        pfsupdate.run(a.pfsshell, script)
    part = find_partition(a.device, PARTITION)
    if not part or part[0] != lba:
        raise SystemExit("%s moved or vanished during the update" % PARTITION)
    pw = set_password(a.device, lba)
    print("== password kept on LBA %d (%s)" % (lba, pw.hex()))
    jb = stage.rstrip("/\\") + ".journal-backup.bin"
    clear_journal(a.device, jb)
    print("== APA journal cleared (sectors 0-15 backed up to %s)" % jb)
    if attr_stale:
        write_attr(a.device, lba, attr)
        print("== attr rewritten at LBA %d + 0x1000" % lba)
    bad = pfsupdate.verify(a.device, PARTITION, tree, plan)
    if read_attr(a.device, lba, len(want_attr)) != want_attr:
        bad.append("attribute area")
    if bad:
        raise SystemExit("the update did not read back as written:\n  " + "\n  ".join(bad))
    print("== read back: every staged file matches, %d kept file(s) unchanged"
          % len(plan.kept))
    if a.keeplist:
        print("== keep-list: %s" % ("added" if protect(a.keeplist) else "already listed"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("device")
    ap.add_argument("--probe", action="store_true",
                    help="print absent, old, english or japanese and stop")
    ap.add_argument("--stage", help="the folder `python -m mingol.stage` wrote")
    ap.add_argument("--hddid", help="the drive's 512-byte identity")
    ap.add_argument("--update", action="store_true",
                    help="update the partition already on the drive in place")
    ap.add_argument("--pfsshell", default="pfsshell",
                    help="pfsshell command line (a path with spaces is quoted as one word)")
    ap.add_argument("--keeplist", help="<OPL>/protect-parts.list on the exFAT partition")
    ap.add_argument("--reinstall", action="store_true",
                    help="remove the partition on the drive and install afresh, "
                         "carrying the game's saves over (needs --saves)")
    ap.add_argument("--saves", help="with --reinstall: where the saves are copied first")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.probe:
        print(probe(a.device))
        return 0
    if not (a.stage and a.hddid):
        ap.error("--stage and --hddid are required")

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
    there = find_partition(a.device, PARTITION)
    if a.update and a.reinstall:
        ap.error("--update and --reinstall are alternatives")
    if a.reinstall and not a.saves:
        ap.error("--reinstall needs --saves")
    if there and not (a.update or a.reinstall):
        raise SystemExit("%s already exists on %s: update it with --update, or "
                         "--reinstall it" % (PARTITION, a.device))
    if (a.update or a.reinstall) and not there:
        raise SystemExit("%s is not on %s: nothing to replace" % (PARTITION, a.device))
    four = net_four(a.device, hddid)
    if four.hex() != game.get("four"):
        raise SystemExit("the stage was sealed with four %s but %s's __net record holds %s"
                         % (game.get("four"), a.device, four.hex()))
    print("== target %s, four %s" % (a.device, four.hex()))
    if a.update:
        return update(a, stage, tree, attr)
    if a.reinstall:
        return reinstall(a, stage, tree, attr)
    return fresh(a, stage, tree, attr)


def reinstall(a, stage, tree, attr):
    from playonline.lib import pfsupdate
    saves = save_files(a.device, tree)
    print("== reinstall %s: %d file(s) only the partition has are carried over"
          % (PARTITION, len(saves)))
    for rel in sorted(saves):
        print("   save %s (%d B)" % (rel, len(saves[rel])))
    if not a.write:
        print("== dry run: nothing written (pass --write)")
        return 0
    backup = os.path.abspath(a.saves)
    backup_saves(saves, backup)
    print("== saves copied to %s and read back" % backup)
    remove_partition(a.device, a.pfsshell)
    print("== removed the old %s" % PARTITION)

    # The saves go in with the stage, then leave the stage again.
    placed, made = [], []
    try:
        for rel, data in saves.items():
            dst = os.path.join(tree, *rel.split("/"))
            d = os.path.dirname(dst)
            while not os.path.isdir(d):
                made.append(d)
                d = os.path.dirname(d)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            placed.append(dst)
        rc = fresh(a, stage, tree, attr)
    finally:
        for p in placed:
            os.remove(p)
        for d in sorted(made, key=len, reverse=True):
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
    with pfsupdate.Installed(a.device, PARTITION) as inst:
        bad = [rel for rel, data in saves.items()
               if rel not in inst.files or inst.read(rel) != data]
    if bad:
        raise SystemExit("saves did not read back from the new partition (copies are "
                         "in %s):\n  %s" % (backup, "\n  ".join(sorted(bad))))
    print("== read back: all %d save file(s) are on the new partition" % len(saves))
    return rc


def fresh(a, stage, tree, attr):
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
