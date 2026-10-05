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
"""Reading the disc, the drive identity and the DNAS tables.

The part of HippaulInstaller's playonline/games/common.py this stage uses:
`extract` reads files straight out of a disc image (2048-byte or raw
2352-byte sectors, through playonline.discs.Image), and the DNAS constant
tables are found on the disc by fingerprint instead of being shipped.
"""
import hashlib
import os
import struct

from playonline import discs as discmod

USER_DATA = discmod.USER_DATA


def _walk(image, lba, size, path):
    sectors = (size + USER_DATA - 1) // USER_DATA
    for name, elba, esize, is_dir in discmod._dir_records(image.read_sector(lba, sectors)):
        if name in (".", ".."):
            continue
        full = "%s/%s" % (path, name) if path else name
        yield full, elba, esize, is_dir
        if is_dir:
            for sub in _walk(image, elba, esize, full):
                yield sub


def listing(disc):
    """[(path, lba, size, is_dir)] for the whole disc, paths without a leading slash."""
    image = discmod.Image(disc)
    pvd = image.read_sector(discmod.PVD_SECTOR)
    if pvd[1:6] != b"CD001":
        raise discmod.NotADisc("%s has no ISO9660 volume descriptor" % disc)
    root = pvd[156:190]
    lba = struct.unpack_from("<I", root, 2)[0]
    size = struct.unpack_from("<I", root, 10)[0]
    return list(_walk(image, lba, size, ""))


def extract(disc, out, only=None, skip=()):
    """Copy the disc's files into `out`. Returns the number of files written.

    `only` limits it to paths starting with one of the given prefixes, and
    `skip` leaves out the ones starting with any of those; both compare
    upper-case. A plain directory is accepted as an already extracted disc
    and is returned as is (0 files written).
    """
    if os.path.isdir(disc):
        return 0
    image = discmod.Image(disc)
    n = 0
    want = tuple(p.upper() for p in (only or ()))
    drop = tuple(p.upper() for p in skip)
    with open(disc, "rb") as f:
        for path, lba, size, is_dir in listing(disc):
            up = path.upper()
            if is_dir or (want and not up.startswith(want)) or (drop and up.startswith(drop)):
                continue
            dest = os.path.join(out, *path.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                left, sector = size, lba
                while left > 0:
                    # A raw image holds 2048 user bytes in every 2352-byte
                    # sector, so read sector by sector unless it is plain.
                    if image.sector_size == USER_DATA:
                        f.seek(sector * USER_DATA)
                        chunk = f.read(min(left, 1 << 20))
                        sector += (len(chunk) + USER_DATA - 1) // USER_DATA
                    else:
                        chunk = image.read_sector(sector, min(512, (left + USER_DATA - 1) // USER_DATA))
                        sector += len(chunk) // USER_DATA
                        chunk = chunk[:left]
                    if not chunk:
                        raise IOError("%s ends inside %s" % (disc, path))
                    fh.write(chunk)
                    left -= len(chunk)
            n += 1
    return n


def read_hddid(path):
    with open(path, "rb") as f:
        blk = f.read()
    if len(blk) != 512 or not blk.startswith(b"Sony Computer Entertainment Inc."):
        raise SystemExit("%s is not a 512-byte SCE drive identity" % path)
    return blk


# ---- DNAS constants ------------------------------------------------------
# The container crypto needs four fixed tables from Sony's DNAS library: the
# 100-entry RSA keystore and three DES constant windows. The disc's
# ZZBIN/DNAS.BIN links that library, so the tables are found there by
# fingerprint instead of being shipped. Each piece is (name, length, sha1 of
# its first 8 bytes, sha1 of the whole piece); the layout of the assembled
# blob is the pieces in this order.
DNAS_PIECES = (
    ("KEYSTORE", 20000, "8e14985475f3b6fcc6971b73ba463de743711528",
     "edc9c9eef6741017521be5cba2f3cb8780cf1651"),
    ("STAT_2ACDD8", 32, "e8632e06da3340f1e10262e1fb3e8a1b474ab7ea",
     "cae7b6d19261df2674b50433013c6aad9ddd67e5"),
    ("STAT_2ACDF8", 8, "053c0f4df0879af5e175f5a92d7a27a971b163ca",
     "053c0f4df0879af5e175f5a92d7a27a971b163ca"),
    ("STAT_2ACE20", 32, "214c6ae0199857d2af13076a51b24b47996ae22a",
     "94173e1cea31e27263e16ea2b20fc3f6f2473963"),
)
DNAS_CONSTS_ENV = "MINGOL_DNAS_CONSTS"


def _find_piece(blob, length, head, whole, align=4):
    view = memoryview(blob)
    for off in range(0, len(blob) - length + 1, align):
        if hashlib.sha1(view[off:off + 8]).hexdigest() != head:
            continue
        if hashlib.sha1(view[off:off + length]).hexdigest() == whole:
            return off
    return None


def dnas_consts(blobs):
    """The DNAS constant tables, found in `blobs` (plaintext programs off the disc)."""
    out = []
    for name, length, head, whole in DNAS_PIECES:
        for blob in blobs:
            off = _find_piece(blob, length, head, whole)
            if off is not None:
                out.append(bytes(blob[off:off + length]))
                break
        else:
            raise SystemExit("the DNAS table %s was not found on this disc; is "
                             "it the right disc, and a good dump?" % name)
    return b"".join(out)


def provide_dnas_consts(blobs, work):
    """Find the tables, write them into `work` and point the container code at them.

    `dnasconsts` reads the file named by MINGOL_DNAS_CONSTS when it is first
    imported, so this must run before that.
    """
    path = os.path.join(work, "dnas-consts.bin")
    if not os.path.isfile(path):
        data = dnas_consts(blobs)
        with open(path, "wb") as f:
            f.write(data)
    os.environ[DNAS_CONSTS_ENV] = path
    return path


def load_dnas_consts():
    """What `dnasconsts` calls: the tables provide_dnas_consts wrote."""
    path = os.environ.get(DNAS_CONSTS_ENV)
    if not path or not os.path.isfile(path):
        raise RuntimeError("the DNAS tables have not been read off the disc yet "
                           "(common.provide_dnas_consts)")
    with open(path, "rb") as f:
        blob = f.read()
    pieces, at = {}, 0
    for name, length, _head, _whole in DNAS_PIECES:
        pieces[name] = blob[at:at + length]
        at += length
    if at != len(blob):
        raise RuntimeError("%s is %d bytes, expected %d" % (path, len(blob), at))
    return pieces
