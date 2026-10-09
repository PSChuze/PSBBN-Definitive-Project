#!/usr/bin/env python3
"""Install Net de Bomberman onto a live PSBBN drive: seal -> mkpart -> pfsshell -> attr.

Nobunaga's PC-side shape (nobuinstall.py), consolidated into a single
partition that carries both the game data and the loader:

  1. seal   each DNAS2 container in the neutral install tree to the TARGET
            drive's identity (the served HDD ID + the __net four, 00001301),
            into a staged game tree. With --disc the tree is bombdisc.py's
            output from the user's own disc and its containers are in disc
            form; those go through disc_to_drive instead (offline, verified
            on all 28 against the retail install's decrypt).
  2. merge  the boot files (bombload.kelf/.elf, BOMBBOOT.ELF, DNAS280.IMG,
            DEV9/ATAD/HDD/PFS.IRX) into the same staged tree. No name
            collisions with the game files.
  3. mkpart PP.SLPS-20343.NET.BOMB (1024 MiB, covers the 540 MiB game plus
            the loader with room to grow). The partition name is fixed by
            MAIN.BIN (its _mountHDD at 0x3206a0 opens this exact name).
  4. put    write the merged tree with pfsshell. The stage dir must be
            space-free -- pfsshell's parser splits on whitespace and does
            not honor quoting -- so we stage inside --work (default is
            HERE/_stage; the install-run.sh points it at $HOME/bombstage).
  5. attr   one browser entry: BOOT2 = pfs:/bombload.kelf +
            DNASBOOT2 = pfs:/MAIN.BIN.

Earlier revisions of this file made two partitions (a small boot one
alongside the game) and used pfsshell's `lcd` to change local dir before
put. The scripts/helper pfsshell builds do not accept `lcd` with an
absolute path (unknown-command error), so puts used to look up bare names
in the process CWD, which quietly missed most files.  Two-partition browser
entries also looked awkward (one launchable, one NOBOOT). This revision
consolidates.

The HDD ID must be the block the console is SERVED at boot -- on a PSBBN
drive with the PlayOnline step installed, that is playonline.hddid (served
by atadpatch). Without it, the console serves the drive's real ATA IDENTIFY
page, which the installer reads off the device. Containers sealed to any
other ID will not decrypt on that drive.

Everything is a dry run (prints the plan and the pfsshell script) unless
--write is passed.

    python3 bombinstall.py <device> --bundle <neutral-tree> [--disc] --boot <bootfiles>
        --hddid <file> --icon <file.ico> [--four 00001301]
        [--game-mib 1024]
        [--pfsshell PFSSHELL] [--helper DIR] [--work DIR]
        [--reinstall | --update] [--write]

--update brings the partition already on the drive up to this stage in
place (playonline.lib.pfsupdate): only the files that changed or are new are
rewritten with pfsshell (rm + put), every file only the drive has (the
game's saves and settings) is kept, no mkpart/rmpart. The attribute area is
rewritten if it changed, fpwd and the header checksums are set again, and
the partition is read back against the stage. The old two-partition layout
is refused: reinstall it.
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "bomb"))
import bombbundle  # noqa: E402  (dnasbundle engine, *.BIN filter)
from dnasdec import ata_material  # noqa: E402

SECTOR = 512
ATTR_OFF = 0x1000
GAME_PART = "PP.SLPS-20343.NET.BOMB"
# Legacy name from the two-partition era; --reinstall drops it if present.
LEGACY_BOOT_PART = "PP.SLPS-20343.100.BOMBERMAN"
DEFAULT_GAME_MIB = 1024
FOUR = "00001301"

LOADER = "bombload.kelf"            # the standalone embed loader (main-hosdmenu),
                                    # signed as a KELF by work/bomb-sign-kelf.sh
SCE_MAGIC = b"Sony Computer Entertainment Inc."

# KELF/BOOT2 launch: the native HDD-OSD title launch, the same path Nobunaga's
# dnasload.elf and PlayOnline's 2.6 MB polbbnexec.kelf take on the operator's
# PSBBN Definitive (HOSDMenu) drive. The PATINFO + bombload.elf form (kept in
# bombattrswap.py --mode patinfo) launched a 262 KB loader there but kicked
# straight back to PSBBN for the 950 KB self-contained one, at both 0x200000
# and 0x01800000 link addresses: that launcher cannot carry a loader this
# size, the KELF path provably can. The loader is self-contained either way
# (reboots the IOP itself with the embedded DNAS280.IMG, loads ps2sdk
# ps2dev9/ps2atad + the scefix HDD-ID shim + Sony HDD/PFS, then BOMBBOOT).
#
# DNASBOOT2 = pfs:/MAIN.BIN goes with it: BOOT2 + DNASBOOT2 is the only attr
# shape our loader has launched with on real hardware (2026-10-02, the
# DNAS-shaped attr, bombattrswap --mode dnas); BOOT2 alone is untested
# there. HippaulInstaller's games/bomb BOOT_BLOCK ships the same shape.
BOOT_BLOCK = (
    "BOOT2 = pfs:/%s\r\n"
    "DNASBOOT2 = pfs:/MAIN.BIN\r\n"
    "VER = 1.02\r\n"
    "VMODE = NTSC\r\n"
    "HDDUNITPOWER = NICHDD\r\n"
) % LOADER

# BOMBBOOT (bombboot-spec.md 2.2) and MAIN.BIN's own _mountHDD mount the
# partition as "hdd0:PP.SLPS-20343.NET.BOMB,T3nheNY3". The console's driver
# checks that against the header's *fpwd* (format password); pfsshell's mkpart
# leaves it zero, so the mount fails silently and BOMBBOOT spins forever in its
# lseek retry (MAIN.BIN never reaches 0x300000).
#
# Only fpwd is set; rpwd (the read password at 0x30) is left ZERO. This is the
# PlayOnline rule (helper/playonline/password.py, DESIGN.md "Partition
# passwords"): the title's mount reads fpwd, and a nonzero rpwd would block
# HOSDMenu from mounting the partition to read bombload.elf for the PATINFO
# launch -- which showed up on real HW as a clean kick back to PSBBN.
# fpwd = apa_password("PP.SLPS-20343.NET.BOMB", b"T3nheNY3").
APA_FPWD = bytes.fromhex("02373c11a0a32358")

# The name follows the language: English only with the translation. The
# Japanese strings are the disc's own (DATA0/HDDICON1.DAT, res/info.sys),
# verbatim. `info` is what PSBBN's game list shows (res/info.sys); None
# leaves the disc's file as it is.
NAMES = {
    "english": {
        "icon": {"title0": "Bomberman Online",
                 "uninstall": ("", "")},
        "info": {"title": "Bomberman Online",
                 "genre": "Action",
                 "note": "The Bomberman battles that have won over countless "
                         "fans with their simple play are finally online."},
    },
    "japanese": {
        "icon": {"title0": "ネットでボンバーマン",
                 "uninstall": ("ゲームを削除します。", "よろしいでしょうか？")},
        "info": None,
    },
}

ICON_SYS = (
    "PS2X\r\n"
    "title0={title0}\r\n"
    "title1=\r\n"
    "bgcola=64\r\n"
    "bgcol0=0,0,0\r\n"
    "bgcol1=64,64,64\r\n"
    "bgcol2=0,0,0\r\n"
    "bgcol3=64,64,64\r\n"
    "lightdir0=1.0,-1.0,1.0\r\n"
    "lightdir1=-1.0,1.0,-1.0\r\n"
    "lightdir2=0.0,0.0,0.0\r\n"
    "lightcolamb=54,54,54\r\n"
    "lightcol0=54,54,54\r\n"
    "lightcol1=16,16,16\r\n"
    "lightcol2=0,0,0\r\n"
    "uninstallmes0={un0}\r\n"
    "uninstallmes1={un1}\r\n"
    "uninstallmes2=\r\n"
)


def translate_tree(staged, tsv):
    """FILES.BIN's messages in English (bombtext, in place in each slot) and
    the English title, genre and note in res/info.sys."""
    import bombtext
    files_bin = os.path.join(staged, "FILES.BIN")
    tmp = files_bin + ".en"
    if bombtext.cmd_msg_build(files_bin, tsv, tmp) != 0:
        raise SystemExit("FILES.BIN translation failed")
    os.replace(tmp, files_bin)
    print("   FILES.BIN messages <- %s" % tsv)
    info = os.path.join(staged, "res", "info.sys")
    if os.path.isfile(info):
        text = open(info, "rb").read().decode("utf-8")
        want = NAMES["english"]["info"]
        out = []
        for line in text.splitlines(True):
            key = line.split("=", 1)[0].strip()
            if "=" in line and key in want:
                end = line[len(line.rstrip("\r\n")):]
                line = "%s= %s%s" % (line.split("=", 1)[0], want[key], end)
            out.append(line)
        open(info, "wb").write("".join(out).encode("utf-8"))
        print("   res/info.sys: English title, genre and note")


def build_attr(icon_path, boot_block=BOOT_BLOCK, lang="japanese"):
    """The attribute area bytes, via the PlayOnline reference builder."""
    _psbbn = os.environ.get("PSBBN_HELPER")
    if _psbbn and _psbbn not in sys.path:
        sys.path.insert(0, _psbbn)
    from playonline import attrarea
    icon = open(icon_path, "rb").read()
    if len(icon) < 0x100 or icon[:8].hex() != "0000010001000000":
        raise SystemExit("icon does not look like a PS2 .ico (needs a real one; see README)")
    names = NAMES[lang]["icon"]
    body = ICON_SYS.format(title0=names["title0"], un0=names["uninstall"][0],
                           un1=names["uninstall"][1])
    return attrarea.build_area(boot_block.encode("ascii"), body.encode("utf-8"), icon)


def state(device):
    """english or japanese by the browser name, absent without the partition."""
    _psbbn = os.environ.get("PSBBN_HELPER")
    if _psbbn and _psbbn not in sys.path:
        sys.path.insert(0, _psbbn)
    from playonline import apa, attrarea
    found = apa.find_partition(device, GAME_PART)
    if found is None:
        return "absent"
    area = attrarea.read_area(device, found[0])
    title = ((attrarea.title0_of(area) if area else None) or "").strip()
    return "english" if title == NAMES["english"]["icon"]["title0"] else "japanese"


def real_hddid(device, out_path):
    """Read the drive's ATA IDENTIFY page as the served HDD ID (no POL shim).

    hdl_dump's `hdd_id` prints the page; the words are little-endian on the
    wire. We store exactly what the console's ata driver would return.
    """
    raise SystemExit(
        "no --hddid given and no automatic read: on a drive without the "
        "PlayOnline step, take the 512-byte ATA IDENTIFY page from the "
        "console (hdl_dump hdd_id) and pass it with --hddid")


# The loader embeds a placeholder 512-byte served-ID block whose model field
# (offset 0x20) carries this unique tag, so the block can be found unambiguously
# -- the IOP kernel copyright strings also contain SCE_MAGIC, so magic alone is
# not enough. The shipped loader always carries the placeholder; the install
# overwrites the whole block with the target drive's served ID.
LOADER_ID_TAG = b"SCEFIXPLACEHOLD"
LOADER_ID_TAG_OFF = 0x20            # tag sits at block + 0x20 (the model field)


def patch_loader_hddid(loader_path, hddid):
    """Overwrite the loader's embedded placeholder served-ID block with
    `hddid`. Found by LOADER_ID_TAG at block+0x20; `hddid` must be a 512-byte
    SCE identify block (starts with SCE_MAGIC)."""
    if len(hddid) != 512 or hddid[:len(SCE_MAGIC)] != SCE_MAGIC:
        raise SystemExit("--hddid must be a 512-byte SCE identify block "
                         "(starts with %r)" % SCE_MAGIC)
    blob = bytearray(open(loader_path, "rb").read())
    hits = [i for i in range(0, len(blob) - len(LOADER_ID_TAG) + 1)
            if blob[i:i + len(LOADER_ID_TAG)] == LOADER_ID_TAG]
    if len(hits) != 1:
        raise SystemExit("%s: expected exactly one placeholder HDD-ID tag, "
                         "found %d (is this the shipped embed loader?)"
                         % (loader_path, len(hits)))
    at = hits[0] - LOADER_ID_TAG_OFF
    if at < 0 or blob[at:at + len(SCE_MAGIC)] != SCE_MAGIC:
        raise SystemExit("%s: placeholder tag not preceded by an SCE block"
                         % loader_path)
    blob[at:at + 512] = hddid
    open(loader_path, "wb").write(bytes(blob))
    print("   patched loader served HDD ID at +%d (scefix now serves the "
          "target drive's block)" % at)


def pfsshell_jobs(device, staged_tree, game_mib, existing_to_remove):
    """Return a list of (host_cwd, script) jobs to feed pfsshell sequentially.

    pfsshell's put only accepts a bare basename and reads from the process
    CWD (its own help: "file name must not contain a path"); there is no
    lcd. So for a nested tree we split into one job per source subdir, each
    with the matching CWD, sharing the same device/partition across jobs.
    """
    jobs = []

    def walk(host_dir, remote_parts, is_first):
        entries = sorted(os.scandir(host_dir), key=lambda e: e.name)
        files = [e.name for e in entries if e.is_file()]
        subdirs = [e for e in entries if e.is_dir()]
        script = ["device %s" % device]
        if is_first:
            for name in existing_to_remove:
                script.append("rmpart %s" % name)
            script.append("mkpart %s %dM PFS" % (GAME_PART, game_mib))
        script.append("mount %s" % GAME_PART)
        for part in remote_parts:
            script.append("cd %s" % part)
        for name in [d.name for d in subdirs]:
            script.append("mkdir %s" % name)
        for name in files:
            script.append("put %s" % name)
        script += ["umount", "exit", ""]
        jobs.append((host_dir, "\n".join(script)))
        for sub in subdirs:
            walk(sub.path, remote_parts + [sub.name], False)

    walk(staged_tree, [], True)
    return jobs


def part_lba(device, part):
    from playonline import apa
    lba, _sectors = apa.find_partition(device, part)
    return lba


def write_attr(device, lba, attr_path):
    area = open(attr_path, "rb").read()
    if area[:9] != b"PS2ICON3D":
        raise SystemExit("attr file has no PS2ICON3D magic")
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        f.write(area)


def set_partition_password(device, ident, fpwd):
    """Write fpwd (0x38) into `ident`'s main APA header and leave rpwd (0x30)
    ZERO (POL rule: the mount checks fpwd; a nonzero rpwd blocks HOSDMenu from
    reading the partition). The checksum is left stale on purpose:
    fix_apa_checksums() runs after this and recomputes it."""
    from playonline import apa
    lba, _sectors = apa.find_partition(device, ident)
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR)
        hdr = bytearray(f.read(0x400))
        if hdr[4:8] != b"APA\x00":
            raise SystemExit("%s: no APA magic at LBA %d" % (ident, lba))
        hdr[0x38:0x40] = fpwd
        f.seek(lba * SECTOR)
        f.write(bytes(hdr))
    return lba


def apa_checksum(hdr):
    """The APA header checksum: the 32-bit sum of the words in [4, 0x400).

    Sony's hdd driver and the HDD-OSD validate it before using a partition.
    pfsshell writes headers without it (or with a stale one), and a wrong
    checksum shows up as exactly the launch-time bounce or the browser's
    "error in the content of the HDD" (the Toshiba/Bucanero fixer exists for
    the same reason). Verified against genuine console-written partitions
    (Nobunaga, Tetramaster, FFXI): stored == sum over [4, 0x400)."""
    total = 0
    for off in range(4, 0x400, 4):
        total = (total + struct.unpack_from("<I", hdr, off)[0]) & 0xFFFFFFFF
    return total


def fix_apa_checksums(device, ident):
    """Recompute the checksum of every header in `ident`'s chain (main + subs).

    pfsshell leaves the main header's checksum stale after its later edits,
    which the OSD reads as a corrupt partition: the icon shows, the launch
    bounces, and the browser's repair screen can follow."""
    from playonline import apa
    fixed = 0
    with open(device, "r+b") as f:
        for p in apa.partitions(device):
            if p.ident != ident:
                continue
            f.seek(p.lba * SECTOR)
            hdr = bytearray(f.read(1024))
            good = apa_checksum(hdr)
            stored = struct.unpack_from("<I", hdr, 0)[0]
            if stored != good:
                struct.pack_into("<I", hdr, 0, good)
                f.seek(p.lba * SECTOR)
                f.write(bytes(hdr))
                fixed += 1
    return fixed


def precheck(device, helper_dir, game_mib, reinstall, update=False):
    """APA-Jail-aware safety gate: reuse nobunaga.check's free-space math.

    Returns (info, existing_to_remove). `existing_to_remove` is any of our
    partition names already on the drive that --reinstall should rmpart.
    Without --reinstall, we refuse if either name is present.
    """
    if helper_dir and helper_dir not in sys.path:
        sys.path.insert(0, helper_dir)
    from nobunaga import check
    from playonline import apa
    info = check.inspect(device)
    print("== precheck: PS2 system %s, jailed %s, free-in-region %d MiB (largest %d), "
          "fits gate below" % (info["system"], info["jailed"], info["free_mib"],
                               info["largest_mib"]))
    if info["others"]:
        print("   other title partitions present (left untouched): %s"
              % ", ".join(info["others"]))
    if info["installed"]:
        # info["installed"] is Nobunaga's own pieces (nobunaga.check.PIECES).
        # For a Bomberman installer that is not a reason to refuse -- coexistence
        # is the whole point. Bomberman double-install is caught below.
        print("   Nobunaga present (left untouched): %s"
              % ", ".join(info["installed"]))
    if not info["system"]:
        raise SystemExit("not a PS2/PSBBN drive (missing __system/__sysconf/__common)")
    names = {p.ident for p in apa.partitions(device) if not p.is_sub}
    existing = [n for n in (GAME_PART, LEGACY_BOOT_PART) if n in names]
    if update:
        if GAME_PART not in names:
            raise SystemExit("%s is not on this drive: nothing to update" % GAME_PART)
        if LEGACY_BOOT_PART in names:
            raise SystemExit("this drive has the old two-partition layout (%s): it "
                             "cannot be updated in place; reinstall it" % LEGACY_BOOT_PART)
        print("   %s present: updating it in place" % GAME_PART)
        return info, []
    if existing:
        if not reinstall:
            raise SystemExit("Bomberman partitions already on this drive (%s); "
                             "pass --reinstall to drop and rebuild them"
                             % ", ".join(existing))
        print("   Bomberman partitions to be dropped and rebuilt: %s"
              % ", ".join(existing))
    if not check.fits(check.free_in_region(device), [game_mib]):
        raise SystemExit("does not fit inside the PS2 region "
                         "(need %d MiB, largest free slot %d MiB)"
                         % (game_mib, info["largest_mib"]))
    return info, existing


def update_partition(a, staged, attr_path):
    """--update: rewrite only what changed in GAME_PART (see the docstring)."""
    from playonline.lib import pfsupdate
    with pfsupdate.Installed(a.device, GAME_PART) as inst:
        lba = inst.lba
        plan = pfsupdate.plan(inst, staged)
    want_attr = open(attr_path, "rb").read() if attr_path else b""
    with open(a.device, "rb") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        attr_stale = bool(want_attr) and f.read(len(want_attr)) != want_attr
    print("== update %s at LBA %d: %s%s" % (GAME_PART, lba, plan.summary(),
                                            ", browser entry changed" if attr_stale else ""))
    for line in plan.lines():
        print(line)
    if plan.empty and not attr_stale:
        print("== the partition is current: nothing to write")
        return
    script = pfsupdate.script(a.device, GAME_PART, staged, plan)
    if not a.write:
        print(script[:800] + ("..." if len(script) > 800 else ""))
        print("== dry run: nothing written (pass --write)")
        return
    if not plan.empty:
        pfsupdate.run(a.pfsshell, script)
    if attr_stale:
        write_attr(a.device, lba, attr_path)
        print("== attr: browser entry rewritten at LBA %d + 0x1000" % lba)
    set_partition_password(a.device, GAME_PART, APA_FPWD)
    n = fix_apa_checksums(a.device, GAME_PART)
    print("== apa: fpwd kept, %d header checksum(s) recomputed" % n)
    bad = pfsupdate.verify(a.device, GAME_PART, staged, plan)
    if bad:
        raise SystemExit("the update did not read back as written:\n  " + "\n  ".join(bad))
    print("== read back: every staged file matches, %d kept file(s) unchanged"
          % len(plan.kept))
    print("== done: %s on %s updated" % (GAME_PART, a.device))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("device")
    ap.add_argument("--bundle", required=True, help="the neutral install tree")
    ap.add_argument("--disc", action="store_true",
                    help="--bundle is bombdisc.py output: its containers are "
                         "in disc form")
    ap.add_argument("--boot", required=True,
                    help="the boot-files folder (merged into the game "
                         "partition alongside the game files)")
    ap.add_argument("--hddid", help="the 512-byte block the console is SERVED")
    ap.add_argument("--icon", help="PS2 .ico for the browser (see README)")
    ap.add_argument("--four", default=FOUR)
    ap.add_argument("--game-mib", type=int, default=DEFAULT_GAME_MIB)
    ap.add_argument("--pfsshell", default="pfsshell")
    ap.add_argument("--helper", help="toolkit scripts/helper dir (fit gate)")
    ap.add_argument("--work", default=os.path.join(HERE, "_stage"),
                    help="stage dir. MUST have no spaces in its path -- "
                         "pfsshell splits `put` args on whitespace")
    ap.add_argument("--reinstall", action="store_true",
                    help="drop the existing Bomberman partitions (both the "
                         "one-partition layout and the earlier two-partition "
                         "layout) before mkpart")
    ap.add_argument("--update", action="store_true",
                    help="update the partition already on the drive in place, "
                         "keeping the game's own files")
    ap.add_argument("--translate", metavar="TSV",
                    help="the English translation (msg_FILES_install.en.tsv): "
                         "FILES.BIN's messages in English and the English name "
                         "in the browser and PSBBN's list. Without it the game "
                         "and its name stay Japanese, as on the disc.")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    lang = "english" if a.translate else "japanese"

    if " " in a.work:
        raise SystemExit("--work must be a space-free path (pfsshell put "
                         "does not accept quoted or escaped paths)")

    if a.update and a.reinstall:
        raise SystemExit("--update and --reinstall exclude each other")
    if a.helper:
        info, existing_to_remove = precheck(
            a.device, a.helper, a.game_mib, a.reinstall, a.update)
    else:
        print("== precheck skipped (no --helper)")
        existing_to_remove = []
    if a.check_only:
        print("== check-only: nothing written")
        return

    if not a.hddid:
        real_hddid(a.device, None)
    ata32 = ata_material(open(a.hddid, "rb").read())
    four = bytes.fromhex(a.four)

    staged = os.path.join(a.work, "game")
    if os.path.exists(a.work):
        shutil.rmtree(a.work)
    os.makedirs(staged)
    print("== seal %s -> %s (keyed to the served ID + four %s)"
          % (a.bundle, staged, a.four))
    if a.disc:
        # pop'n's disc_to_drive, the one verified on this title, ships beside
        # this file (lib/ in the toolkit). Put it ahead of NOBU_TOOLS, whose
        # Nobunaga copy builds different bytes.
        lib = os.path.join(HERE, "lib")
        sys.path.insert(0, lib if os.path.isdir(lib) else HERE)
        import disc_to_drive
        seal = lambda b: disc_to_drive.build_drive_form(b, ata32, four)  # noqa: E731
    else:
        seal = lambda b: bombbundle.dnasbundle.seal(b, ata32, four)  # noqa: E731
    n_c, n_f = bombbundle.map_tree(a.bundle, staged, seal)
    print("   sealed %d containers, copied %d files" % (n_c, n_f))
    if a.translate:
        translate_tree(staged, a.translate)

    # Merge bootfiles into the same staged tree so they land at the partition
    # root next to the game files. Refuse to overwrite (name collision would
    # be a real bug -- neither set has a member the other has).
    n_b = 0
    for name in sorted(os.listdir(a.boot)):
        src = os.path.join(a.boot, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(staged, name)
        if os.path.exists(dst):
            raise SystemExit("boot file %s collides with game file at %s"
                             % (name, dst))
        shutil.copy(src, dst)
        n_b += 1
    print("   merged %d boot files into %s" % (n_b, staged))

    # Patch the served HDD ID into the loader's embedded scefix block, so the
    # shim serves the exact ID the containers were sealed to (libdnas2 keys
    # MAIN.BIN's decrypt off it). The loader ships with a placeholder 512-byte
    # SCE identify block starting with SCE_MAGIC; replace it with --hddid.
    # polkelf signs only the first 32 content bytes, so the same tag patch
    # works on the signed bombload.kelf. The plain bombload.elf (PATINFO
    # fallback, bombattrswap.py --mode patinfo) is patched too when present.
    hddid_blk = open(a.hddid, "rb").read()
    patch_loader_hddid(os.path.join(staged, LOADER), hddid_blk)
    for extra in ("bombload.elf",):
        p = os.path.join(staged, extra)
        if extra != LOADER and os.path.isfile(p):
            patch_loader_hddid(p, hddid_blk)

    if a.update:
        attr_path = None
        if a.icon:
            attr_path = os.path.join(a.work, "attr.bin")
            open(attr_path, "wb").write(build_attr(a.icon, BOOT_BLOCK, lang))
        update_partition(a, staged, attr_path)
        return

    jobs = pfsshell_jobs(a.device, staged, a.game_mib, existing_to_remove)
    total_cmds = sum(s.count("\n") for _cwd, s in jobs)
    total_puts = sum(1 for _cwd, s in jobs for ln in s.splitlines()
                     if ln.startswith("put"))
    print("== pfsshell plan: %d jobs, %d commands total, %d put lines"
          % (len(jobs), total_cmds, total_puts))
    for cwd, script in jobs:
        head = "\n".join("   " + ln for ln in script.splitlines()[:4])
        print("   cwd=%s" % cwd)
        print(head)
        print("   ...")

    if not a.icon:
        print("== attr: no --icon given; the partition will read as Corrupted "
              "Data in the browser (the game still boots). Pass --icon to fix.")
    attr_path = None
    if a.icon:
        attr_path = os.path.join(a.work, "attr.bin")
        open(attr_path, "wb").write(build_attr(a.icon, BOOT_BLOCK, lang))

    if not a.write:
        print("== attr: dry run -- --write to apply")
        return

    print("== running %d pfsshell jobs" % len(jobs))
    for cwd, script in jobs:
        print("   -- cwd=%s" % cwd)
        subprocess.run([a.pfsshell], input=script, text=True, check=True, cwd=cwd)
    lba_game = part_lba(a.device, GAME_PART)
    if attr_path:
        print("== attr: browser entry at LBA %d + 0x1000" % lba_game)
        write_attr(a.device, lba_game, attr_path)
    set_partition_password(a.device, GAME_PART, APA_FPWD)
    print("== apa: fpwd set, rpwd left zero (BOMBBOOT mounts hdd0:%s,<pw>; "
          "HOSDMenu can still read it)" % GAME_PART)
    # Must come after the password write: it recomputes the header checksum,
    # which pfsshell also leaves stale after its own later edits.
    n = fix_apa_checksums(a.device, GAME_PART)
    print("== apa: %d header checksum(s) recomputed" % n)
    print("== done: %s on %s" % (GAME_PART, a.device))


if __name__ == "__main__":
    main()
