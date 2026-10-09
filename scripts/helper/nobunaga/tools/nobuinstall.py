"""Install Nobunaga onto a live PSBBN drive: seal -> mkpart -> pfsshell -> attr.

Two front-ends, one back-end:

  --disc <disc-root>   The clean path: seal every DNAS2 container straight
                       from the player's own disc extract (23 .ERX + 6 .EBN +
                       AUTH/BIN/SLPM_651.97 = 30 containers). No decrypted
                       game modules ship or need to exist beforehand. Also
                       generates the attr area from the disc's icon if
                       --attr is not passed. Recommended.

  --bundle <tree>      Legacy path: seal from a pre-decrypted drive-neutral
                       bundle (work/nobu-neutral). Kept for the transition
                       and for testers who already have a bundle; retired
                       once TOOLKIT-INTEGRATION.md's migration lands.

Common flow:

  1. seal   each DNAS2 container to the TARGET drive's identity (its served
            HDD ID + the __net four, 00001301). --disc uses tools/disc_dec
            + tools/disc_to_drive; --bundle reuses dnasbundle.seal. Either
            way no Sony private key is used -- the geometry comes from
            intact RSA records.
  2. mkpart create PP.SLPM-65197.KOEI.NOBUON (3584 MiB) with pfsshell; a size
            past the drive ceiling becomes a main + APA sub-partitions, one
            PFS volume across all of them, exactly as pfsshell shapes FFXI.
  3. put    write the staged tree into that volume with pfsshell.
  4. attr   write the drive-independent attribute area (English browser title
            + icon + boot block) at the main partition + 0x1000, so the
            browser shows the title instead of "Corrupted Data".

Translation (optional): --translation <pack> overlays user-supplied plaintext
data files (e.g. English UIMSG.BIN/WDMMSG.BIN/STRDAT tables). Alternatively,
--disc mode auto-creates <disc-root>/../translation/ on first run; drop the
zip's contents there and re-run without --translation to have them applied.

The HDD ID must be the block the console is served at boot - on PSBBN that is
the PlayOnline step's minted `playonline.hddid`, served by atadpatch. Modules
sealed to any other ID will not decrypt on that drive.

Everything is a dry run unless --write is passed. This module writes NEW files
only; it never edits the PlayOnline package, and reuses it only by reading.

    python3 nobuinstall.py <device> --disc <disc-root> --hddid <file> \
        [--attr <attr-area.bin>] [--four 00001301] [--part-mib 3584] \
        [--pfsshell PFSSHELL] [--hdl "HDL Dump.elf"] [--work DIR] [--write]

    # legacy path:
    python3 nobuinstall.py <device> --bundle <neutral-tree> --hddid <file> \
        --attr <attr-area.bin> ...
"""
import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dnasbundle                                # noqa: E402
import nobupatch                                 # noqa: E402
import disc_dec                                  # noqa: E402
import disc_to_drive                             # noqa: E402
import lwz                                       # noqa: E402
from dnasdec import ata_material                 # noqa: E402

SECTOR = 512
ATTR_OFF = 0x1000
PARTITION = "PP.SLPM-65197.KOEI.NOBUON"
DEFAULT_MIB = 3584                               # 128+128+256+512+1024+1024, genuine
FOUR = "00001301"
# The toolkit's helper dir, where nobunaga.check + the playonline package live.
DEFAULT_HELPER = r"E:\Code\PlayOnline Project\psbbn-playonline\scripts\helper"

# Nobunaga (SLPM-65197) supported version: Hiryuu no Shou expansion. The disc
# carries `SYSTEM.CNF: BOOT2 = cdrom0:\SLPM_657.83;1` and its game ELF is at
# AUTH/BIN/SLPM_651.97. Both must be present for `--disc` to accept the extract.
DISC_BOOT2   = "SLPM_657.83"
DISC_GAME    = os.path.join("AUTH", "BIN", "SLPM_651.97")

# On-disc DNAS2 containers we transcrypt to the target drive.
DISC_AUTH_MODULES = "AUTH/MODULES"                # 23 .ERX files
DISC_AUTH_OVERLAY = "AUTH/OVERLAY"                # 6 .EBN files
DISC_BOOT_ELF     = "AUTH/BIN/SLPM_651.97"        # boot ELF (single container)
# Where the boot ELF lands in the installed PP tree.
INSTALLED_BOOT    = "SLPM-65197"

# The 4 verdict-patched .EBN modules -- nobupatch handles NBONLINE; others
# fall through unchanged.
PATCHED_MODULES = {"NBONLINE.EBN"}


def precheck(device, helper_dir, update=False):
    """APA-Jail-aware safety gate: reuse nobunaga.check so the install can
    never carve past the PS2 region into the exFAT games. Returns check.inspect
    info, or raises SystemExit if the drive isn't a valid, roomy PSBBN target.
    With `update` the partition must already be there instead (nothing is
    carved, so room is not checked)."""
    if helper_dir and helper_dir not in sys.path:
        sys.path.insert(0, helper_dir)
    try:
        from nobunaga import check
    except Exception as e:
        raise SystemExit("cannot import the fit/jail check (nobunaga.check) from %r: %s\n"
                         "  pass --helper <toolkit>/scripts/helper" % (helper_dir, e))
    info = check.inspect(device)
    print("== precheck: PS2 system %s, jailed %s, free-in-region %d MiB (largest %d), "
          "need %d MiB, fits %s" % (info["system"], info["jailed"], info["free_mib"],
                                    info["largest_mib"], info["need_mib"], info["fits"]))
    if info["others"]:
        print("   other title partitions present (left untouched): %s" % ", ".join(info["others"]))
    if not info["system"]:
        raise SystemExit("not a PS2/PSBBN drive (missing __system/__sysconf/__common)")
    if update:
        if not info["installed"]:
            raise SystemExit("Nobunaga is not installed on this drive: nothing to update")
        return info
    if info["installed"]:
        raise SystemExit("Nobunaga is already installed on this drive (%s); refusing"
                         % ", ".join(info["installed"]))
    if not info["fits"]:
        raise SystemExit("Nobunaga's %d MiB does not fit inside the PS2 region (only %d MiB "
                         "free there) - refusing so the exFAT games are never touched"
                         % (info["need_mib"], info["free_mib"]))
    return info


def seal_tree(bundle, staged, ata32, four, verdict_patch=False, capture=None):
    """Seal every container in the neutral bundle to (ata32, four); copy the rest.

    NBONLINE.EBN seals STOCK unless verdict_patch is set. The verdict patch
    (nobupatch) edits the module under its RSA-signed SHA-1; nothing here can
    re-sign, so the console's DNAS loader rejects the patched module and the
    game drops back to the browser (2026-10-02). The install that reached the
    game on hardware shipped NBONLINE stock and never needed the patch: the
    verdict it overrides does not gate a third-party drive, and the DNAS skip
    comes from NBCONNSV naming the Koei test host."""
    n_c = n_f = n_p = 0
    for path, rel in dnasbundle._walk(bundle):
        out = os.path.join(staged, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        blob = open(path, "rb").read()
        looks = rel.upper().endswith(dnasbundle.CONTAINER_EXT) or os.path.basename(rel) == "SLPM-65197"
        if looks and dnasbundle.is_container(blob):
            if verdict_patch and os.path.basename(rel).upper() == nobupatch.NBONLINE:
                blob = patch_nbonline(blob)
                n_p += 1
            sealed = dnasbundle.seal(blob, ata32, four)
            open(out, "wb").write(sealed)
            # Capture the first sealed container (its known neutral + drive form)
            # so verify_seal_serve can round-trip it against the served HDD ID.
            if capture is not None and not capture:
                capture["neutral"] = blob
                capture["sealed"] = sealed
                capture["name"] = os.path.basename(rel)
            n_c += 1
        else:
            shutil.copyfile(path, out)
            n_f += 1
    return n_c, n_f, n_p


def patch_nbonline(blob):
    """Patch the decrypted NBONLINE module inside its neutral container.

    The neutral container holds the decrypted outer layer at sec+0x300; the
    game module sits one inner RC6 layer deeper (dnasdec's chain: outer ->
    inner -> module). Extract it, patch the verdict words (nobupatch), push it
    back through inner, and write the result in place. Every RSA record stays
    byte-identical, but the signature record holds the SHA-1 of the inner
    ciphertext, so after this the module no longer matches its signed hash
    (dnasdec reports sig_ok False) and the console's DNAS loader rejects it.
    Only used with --verdict-patch; see seal_tree."""
    import struct
    import dnas2
    import rc6
    for sec, extent in dnasbundle._sections(blob):
        outer = bytearray(blob[sec + 0x300:sec + 0x300 + extent])
        if not outer:
            continue
        keys = dnas2.keys()
        sizes_r = dnas2.unrecord(bytes(blob[sec + 0x100:sec + 0x180]), keys[3][1], keys[3][2])
        sizes = sizes_r[0] if sizes_r else None
        if not sizes:
            continue
        v2 = struct.unpack("<I", sizes[4:8])[0]
        d9, d10 = sizes[9] * 16, sizes[10] * 16
        stat = None
        for t in (10, 6, 14):
            r = dnas2.unrecord(bytes(blob[sec:sec + 0x80]), keys[t][1], keys[t][2])
            if r and r[0]:
                stat = r[0]
                break
        if not stat:
            continue
        s32 = stat[:32]
        inner_len = v2 + d9 + 16
        inner = bytearray(rc6.cbc(bytes(outer[d10:d10 + inner_len]), s32[0:16], s32[16:32], True))
        module = bytes(inner[d9:d9 + v2])
        patched = nobupatch.patch_module(module)
        if patched == module:
            continue
        inner[d9:d9 + v2] = patched
        outer[d10:d10 + inner_len] = rc6.cbc(bytes(inner), s32[0:16], s32[16:32], False)
        blob = blob[:sec + 0x300] + bytes(outer) + blob[sec + 0x300 + extent:]
    return blob


def _quote(name):
    return '"%s"' % name if " " in name else name


def emit_dir(out, host_dir):
    """pfsshell put/mkdir/cd for one directory of the staged tree (recursive)."""
    with os.scandir(host_dir) as it:
        entries = sorted(it, key=lambda e: e.name)
    files = [e for e in entries if e.is_file()]
    if files:
        out.append("lcd %s" % _quote(host_dir.replace("\\", "/")))
        for e in files:
            out.append("put %s" % _quote(e.name))
    for e in entries:
        if e.is_dir():
            out.append("mkdir %s" % _quote(e.name))
            out.append("cd %s" % _quote(e.name))
            emit_dir(out, e.path)
            out.append("cd ..")


def pfsshell_script(device, staged, part_mib):
    out = ["device %s" % device,
           "mkpart %s %dM PFS" % (PARTITION, part_mib),
           "mount %s" % PARTITION]
    emit_dir(out, staged)
    out += ["umount", "exit", ""]
    return "\n".join(out)


def part_lba(helper_dir, device):
    """The PP main partition's start LBA (sectors), via the pure-Python APA
    reader - robust on any APA drive/image, unlike parsing hdl_dump toc
    (which rejects emulator images with no tail chain)."""
    if helper_dir and helper_dir not in sys.path:
        sys.path.insert(0, helper_dir)
    from playonline import apa
    lba, _sectors = apa.find_partition(device, PARTITION)
    return lba


def write_attr(device, lba, attr_path):
    area = open(attr_path, "rb").read()
    if area[:9] != b"PS2ICON3D":
        raise SystemExit("attr file has no PS2ICON3D magic")
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        f.write(area)


def write_passwords(device, lba, helper_dir):
    """Set the APA header passwords the game mounts NOBUON with.

    The game opens `hdd0:PP.SLPM-65197.KOEI.NOBUON,NOBUONF,NOBUONR`; the header
    must carry apa_password(id, "NOBUONR"/"NOBUONF") in rpwd (+0x30) and fpwd
    (+0x38), or the hdd driver returns -EACCES right after reading the header
    (the black-screen boot #12-#42 diagnosed 2026-09-28; see the project's
    HANDOFF-hw-boot.md). pfsshell's mkpart leaves both fields zero, so this is
    required after mkpart on any PC-side install. Koei's console installer sets
    them itself."""
    if helper_dir and helper_dir not in sys.path:
        sys.path.insert(0, helper_dir)
    from playonline.lib.polhdd import apa_password, checksum
    rpwd = apa_password(PARTITION, b"NOBUONR")
    fpwd = apa_password(PARTITION, b"NOBUONF")
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR)
        hdr = bytearray(f.read(1024))
        if hdr[0x10:0x10 + len(PARTITION)] != PARTITION.encode():
            raise SystemExit("LBA %d is not %s; refusing to write passwords" % (lba, PARTITION))
        hdr[0x30:0x38] = rpwd
        hdr[0x38:0x40] = fpwd
        struct.pack_into("<I", hdr, 0, 0)
        struct.pack_into("<I", hdr, 0, checksum(bytes(hdr)))
        f.seek(lba * SECTOR)
        f.write(bytes(hdr))
    return rpwd, fpwd



def update_in_place(a, staged, attr_path):
    """The installed partition brought up to `staged` (playonline.lib.pfsupdate,
    as the Minna and Bomberman updates do): changed files rewritten, new ones
    put, files only the partition has kept. Never mkpart or rmpart. pfsshell
    can disturb the header, so the NOBUON passwords are set again; the
    attribute area is rewritten if it differs; everything is read back."""
    from playonline.lib import pfsupdate
    with pfsupdate.Installed(a.device, PARTITION) as inst:
        lba = inst.lba
        plan = pfsupdate.plan(inst, staged)
    area = open(attr_path, "rb").read()
    with open(a.device, "rb") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        attr_stale = f.read(len(area)) != area
    print("== update %s at LBA %d: %s%s" % (PARTITION, lba, plan.summary(),
                                            ", browser entry changed" if attr_stale else ""))
    for line in plan.lines():
        print(line)
    if plan.empty and not attr_stale:
        print("== the partition is current: nothing to write")
        return
    script = pfsupdate.script(a.device, PARTITION, staged, plan)
    if not a.write:
        print("== dry run: nothing written (pass --write)")
        return
    if not plan.empty:
        pfsupdate.run(a.pfsshell, script)
    if part_lba(a.helper, a.device) != lba:
        raise SystemExit("%s moved or vanished during the update" % PARTITION)
    write_passwords(a.device, lba, a.helper)
    print("== passwords: NOBUONR/NOBUONF set again on %s" % PARTITION)
    if attr_stale:
        write_attr(a.device, lba, attr_path)
        print("== attr rewritten at LBA %d + 0x1000" % lba)
    bad = pfsupdate.verify(a.device, PARTITION, staged, plan)
    if bad:
        raise SystemExit("the update did not read back as written:\n  " + "\n  ".join(bad))
    print("== read back: every staged file matches, %d kept file(s) unchanged"
          % len(plan.kept))


RETAIL_HOST = b"nobol.koei.co.jp:9070"
TEST_HOST = b"testconsv1.ax.koei.co.jp:9070"


def connect_to_test_host(staged):
    """Point NBCONNSV.BIN at Koei's test connect host, and CRC32TBL.BIN with it.

    The game skips its DNAS check, whose servers are gone, only when the host
    it connects to is one of Koei's test hosts; with the disc's retail host it
    runs the full check, which cannot pass, and exits. The community server's
    DNS answers both names. CRC32TBL.BIN holds each data file's CRC-32
    (little-endian) and the game checks NBCONNSV.BIN against it, so its entry
    changes too. Both edits are refused unless the files are the disc's own.
    This is the data-only change the hardware-proven install was made with.
    """
    import zlib
    conn = os.path.join(staged, "NBCONNSV.BIN")
    table = os.path.join(staged, "CRC32TBL.BIN")
    host = open(conn, "rb").read()
    crcs = bytearray(open(table, "rb").read())
    if host == TEST_HOST:
        return False
    if host != RETAIL_HOST:
        raise SystemExit("NBCONNSV.BIN names %r, not the disc's %r" % (host, RETAIL_HOST))
    old = struct.pack("<I", zlib.crc32(RETAIL_HOST))
    if crcs.count(old) != 1:
        raise SystemExit("CRC32TBL.BIN does not list NBCONNSV.BIN's checksum once")
    at = crcs.index(old)
    crcs[at:at + 4] = struct.pack("<I", zlib.crc32(TEST_HOST))
    open(conn, "wb").write(TEST_HOST)
    open(table, "wb").write(bytes(crcs))
    print("== NBCONNSV.BIN -> %s (CRC32TBL.BIN entry at %d updated)"
          % (TEST_HOST.decode("ascii"), at))
    return True


def overlay_translation(staged, pack):
    """Overwrite plaintext data files in the staged tree with a user-supplied
    translation pack (e.g. translated UIMSG.BIN / WDMMSG.BIN / STRDAT tables).

    Only files that already exist in the staged tree are replaced, and a file
    that is itself a DNAS2 container is refused - the translation is plaintext
    game data, never sealed code. The pack is supplied by the user; no
    translated content ships with the toolkit."""
    n = 0
    for path, rel in dnasbundle._walk(pack):
        dest = os.path.join(staged, rel)
        if not os.path.exists(dest):
            print("   translation: %s is not in the game tree, skipping" % rel)
            continue
        if dnasbundle.is_container(open(path, "rb").read()):
            print("   translation: %s looks like a DNAS2 container, refusing" % rel)
            continue
        shutil.copyfile(path, dest)
        n += 1
    return n


# ---- disc-based seal ---------------------------------------------------------

def verify_disc(disc_root):
    """Sanity-check the disc extract before we start sealing.

    Nobunaga (SLPM-65197) has several Japan-only pressings. The one this
    installer supports is the **Hiryuu no Shou** expansion disc, whose SYSTEM.CNF
    BOOT2 line is `cdrom0:\\SLPM_657.83;1` and whose game ELF sits at
    `AUTH/BIN/SLPM_651.97`. Other pressings (base game 2003, various
    pre-expansion incremental patches) will not have this exact combination.
    """
    if not os.path.isdir(disc_root):
        raise SystemExit("--disc %r is not a directory" % disc_root)
    scnf = os.path.join(disc_root, "SYSTEM.CNF")
    if not os.path.isfile(scnf):
        raise SystemExit("--disc %r has no SYSTEM.CNF; not a disc extract" % disc_root)
    lines = open(scnf, "rb").read().decode("ascii", "replace").splitlines()
    boot2 = ""
    for ln in lines:
        if "BOOT2" in ln.upper():
            boot2 = ln; break
    if DISC_BOOT2 not in boot2:
        which = ""
        if "SLPM_651.97" in boot2:
            which = ("This is the ORIGINAL 2003 Nobunaga no Yabou Online disc "
                     "(SLPM-65197, boot file SLPM_651.97), which cannot be installed. ")
        raise SystemExit("SYSTEM.CNF BOOT2 = %r; expected %r. %s"
                         "The install needs the Hiryuu no Shou EXPANSION disc "
                         "(Nobunaga no Yabou Online: Hiryuu no Shou, 2004, SLPM-65783, "
                         "boot file SLPM_657.83). Put that disc's .iso in the games folder "
                         "and run this step again."
                         % (boot2.strip(), DISC_BOOT2, which))
    game = os.path.join(disc_root, DISC_GAME.replace("/", os.sep))
    if not os.path.isfile(game):
        raise SystemExit("disc extract is missing %s. Extract the whole disc, "
                         "not just the root files." % DISC_GAME)
    # Count expected containers.
    n_erx = sum(1 for f in os.listdir(os.path.join(disc_root, DISC_AUTH_MODULES.replace("/", os.sep)))
                if f.upper().endswith(".ERX"))
    n_ebn = sum(1 for f in os.listdir(os.path.join(disc_root, DISC_AUTH_OVERLAY.replace("/", os.sep)))
                if f.upper().endswith(".EBN"))
    print("== disc verified: Hiryuu no Shou (BOOT2 = %s), %d .ERX + %d .EBN + boot ELF"
          % (DISC_BOOT2, n_erx, n_ebn))
    return dict(n_erx=n_erx, n_ebn=n_ebn)


def _patcher_for(container_name, verdict_patch=False):
    """Return a per-container module patcher, or None if the container should
    seal unchanged. Only NBONLINE.EBN has a patch (the DNAS2 verdict override),
    and only when verdict_patch is set: it breaks the module's signed SHA-1, so
    real hardware rejects it (see seal_tree)."""
    if verdict_patch and container_name.upper() == "NBONLINE.EBN":
        def patch(_i, module):
            return nobupatch.patch_module(module)
        return patch
    return None


def seal_from_disc(disc_root, staged, ata32, four, verdict_patch=False, capture=None):
    """Seal every disc container to (ata32, four); copy the plaintext PP tree
    files verbatim.

    Layout on disc (Hiryuu no Shou):
        AUTH/MODULES/<name>.ERX   -> <name>.ERX   in the staged root
        AUTH/OVERLAY/<name>.EBN   -> <name>.EBN
        AUTH/BIN/SLPM_651.97      -> SLPM-65197
        INST/RES/{info.sys, ...}  -> res/... (see disc extract)
        Various plaintext data files not in AUTH/ ship as-is.

    NBONLINE.EBN seals stock; the verdict patch is applied only when
    verdict_patch is set (it invalidates the signed hash - see seal_tree).
    """
    os.makedirs(staged, exist_ok=True)
    n_containers = n_copied = n_patched = 0

    def seal_one(disc_path, dst_name, container_name):
        nonlocal n_containers, n_patched
        enc = open(disc_path, "rb").read()
        patcher = _patcher_for(container_name, verdict_patch)
        if patcher is not None:
            df = disc_to_drive.build_drive_form_patched(enc, ata32, four, patcher)
            n_patched += 1
        else:
            df = disc_to_drive.build_drive_form(enc, ata32, four)
        open(os.path.join(staged, dst_name), "wb").write(df)
        n_containers += 1
        # Capture the first sealed container for verify_seal_serve. The disc
        # path has no in-memory neutral (build_drive_form seals disc form
        # directly), so derive the known neutral from the drive form under the
        # SEAL id; the check re-derives it under the SERVED id and compares.
        if capture is not None and not capture:
            try:
                capture["neutral"] = dnasbundle.neutralize(df, ata32, four)
                capture["sealed"] = df
                capture["name"] = container_name
            except Exception:
                pass

    # Modules (.ERX)
    mods = os.path.join(disc_root, DISC_AUTH_MODULES.replace("/", os.sep))
    for fn in sorted(os.listdir(mods)):
        if fn.upper().endswith(".ERX"):
            seal_one(os.path.join(mods, fn), fn, fn)

    # Overlays (.EBN)
    ovl = os.path.join(disc_root, DISC_AUTH_OVERLAY.replace("/", os.sep))
    for fn in sorted(os.listdir(ovl)):
        if fn.upper().endswith(".EBN"):
            seal_one(os.path.join(ovl, fn), fn, fn)

    # Boot ELF
    seal_one(os.path.join(disc_root, DISC_BOOT_ELF.replace("/", os.sep)),
             INSTALLED_BOOT, INSTALLED_BOOT)

    # Plaintext game data comes in two places:
    #   (a) The disc's INST/RES/ directory holds the four browser resource
    #       files that install as `res/*` (lowercase) in the PP root. Other
    #       INST/ files (BGMINST.BIN, OPENING.PSS, SEINST.BIN, KOEILOGO.PSS,
    #       OP2D2.BIN, 2DICON.BIN, EGDIC.PAK) are boot-time installer assets
    #       -- the retail installer plays the intro from disc, it does NOT
    #       copy those to the drive.
    #   (b) The bulk of the game (~200 files) is packed inside
    #       INSTIMG/NOBUON.LWZ. `lwz.py` decompresses it flat into the PP root.
    _INST_RES_TO_LOWER = {
        "INFO.SYS":    "info.sys",
        "JKT_001.PNG": "jkt_001.png",
        "JKT_002.PNG": "jkt_002.png",
        "JKT_CP.PNG":  "jkt_cp.png",
    }
    inst_res = os.path.join(disc_root, "INST", "RES")
    if os.path.isdir(inst_res):
        for fn in sorted(os.listdir(inst_res)):
            up = fn.upper()
            if up not in _INST_RES_TO_LOWER:
                continue        # skip HDDICON.SYS, HDDSYS.CNF, NOBUON.ICO (not
                                # in the installed tree)
            src = os.path.join(inst_res, fn)
            dst = os.path.join(staged, "res", _INST_RES_TO_LOWER[up])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                continue
            open(dst, "wb").write(open(src, "rb").read())
            n_copied += 1

    # NOBUON.LWZ. Layout: entries are cp932 paths like `..\patch\recentver\...`
    # or `PP.SLPM-65197.KOEI.NOBUON\...`. lwz.clean() strips leading .. so the
    # payload lands under staged/ by basename.
    n_lwz = _extract_nobuon_lwz(disc_root, staged)
    n_copied += n_lwz

    return n_containers, n_copied, n_patched


def _extract_nobuon_lwz(disc_root, staged):
    """Extract NOBUON.LWZ from the disc extract's INSTIMG/ subdir OR from a
    sibling ISO (whichever is found), writing each entry into the staged tree.
    Container files (a belt-and-braces sanity check) are refused."""
    src = os.path.join(disc_root, "INSTIMG", "NOBUON.LWZ")
    if not os.path.isfile(src):
        # Fall back: look for the ISO next to disc_root.
        parent = os.path.dirname(os.path.abspath(disc_root)) or "."
        iso_hits = []
        for fn in os.listdir(parent):
            if fn.lower().endswith(".iso"):
                iso_hits.append(os.path.join(parent, fn))
        if len(iso_hits) == 1:
            src = iso_hits[0]
            print("== NOBUON.LWZ not extracted; reading from ISO %s" % src)
        elif len(iso_hits) > 1:
            raise SystemExit("multiple ISO candidates next to --disc; "
                             "keep only the right one, or extract INSTIMG/NOBUON.LWZ")
        else:
            raise SystemExit(
                "NOBUON.LWZ not found under %s/INSTIMG/ and no ISO next to the "
                "extract. Re-extract the disc (including INSTIMG/) or place the "
                "ISO alongside." % disc_root)
    m, base = lwz.open_archive(src)
    n = 0
    for name, _a, _b, q, dlen in lwz.entries(m, base):
        data, _kind = lwz.payload(m, q, dlen)
        # Retail installer flattens NOBUON.LWZ entries to basename at the PP
        # partition root -- the neutral tree confirms this layout. Paths in
        # the archive are Koei's internal build tree, e.g.:
        #   ..\..\Client\xm\ForInstaller\dnasload.elf
        #   ..\..\DataWork\nbconnsv\forMaster\NBCONNSV.BIN
        #   ..\patch\recentver\data\worldmap\cmap0\CMAP001.BIN
        # All install to <root>/<basename>.
        bn = os.path.basename(name.replace("\\", "/"))
        if not bn:
            continue
        dst = os.path.join(staged, bn)
        if os.path.exists(dst):                  # never overwrite a sealed file
            continue
        if dnasbundle.is_container(data):
            continue
        open(dst, "wb").write(data)
        n += 1
    print("== NOBUON.LWZ: extracted %d plaintext files" % n)
    return n


# ---- attr-area auto-generation ------------------------------------------------

def build_attr_from_disc(disc_root, out_path, title0=None, title1=""):
    """Assemble an attr-area.bin from the disc's own icon and a title string.

    Uses playonline.attrarea (in the toolkit helper dir), the same builder
    tools/osdtitle.py uses to rewrite an existing area.
    """
    title0 = title0 or "Nobunaga's Ambition Online"
    # Find playonline package (helper dir is in sys.path by the time we're called)
    from playonline import attrarea
    # Disc icon: prefer INST/RES/NORMAL.ICO -> disc's PS2 icon; else fall back
    # to any *.ICO in INST/RES.
    icon = None
    res = os.path.join(disc_root, "INST", "RES")
    for cand in ("NORMAL.ICO", "normal.ico"):
        p = os.path.join(res, cand)
        if os.path.isfile(p):
            icon = open(p, "rb").read(); break
    if icon is None and os.path.isdir(res):
        for fn in os.listdir(res):
            if fn.upper().endswith(".ICO"):
                icon = open(os.path.join(res, fn), "rb").read(); break
    if icon is None:
        raise SystemExit("no ICO under %s; provide --attr explicitly" % res)
    boot = attrarea.build_boot_block(INSTALLED_BOOT, "1.00",
                                     "pfs:/dnasload.elf")
    # uninstallmes0..2 present (empty): without them stock HDD-OSD shows
    # "Corrupted Data" (PCSX2 HDD-OSD rig, 2026-10-08).
    icon_sys = attrarea.build_icon_sys(title0, title1, uninstall=("", "", ""),
                                       encoding="ascii", spaced=True)
    area = attrarea.build_area(boot, icon_sys, icon)
    open(out_path, "wb").write(area)
    print("== attr auto-built: %s (%d B)  title0=%r" % (out_path, len(area), title0))
    return out_path


# ---- translation folder ------------------------------------------------------

_TRANSLATION_README = (
    "# Nobunaga translation pack drop\n"
    "#\n"
    "# Extract the English translation zip into this folder. The installer\n"
    "# will overlay every file inside that also exists in the game tree,\n"
    "# skipping anything that looks like a DNAS2-sealed container.\n"
    "#\n"
    "# Layout: mirror the game tree, e.g.\n"
    "#   UIMSG.BIN\n"
    "#   WDMMSG.BIN\n"
    "#   STRDAT.BIN\n"
    "#\n"
    "# Or drop the zip's contents in flat if the pack already does.\n"
    "#\n"
    "# This folder is auto-created by nobuinstall.py --disc. Delete it if you\n"
    "# want the installer to skip the translation step.\n"
)

def ensure_translation_dir(disc_root):
    """Create a Translation/ folder next to the disc extract, with a README
    that tells the user where to drop their translation pack.

    Returns the folder path. Non-empty (files other than the README) means the
    user has dropped a pack; the installer overlays it after the seal.
    """
    parent = os.path.dirname(os.path.abspath(disc_root)) or "."
    tdir = os.path.join(parent, "translation")
    if not os.path.isdir(tdir):
        os.makedirs(tdir, exist_ok=True)
        open(os.path.join(tdir, "README.txt"), "w").write(_TRANSLATION_README)
        print("== translation: created %s (drop the English pack here)" % tdir)
    # Detect real content.
    real = [f for f in os.listdir(tdir)
            if not f.upper().startswith("README")
            and os.path.isfile(os.path.join(tdir, f))]
    if not real:
        # Also check subdirs
        real = [d for d in os.listdir(tdir)
                if os.path.isdir(os.path.join(tdir, d))]
    return tdir, bool(real)


def _disc_slpm_sections(disc_root):
    """(ioprp_bytes, elf_bytes) from the player's OWN SLPM_651.97 on the disc.

    The boot loader needs the game's boot ELF (section 2) and IOP reboot image
    (section 1). They come from the player's disc, decrypted on the fly - nothing
    Koei is shipped. disc_dec decrypts each section of the multi-section boot
    container; we pick the ELF section and the romdir (RESET) IOP-image section
    by content, not index, so a layout change can't silently swap them. Each
    section keeps its 16-byte plaintext trailer (tag=True), so the fill equals
    the proven loader's embedded sections byte for byte (782068 / 268993)."""
    import disc_dec
    enc = open(os.path.join(disc_root, DISC_GAME), "rb").read()
    ioprp = elf = None
    for (_i, cur, ds, _v1, _v2, _d9) in disc_dec.sections(enc):
        m = disc_dec._decrypt_section(enc, cur, ds, tag=True)
        if m[:4] == b"\x7fELF":
            elf = m
        elif m[:6] == b"RESET\x00" or b"ROMDIR" in m[:0x200]:
            ioprp = m
    if elf is None or ioprp is None:
        raise SystemExit("could not find the ELF and IOP-image sections in %s "
                         "(ELF %s, IOPRP %s)" % (DISC_GAME, elf is not None, ioprp is not None))
    return ioprp, elf


def fill_loader(disc_root, kelf, hddid, out_path, helper):
    """Fill the pre-signed spoof loader for THIS drive and write it to out_path.

    `kelf` is the shipped, signed-but-unfilled loader (serves no HDD ID, carries
    no game ELF yet). We fill its unsigned slots with the drive's HDD ID and the
    player's own boot ELF + IOP image, via playonline.loader - which does not
    re-sign, so no PS2 keys are needed. The result is a valid dnasload.elf that
    serves this drive's ID and (via the embedded atadpatch) spoofs the psbb
    i.Link the access_flag25 record is keyed to."""
    import tempfile
    ioprp, elf = _disc_slpm_sections(disc_root)
    tmp = tempfile.mkdtemp(prefix="nobuloader-")
    try:
        ep = os.path.join(tmp, "boot.elf"); ip = os.path.join(tmp, "ioprp.img")
        open(ep, "wb").write(elf); open(ip, "wb").write(ioprp)
        env = dict(os.environ)
        if helper:
            env["PYTHONPATH"] = helper + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.run([sys.executable, "-m", "playonline.loader", kelf,
                        "--elf", ep, "--ioprp", ip, "--hddid", hddid,
                        "--argv0", "hdd0:%s:pfs:/SLPM-65197" % PARTITION,
                        "-o", out_path], check=True, env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path


def verify_seal_serve(staged, four, capture):
    """The HDD ID the staged loader SERVES must decrypt the sealed containers,
    or the console halts at 'dnas2 prep = -102' (wrong decrypt key).

    Title-agnostic round-trip (no hardcoded plaintext head): re-neutralize one
    captured sealed container under the SERVED id and compare to its known
    neutral -- dnasbundle.neutralize is the exact inverse of seal, so they match
    only when the served id equals the seal id. No console identity is involved,
    so this offline check is exactly what the console's libdnas2 does. Prints a
    plain line (so it lands in the installer log and on screen) and returns True
    on match; runs for fresh and --update alike. Skips quietly when there is
    nothing to check (no spoof loader, loader still unfilled, or no capture)."""
    loader = os.path.join(staged, "dnasload.elf")
    if not capture or "sealed" not in capture or not os.path.isfile(loader):
        print("== SEAL CHECK: skipped (no captured container / staged loader)")
        return True
    lb = open(loader, "rb").read()
    mg = b"Sony Computer Entertainment Inc."
    blocks, i = set(), lb.find(mg)
    while i >= 0:
        blk = lb[i:i + 512]
        if len(blk) == 512 and blk[0x20:0x24] == b"SCPH" and any(blk[0x40:0x48]):
            blocks.add(blk)
        i = lb.find(mg, i + 1)
    if b"SCEFIXPLACEHOLD" in lb or len(blocks) != 1:
        print("== SEAL CHECK: skipped (loader not filled, or %d served blocks)"
              % len(blocks))
        return True
    blk = blocks.pop()
    served = hashlib.sha1(blk).hexdigest()
    ata = ata_material(blk)
    ata32 = ata[0] if isinstance(ata, tuple) else ata
    try:
        got = dnasbundle.neutralize(capture["sealed"], ata32, four)
    except Exception as e:
        print("== SEAL CHECK: skipped (neutralize failed: %s)" % e)
        return True
    ok = (got == capture["neutral"])
    print("== SEAL CHECK: served HDD ID %s  ->  container (%s) decrypts: %s"
          % (served, capture.get("name", "?"),
             "YES  (seal == serve, OK)" if ok else "NO  <<< MISMATCH"))
    if not ok:
        print("== !! The served id does NOT match the id the containers were sealed to.")
        print("== !! This console will halt at 'dnas2 prep = -102'. The seal and the")
        print("== !! served loader must use the SAME HDD ID. (served sha1 %s)" % served)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("device", help="the target drive (a device pfsshell's `device` gets)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--disc", help="root of the player's disc extract (Hiryuu no Shou, SLPM-65197); "
                     "the recommended path -- seals every container from the disc directly, "
                     "no pre-shipped neutral bundle needed")
    src.add_argument("--bundle", help="legacy: drive-neutral module tree (work/nobu-neutral). "
                     "Retained for the transition; --disc is the supported path.")
    ap.add_argument("--hddid", required=True, help="the 512-byte block the console is SERVED (playonline.hddid)")
    ap.add_argument("--attr", help="attr-area.bin (English title + icon + boot). "
                    "Optional with --disc (auto-built from the disc's own icon).")
    ap.add_argument("--title0", default=None,
                    help="override the browser title used when --attr is auto-built "
                         "(default: \"Nobunaga's Ambition Online\")")
    ap.add_argument("--translation", help="a user-supplied pack of translated plaintext data "
                    "files (UIMSG.BIN/WDMMSG.BIN/STRDAT...) to overlay onto the game tree. "
                    "With --disc, if this is omitted, the installer auto-creates a "
                    "'translation/' folder next to the disc extract for the user to drop "
                    "the zip's contents into; anything found there is applied.")
    ap.add_argument("--no-translation", action="store_true",
                    help="install the game's own Japanese text even when the "
                    "translation/ folder has a pack in it")
    ap.add_argument("--translation-pack", metavar="ZIP",
                    help="a published translation pack (nobunaga.download fetches "
                    "it): UIMSG/WDMMSG/STRDAT are rebuilt in English from the "
                    "disc's own copies and re-listed in CRC32TBL.BIN "
                    "(nobunaga.english). Implies --no-translation's folder skip.")
    ap.add_argument("--loader", help="the pre-signed spoof loader KELF (polbbnexec-inputpatch.kelf) "
                    "to install as pfs:/dnasload.elf in place of the disc's stock dnasload (which "
                    "cannot pass the dead DNAS console binding). With --disc it is FILLED here for "
                    "this drive (HDD ID + the player's own boot ELF/IOP image from the disc; no "
                    "re-signing, so no PS2 keys needed); with --bundle it is copied as-is (expected "
                    "already filled). Without it the stock dnasload is kept and the install will not "
                    "boot past the DNAS check.")
    ap.add_argument("--four", default=FOUR)
    ap.add_argument("--verdict-patch", action="store_true",
                    help="ALSO apply the NBONLINE verdict patch (nobupatch). Off by "
                         "default: the patch changes the module under its RSA-signed "
                         "SHA-1, which cannot be re-signed, so the console's DNAS "
                         "loader rejects the module and the game bails back to the "
                         "browser. The install that reached the game on hardware "
                         "shipped NBONLINE stock; its DNAS skip comes from NBCONNSV "
                         "naming the Koei test host, not from this patch.")
    ap.add_argument("--part-mib", type=int, default=DEFAULT_MIB)
    ap.add_argument("--pfsshell", default="pfsshell")
    ap.add_argument("--hdl", default="hdl_dump")
    ap.add_argument("--helper", default=DEFAULT_HELPER,
                    help="toolkit scripts/helper dir (for the nobunaga.check fit/jail gate)")
    ap.add_argument("--work", default=os.path.join(HERE, "_stage"))
    ap.add_argument("--check-only", action="store_true",
                    help="run only the fit/jail safety gate (and, with --disc, the disc "
                    "version check) and exit; no seal, no write")
    ap.add_argument("--update", action="store_true",
                    help="bring the partition already on the drive up to this stage in "
                    "place: only changed files are rewritten, files only the partition "
                    "has (saves, settings) are kept. With or without --translation, so "
                    "it also applies or removes the English text.")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    # If --disc: verify the version + extract shape BEFORE touching the drive.
    if a.disc:
        verify_disc(a.disc)

    # Safety: refuse before touching the drive if it won't fit the PS2 region.
    precheck(a.device, a.helper, update=a.update)
    if a.check_only:
        print("== check-only: drive is a valid, roomy target (nothing written)")
        return

    # Make sure the helper dir is importable (for playonline.attrarea, polhdd, apa).
    if a.helper and a.helper not in sys.path:
        sys.path.insert(0, a.helper)

    ata32 = ata_material(open(a.hddid, "rb").read())
    four = bytes.fromhex(a.four)
    staged = os.path.join(a.work, PARTITION)

    if os.path.exists(a.work):
        shutil.rmtree(a.work)
    os.makedirs(staged)

    seal_cap = {}
    if a.disc:
        print("== seal %s -> %s (keyed to %s + four %s)"
              % (a.disc, staged, a.hddid, a.four))
        n_c, n_f, n_p = seal_from_disc(a.disc, staged, ata32, four, a.verdict_patch, seal_cap)
        print("   sealed %d containers, copied %d files, verdict-patched %d NBONLINE"
              % (n_c, n_f, n_p))
        # Translation handling: --translation wins; else auto-folder pattern.
        if a.no_translation or a.translation_pack:
            a.translation = None
        elif not a.translation:
            tdir, has = ensure_translation_dir(a.disc)
            a.translation = tdir if has else None
    else:
        print("== seal %s -> %s (keyed to %s + four %s)"
              % (a.bundle, staged, a.hddid, a.four))
        n_c, n_f, n_p = seal_tree(a.bundle, staged, ata32, four, a.verdict_patch, seal_cap)
        print("   sealed %d containers, copied %d files, verdict-patched %d NBONLINE"
              % (n_c, n_f, n_p))

    if a.translation_pack:
        from nobunaga import english
        pack = english.load_pack(a.translation_pack)
        counts = english.translate_text(staged, pack)
        print("== translation: pack %s (%s): %s" % (
            pack["version"], pack["date"],
            ", ".join("%s %d strings" % (n, c) for n, c in sorted(counts.items()))))
    elif a.translation:
        n_t = overlay_translation(staged, a.translation)
        print("== translation: overlaid %d data file(s) from %s" % (n_t, a.translation))

    # After the translation, whose pack may carry its own CRC32TBL.BIN.
    if a.disc:
        connect_to_test_host(staged)

    # Replace the disc's stock dnasload with the spoof loader, if one was given.
    # The stock dnasload cannot pass the (dead) DNAS console binding; the spoof
    # loader serves the drive HDD ID and answers sceCdRI with the psbb i.Link the
    # access_flag25 record is keyed to. The toolkit fills it per drive and hands
    # it in here; nobuinstall just stages it as dnasload.elf.
    if a.loader:
        if not os.path.isfile(a.loader):
            raise SystemExit("--loader %s not found" % a.loader)
        dst = os.path.join(staged, "dnasload.elf")
        had = os.path.exists(dst)
        if a.disc:
            fill_loader(a.disc, a.loader, a.hddid, dst, a.helper)
            print("== loader: filled %s for this drive and installed as dnasload.elf (%s stock)"
                  % (os.path.basename(a.loader), "replaced" if had else "no"))
        else:
            shutil.copyfile(a.loader, dst)
            print("== loader: installed %s as dnasload.elf (%s stock; copied as-is)"
                  % (a.loader, "replaced" if had else "no"))
    else:
        print("== loader: NONE given; keeping the disc's stock dnasload.elf "
              "(install will NOT boot past the DNAS console check without --loader)")

    # Guard + diagnostic: the served id must decrypt the just-sealed containers,
    # or the console halts at 'dnas2 prep = -102'. Runs before the write for both
    # fresh and --update; printed so it lands in the installer log (and on screen).
    verify_seal_serve(staged, four, seal_cap)

    # Attr area: --attr wins; else auto-build from disc icon (needs --disc).
    attr_path = a.attr
    if not attr_path:
        if not a.disc:
            raise SystemExit("--attr is required with --bundle (auto-build needs --disc)")
        attr_path = build_attr_from_disc(a.disc,
                                         os.path.join(a.work, "attr-area.bin"),
                                         title0=a.title0)

    if a.update:
        return update_in_place(a, staged, attr_path)

    script = pfsshell_script(a.device, staged, a.part_mib)
    print("== pfsshell script (%d commands):" % (script.count("\n")))
    print("\n".join("   " + ln for ln in script.splitlines()[:6]) + "\n   ... (%d put lines)"
          % sum(1 for ln in script.splitlines() if ln.startswith("put")))

    if not a.write:
        print("== attr: would write %s at %s + 0x1000 (dry run, pass --write to apply)"
              % (attr_path, PARTITION))
        return

    print("== mkpart + put via pfsshell")
    subprocess.run([a.pfsshell], input=script, text=True, check=True)
    lba = part_lba(a.helper, a.device)
    print("== attr: writing %s at LBA %d + 0x1000" % (attr_path, lba))
    write_attr(a.device, lba, attr_path)
    rpwd, fpwd = write_passwords(a.device, lba, a.helper)
    print("== passwords: set NOBUONR/NOBUONF on %s (rpwd %s, fpwd %s)"
          % (PARTITION, rpwd.hex(), fpwd.hex()))
    print("== done: Nobunaga installed to %s on %s" % (PARTITION, a.device))


if __name__ == "__main__":
    main()
