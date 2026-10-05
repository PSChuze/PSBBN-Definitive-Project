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
"""Stage Minna no Golf Online (SCPS-15049) off the player's disc.

    python -m mingol.stage --disc IMAGE_OR_TREE --hddid FILE --out DIR
        --kelf scripts/assets/mingol/polbbnexec-mingol.kelf
        (--four HEX8 | --device DEV) [--aux-disc NOBUNAGA_DISC]
        [--aux-search DIR ...] [--require-aux]
        [--translate [--translation-dir DIR] | --translation-pack ZIP]

--translate downloads the latest English translation pack from openlobby.fyi
(english.py, download.py; MINGOL_TRANSLATION_URL=none turns that off), falling
back on the newest pack in --translation-dir, and checks it against the
disc's overlays MENU, NHTTP, GAME and HTTP; --translation-pack uses a local
pack instead. The English overlays would be sealed in place of the disc's,
but the game refuses a changed overlay, so ENGLISH_SEALS is off and the game
stays Japanese, browser title included, with a note saying why.

Ported from HippaulInstaller (playonline/games/mingol), which builds the same
partition for a PCSX2 image. Nothing comes from a kit: everything is made
from the player's disc.

  tree/      what the retail installer leaves in PP.SCPS-15049..APPLICATION:
             the disc's files minus FMOD/, FMOD2/ (but see below), FRES/, ZZBIN/, FEEGAGUI.ELF
             and SCPS_150.49; the nine ZZENC/ZZBIN/*.BIN containers sealed to
             the drive's HDD ID and the four of its __net record
             (disc_to_drive), each checked to decrypt to its plaintext twin in
             ZZBIN/; the install marker INSTALL.VER; DNAS.BIN at the root, the
             disc's plaintext DNAS overlay with its online gate skipped
             (bootpatch), which the patched boot ELF loads as pfs2:/DNAS.BIN;
             FMOD/ and FMOD2/ holding the disc's IOP modules (*.IRX, *.ICO,
             *.SYS; the loader's shim sends the game's cdrom0 FMOD loads
             there, so it needs no disc); and dnasload.elf, the loader the
             browser launches.
  dnasload.elf
             the signed loader KELF the toolkit ships (DRIVERS=3, driver
             slots) filled for this disc and drive: the patched SCPS_150.49,
             the 2.70 IOP kernel (ioprp), the disc's DEV9/ATAD/HDD/PFS IRXs
             (ATAD with its genuine-drive check skipped, atadgp)
             and the drive's HDD ID; argv[0] cdrom0:\\SCPS_150.49;1. Also
             copied into tree/.
  attr.bin   the browser's attribute area: BOOT2 = pfs:/dnasload.elf and the
             disc's own icon.
  game.json  the partition, its size, the APA passwords and notes.

The four. A PSBBN drive that has had the PlayOnline step carries one shared
__net record at +0x201800, keyed to the drive's HDD ID. That record is never
written here: `--device` decodes it and the containers are sealed with its
four (`--four` passes one explicitly, for an offline stage).

The one module the disc lacks (SYSMEM, for the IOP kernel image) comes from
the Nobunaga no Yabou Online Hiryuu no Shou disc (SLPM-65783), found with
--aux-disc, in the --aux-search folders, or beside the Minna disc.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import tempfile

from playonline import attrarea, discs as discmod
from playonline.lib import polhdd

from . import common

KEY = "mingol"
PRODUCT = "SCPS-15049"
PARTITION = "PP.SCPS-15049..APPLICATION"
PART_MIB = 1536                       # the retail layout: a 1 GiB main + one 512 MiB sub
BOOT_FILE = "SCPS_150.49"
PASSWORD = b"MM21"
LOADER_NAME = "dnasload.elf"
TITLE0_EN = u"Everybody's Golf Online"

# The nine overlays the game reads sealed (pfs2:/ZZENC/ZZBIN/<name>).
CONTAINERS = ("EDAUTH.BIN", "GAME.BIN", "HTTP.BIN", "INSTALL.BIN", "MENU.BIN",
              "MOVIE.BIN", "NHTTP.BIN", "PATCH.BIN", "SYSTEM.BIN")
# Whether the English overlays are sealed in place of the disc's. Off: the game
# rejects them. Sealed from the English plaintext (disc_to_drive.
# build_drive_form_patched) each decrypts back to that plaintext on the PC, but
# under PCSX2 (2026-10-05) sceDNAS2InstExtractData refuses the English
# MENU.BIN with -10202 and the game stops; the stock overlays load. The DNAS
# library checks the module by a value we have not found (not r20/r28, H1 or
# the inner layer), so a changed overlay cannot be sealed yet. Until then
# --translate checks the pack against the disc and the game stays Japanese.
ENGLISH_SEALS = False


# The disc's files the retail installer does not copy (FMOD/ is the disc
# boot's IOP set, FMOD2/ a second sound set, FRES/ and FEEGAGUI.ELF the
# e-money client, ZZBIN/ the plaintext overlays, ZZENC/ sealed here), and the
# ones this step reads.
TREE_SKIP = ("FMOD/", "FMOD2/", "FRES/", "ZZBIN/", "ZZENC/", "FEEGAGUI.ELF", BOOT_FILE)
WORK_FILES = ("SYSTEM.CNF", BOOT_FILE, "ZZBIN/", "ZZENC/ZZBIN/", "FMOD/", "FMOD2/",
              "CNF/SYS_NET.ICO")

# The IOP modules the game loads from cdrom0:\FMOD\ and cdrom0:\FMOD2\ once
# it runs (network, pad, USB, sound). With no disc the loader's shim sends
# those loads to pfs2:/FMOD/ and pfs2:/FMOD2/, so they are copied there:
# (folder, file extensions). FMOD/'s two kernel images stay behind.
FMOD_DIRS = (("FMOD", (".IRX", ".ICO", ".SYS")), ("FMOD2", (".IRX",)))

# The browser boot block: launch the loader from the partition (the disc's
# SYSTEM.CNF says cdrom0:\SCPS_150.49;1, which makes the browser ask for the
# disc).
BOOT_BLOCK = (b"BOOT2 = pfs:/dnasload.elf\r\n"
              b"DNASBOOT2 = pfs:/SCPS_150.49\r\n"
              b"VER = 1.01\r\n"
              b"VMODE = NTSC\r\n"
              b"HDDUNITPOWER= NICHDD\r\n")

# icon.sys in the spelling, and with the values, of a retail install.
TITLE0 = u"\u307f\u3093\u306a\u306e\uff27\uff2f\uff2c\uff26 \u30aa\u30f3\u30e9\u30a4\u30f3"
TITLE1 = u"\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u30c7\u30fc\u30bf"
UNINSTALL = (u"\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u3057\u305f\u30b2\u30fc\u30e0"
             u"\u3092\u6d88\u53bb\u3057\u307e\u3059\u3002",
             u"\u30bb\u30fc\u30d6\u30c7\u30fc\u30bf\u306f\u524a\u9664\u3055\u308c"
             u"\u307e\u305b\u3093\u3002",
             u"")
ICON_LOOK = (u"bgcola = 64\r\n"
             u"bgcol0 = 20, 70, 90\r\n"
             u"bgcol1 = 20, 20, 60\r\n"
             u"bgcol2 = 20, 20, 60\r\n"
             u"bgcol3 = 20, 70, 90\r\n"
             u"lightdir0 =  0.5,  0.5,  0.5\r\n"
             u"lightdir1 =  0.0, -0.4, -1.0\r\n"
             u"lightdir2 = -0.5, -0.5,  0.5\r\n"
             u"lightcolamb = 31, 31, 31\r\n"
             u"lightcol0   = 62, 62, 55\r\n"
             u"lightcol1   = 33, 42, 64\r\n"
             u"lightcol2   = 18, 18, 49\r\n")
# A retail install's icons sit 0x800 into the area.
ICON_OFFSET = 0x800

# The Nobunaga disc that can supply SYSMEM.
AUX_PRODUCT = "SLPM-65783"
AUX_BOOT = "SLPM_657.83"
AUX_CONTAINER = "AUTH/BIN/SLPM_651.97"
SYSMEM_SHA1 = "7fafca0f275bbb53d20e1e388313d2e46a427feb"


def progress(text):
    print("progress: %s" % text, flush=True)


def _path(root, rel):
    return os.path.join(root, *rel.split("/"))


def _read(root, rel):
    with open(_path(root, rel), "rb") as f:
        return f.read()


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _boot2(cnf):
    for line in cnf.decode("latin-1").replace("\r", "\n").split("\n"):
        if line.upper().startswith("BOOT2"):
            return line.split("=", 1)[1].strip()
    return ""


class Notes(object):
    def __init__(self):
        self.lines = []

    def note(self, text):
        self.lines.append(text)
        print("note: %s" % text, flush=True)


# ---- the disc --------------------------------------------------------------

def read_disc(disc, work):
    """A folder with the files this step reads: the disc itself if it is a folder."""
    if os.path.isdir(disc):
        root = disc
    else:
        root = os.path.join(work, "disc")
        common.extract(disc, root, only=WORK_FILES)
    try:
        cnf = _read(root, "SYSTEM.CNF")
    except (IOError, OSError):
        raise SystemExit("%s has no SYSTEM.CNF; is it the Minna no Golf Online disc?" % disc)
    if BOOT_FILE not in _boot2(cnf).upper():
        raise SystemExit("%s is not Minna no Golf Online (SYSTEM.CNF BOOT2 is %r, "
                         "this needs %s)" % (disc, _boot2(cnf), BOOT_FILE))
    for rel in (BOOT_FILE, "ZZBIN/DNAS.BIN", "FMOD/DNAS270.IMG", "CNF/SYS_NET.ICO"):
        if not os.path.isfile(_path(root, rel)):
            raise SystemExit("the disc is missing %s; is it a complete dump?" % rel)
    return root


def copy_tree(disc, tree):
    """The disc's files that go into the partition unchanged. Returns the count."""
    if not os.path.isdir(disc):
        return common.extract(disc, tree, skip=TREE_SKIP)
    skip = tuple(s.upper() for s in TREE_SKIP)
    n = 0
    for dirpath, dirs, names in os.walk(disc):
        rel = os.path.relpath(dirpath, disc).replace(os.sep, "/")
        rel = "" if rel == "." else rel + "/"
        dirs[:] = [d for d in dirs if not (rel + d + "/").upper().startswith(skip)]
        for name in names:
            if (rel + name).upper().startswith(skip) or name.startswith("."):
                continue
            dst = _path(tree, rel + name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(dirpath, name), dst)
            n += 1
    return n


def copy_fmod(root, tree):
    """The disc's FMOD/ and FMOD2/ modules, for the disc-less redirect. Returns the count."""
    n = 0
    for folder, exts in FMOD_DIRS:
        src = _path(root, folder)
        names = sorted(os.listdir(src)) if os.path.isdir(src) else []
        names = [x for x in names if x.upper().endswith(exts)]
        if not names:
            raise SystemExit("the disc has no %s/ modules; is it a complete dump?" % folder)
        for name in names:
            _write(_path(tree, "%s/%s" % (folder, name.upper())), _read(root, "%s/%s" % (folder, name)))
            n += 1
    return n


# ---- the sealed overlays ---------------------------------------------------

def seal(root, tree, hddid, four, english=None):
    """Seal the nine containers to the drive, each checked to decrypt to the
    plaintext sealed: the disc's ZZBIN/ twin, or for a name in `english`
    ({file name: English overlay}) that overlay, sealed in its place."""
    from . import disc_to_drive, dnasdec
    english = english or {}
    ata32 = dnasdec.ata_material(hddid)
    for i, name in enumerate(CONTAINERS):
        progress("sealing %s (%d of %d)" % (name, i + 1, len(CONTAINERS)))
        enc = _read(root, "ZZENC/ZZBIN/" + name)
        plain = _read(root, "ZZBIN/" + name)
        if name in english:
            stock, plain = plain, english[name]
            if len(plain) != len(stock):
                raise SystemExit("the English %s is not the size of the disc's" % name)

            def patcher(index, module, stock=stock, plain=plain, name=name):
                if index != 0 or module != stock:
                    raise SystemExit("ZZENC/ZZBIN/%s does not hold ZZBIN/%s; is the "
                                     "dump damaged?" % (name, name))
                return plain
            drive = disc_to_drive.build_drive_form_patched(enc, ata32, four, patcher)
        else:
            drive = disc_to_drive.build_drive_form(enc, ata32, four)
        mods = dnasdec.decrypt(drive, ata32, four)
        if len(mods) != 1 or mods[0] != plain:
            raise SystemExit("ZZENC/ZZBIN/%s does not decrypt to %s once sealed; "
                             "is the dump damaged?"
                             % (name, "the English overlay" if name in english
                                else "ZZBIN/" + name))
        _write(_path(tree, "ZZENC/ZZBIN/" + name), drive)
    return len(CONTAINERS)


# ---- the IOP reboot image --------------------------------------------------

def _is_aux(path):
    """True if `path` (an image or an extracted tree) is the Hiryuu no Shou disc."""
    if os.path.isdir(path):
        try:
            boot2 = _boot2(_read(path, "SYSTEM.CNF"))
        except (IOError, OSError):
            return False
        return AUX_BOOT in boot2.upper() and os.path.isfile(_path(path, AUX_CONTAINER))
    try:
        code, _boot = discmod.product_code(discmod.Image(path))
    except (discmod.NotADisc, IOError, OSError, ValueError):
        return False
    return code == AUX_PRODUCT


def find_aux_disc(folders):
    """The Nobunaga disc in one of `folders` (an image, or a disc/ tree), or None."""
    for folder in folders:
        if not folder or not os.path.isdir(folder):
            continue
        if _is_aux(folder):
            return folder
        tree = os.path.join(folder, "disc")
        if os.path.isdir(tree) and _is_aux(tree):
            return tree
        for sub in (folder, tree):
            if not os.path.isdir(sub):
                continue
            try:
                found = discmod.images_in(sub)
            except OSError:
                continue
            for path in found:
                if _is_aux(path):
                    return path
    return None


def ioprp_from_aux(aux, work):
    """The IOP reboot image inside the Nobunaga disc's SLPM_651.97 (it has SYSMEM)."""
    from . import disc_dec
    if os.path.isdir(aux):
        root = aux
    else:
        root = os.path.join(work, "aux")
        common.extract(aux, root, only=("SYSTEM.CNF", AUX_CONTAINER))
    try:
        boot2 = _boot2(_read(root, "SYSTEM.CNF"))
        enc = _read(root, AUX_CONTAINER)
    except (IOError, OSError):
        raise SystemExit("%s is not the Nobunaga no Yabou Online Hiryuu no Shou disc "
                         "(no %s)" % (aux, AUX_CONTAINER))
    if AUX_BOOT not in boot2.upper():
        raise SystemExit("%s is not the Hiryuu no Shou disc (BOOT2 %r)" % (aux, boot2))
    for _i, cur, size, _v1, _v2, _d9 in disc_dec.sections(enc):
        mod = disc_dec._decrypt_section(enc, cur, size)
        if mod.startswith(b"RESET\0"):
            return mod
    raise SystemExit("%s holds no IOP reboot image" % AUX_CONTAINER)


def build_ioprp(root, aux, work, m):
    """DNAS270.IMG, with SYSMEM from the Nobunaga disc when there is one."""
    from . import ioprp
    image = _read(root, "FMOD/DNAS270.IMG")
    ioprp.check_roundtrip(image)
    if not aux:
        m.note("no Nobunaga disc (SLPM-65783) was found, so the loader reboots the "
               "IOP with the disc's DNAS270.IMG, which has no SYSMEM; the proven "
               "boot used DNAS270.IMG + SYSMEM, and a reboot image without SYSMEM "
               "hung the IOP when it was tried. Minna boots only with that disc.")
        return image, "DNAS270.IMG without SYSMEM"
    progress("reading SYSMEM off the Nobunaga disc")
    donor = ioprp_from_aux(aux, work)
    data, _ext = ioprp.module(donor, "SYSMEM")
    if ioprp.sha1(data) != SYSMEM_SHA1:
        m.note("the Nobunaga disc's SYSMEM is not the one the proven boot used "
               "(sha1 %s)" % ioprp.sha1(data))
    out = ioprp.with_sysmem(image, donor)
    if ioprp.sha1(out) != ioprp.PROVEN_SHA1:
        m.note("the IOP reboot image (sha1 %s) differs from the proven one"
               % ioprp.sha1(out))
    return out, "DNAS270.IMG + SYSMEM from the Nobunaga disc"


# ---- the loader and the attribute area ------------------------------------

def fill_loader(root, kelf_path, ioprp_img, hddid, out_path):
    """The signed loader filled for this disc and drive; returns the patched boot ELF."""
    from . import atadgp, bootpatch, loader
    if not os.path.isfile(kelf_path):
        raise SystemExit("the Minna no Golf Online loader is missing (%s)" % kelf_path)
    with open(kelf_path, "rb") as f:
        blob = f.read()
    if not loader.is_empty(blob):
        raise SystemExit("%s is already filled; it must be the unfilled build" % kelf_path)
    elf = bootpatch.boot_elf(_read(root, BOOT_FILE))
    drivers = dict((n, _read(root, "FMOD/%s.IRX" % n)) for n in loader.DRIVERS)
    # A console's drive is often not a genuine Sony one, which the disc's
    # atad refuses inside its own probe; the gate-skipped atad serves the ID.
    drivers["ATAD"] = atadgp.patch(drivers["ATAD"], hddid)
    _write(out_path, loader.fill(blob, elf, ioprp_img, hddid, drivers))
    return elf


def build_attr(root, english):
    """The attribute area for partition + 0x1000 (English title with English text)."""
    if english:
        title0, title1, enc = TITLE0_EN, u"", "ascii"
        uninstall = ()
    else:
        title0, title1, enc = TITLE0, TITLE1, "utf-8"
        uninstall = UNINSTALL
    body = u"PS2X\r\ntitle0 = %s\r\ntitle1 = %s\r\n" % (title0, title1) + ICON_LOOK
    for i, text in enumerate(uninstall):
        body += u"uninstallmes%d = %s\r\n" % (i, text)
    return attrarea.build_area(BOOT_BLOCK, body.encode(enc),
                               _read(root, "CNF/SYS_NET.ICO"), icon_off=ICON_OFFSET)


# ---- the stage step --------------------------------------------------------

def stage(args):
    hddid = common.read_hddid(args.hddid)
    if args.four:
        four = bytes.fromhex(args.four)
        if len(four) != 4:
            raise SystemExit("--four takes 8 hex digits")
        four_from = "given"
    elif args.device:
        from . import write
        four = write.net_four(args.device, hddid)
        four_from = "the __net record of %s" % args.device
    else:
        raise SystemExit("give --four or --device (to read the drive's __net record)")

    aux = args.aux_disc
    if aux and not _is_aux(aux):
        raise SystemExit("%s is not the Nobunaga no Yabou Online Hiryuu no Shou disc (%s)"
                         % (aux, AUX_PRODUCT))
    if not aux:
        aux = find_aux_disc(list(args.aux_search or ())
                            + [os.path.dirname(os.path.abspath(args.disc))])
    if not aux and args.require_aux:
        raise SystemExit("no Nobunaga no Yabou Online Hiryuu no Shou disc (%s) was found; "
                         "Minna no Golf Online boots only with the IOP module it "
                         "supplies" % AUX_PRODUCT)

    out = os.path.abspath(args.out)
    if os.path.isdir(out):
        shutil.rmtree(out)
    tree = os.path.join(out, "tree")
    os.makedirs(tree)
    m = Notes()
    print("four %s (%s)" % (four.hex(), four_from), flush=True)

    work = tempfile.mkdtemp(prefix="mingol-")
    try:
        progress("reading the disc")
        root = read_disc(args.disc, work)
        dnas_plain = _read(root, "ZZBIN/DNAS.BIN")
        common.provide_dnas_consts([dnas_plain], work)
        from . import bootpatch                    # after the tables are known

        from . import english as englishmod
        english = englishmod.apply(root, m, translate=args.translate,
                                   pack_path=args.translation_pack,
                                   local=args.translation_dir)
        if english and not ENGLISH_SEALS:
            m.note("--translate: the English overlays are not installed: the game's "
                   "DNAS library refuses a changed overlay (-10202), so the game "
                   "stays Japanese")
            english = {}

        m.note("browser name: %s" % (TITLE0_EN if english else "Japanese, as on the disc"))

        progress("copying the game's files")
        copied = copy_tree(args.disc, tree)
        copied += copy_fmod(root, tree)
        sealed = seal(root, tree, hddid, four, english)
        _write(_path(tree, "INSTALL.VER"), struct.pack("<I", 4))
        _write(_path(tree, "DNAS.BIN"), bootpatch.dnas_overlay(dnas_plain))

        progress("filling the loader")
        ioprp_img, ioprp_what = build_ioprp(root, aux, work, m)
        loader_out = os.path.join(out, LOADER_NAME)
        elf = fill_loader(root, args.kelf, ioprp_img, hddid, loader_out)
        shutil.copyfile(loader_out, os.path.join(tree, LOADER_NAME))
        with open(os.path.join(out, "attr.bin"), "wb") as f:
            f.write(build_attr(root, bool(english)))
        if not bootpatch.is_known_pressing(_read(root, BOOT_FILE), dnas_plain):
            m.note("this pressing's SCPS_150.49 or DNAS.BIN is not the one the boot "
                   "was proven with; the patches applied, but it is untested")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    pwd = polhdd.apa_password(PARTITION, PASSWORD)
    if len(pwd) != 8:
        raise SystemExit("the APA password came out %d bytes, not 8" % len(pwd))
    m.note("IOP reboot image: %s (sha1 %s)" % (ioprp_what, hashlib.sha1(ioprp_img).hexdigest()))
    if aux:
        m.note("second disc: %s" % aux)
    with open(os.path.join(out, "game.json"), "w") as f:
        json.dump({"key": KEY, "partition": PARTITION, "need_mib": PART_MIB,
                   "rpwd": pwd.hex(), "fpwd": pwd.hex(), "four": four.hex(),
                   "has_sysmem": bool(aux), "notes": m.lines}, f, indent=1, sort_keys=True)
    print("staged %s: %d containers sealed, %d files copied, boot ELF %s, %s"
          % (PARTITION, sealed, copied, hashlib.sha1(elf).hexdigest()[:8], ioprp_what))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--disc", required=True, help="the disc image (or an extracted folder)")
    ap.add_argument("--hddid", required=True, help="the drive's 512-byte identity")
    ap.add_argument("--out", required=True, help="the folder to stage into (emptied first)")
    ap.add_argument("--kelf", required=True, help="the signed, unfilled loader "
                    "(scripts/assets/mingol/polbbnexec-mingol.kelf)")
    ap.add_argument("--four", help="the __net four to seal with, 8 hex digits")
    ap.add_argument("--device", help="read the four from this drive's __net record")
    ap.add_argument("--aux-disc", help="the Nobunaga no Yabou Online Hiryuu no Shou "
                    "disc (SLPM-65783, an image or an extracted tree), for the SYSMEM "
                    "module the IOP reboot image needs")
    ap.add_argument("--aux-search", action="append", metavar="DIR",
                    help="a folder to look for that disc in (repeatable); the "
                    "Minna disc's own folder is always searched")
    ap.add_argument("--require-aux", action="store_true",
                    help="refuse to stage without the Nobunaga disc")
    ap.add_argument("--translate", action="store_true",
                    help="download the English translation pack and check it "
                    "against the disc (not installed yet: ENGLISH_SEALS)")
    ap.add_argument("--translation-dir", metavar="DIR",
                    help="with --translate, a folder of packs to use when the "
                    "download cannot be had")
    ap.add_argument("--translation-pack", metavar="ZIP",
                    help="a local English translation pack (zip or folder); no download")
    return stage(ap.parse_args(argv))
