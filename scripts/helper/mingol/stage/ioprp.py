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
r"""The IOP reboot image the loader boots the game's IOP with.

The game's boot ELF reboots the IOP with `rom0:UDNL cdrom0:\FMOD\DNAS270.IMG`.
The loader cannot leave that to the game (the reboot is patched out, see
bootpatch), so it reboots the IOP itself with SifIopRebootBuffer before the
handover, and the image has to be the game's own 2.70 kernel: the boot ELF
and its DNAS library check the IOP's loadfile version ("2700") and refuse
or retry on any other.

DNAS270.IMG holds the 2.70 kernel modules but no SYSMEM; on a disc boot the
ROM's UDNL supplies that, and it does the same for SifIopRebootBuffer: the
loader reboots with the image as it is and SYSMEM comes from the console's
rom0. That is the shipped build (ROM_SYSMEM=0) and it boots the game on real
hardware (2026-10-08). The loader source (HippaulInstaller's
playonline/games/mingol/loader-src, the source of polbbnexec-mingol.kelf)
can also splice the console's SYSMEM in itself (ROM_SYSMEM=1: it walks the
BIOS ROMDIR at kseg1 0xBFC00000 and inserts SYSMEM, data and EXTINFO, as the
image's first module, romsysmem.h). That splice is BIOS-dependent: proven
under PCSX2 (SCPH-50000) but it hung on the operator's console on
2026-10-08, so it is built out. Either way the installer fills the slot with
the disc's DNAS270.IMG as it is, and no second disc is needed.

ROMDIR format (ps2sdk romdir.h): 16-byte entries {name[10], u16 extinfo
size, u32 size}, RESET/ROMDIR/EXTINFO first, a zero entry last; then the
concatenated EXTINFO records; then the modules, each padded to 16 bytes
except the last.
"""
import hashlib
import struct

HEAD = ("RESET", "ROMDIR", "EXTINFO")

# The disc's FMOD/DNAS270.IMG the boot was proven with (251,729 bytes).
DNAS270_SHA1 = "962fef33c09e4458a8357634898841a4e0434857"


class RomdirError(ValueError):
    pass


def parse(blob):
    """[{name, ext_sz, size, extinfo, data}] for a ROMDIR image."""
    off, entries = 0, []
    while off + 16 <= len(blob):
        name = blob[off:off + 10].rstrip(b"\0").decode("latin-1")
        ext_sz, size = struct.unpack_from("<HI", blob, off + 10)
        if not name and ext_sz == 0 and size == 0:
            break
        entries.append({"name": name, "ext_sz": ext_sz, "size": size})
        off += 16
    else:
        raise RomdirError("the ROMDIR has no terminating entry")
    if [e["name"] for e in entries[:3]] != list(HEAD):
        raise RomdirError("not a ROMDIR image (first entries %s)"
                          % [e["name"] for e in entries[:3]])
    table = (len(entries) + 1) * 16
    if entries[1]["size"] != table:
        raise RomdirError("ROMDIR says %d bytes, the table is %d" % (entries[1]["size"], table))
    if sum(e["ext_sz"] for e in entries) != entries[2]["size"]:
        raise RomdirError("EXTINFO size does not match its records")
    p = table
    for e in entries:
        e["extinfo"] = blob[p:p + e["ext_sz"]]
        p += e["ext_sz"]
    p = (table + entries[2]["size"] + 15) & ~15
    for e in entries[3:]:
        e["data"] = blob[p:p + e["size"]]
        if len(e["data"]) != e["size"]:
            raise RomdirError("%s runs past the end of the image" % e["name"])
        p = (p + e["size"] + 15) & ~15
    return entries


def serialize(entries):
    """The image bytes, in the retail layout (no padding after the last module)."""
    table = (len(entries) + 1) * 16
    entries[0]["size"] = 0
    entries[1]["size"] = table
    entries[2]["size"] = sum(e["ext_sz"] for e in entries)
    out = bytearray()
    for e in entries:
        out += e["name"].encode("latin-1").ljust(10, b"\0")
        out += struct.pack("<HI", e["ext_sz"], e["size"])
    out += bytes(16)
    for e in entries:
        out += e.get("extinfo", b"")
    out += bytes((-len(out)) & 15)
    body = entries[3:]
    for i, e in enumerate(body):
        out += e["data"]
        if i != len(body) - 1:
            out += bytes((-e["size"]) & 15)
    return bytes(out)


def module(blob, name):
    """(data, extinfo) of one module in a ROMDIR image."""
    for e in parse(blob):
        if e["name"] == name:
            return e["data"], e["extinfo"]
    raise RomdirError("the image has no %s module" % name)


def has_module(blob, name):
    return any(e["name"] == name for e in parse(blob))


def with_sysmem(image, donor):
    """`image` with the donor image's SYSMEM inserted as its first module."""
    entries = parse(image)
    if any(e["name"] == "SYSMEM" for e in entries):
        raise RomdirError("the image already has a SYSMEM module")
    data, extinfo = module(donor, "SYSMEM")
    entries.insert(3, {"name": "SYSMEM", "ext_sz": len(extinfo), "size": len(data),
                       "extinfo": extinfo, "data": data})
    out = serialize(entries)
    if [e["name"] for e in parse(out)][3] != "SYSMEM":
        raise RomdirError("SYSMEM did not land first")
    return out


def check_roundtrip(image):
    """Refuse an image this parser would not write back byte for byte."""
    if serialize(parse(image)) != image:
        raise RomdirError("the image does not round-trip through the ROMDIR parser")


def sha1(data):
    return hashlib.sha1(data).hexdigest()
