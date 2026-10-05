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
"""Fill the Minna no Golf Online loader (scripts/assets/mingol/polbbnexec-mingol.kelf).

The loader is our polbbnexec built with DRIVERS=3 (HippaulInstaller's
playonline/games/mingol/loader-src/build.sh, its assets/games/mingol-loader.elf)
and signed as a KELF with playonline.lib.polkelf --encrypt, so a real console
runs it. Only the first 32 content bytes of that KELF are signed; everything
filled here lies in the unsigned block after them, so filling needs no keys.
It ships empty. Two structs in its data segment take what comes off the
player's disc:

  the install header (POLBBNFORKHDR1), filled by playonline.loader.fill:
    boot ELF   SCPS_150.49 with the disc-less patches (bootpatch)
    IOPRP      the 2.70 kernel image (ioprp)
    HDD ID     the drive's identity, which the shim serves
    argv[0]    cdrom0:\\SCPS_150.49;1, what the game expects to be called

  the driver slots (POLDRIVERSLOTS1), filled here: the disc's FMOD/DEV9.IRX,
  ATAD.IRX, HDD.IRX and PFS.IRX, which the loader leaves resident after the
  IOP reboot. Layout (polbbnexec.c drv_slots_t): magic[16], u32 version,
  u32 count, then per slot {u32 offset from the magic, u32 capacity, u32 len,
  u32 reserved}.

The PCSX2-proven loader (E:/ps2hdd/mingol/mingol-direct.elf) linked the same
four files in; filling the slots gives the IOP the same bytes.
"""
import struct

from playonline import loader as polloader

DRV_MAGIC = b"POLDRIVERSLOTS1\0"
DRV_VERSION = 1
DRIVERS = ("DEV9", "ATAD", "HDD", "PFS")      # slot order, FMOD/<name>.IRX
ARGV0 = "cdrom0:\\SCPS_150.49;1"


class LoaderError(ValueError):
    pass


def driver_slots(blob):
    """(offset of the magic, [(offset, capacity, len)]) for the driver slots."""
    at = blob.find(DRV_MAGIC)
    if at < 0 or blob.find(DRV_MAGIC, at + 1) >= 0:
        raise LoaderError("the loader has %s driver-slot header"
                          % ("no" if at < 0 else "more than one"))
    version, count = struct.unpack_from("<II", blob, at + 16)
    if version != DRV_VERSION or count != len(DRIVERS):
        raise LoaderError("driver slots version %d count %d; this code knows %d/%d"
                          % (version, count, DRV_VERSION, len(DRIVERS)))
    if not blob.startswith(b"\x7fELF"):
        # A KELF: the content starts at HeaderSize (u16 at +20) and only its
        # first 32 bytes are signed; nothing filled may lie inside them.
        first_unsigned = struct.unpack_from("<H", blob, 20)[0] + 32
        if at < first_unsigned:
            raise LoaderError("the driver slots are inside the signed region of the KELF")
    slots = []
    for i in range(count):
        off, cap, ln, _r = struct.unpack_from("<4I", blob, at + 24 + 16 * i)
        if at + off + cap > len(blob):
            raise LoaderError("driver slot %d runs past the end of the file" % i)
        slots.append((off, cap, ln))
    return at, slots


def is_empty(blob):
    info = polloader.read(blob)
    _at, slots = driver_slots(blob)
    return not (info["elf_len"] or info["ioprp_len"] or info["has_hddid"]
                or any(ln for _o, _c, ln in slots))


def fill(blob, boot_elf, ioprp, hddid, drivers):
    """The loader filled for one disc and drive. `drivers` maps DEV9..PFS to bytes."""
    out = bytearray(polloader.fill(blob, boot_elf=boot_elf, ioprp=ioprp,
                                   hddid=hddid, argv0=ARGV0))
    at, slots = driver_slots(bytes(out))
    for i, name in enumerate(DRIVERS):
        data = drivers[name]
        off, cap, _ln = slots[i]
        if not data.startswith(b"\x7fELF"):
            raise LoaderError("FMOD/%s.IRX is not an IRX" % name)
        if len(data) > cap:
            raise LoaderError("FMOD/%s.IRX is %d bytes and its slot holds %d"
                              % (name, len(data), cap))
        out[at + off:at + off + len(data)] = data
        struct.pack_into("<I", out, at + 24 + 16 * i + 8, len(data))
    if len(out) != len(blob):
        raise AssertionError("filling changed the file length")
    return bytes(out)


def read_driver(blob, name):
    """What a filled loader holds in one driver slot."""
    at, slots = driver_slots(blob)
    off, _cap, ln = slots[DRIVERS.index(name)]
    return blob[at + off:at + off + ln]
