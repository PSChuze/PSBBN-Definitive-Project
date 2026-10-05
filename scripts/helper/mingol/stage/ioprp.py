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
ROM's UDNL supplies that. A buffer reboot needs the image to carry one. The
proven image (work/IOPRP-dnas270-sysmem.IMG, sha1 356c7c48) is DNAS270.IMG
with SYSMEM, data and EXTINFO, inserted as the first module; that SYSMEM
came from the IOP reboot image inside Nobunaga's AUTH/BIN/SLPM_651.97
(section 1). Minna's own disc carries no SYSMEM anywhere, so:

  with the Nobunaga disc (--aux-disc), its SYSMEM is inserted and the image
  is the proven one, byte for byte;

  without it, DNAS270.IMG is used as it is. That relies on the reboot taking
  SYSMEM from the ROM, which has not been tried; the stage step says so in
  the manifest's notes.

ROMDIR format (ps2sdk romdir.h): 16-byte entries {name[10], u16 extinfo
size, u32 size}, RESET/ROMDIR/EXTINFO first, a zero entry last; then the
concatenated EXTINFO records; then the modules, each padded to 16 bytes
except the last.
"""
import hashlib
import struct

HEAD = ("RESET", "ROMDIR", "EXTINFO")

# The proven reboot image (DNAS270.IMG + Nobunaga's SYSMEM), for the check.
PROVEN_SHA1 = "356c7c48dfb29452dca8dd1bf634eac9fb28aa81"


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
