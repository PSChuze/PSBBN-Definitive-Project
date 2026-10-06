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
"""Update a game partition in place from a new stage, keeping the game's files.

The game installers' update path (HippaulInstaller's games/update.py, done on a
live drive with pfsshell instead of rewriting an image):

  plan     the staged tree is compared file by file with the partition, read
           with polfill (read-only): changed (same path, other bytes), added
           (not on the drive) and kept (only on the drive: the game's saves and
           settings, carried over untouched). An installer can name drive-only
           files that are its own (`stale`), to be removed.
  script   pfsshell commands: rm the stale and changed files, mkdir the new
           directories, put the changed and new files. Never mkpart, rmpart or
           a format: the partition, its size and its passwords stay.
  verify   read everything back: each staged file must match, each kept file
           must hash as before, each stale file must be gone.

The caller restores what pfsshell can disturb outside PFS (APA passwords,
header checksums, the APA journal) and the attribute area.
"""
import hashlib
import os
import shlex
import subprocess

from . import polfill, polpfsread
from .polnetdump import partitions, sub_partitions

FIO_S_IFDIR = 0x1000


class Installed:
    """A PFS partition as it is on the drive: {path: inode} and its directories."""

    def __init__(self, device, partition):
        self.partition = partition
        self.f = open(device, "rb")
        try:
            self.f.seek(0, 2)
            size = self.f.tell()
            hit = [p for p in partitions(self.f, size) if p[3] == partition]
            if not hit:
                raise SystemExit("%s is not on %s" % (partition, device))
            self.lba, length = hit[0][0], hit[0][1]
            self.part, root = polpfsread.mount(self.f, self.lba, length,
                                               sub_partitions(self.f, size).get(self.lba))
            if not self.part:
                raise SystemExit("%s on %s is not a mountable PFS volume" % (partition, device))
            self.files, self.dirs = {}, set()
            self._walk(root, "")
        except BaseException:
            self.f.close()
            raise

    def _walk(self, ino, prefix):
        for name, zone, sub, _flags in polfill.read_dir_full(self.part, ino):
            if name in (b".", b".."):
                continue
            rel = prefix + name.decode("latin-1")
            child = polfill.read_inode(self.part, zone, sub)
            if not child["ok"] or child["magic"] != polfill.PFS_SEGD_MAGIC:
                raise SystemExit("%s: /%s has a bad inode; check the partition first"
                                 % (self.partition, rel))
            if child["mode"] & FIO_S_IFDIR:
                self.dirs.add(rel)
                self._walk(child, rel + "/")
            else:
                self.files[rel] = child

    def read(self, rel):
        """The file's bytes, or None when the reader cannot follow it whole
        (an inode continued in a further segment); such a file counts as
        changed and is rewritten."""
        ino = self.files[rel]
        data = polfill.read_content(self.part, ino)
        return data if len(data) == ino["size"] else None

    def sha(self, rel):
        data = self.read(rel)
        return None if data is None else hashlib.sha1(data).hexdigest()

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def staged_files(tree):
    out = {}
    for dirpath, _dirs, names in os.walk(tree):
        for n in names:
            full = os.path.join(dirpath, n)
            out[os.path.relpath(full, tree).replace(os.sep, "/")] = full
    return out


class Plan:
    def __init__(self, changed, added, kept, stale, new_dirs, kept_sha):
        self.changed, self.added, self.kept, self.stale = changed, added, kept, stale
        self.new_dirs, self.kept_sha = new_dirs, kept_sha

    @property
    def empty(self):
        return not (self.changed or self.added or self.stale)

    def summary(self):
        return ("%d changed, %d new, %d removed (the installer's), %d of the game's own kept"
                % (len(self.changed), len(self.added), len(self.stale), len(self.kept)))

    def lines(self):
        for tag, paths in (("changed", self.changed), ("new", self.added),
                           ("removed", self.stale), ("kept", self.kept)):
            for p in paths:
                yield "   %-8s %s" % (tag, p)


def plan(inst, tree, is_stale=lambda rel: False):
    """Compare `tree` with the partition. `is_stale(rel)` says whether a file
    only the drive has is the installer's own (removed) rather than the game's
    (kept)."""
    new = staged_files(tree)
    changed, added = [], []
    for rel in sorted(new):
        if rel not in inst.files:
            added.append(rel)
            continue
        if os.path.getsize(new[rel]) != inst.files[rel]["size"]:
            changed.append(rel)
            continue
        with open(new[rel], "rb") as f:
            if inst.read(rel) != f.read():
                changed.append(rel)
    only = sorted(p for p in inst.files if p not in new)
    stale = [p for p in only if is_stale(p)]
    kept = [p for p in only if p not in stale]
    kept_sha = {p: inst.sha(p) for p in kept}
    unreadable = [p for p, s in kept_sha.items() if s is None]
    if unreadable:
        raise SystemExit("cannot read %s on the drive whole, so it could not be "
                         "checked after the update; nothing written" % ", ".join(unreadable))
    want = {"/".join(r.split("/")[:i]) for r in new for i in range(1, r.count("/") + 1)}
    new_dirs = sorted((d for d in want if d not in inst.dirs),
                      key=lambda d: (d.count("/"), d))
    clash = [d for d in new_dirs if d in inst.files]
    if clash:
        raise SystemExit("the stage needs a directory where the drive has a file: %s"
                         % ", ".join(clash))
    return Plan(changed, added, kept, stale, new_dirs, kept_sha)


def _quote(name):
    if any(c.isspace() for c in name):
        raise SystemExit("pfsshell cannot take a name with spaces: %r" % name)
    return name


def script(device, partition, tree, p):
    """The pfsshell commands that carry out plan `p`."""
    out = ["device %s" % device, "mount %s" % partition]

    def cd(d):
        out.append("cd /%s" % _quote(d))

    for rel in p.stale:
        d, _, name = rel.rpartition("/")
        cd(d)
        out.append("rm %s" % _quote(name))
    for d in p.new_dirs:
        parent, _, name = d.rpartition("/")
        cd(parent)
        out.append("mkdir %s" % _quote(name))
    by_dir = {}
    for rel in p.changed + p.added:
        d, _, name = rel.rpartition("/")
        by_dir.setdefault(d, []).append((name, rel in p.changed))
    changed = set(p.changed)
    for d in sorted(by_dir):
        cd(d)
        host = os.path.join(tree, *d.split("/")) if d else tree
        out.append("lcd %s" % _quote(host.replace("\\", "/")))
        for name, _ in sorted(by_dir[d]):
            if ("%s/%s" % (d, name) if d else name) in changed:
                out.append("rm %s" % _quote(name))
            out.append("put %s" % _quote(name))
    return "\n".join(out + ["umount", "exit", ""])


def run(pfsshell, text):
    cmd = [pfsshell] if os.path.isfile(pfsshell) else shlex.split(pfsshell)
    subprocess.run(cmd, input=text, text=True, check=True)


def verify(device, partition, tree, p):
    """[] when the partition holds the stage exactly, the kept files as they
    were and none of the stale ones; otherwise what is wrong."""
    bad = []
    with Installed(device, partition) as inst:
        for rel, host in sorted(staged_files(tree).items()):
            with open(host, "rb") as f:
                if rel not in inst.files or inst.read(rel) != f.read():
                    bad.append("staged file not as staged: " + rel)
        for rel, sha in sorted(p.kept_sha.items()):
            if rel not in inst.files or inst.sha(rel) != sha:
                bad.append("kept file changed: " + rel)
        bad += ["not removed: " + r for r in p.stale if r in inst.files]
    return bad
