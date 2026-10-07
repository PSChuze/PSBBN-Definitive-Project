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
r"""The code patches of the PCSX2-proven disc-less boot, applied to the disc's bytes.

Nothing patched ships: each edit names the bytes it expects to find, and the
whole set is refused unless every one of them is there (and, for a known
pressing, the result's SHA-1 is the proven one).

The boot ELF, SCPS_150.49 (file offsets; VA = offset + 0x000ffd80):

  0x1009e8  skip the game's own IOP reboot (rom0:UDNL cdrom0:\FMOD\DNAS270.IMG)
            surgically: `b 0x100a24` keeps the SIF/fileio re-init after it.
            The loader has already rebooted the IOP with the same kernel and
            left the drivers resident.
  0x10024c  nop the call to the driver-load routine 0x100bb0, which would load
            DEV9/ATAD/HDD/PFS from cdrom0:\FMOD; the loader's resident copies
            of the same four modules serve instead.
  0x100578, 0x10058c, 0x100590, 0x10060c
            the plaintext overlay branch builds cdrom0:\ZZBIN\<NAME>;1. In an
            installed boot DNAS.BIN is the only overlay that takes it (every
            other one is read sealed from pfs2:/ZZENC), so the branch is turned
            into pfs2:/DNAS.BIN: device string 0x150da8 -> 0x150db8 ("pfs2:/"),
            the "ZZBIN\\" strcat and its argument nopped, and ";1" -> "".
  0x1095b8  the DNAS module-version gate in the file-open wrapper 0x109680
            returns 0 (pass) at once. It wants the resident IOP to report
            "2700"; with the gate skipped the boot does not depend on which
            kernel image the loader rebooted with.
  0x12e368, 0x12eca8, 0x12dc40 (+ stubs at 0x100bb0)
            the disc read of the online DNAS step, answered without a disc.
            Before it calls sceDNAS2Init, SYSTEM.BIN's DNAS state machine
            (0x1915d0) reads 0x20 sectors of the disc (state 0) and then
            waits for sceCdSync, sceCdGetError == 0 and sceCdDiskReady == 2.
            With no disc sceCdRead never starts and the game sits at
            "DNAS install authentication" for good. The sector data only
            feeds sceDNAS2Init, which DNAS.BIN below already answers without
            reading it. SYSTEM.BIN is sealed, so the answer is given in the
            boot ELF's libcdvd instead, and only to those three call sites:
            sceCdRead, sceCdGetError and sceCdDiskReady each jump to a stub
            that returns 1, 0 and 2 when the return address is the state
            machine's (0x1916c0, 0x1916f8, 0x191824) and otherwise runs the
            function as before. The stubs sit in the driver-load routine
            0x100bb0, dead since its one call (0x10024c) is gone.

DNAS.BIN (the plaintext DNAS 2.70 overlay, staged at the partition root as
pfs2:/DNAS.BIN for the redirect above). Its online gate needs Sony's DNAS
servers, which are gone, so the three calls SYSTEM.BIN's state machine
(0x1915d0) polls report success. DNAS.BIN is not a signed container, so this
is safe to edit; SYSTEM.BIN and every other sealed overlay stay stock.

  0x1e60    sceDNAS2Init     -> jr ra; li v0,0
  0x1ea0    AuthInstall      -> jr ra; li v0,0
  0x2a00    GetStatus        -> *a0 = 5 (pass); jr ra; li v0,0

  0x7cab8   console binding check (thunk 0x620eb8) -> jr ra; li v0,1

The last one is the DNAS -102 fix. sceDNAS2InstExtractDataLength first
checks that the console ID (sceCdRI) matches what the install was bound to,
and fails with -102 when it does not: always under PCSX2, which reports a
zero ID, and on a console whose ID is not the one the record names (where
the read is also what hung the console). The check runs before any key is
derived and the decrypt reads the drive ID on its own path, so skipping it
loses nothing the decrypt needs. The rest of the decrypt side
(sceDNAS2InstExtractDataLength onward) is untouched: it is what reads the
sealed overlays.
"""
import hashlib

# (file offset, original bytes, patched bytes), little-endian words as on disc.
BOOT_ELF_PATCHES = (
    (0x0004cc, "ec02040c", "00000000"),                    # 0x10024c
    (0x0007f8, "a80da524", "b80da524"),                    # 0x100578
    (0x00080c, "62ed040cd80da524", "0000000000000000"),    # 0x10058c, 0x100590
    (0x00088c, "e00da524", "e20da524"),                    # 0x10060c
    (0x000c68, "1500043c2236040c", "0e00001000000000"),    # 0x1009e8
    (0x009838, "b0ffbd271500023c", "0800e00300000224"),    # 0x1095b8
    # 0x100bb0 stubs: lui t0,<ra hi>; ori t0,<ra lo>; bne ra,t0,+3; li v0,<r>;
    # jr ra; <undo>; j <fn+8>; <displaced 1st/2nd insn>
    (0x000e30,
     "f0ffbd271500043c0000bfffe80e8424"
     "2d2800002d300000a402040cffff0724"
     "1500043c2d280000f80e84242d300000"
     "a402040c100007241500043c1500063c"
     "080f84240b000524c00ec624a402040c"
     "100007241500043c1500063c180f8424",
     "1900083cc01608350300e81701000224"
     "0800e00300000000dcb8040880ffbd27"
     "1900083cf81608350300e81700000224"
     "0800e003000000002cbb0408d0ffbd27"
     "1900083c241808350300e81702000224"
     "0800e003a000bd2712b704087000b6ff"),
    (0x02e5e8, "80ffbd27", "ec020408"),                    # 0x12e368 sceCdRead
    (0x02ef28, "d0ffbd27", "f4020408"),                    # 0x12eca8 sceCdGetError
    (0x02dec0, "60ffbd277000b6ff", "fc02040860ffbd27"),    # 0x12dc40 sceCdDiskReady
)
DNAS_PATCHES = (
    (0x001e60, "f0ffbd272d582001", "0800e00300000224"),
    (0x001ea0, "d0ffbd276300023c", "0800e00300000224"),
    (0x002a00, "6300023c2d3080002c9f438cf8ff0224",
               "05000224000082ac0800e00300000224"),
    (0x07cab8, "f0ffbd270000bfff", "0800e00301000224"),
)

# The disc's files and the proven results, for the one known pressing
# (SCPS-15049, VER 1.01, build 030518).
BOOT_ELF_STOCK = "189fa1f13969b66b755f711fdb9401701b92c54e"
BOOT_ELF_PROVEN = "1d2f290852d47c7d930cfc143c1dc5bbbed71b97"
DNAS_STOCK = "9d7c542c939129283d5c88246741ffa85dddf409"
DNAS_PROVEN = "2e67f5d53840686b6619432d7ffefb42f2eeec25"


class PatchError(ValueError):
    pass


def _apply(name, data, patches, stock, proven):
    out = bytearray(data)
    for off, old, new in patches:
        old, new = bytes.fromhex(old), bytes.fromhex(new)
        have = bytes(out[off:off + len(old)])
        if have != old:
            raise PatchError("%s: expected %s at 0x%x, found %s; not the disc this "
                             "patch was made for" % (name, old.hex(), off, have.hex()))
        out[off:off + len(new)] = new
    out = bytes(out)
    if hashlib.sha1(data).hexdigest() == stock and hashlib.sha1(out).hexdigest() != proven:
        raise PatchError("%s: the patched file is not the proven one" % name)
    return out


# The overlay loader (0x1004e0) has two paths, chosen by a flag byte at
# 0x168ac8. Set, as on the hard drive install: pfs2:/zzenc/zzbin/<name>,
# decrypted by the DNAS library. Clear: the old disc path, which the patches
# above already send to pfs2:/<NAME> and which loads the file as it is, with
# no DNAS step (DNAS.BIN itself loads that way). The English install takes
# the second path for every overlay, because the DNAS library refuses an
# overlay whose text was changed (-10202) however it is sealed: 0x10052c
# beqz v0 -> b, and the overlays are staged as plain files at the root of
# the partition. The Japanese install keeps the first path.
PLAIN_OVERLAYS_PATCH = (0x0007ac, "11004010", "11000010")      # 0x10052c


def boot_elf(data, plain_overlays=False):
    """SCPS_150.49 with the disc-less boot patches, and with `plain_overlays`
    the overlay loader sent down its plain-file path for every overlay."""
    if not data.startswith(b"\x7fELF"):
        raise PatchError("SCPS_150.49 is not an ELF")
    out = _apply("SCPS_150.49", data, BOOT_ELF_PATCHES, BOOT_ELF_STOCK, BOOT_ELF_PROVEN)
    if plain_overlays:
        out = _apply("SCPS_150.49", out, (PLAIN_OVERLAYS_PATCH,), None, None)
    return out


def dnas_overlay(data):
    """ZZBIN/DNAS.BIN with the online-gate skip."""
    return _apply("DNAS.BIN", data, DNAS_PATCHES, DNAS_STOCK, DNAS_PROVEN)


def is_known_pressing(boot, dnas):
    return (hashlib.sha1(boot).hexdigest() == BOOT_ELF_STOCK
            and hashlib.sha1(dnas).hexdigest() == DNAS_STOCK)
