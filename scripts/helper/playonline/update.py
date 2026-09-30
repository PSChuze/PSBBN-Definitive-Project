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
"""Update an installed title from the patch server, on the PC.

The console's own updater works, but the PS2 takes files at a few hundred
kilobytes a second, so a full FFXI update (39,000 files, 5.5 GB) takes many
hours. This module does what the updater does, with the drive attached to
the PC:

  1. read the title's `patch.ver`, ask the server for the latest version and
     fetch the patch list (`polp`)
  2. take each file whose newest row is newer than the drive's version, and
     no newer than the server's latest; fetch and check it against the list
  3. prepare each file the way the updater would have written it. The
     updater (`sqPatchMain` in polapp) stages every download as
     `<name>.tmp2`. A name it classifies as keyed is converted from the
     universal form the server sends to the drive-keyed form and stored
     under its own name, and the `.tmp2` stays beside it; any other name is
     renamed into place. The classifier matches names ending `.pex`, `.prg`
     or `.enc` and names that start with `S` and a capital letter, case
     sensitive. Keyed files need the HDD ID the install was keyed to, and
     the drive's `__net` record
  4. write pfsshell commands that put every file, then `patch.cfg` (the list
     as served), `patch2.cfg` (the blocks of the files this update fetched)
     and last `patch.ver`. If the write stops part way, the drive still
     reports its old version and the console, or this module, starts over.

Nothing already on the partition is removed, except a file this update
replaces.

    python3 -m playonline.update DRIVE --title ffxi-us --work DIR --out cmds \\
        --hddid playonline.hddid --derive-elf ELF
    sudo pfsshell < cmds
    python3 -m playonline.update DRIVE --title ffxi-us --work DIR --verify

Exit status 3 means the title is already at the server's latest version.
"""
import argparse
import concurrent.futures
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import zlib

from . import apa, pfsput, polp, titles
from .lib import polfill, polnetdump, polpfsread

FIO_S_IFDIR = 0x1000
SECTOR = 512

# The version files the updater keeps beside the title's own files.
PATCH_VER, PATCH_CFG, PATCH_WORK = "patch.ver", "patch.cfg", "patch2.cfg"
OWN_FILES = (PATCH_VER, PATCH_CFG, PATCH_WORK)
RETRIES = 4


def keyed_on_console(path):
    """True when the updater converts this file to the drive's key.

    polapp's classifier (US 1.18.03b, 0xc33238) works on the name alone and
    ignores the drive's plaintext switch. Uppercase `.PEX` is not matched.
    """
    base = path.rsplit("/", 1)[-1]
    if base.endswith((".pex", ".prg", ".enc")):
        return True
    return len(base) >= 2 and base[0] == "S" and base[1].isupper()


def number_of(title):
    """The patch service's product number: the partition name's slot
    (`PP.SCUS-97266.0001.FFXI` -> "0001"), not the disc serial."""
    return title.partition.split(".")[2]


def region_for(image, title):
    """The region tag the drive's Viewer sends for this title.

    The US Viewer sends "P2U" and the JP Viewer "PS2", for the titles it
    launches as well as for itself. FFXI is the exception: consoles of both
    regions have asked for it as PS2/0001, and no P2U/0001 request has been
    seen.
    """
    if title.key.startswith("ffxi-"):
        return "PS2"
    names = {p.ident for p in apa.partitions(image)}
    if titles.TITLES["viewer-us"].partition in names:
        return "P2U"
    return "PS2"


# --- the partition ------------------------------------------------------------

class Drive(object):
    """A title's partition, read through the reader that follows sub-partitions."""

    def __init__(self, image, title):
        self.image, self.title = image, title
        try:
            self.lba, self.sectors = apa.find_partition(image, title.partition)
        except KeyError:
            raise SystemExit("%s: %s is not on this drive" % (image, title.partition))
        self.f = open(image, "rb")
        self.f.seek(0, os.SEEK_END)
        self.size = self.f.tell()
        self.subs = polnetdump.sub_partitions(self.f, self.size).get(self.lba)
        self.part, self.root = polpfsread.mount(self.f, self.lba, self.sectors, self.subs)
        if self.part is None:
            raise SystemExit("%s did not mount" % title.partition)
        self.files, self.dirs = {}, set()
        self._walk(self.root, (), 0)

    def close(self):
        self.f.close()

    def _walk(self, ino, at, depth):
        for name, inode, sub, _flags in polfill.read_dir_full(self.part, ino):
            if name in (b".", b".."):
                continue
            child = polfill.read_inode(self.part, inode, sub)
            if not child["ok"]:
                continue
            here = at + (name.decode("latin-1"),)
            if child["mode"] & FIO_S_IFDIR:
                self.dirs.add(here)
                if depth < 24:
                    self._walk(child, here, depth + 1)
            else:
                self.files[here] = child

    def read(self, path):
        ino = self.files.get(tuple(path.split("/")))
        return None if ino is None else polfill.read_content(self.part, ino)

    def version(self):
        raw = self.read(PATCH_VER)
        if raw is None:
            raise SystemExit("%s has no patch.ver, so it was never installed "
                             "the way the Viewer installs a title" % self.title.partition)
        return raw.split(b"\0")[0].decode("latin-1").strip()

    def zones_free(self):
        """Free zones across the main partition and every sub-partition.

        Each has its own bitmap and its own zone numbering: the main's sits
        0x2000 sectors past the superblock, a sub's at sector `1 << scale`.
        """
        scale = self.part.scale
        free = 0
        for sub, lba in sorted(self.part.subs.items()):
            self.f.seek(lba * SECTOR)
            h = self.f.read(0x400)
            if sub and struct.unpack_from("<I", h, 0x5C)[0] != sub:
                raise SystemExit("sub-partition at LBA %d does not call itself %d"
                                 % (lba, sub))
            zones = struct.unpack_from("<I", h, 0x44)[0] >> scale
            start = (1 << scale) + (0x2000 if sub == 0 else 0)
            self.f.seek((lba + start) * SECTOR)
            bm = self.f.read((zones + 8 * SECTOR - 1) // (8 * SECTOR) * SECTOR)
            whole, rest = divmod(zones, 8)
            used = sum(bin(b).count("1") for b in bm[:whole])
            used += bin(bm[whole] & ((1 << rest) - 1)).count("1") if rest else 0
            free += zones - used
        return free

    def zones_for(self, size):
        """Zones a file of `size` bytes takes: its data, its inode, and one
        spare for the segment inode a fragmented file needs."""
        return -(-size // self.part.zone_size) + 2


# --- the drive's keys ---------------------------------------------------------

class Keys(object):
    """What converting a file to the drive's key needs."""

    def __init__(self, image, hddid_path, pcsx2=False):
        from .lib import ci_transcrypt, polrecord
        from .repair import read_record
        with open(hddid_path, "rb") as f:
            self.hddid = f.read()
        self.hddid_path = hddid_path
        self.pcsx2 = pcsx2
        self.record = read_record(image)
        _ata, key = ci_transcrypt.ata_material(self.hddid, pcsx2)
        head = polrecord.decode(self.record, key, 24)
        if any(head[12:20]):
            raise SystemExit("the drive's __net record does not open with %s: it "
                             "is not the HDD ID this drive was keyed to"
                             % hddid_path)
        self.four = head[:4]

    def installed(self, universal):
        from .lib import ci_transcrypt
        out = ci_transcrypt.transcrypt(universal, self.hddid, self.four, pcsx2=self.pcsx2)
        self.check(out)
        return out

    def check(self, installed, what="the converted file"):
        from .lib import ci_transcrypt
        bad = [(label, detail) for label, good, detail
               in ci_transcrypt.check(installed, self.hddid, self.four, pcsx2=self.pcsx2)
               if not good]
        if bad:
            raise SystemExit("%s does not read back with this drive's key: %s"
                             % (what, "; ".join("%s: %s" % b for b in bad)))


def check_drive_key(drive, keys):
    """Read one module already on the partition with the key, before any
    conversion, so a wrong HDD ID stops here and not on the console."""
    for path in sorted(drive.files):
        name = "/".join(path)
        if name.endswith(".pex.enc"):
            keys.check(drive.read(name), "/" + name + " on the drive")
            return name
    return None


# --- the plan -----------------------------------------------------------------

class Plan(object):
    def __init__(self, have, latest, listing, blocks, chosen, region, tool):
        self.have, self.latest = have, latest
        self.listing = listing          # the list, decompressed, as served
        self.blocks = blocks
        self.chosen = chosen            # [(block, row)] in list order
        self.region, self.tool = region, tool

    @property
    def current(self):
        return polp.version_key(self.latest) <= polp.version_key(self.have)


def plan(drive, host, port, region, tool=True):
    have = drive.version()
    client = polp.Client(host, port, region, number_of(drive.title), tool=tool)
    try:
        status, latest = client.version(have)
        if polp.version_key(latest) <= polp.version_key(have):
            return Plan(have, latest, None, [], [], region, client.tool)
        listing = client.patch_list()
    except polp.Rejected:
        raise SystemExit("the server at %s:%d has no %s/%s update"
                         % (host, port, region, number_of(drive.title)))
    finally:
        client.close()
    blocks = polp.parse_list(listing.decode("latin-1"))
    chosen = []
    for b in blocks:
        if b.path in OWN_FILES:
            continue
        row = b.newest(latest)
        if row is not None and polp.version_key(row.version) > polp.version_key(have):
            chosen.append((b, row))
    return Plan(have, latest, listing, blocks, chosen, region, client.tool)


def need_zones(drive, chosen):
    """(zones the update takes, zones it frees) on the partition."""
    take = give = 0
    new_dirs = set()
    for b, row in chosen:
        path = tuple(b.path.split("/"))
        take += drive.zones_for(row.size)
        if keyed_on_console(b.path):
            take += drive.zones_for(row.size)          # the .tmp2 beside it
        old = drive.files.get(path)
        if old is not None:
            give += drive.zones_for(old["size"])
        for k in range(1, len(path)):
            if path[:k] not in drive.dirs:
                new_dirs.add(path[:k])
    return take + 2 * len(new_dirs) + 16, give


# --- fetching -----------------------------------------------------------------

def fetch_all(plan_, host, port, product, stage, connections=8, log=print):
    """Download, check and decompress every chosen file into `stage`.

    A file already in `stage` that matches its row is kept, so an
    interrupted run picks up where it stopped. A keyed file is staged as its
    `.tmp2`, the universal form, and converted later.
    """
    local = threading.local()
    lock = threading.Lock()
    done = {"n": 0, "bytes": 0, "kept": 0}
    total = len(plan_.chosen)
    t0 = time.monotonic()

    def target(b):
        dest = os.path.join(stage, *b.path.split("/"))
        return dest + ".tmp2" if keyed_on_console(b.path) else dest

    def one(item):
        b, row = item
        dest = target(b)
        if os.path.isfile(dest) and os.path.getsize(dest) == row.size:
            with open(dest, "rb") as f:
                if row.check(f.read()) is None:
                    with lock:
                        done["n"] += 1
                        done["kept"] += 1
                    return
        client = getattr(local, "client", None)
        if client is None:
            client = local.client = polp.Client(host, port, plan_.region, product,
                                                tool=plan_.tool)
            with lock:
                clients.append(client)
        # A dropped connection or a damaged file is tried again on a fresh
        # connection; a file the server does not have is not.
        for attempt in range(RETRIES):
            try:
                blob = client.fetch(row.blob, row.blob_size)
                raw = polp.slc_decompress(blob)
                why = row.check(raw)
                if why:
                    raise IOError(why)
                break
            except polp.Rejected:
                raise IOError("%s: the server does not have %s" % (b.path, row.blob))
            except (OSError, ValueError, zlib.error) as e:
                client.close()
                if attempt + 1 == RETRIES:
                    raise IOError("%s: %s (after %d tries)" % (b.path, e, RETRIES))
                time.sleep(2 * (attempt + 1))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".part", "wb") as f:
            f.write(raw)
        os.replace(dest + ".part", dest)
        with lock:
            done["n"] += 1
            done["bytes"] += len(blob)
            n = done["n"]
        if n % 500 == 0 or n == total:
            secs = max(time.monotonic() - t0, 0.001)
            log("  %d/%d files, %.0f MB fetched, %.1f MB/s"
                % (n, total, done["bytes"] / 1e6, done["bytes"] / 1e6 / secs))

    clients = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max(1, connections)) as pool:
            for fut in concurrent.futures.as_completed(
                    [pool.submit(one, item) for item in plan_.chosen]):
                fut.result()
    finally:
        for c in clients:
            c.close()
    if done["kept"]:
        log("  %d file(s) were already fetched and still match the list" % done["kept"])
    return done


def convert(plan_, stage, keys, title, log=print):
    """Put the drive-keyed form of every keyed file beside its `.tmp2`."""
    keyed = [b for b, _row in plan_.chosen if keyed_on_console(b.path)]
    for b in keyed:
        dest = os.path.join(stage, *b.path.split("/"))
        with open(dest + ".tmp2", "rb") as f:
            universal = f.read()
        try:
            out = keys.installed(universal)
        except (ValueError, SystemExit) as e:
            raise SystemExit("%s: the updater would convert this file to the "
                             "drive's key, and it cannot be converted: %s"
                             % (b.path, e))
        if b.path == title.product:
            out = patch_boot_container(out, keys)
        with open(dest, "wb") as f:
            f.write(out)
    if keyed:
        log("  %d file(s) converted to the drive's key" % len(keyed))
    return len(keyed)


def patch_boot_container(installed, keys):
    """The Viewer's boot container carries gates the installer patched. An
    update that ships the container would remove them, so they are applied
    again, as `route prepare` and `repair` do."""
    from .lib import ci_viewerpatch
    from .route import _run
    tmp = tempfile.mkdtemp(prefix="polupdate-")
    try:
        src, rec, out = (os.path.join(tmp, n) for n in ("in", "record", "out"))
        with open(src, "wb") as f:
            f.write(installed)
        with open(rec, "wb") as f:
            f.write(keys.record)
        _run(ci_viewerpatch, ["ci_viewerpatch", "--container", src,
                              "--hddid", keys.hddid_path, "--record", rec, "-o", out])
        with open(out, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_own_files(plan_, meta):
    """patch.cfg, patch2.cfg and patch.ver as the updater leaves them."""
    os.makedirs(meta, exist_ok=True)
    with open(os.path.join(meta, PATCH_CFG), "wb") as f:
        f.write(plan_.listing)
    with open(os.path.join(meta, PATCH_WORK), "wb") as f:
        f.write(polp.work_list([b for b, _row in plan_.chosen]))
    # Square Enix's patch.ver is the ten characters and nothing else.
    with open(os.path.join(meta, PATCH_VER), "wb") as f:
        f.write(plan_.latest.encode("ascii"))


# --- the commands -------------------------------------------------------------

def commands(drive, plan_, stage, meta):
    q = pfsput.quote
    out = ["device %s" % drive.image, "mount %s" % drive.title.partition]
    want_dirs = set()
    for b, _row in plan_.chosen:
        path = tuple(b.path.split("/"))
        for k in range(1, len(path)):
            want_dirs.add(path[:k])
    for d in sorted(want_dirs - drive.dirs):       # sorted, so a parent comes first
        out.append("cd /%s" % "/".join(d[:-1]) if len(d) > 1 else "cd /")
        out.append("mkdir %s" % q(d[-1]))

    by_dir = {}
    for b, _row in plan_.chosen:
        path = tuple(b.path.split("/"))
        names = [path[-1]]
        if keyed_on_console(b.path):
            names.append(path[-1] + ".tmp2")
        by_dir.setdefault(path[:-1], []).extend(names)
    for d in sorted(by_dir):
        out.append("cd /%s" % "/".join(d))
        out.append("lcd %s" % q(pfsput.host_path(os.path.join(stage, *d))))
        for name in by_dir[d]:
            if d + (name,) in drive.files:
                out.append("rm %s" % q(name))
            out.append("put %s" % q(name))

    out += ["cd /", "lcd %s" % q(pfsput.host_path(meta))]
    for name in (PATCH_CFG, PATCH_WORK, PATCH_VER):       # the version last
        if (name,) in drive.files:
            out.append("rm %s" % name)
        out.append("put %s" % name)
    return out + ["umount", "exit"]


def verify(drive, work):
    """[problems]: every staged file against what the partition holds."""
    bad = []
    stage, meta = os.path.join(work, "tree"), os.path.join(work, "meta")
    for base, prefix in ((stage, ()), (meta, ())):
        for dirpath, _dirs, names in os.walk(base):
            rel = os.path.relpath(dirpath, base)
            at = prefix + (() if rel == "." else tuple(rel.split(os.sep)))
            for n in names:
                if n.endswith(".part"):
                    continue
                path = "/".join(at + (n,))
                have = drive.read(path)
                with open(os.path.join(dirpath, n), "rb") as f:
                    want = f.read()
                if have is None:
                    bad.append("/%s is not on the partition" % path)
                elif have != want:
                    bad.append("/%s differs from what was staged" % path)
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("drive", help="device path or drive image")
    ap.add_argument("--title", required=True)
    ap.add_argument("--work", required=True,
                    help="where downloads are kept; reused by a later run")
    ap.add_argument("--out", help="write the pfsshell commands here")
    ap.add_argument("--server", default=None,
                    help="the patch server (default %s)" % _default_host())
    ap.add_argument("--port", type=int, help="its port (default 53000 + title number)")
    ap.add_argument("--region", choices=("PS2", "P2U"),
                    help="the region tag to ask with (default: the drive's Viewer)")
    ap.add_argument("--hddid", help="the HDD ID file the install was keyed with")
    ap.add_argument("--derive-elf", help="the boot executable the key derivation "
                                         "reads (see route.py)")
    ap.add_argument("--disc", help="a PlayOnline disc image, for its keys")
    ap.add_argument("--pcsx2", action="store_true",
                    help="the drive was keyed for PCSX2's zero identity")
    ap.add_argument("--connections", type=int, default=8)
    ap.add_argument("--check", action="store_true",
                    help="only say what an update would fetch")
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
            for line in bad[:40]:
                print("  " + line)
            print("%s: %s" % (title.partition, "%d problem(s)" % len(bad) if bad
                              else "every staged file is on the partition"))
            return 1 if bad else 0

        host = args.server or _default_host()
        port = args.port or polp.port_for(number_of(title))
        region = args.region or region_for(args.drive, title)
        print("%s at %s; asking %s:%d as %s" % (title.partition, drive.version(),
                                                host, port, region))
        p = plan(drive, host, port, region)
        if p.current:
            print("already at the latest version, %s" % p.latest)
            return 3
        size = sum(row.size for _b, row in p.chosen)
        blob = sum(row.blob_size for _b, row in p.chosen)
        keyed = sum(1 for b, _row in p.chosen if keyed_on_console(b.path))
        print("update %s -> %s: %d file(s), %.1f MB to fetch, %.1f MB on the drive, "
              "%d keyed" % (p.have, p.latest, len(p.chosen), blob / 1e6, size / 1e6, keyed))
        if not p.tool:
            print("  the server paces this download for a console (it does not "
                  "know the PC updater's tag), so it will be slow")
        take, give = need_zones(drive, p.chosen)
        free = drive.zones_free()
        zmb = drive.part.zone_size / 1e6
        print("  partition: %.0f MB free, the update needs %.0f MB and frees %.0f MB"
              % (free * zmb, take * zmb, give * zmb))
        if take - give > free:
            print("the partition is too small for this update")
            return 1
        if args.check:
            return 0

        keys = None
        if keyed:
            if not (args.hddid and args.derive_elf):
                sys.exit("this update has %d keyed file(s): --hddid and "
                         "--derive-elf are required" % keyed)
            from . import discs, route
            route.use_keys(discs.identify(args.disc) if args.disc else None,
                           args.derive_elf)
            keys = Keys(args.drive, args.hddid, args.pcsx2)
            name = check_drive_key(drive, keys)
            if name:
                print("  the key reads /%s on the drive" % name)

        stage, meta = os.path.join(args.work, "tree"), os.path.join(args.work, "meta")
        fetch_all(p, host, port, number_of(title), stage, args.connections)
        if keys:
            convert(p, stage, keys, title)
        write_own_files(p, meta)
        cmds = commands(drive, p, stage, meta)
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(cmds) + "\n")
            print("  %d pfsshell command(s) in %s" % (len(cmds), args.out))
        return 0
    finally:
        drive.close()


def _default_host():
    from .patchhost import DEFAULT_HOST
    return DEFAULT_HOST


if __name__ == "__main__":
    sys.exit(main())
