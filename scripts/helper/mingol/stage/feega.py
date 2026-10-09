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
r"""The Feega account client (FEEGAGUI.ELF) with no disc.

"Join feega" and the other account screens are not in the game. The game's
SYSTEM.BIN runs a separate program off the disc:

    LoadExecPS2("cdrom0:\FEEGAGUI.ELF;1", 9,
                {"BBN", "0", "CD"|"DVD", "SCPS15049100", "eg8agt3", "1.0.0",
                 "0"|"1", <the game's argv[0]>, "Register"})

FEEGAGUI.ELF reboots the IOP with cdrom0:\FMOD\IOPRP270.IMG, loads about
twenty IOP modules from cdrom0:\FMOD\ and cdrom0:\FMOD2\, reads its screens,
sounds, the JIS/UCS tables and the connect video from cdrom0:\FRES\, and goes
back with LoadExecPS2(<the game's argv[0]>, 2, {result, "Register"}), after
powering the network adapter (and with it the hard disk) off. The game reads
argv[2] == "Register" at entry and picks up from the result. The BIOS's
LoadExecPS2 resets the IOP to the ROM's own modules before it loads the
file, so with no disc both directions end in the browser.

What the install does about it:

  pfs2:/RELAUNCH.ELF   the filled loader as a plain ELF (relaunch(): the
                       signed loader keeps only its first 32 bytes
                       encrypted, and carries a copy of them in its
                       plain_head slot). Before the loader
                       starts the game or the client it puts a small program
                       of its own at 0x00090000 (loader-src/relaunch.c) and
                       points the LoadExecPS2 system call of that ELF at it.
                       For a cdrom0: name that program keeps the IOP as it is
                       (the shim, the drivers, the partition on pfs2:), loads
                       this file and starts it with argv[0] = the name.
                       Called as FEEGAGUI.ELF the loader boots the IOP
                       exactly as for the game (the 2.70 kernel image, the
                       shim, the disc's drivers; IOPRP270.IMG and DNAS270.IMG
                       differ only in their CDVDMAN/CDVDFSV), tells the shim
                       this IOP is FEEGAGUI's, reads pfs2:/FEEGAGUI.ELF into
                       place and starts it with the game's arguments; called
                       as SCPS_150.49 it boots the game with the arguments it
                       was given.
  pfs2:/FEEGAGUI.ELF   the disc's client with five code changes and five
                       strings (PATCHES): no IOP reboot of its own (the
                       loader did it); none of its own DEV9/ATAD/HDD/PFS (the
                       loader's are up: a second hdd driver hangs the IOP,
                       and a second DEV9 ends NO_RESIDENT, which the client
                       takes as a failure and then skips SMAP, the network);
                       no power-off of the network adapter on
                       the way out (the way back is on the hard disk); and
                       its look in cdrom0:\FRES for the alternative screens
                       turned into one of pfs2:/FRES (the names as pfs gives
                       them, without ";1"). On that IOP its cdrom0:\FMOD\
                       module loads go to pfs2:/FMOD/ (the shim, as for the
                       game) and its cdrom0:\FRES\ reads to pfs2:/FRES/.
                       Proven under PCSX2 on 2026-10-09: the feega-ID menu
                       and "Join feega" up to the server's Notice, and the
                       way back to the game's feega-ID screen.
  pfs2:/FRES/          the disc's FRES/ but ROOT_ED.PEM (the Feega CA stays
                       at the partition root, where servers.py puts it).

English: a translation pack may carry the client's English as an "elf_text"
section in its manifest (the format of the overlay text, see english.py):

    "elf_text": {"FEEGAGUI.ELF": {"file": "text/feegagui.tsv",
                                  "kind": "elf", "original_sha1": "..."}}

An installer that predates this section ignores it. With no such section,
or one that does not fit the disc, the client stays Japanese.
"""
import hashlib
import json
import os
import struct

NAME = "FEEGAGUI.ELF"
RELAUNCH = "RELAUNCH.ELF"
FRES = "FRES"
FRES_SKIP = ("ROOT_ED.PEM",)

# The SCPS-15049 disc's FEEGAGUI.ELF (7,596,996 bytes).
STOCK_SHA1 = "3319836f58b0f246f21fe29f841b0c29bc4ba4a8"

# Both of its loadable segments sit 0xff000 below their file offsets.
VA_DELTA = 0xff000


def _w(word):
    return struct.pack("<I", word)


def _s(text, size):
    return text.ljust(size, b"\0")


# (address, original bytes, new bytes, why)
PATCHES = (
    (0x1051a0, _w(0x0c0766ac), _w(0x24020001),
     "sceSifRebootIop(cdrom0:\\FMOD\\IOPRP270.IMG;1) -> v0 = 1: the loader booted the IOP"),
    (0x1051b0, _w(0x0c07669e), _w(0x24020001),
     "sceSifSyncIop() -> v0 = 1"),
    (0x1057c4, _w(0x0c076020), _w(0x24020000),
     "devctl(dev9x:, DDIOC_OFF) -> v0 = 0: keep the drive up for the way back"),
    (0x102e20, _w(0x0c040a80), _w(0x24020001),
     "no DEV9 load of its own -> v0 = 1: the loader's is up (a second one only "
     "re-probes the chip and ends NO_RESIDENT, which the client takes as a "
     "failure and then skips SMAP, the network)"),
    (0x102e30, _w(0x12600011), _w(0x10000011),
     "skip its own ATAD/HDD/PFS: the loader's are up, and a second hdd driver "
     "hangs the IOP"),
    (0x81b348, _s(b"cdrom0:\\FRES", 16), _s(b"pfs2:/FRES", 16),
     "the alternative-screen check lists pfs2:/FRES"),
    (0x81b370, _s(b"BG_SV.RGB;1", 16), _s(b"BG_SV.RGB", 16), "pfs names carry no ;1"),
    (0x81b380, _s(b"CNCT_SV.M2V;1", 16), _s(b"CNCT_SV.M2V", 16), "pfs names carry no ;1"),
    (0x81b390, _s(b"BGM_SV.SQ;1", 16), _s(b"BGM_SV.SQ", 16), "pfs names carry no ;1"),
    (0x81b3a0, _s(b"EFF_SV.HD;1", 16), _s(b"EFF_SV.HD", 16), "pfs names carry no ;1"),
)


class FeegaError(ValueError):
    pass


def patch(elf):
    """The disc's FEEGAGUI.ELF (or an English one made from it) with PATCHES
    in. Every original byte is checked first; nothing changes size."""
    d = bytearray(elf)
    if d[:4] != b"\x7fELF":
        raise FeegaError("FEEGAGUI.ELF is not an ELF")
    for va, orig, new, _why in PATCHES:
        off = va - VA_DELTA
        if d[off:off + len(orig)] != orig:
            raise FeegaError("FEEGAGUI.ELF at %#x is not what the patch was made for "
                             "(another pressing?)" % va)
        d[off:off + len(new)] = new
    return bytes(d)


def english_elf(stock, pack_path, note=print):
    """The client in English from the pack's "elf_text" section, or None."""
    if not pack_path:
        return None
    from . import english as englishmod
    try:
        read, z = englishmod._reader(pack_path)
    except (Exception, englishmod.Refused) as e:   # not a pack we can open
        note("--translate: the Feega client stays Japanese (%s)" % e)
        return None
    try:
        try:
            man = json.loads(read(englishmod.MANIFEST).decode("utf-8"))
        except (Exception, englishmod.Refused):
            return None
        ent = (man.get("elf_text") or {}).get(NAME) if isinstance(man, dict) else None
        if not isinstance(ent, dict):
            note("--translate: the pack has no English for the Feega client; "
                 "it stays Japanese")
            return None
        if ent.get("original_sha1") != hashlib.sha1(stock).hexdigest():
            note("--translate: the pack's Feega client English is for another "
                 "FEEGAGUI.ELF; it stays Japanese")
            return None
        name = ent.get("file")
        want = (man.get("files") or {}).get(name)
        data = read(name)
        if not isinstance(want, dict) or len(data) != want.get("size") or \
                hashlib.sha256(data).hexdigest() != str(want.get("sha256", "")).lower():
            note("--translate: the pack's %s does not match its manifest; "
                 "the Feega client stays Japanese" % name)
            return None
        table = englishmod.rows(data.decode("utf-8"))
        out, n = englishmod.overlay_build(stock, table, NAME)
        note("--translate: the Feega client in English (%d strings)" % n)
        return out
    except (Exception, englishmod.Refused) as e:
        note("--translate: the Feega client stays Japanese (%s)" % e)
        return None
    finally:
        if z is not None:
            z.close()


def stage(root, tree, note=print, pack_path=None):
    """FEEGAGUI.ELF (patched; English when the pack has it) and FRES/ into
    the partition tree. Returns the number of files written."""
    src = os.path.join(root, NAME)
    if not os.path.isfile(src):
        raise SystemExit("the disc is missing %s; is it a complete dump?" % NAME)
    with open(src, "rb") as f:
        stock = f.read()
    if hashlib.sha1(stock).hexdigest() != STOCK_SHA1:
        note("this pressing's FEEGAGUI.ELF (sha1 %s) is not the one the Feega "
             "client was made disc-less with" % hashlib.sha1(stock).hexdigest())
    elf = english_elf(stock, pack_path, note) or stock
    try:
        elf = patch(elf)
    except FeegaError as e:
        raise SystemExit("the Feega client cannot run without the disc: %s" % e)
    with open(os.path.join(tree, NAME), "wb") as f:
        f.write(elf)
    n = 1
    fres = os.path.join(root, FRES)
    names = sorted(os.listdir(fres)) if os.path.isdir(fres) else []
    if not any(x.upper() == "JIS2UCS.BIN" for x in names):
        raise SystemExit("the disc is missing FRES/JIS2UCS.BIN; is it a complete dump?")
    os.makedirs(os.path.join(tree, FRES), exist_ok=True)
    for x in names:
        if x.upper() in FRES_SKIP or not os.path.isfile(os.path.join(fres, x)):
            continue
        with open(os.path.join(fres, x), "rb") as f:
            data = f.read()
        with open(os.path.join(tree, FRES, x.upper()), "wb") as f:
            f.write(data)
        n += 1
    return n


# ---- the plain loader ------------------------------------------------------

PLAIN_HEAD_MAGIC = b"POLPLAINHEAD1" + bytes(3)


def relaunch(kelf):
    """The filled loader KELF as the plain ELF it carries: the KELF's
    content (from its header size on) with the first 32 bytes, which the KELF
    keeps encrypted, put back from the loader's plain_head slot."""
    if kelf[:4] == b"\x7fELF":
        return kelf
    content = kelf[struct.unpack_from("<H", kelf, 20)[0]:]
    at = content.find(PLAIN_HEAD_MAGIC)
    if at < 32 or content.find(PLAIN_HEAD_MAGIC, at + 1) >= 0:
        raise SystemExit("the Minna no Golf Online loader has no plain_head slot; "
                         "it predates the Feega client (rebuild and re-sign it)")
    head = content[at + 16:at + 48]
    if head[:4] != b"\x7fELF" or struct.unpack_from("<I", head, 28)[0] != 52:
        raise SystemExit("the loader's plain_head slot was never stamped")
    elf = head + content[32:]
    if elf[at + 16:at + 48] != head:
        raise AssertionError("plain_head moved")
    return elf
