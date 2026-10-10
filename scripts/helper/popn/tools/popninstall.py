"""Install pop'n Puzzle Dama Online onto a live PSBBN drive from a disc extract.

Mirrors the shape of Nobunaga's nobuinstall.py, minus the neutral-bundle step
(we go straight from disc bytes to drive form). Order of operations:

  1. seal   Every disc DNAS2 container (.ENC / MAIN.BIN) is decrypted from the
            disc and re-sealed to the TARGET drive's identity (its served
            HDD ID + the __net four = 00001301). This produces the drive-form
            files the retail installer would have written:
              MAIN.BIN -> BLJA-00010
              MODULES/<name>.ENC -> MODULES/<name>.IRX
            Plaintext data files (IMAGE.DAT, ICON.SYS, res/*, LICENSE, etc.)
            copy verbatim. Reuses work/dnas/disc_to_drive.build_drive_form,
            proven byte-structurally identical to the retail install on every
            fixed record.
  1b. loader (optional, --loader) Replace the stock dnasload.elf copied by the
            seal with the pre-signed polbbnexec loader, FILLED for this drive:
            the drive's HDD ID + the player's own patched boot ELF and
            DNAS280.IMG IOPRP, both carved from the disc's MAIN.BIN
            (patch_boot_elf). No re-signing, so no PS2 keys on the player's
            machine. Required for a disc-less boot; without it the install
            stays on stock dnasload and stops at the DNAS console check.
  1c. english (optional, --translate) The boot ELF gets the English strings
            (pntext elf-b) + patch_boot_elf ENGLISH_PATCHES, and IMAGE.DAT /
            IMAGE1.DAT / IMAGE3.DAT are rebuilt with English textures from the disc's
            originals (translation/apply_textures_nat.py; --no-textures skips).
  2. mkpart Create PP.BLJA-00010 (128 MiB) as PFS via pfsshell, password
            POPNPUZZ for both fpwd and rpwd (SLPM_624.64 opens it as
            `hdd0:PP.BLJA-00010,POPNPUZZ,POPNPUZZ`, see FACTS.md).
  3. put    Write the staged tree into the volume with pfsshell.
  4. attr   Write the browser's attribute area at PP main +0x1000: the boot
            block (BOOT2 = pfs:/dnasload.elf + DNASBOOT2 = pfs:/BLJA-00010),
            icon.sys and the disc's own 3D icon. Built from the disc unless
            --attr names a prebuilt area. HDD-OSD and HOSDMenu list a title
            from this area only (PSBBN reads res/info.sys), so without it they
            show "Corrupted Data". English title with --translate, else the
            disc's Japanese one.
  5. passwords  Set fpwd/rpwd on the APA header (PSBBN's pfsshell mkpart leaves
                them zero; the game refuses to mount if they don't match).

  swap  (--loader-swap, existing install) refills pfs:/dnasload.elf only, after
        the served-vs-sealed guard: a sealed container on the drive must
        decrypt under the --hddid the loader will serve, or it refuses (exit 3;
        --reseal re-seals the containers to it, --recover-hddid lifts the ID
        the drive's own loader serves, saved only if the containers open with
        it). --check-seal runs the guard alone.

Everything runs as a dry-run (prints the plan) unless --write is passed.
Never edits or touches the PlayOnline package; reads it only if --helper is
supplied to reuse the fit/jail safety gate.

    python3 popninstall.py <device> --disc <disc-root> --hddid <file> \
        [--loader polbbnexec-popn.kelf] [--translate elf.en.tsv [--no-textures]] \
        [--attr <attr-area.bin>] [--four 00001301] [--part-mib 128] \
        [--pfsshell PFSSHELL] [--helper <toolkit>/scripts/helper] \
        [--work DIR] [--write]

The `disc-root` argument points to the extracted disc tree; it must contain
MAIN.BIN, MODULES/<name>.ENC (15 files), DNASLOAD.ELF, IMAGE.DAT / IMAGE1.DAT /
IMAGE3.DAT / SYS_NET.ICO / ICON.SYS, LICENSE/LIBEENET.TXT, BN_RES/{INFO.SYS,
JKT_001.PNG, JKT_CP.PNG, NOTICE.PNG}. It becomes `res/` on the install side.
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "nobunaga", "tools"))
import disc_to_drive                              # noqa: E402
import netcnf_install                             # noqa: E402  (shared network-config fix)
from dnasdec import ata_material                   # noqa: E402

SECTOR = 512
ATTR_OFF = 0x1000
PARTITION = "PP.BLJA-00010"
DEFAULT_MIB = 128
FOUR = "00001301"
PASSWORD = b"POPNPUZZ"          # both fpwd and rpwd for pop'n (FACTS.md)

# The 15 disc .ENC files that seal into MODULES/*.IRX.
MODULE_NAMES = [
    "BBNETCNF", "EENETCTL", "ENT_DEVM", "ENT_SMAP", "LIBSD",
    "MODHSYN",  "MODMIDI",  "NETCNF",   "NETCNFIF", "PADMAN",
    "SDDRV",    "SDVSTR",   "SIO2MAN",  "USBD",     "USBKB",
]

# Plaintext files copied verbatim from disc -> install (src -> dst).
# Sizes shift slightly vs the IA install (IA is sector-padded) but the disc
# forms are what SLPM_624.64 references; the game reads by size from disc,
# not by fixed offset from install.
PLAIN_COPIES = [
    ("DNASLOAD.ELF",           "dnasload.elf"),
    ("ICON.SYS",               "ICON.SYS"),
    ("IMAGE.DAT",              "IMAGE.DAT"),
    ("IMAGE1.DAT",             "IMAGE1.DAT"),
    ("IMAGE3.DAT",             "IMAGE3.DAT"),
    ("SYS_NET.ICO",            "SYS_NET.ICO"),
    ("LICENSE/LIBEENET.TXT",   "LICENSE/LIBEENET.TXT"),
    ("BN_RES/INFO.SYS",        "res/info.sys"),
    ("BN_RES/JKT_001.PNG",     "res/jkt_001.png"),
    ("BN_RES/JKT_CP.PNG",      "res/jkt_cp.png"),
    ("BN_RES/NOTICE.PNG",      "res/notice.png"),
]

def precheck(device, helper_dir):
    """Reuse the PSBBN fit/jail check if the helper dir is provided. Prefers
    popn.check (pop'n-specific: PP.BLJA-00010 + 128 MiB) and falls back to
    nobunaga.check (roomy generic PSBBN inspection). Returns info dict or None."""
    if not helper_dir:
        print("== precheck: skipped (no --helper); the caller is responsible "
              "for verifying the target drive")
        return None
    if helper_dir not in sys.path:
        sys.path.insert(0, helper_dir)
    check = None
    for pkg in ("popn", "nobunaga"):
        try:
            check = __import__("%s.check" % pkg, fromlist=["check"])
            break
        except Exception:
            continue
    if check is None:
        raise SystemExit("cannot import popn.check or nobunaga.check from %r"
                         % helper_dir)
    info = check.inspect(device)
    print("== precheck: PS2 system %s, jailed %s, free %d MiB (largest %d), "
          "need %d MiB" % (info["system"], info["jailed"], info["free_mib"],
                           info["largest_mib"], DEFAULT_MIB))
    if info.get("others"):
        print("   other title partitions present (untouched): %s"
              % ", ".join(info["others"]))
    if not info["system"]:
        raise SystemExit("not a PS2/PSBBN drive (missing __system/__sysconf/__common)")
    if PARTITION in info.get("installed", []) or PARTITION in info.get("others", []):
        raise SystemExit("%s already exists on this drive; refusing" % PARTITION)
    if info["largest_mib"] < DEFAULT_MIB:
        raise SystemExit("largest free hole %d MiB < %d MiB required for %s"
                         % (info["largest_mib"], DEFAULT_MIB, PARTITION))
    return info

def seal_tree(disc_root, staged, ata32, four):
    """Seal disc containers to drive form + copy plaintext data files.

    disc_root: the extracted disc tree (must contain MAIN.BIN, MODULES/*.ENC,
    DNASLOAD.ELF, IMAGE*.DAT, ICON.SYS, SYS_NET.ICO, LICENSE/, BN_RES/).
    staged:    output dir; the future contents of PP.BLJA-00010."""
    os.makedirs(staged, exist_ok=True)
    n_sealed = 0

    # MAIN.BIN -> BLJA-00010
    main_p = os.path.join(disc_root, "MAIN.BIN")
    enc = open(main_p, "rb").read()
    drive_form = disc_to_drive.build_drive_form(enc, ata32, four)
    open(os.path.join(staged, "BLJA-00010"), "wb").write(drive_form)
    n_sealed += 1

    # MODULES/*.ENC -> MODULES/*.IRX
    os.makedirs(os.path.join(staged, "MODULES"), exist_ok=True)
    for m in MODULE_NAMES:
        src = os.path.join(disc_root, "MODULES", m + ".ENC")
        dst = os.path.join(staged, "MODULES", m + ".IRX")
        enc = open(src, "rb").read()
        drive_form = disc_to_drive.build_drive_form(enc, ata32, four)
        open(dst, "wb").write(drive_form)
        n_sealed += 1

    n_copied = 0
    for src_rel, dst_rel in PLAIN_COPIES:
        src = os.path.join(disc_root, src_rel.replace("/", os.sep))
        dst = os.path.join(staged, dst_rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        n_copied += 1

    return n_sealed, n_copied

def _quote(name):
    return '"%s"' % name if " " in name else name

def emit_dir(out, host_dir):
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
    if helper_dir and helper_dir not in sys.path:
        sys.path.insert(0, helper_dir)
    from playonline import apa
    lba, _sectors = apa.find_partition(device, PARTITION)
    return lba

# The browser names, as in popn/retitle.py (the Japanese pair is the disc's
# own PAT_EXT/ICON.SYS text). retitle can switch them later in place.
ATTR_TITLES = {
    "english": ("pop'n Puzzle Dama Online", ""),
    "japanese": ("pop'n対戦ぱずるだま", "ONLINE"),
}
# The boot block the console-proven drive carries (hwaudit 2026-10-08): the
# loader, the DNAS container, retail-style VER/VMODE/HDDUNITPOWER, CRLF.
ATTR_PRODUCT = "BLJA-00010"
ATTR_VER = "1.00"
ATTR_MAX = 0x400000 - ATTR_OFF      # the PFS superblock starts at +0x400000


def _attrarea(helper_dir):
    if helper_dir and helper_dir not in sys.path:
        sys.path.insert(0, helper_dir)
    from playonline import attrarea
    return attrarea


def build_attr(disc_root, helper_dir, language="english"):
    """The attribute area for PP.BLJA-00010, from the disc's own icon.

    Same shape as the area on the console-proven drive (written by
    popnattr.py): slot 0 boot block, slot 1 PS2X icon.sys (UTF-8, `key = v`),
    slot 2 the disc's NORMAL.ICO at 0x600, slot 3 pointing at slot 2."""
    attrarea = _attrarea(helper_dir)
    icon = None
    for rel in (("PAT_EXT", "NORMAL.ICO"), ("ICON", "NORMAL.ICO")):
        p = os.path.join(disc_root, *rel)
        if os.path.isfile(p):
            icon = open(p, "rb").read()
            break
    if icon is None:
        raise SystemExit("no PAT_EXT/NORMAL.ICO or ICON/NORMAL.ICO under %s; "
                         "pass --attr" % disc_root)
    if len(icon) < 0x100 or icon[:4] != bytes.fromhex("00000100"):
        raise SystemExit("%s does not look like a PS2 3D icon" % p)
    boot = attrarea.build_boot_block(ATTR_PRODUCT, ATTR_VER, "pfs:/dnasload.elf")
    title0, title1 = ATTR_TITLES[language]
    # uninstallmes0..2 present (empty): without them stock HDD-OSD shows
    # "Corrupted Data" (PCSX2 HDD-OSD rig, 2026-10-08).
    icon_sys = attrarea.build_icon_sys(title0, title1, uninstall=("", "", ""),
                                       encoding="utf-8", spaced=True)
    return attrarea.build_area(boot, icon_sys, icon)


def check_attr(area):
    if area[:9] != b"PS2ICON3D":
        raise SystemExit("attr area has no PS2ICON3D magic")
    if len(area) > ATTR_MAX:
        raise SystemExit("attr area is %d B; it would reach the PFS superblock"
                         % len(area))


def attr_present(device, lba):
    with open(device, "rb") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        return f.read(9) == b"PS2ICON3D"


def write_attr(device, lba, area):
    """Write the area at main +0x1000 and read it back."""
    if isinstance(area, str):
        area = open(area, "rb").read()
    check_attr(area)
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        f.write(area)
        f.flush()
        f.seek(lba * SECTOR + ATTR_OFF)
        if f.read(len(area)) != area:
            raise SystemExit("attr read-back does not match what was written")
    return len(area)


def attr_area_for(a):
    """--attr if given, else built from the disc in the install's language."""
    if a.attr:
        return open(a.attr, "rb").read(), "from %s" % a.attr
    lang = "english" if a.translate else "japanese"
    return build_attr(a.disc, _helper_dir(a.helper), lang), "built from the disc (%s title)" % lang

def write_passwords(device, lba, helper_dir):
    """POPNPUZZ for both fpwd and rpwd. pfsshell mkpart leaves them zero;
    SLPM_624.64 mounts `hdd0:PP.BLJA-00010,POPNPUZZ,POPNPUZZ` and hits -EACCES
    if the header slots don't match."""
    if helper_dir and helper_dir not in sys.path:
        sys.path.insert(0, helper_dir)
    from playonline.lib.polhdd import apa_password, checksum
    pwd = apa_password(PARTITION, PASSWORD)
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR)
        hdr = bytearray(f.read(1024))
        if hdr[0x10:0x10 + len(PARTITION)] != PARTITION.encode():
            raise SystemExit("LBA %d is not %s; refusing to write passwords"
                             % (lba, PARTITION))
        hdr[0x30:0x38] = pwd    # rpwd
        hdr[0x38:0x40] = pwd    # fpwd
        struct.pack_into("<I", hdr, 0, 0)
        struct.pack_into("<I", hdr, 0, checksum(bytes(hdr)))
        f.seek(lba * SECTOR)
        f.write(bytes(hdr))
    return pwd

def fill_loader(disc_root, kelf, hddid, out_path, helper, translate_tsv=None):
    """Fill the pre-signed spoof loader for THIS drive and write it to out_path,
    then return it. Mirrors nobuinstall.fill_loader.

    `kelf` is the shipped, signed-but-unfilled polbbnexec loader (serves no HDD
    ID, carries no game ELF yet). We fill its unsigned slots via
    playonline.loader -- which does NOT re-sign, so no PS2 keys are needed on
    the player's machine. The two code inputs are carved from the player's own
    disc MAIN.BIN (nothing Konami/Sony is shipped):
      --elf    the EXEC game ELF with the 3 disc-less-boot patches applied
               (patch_boot_elf; DNAS startup + in-game auth skips + the login
               disc-ownership skip)
      --ioprp  DNAS280.IMG, the version-"2800" IOP reboot image the game
               demands (Nobunaga's 2710 image loops the init forever)
    The result serves this drive's HDD ID (ps2atad has no MagicGate check) and,
    via the embedded atadpatch, spoofs the sceCdRI i.Link the DNAS records are
    keyed to. It installs as pfs:/dnasload.elf in place of the stock copy."""
    if not os.path.isfile(kelf):
        raise SystemExit("--loader %s not found" % kelf)
    if helper and helper not in sys.path:
        sys.path.insert(0, helper)
    import patch_boot_elf
    main_bin = open(os.path.join(disc_root, "MAIN.BIN"), "rb").read()
    # English path: also the English-release behaviour patches (English keyboard
    # by default, ...), patch_boot_elf.ENGLISH_PATCHES
    ioprp, elf = patch_boot_elf.boot_sections_from_main(main_bin, english=bool(translate_tsv))
    tmp = tempfile.mkdtemp(prefix="popnloader-")
    try:
        ep = os.path.join(tmp, "boot.elf"); ip = os.path.join(tmp, "ioprp.img")
        open(ep, "wb").write(elf); open(ip, "wb").write(ioprp)
        # Optional English translation: rebuild the boot-patched ELF with the
        # translated strings (the text lives in the ELF's rodata; pntext.py elf-b
        # fits each English string into its cp932 slot). The loader then embeds
        # the English ELF. The menu images are a separate step (stage_images).
        if translate_tsv:
            ep_en = os.path.join(tmp, "boot.en.elf")
            tenv = dict(os.environ); tenv["PYTHONUTF8"] = "1"
            pntext_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pntext.py")
            subprocess.run([sys.executable, pntext_py, "elf-b", ep, translate_tsv, ep_en],
                           check=True, env=tenv)
            ep = ep_en
            print("   translation: applied %s -> English boot ELF" % os.path.basename(translate_tsv))
        env = dict(os.environ)
        if helper:
            env["PYTHONPATH"] = helper + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.run([sys.executable, "-m", "playonline.loader", kelf,
                        "--elf", ep, "--ioprp", ip, "--hddid", hddid,
                        "--argv0", "hdd0:%s:pfs:/BLJA-00010" % PARTITION,
                        "-o", out_path], check=True, env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path

# The texture-bearing files the English image pass rewrites (every file that has a
# screen in translation/screens/*.py or apply_textures_nat's built-ins). All three
# are in PLAIN_COPIES, so the stock ones are always staged first.
IMAGE_FILES = ("IMAGE.DAT", "IMAGE1.DAT", "IMAGE3.DAT")
# IMAGE1.DAT opens with a certificate area (a PEM cert at +0x10) the game checks;
# it must stay byte-exact. IMAGE3.DAT has no certificate, only per-block headers +
# LZSS layout tables before each texture (0x0-0x130, 0x40000-0x40130). Both, and
# every other byte outside the screens' texture slots, are covered by the
# outside-slots check in images_en.
IMAGE1_CERT_LEN = 0x8f0


def _screen_slots(apply_py):
    """{file: [(fo, slot_end), ...]} for every screen apply_textures_nat builds."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("popn_apply_textures_nat", apply_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = {}
    for s in mod.build_screens():
        out.setdefault(s.get("file", "IMAGE.DAT"), []).append((s["fo"], s["slot_end"]))
    return out


def texture_deps():
    """(ok, missing, have_cv2). The image pass needs Pillow + numpy. OpenCV (cv2)
    is optional to run but the shipped textures are built WITH it (it drives the
    inpaint and the glyph-mask top-hat), so without it the result differs from the
    reference build and inpainted panels come out flatter."""
    missing = []
    for mod in ("PIL", "numpy"):
        try:
            __import__(mod)
        except Exception:
            missing.append({"PIL": "Pillow"}.get(mod, mod))
    try:
        import cv2  # noqa: F401
        have_cv2 = True
    except Exception:
        have_cv2 = False
    return not missing, missing, have_cv2


def _apply_textures_script():
    """translation/apply_textures_nat.py, next to tools/ (the popn repo layout and
    the toolkit's bundled helper/popn/ both keep it there). It loads its screens
    from translation/screens/*.py relative to itself."""
    toolsdir = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(toolsdir, os.pardir, "translation",
                                      "apply_textures_nat.py"))
    if not os.path.isfile(p):
        raise SystemExit("texture translation unavailable: %s not found (the "
                         "translation/ folder with apply_textures_nat.py and "
                         "screens/ must sit beside tools/)" % p)
    return p


def images_en(disc_root, out_dir):
    """Render the English textures onto the disc's IMAGE.DAT, IMAGE1.DAT and IMAGE3.DAT and
    write the patched copies to out_dir/<name>. Returns the list of names written.

    Runs translation/apply_textures_nat.py in its directory form (disc dir -> out
    dir), i.e. apply_textures_nat.build() over every screen, so in the same
    Python environment the bytes are the same as the popn repo's own build of
    the same disc (across OSes OpenCV's inpaint differs slightly; see
    textures_build.py). It is the natural,
    atlas-safe editor: Japanese glyphs are masked and the panel background is
    inpainted behind them, and pntexnat asserts nothing changes outside each
    element, so a shared sprite sheet is never disturbed. Every edited texture is
    recompressed into its own slot, so file sizes do not change.

    Slow (several minutes; one sheet only fits with an exact-cost optimal parse),
    so the per-screen lines are streamed as they finish and a heartbeat is
    printed while a long screen is still working. Needs Pillow + numpy (cv2
    strongly recommended, see texture_deps). The text face is the bundled Comic
    Neue Bold (tools/ComicNeue-Bold.ttf, SIL OFL) unless POPN_TEX_FONT overrides."""
    import threading
    import time
    toolsdir = os.path.dirname(os.path.abspath(__file__))
    apply_py = _apply_textures_script()
    for name in IMAGE_FILES:
        if not os.path.isfile(os.path.join(disc_root, name)):
            raise SystemExit("%s not found in the disc at %s" % (name, disc_root))
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = toolsdir + os.pathsep + env.get("PYTHONPATH", "")
    font = os.path.join(toolsdir, "ComicNeue-Bold.ttf")
    if os.path.isfile(font):
        env.setdefault("POPN_TEX_FONT", font)
    # textures_build.py pins Pillow's text layout to BASIC (the Linux wheels
    # default to RAQM, which shifts glyphs and changes every texture).
    proc = subprocess.Popen([sys.executable, "-u",
                             os.path.join(toolsdir, "textures_build.py"),
                             apply_py, disc_root, out_dir],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env)
    state = {"last": time.time(), "n": 0}

    def pump():
        for line in proc.stdout:
            line = line.rstrip("\n")
            state["last"] = time.time()
            if line.rstrip().endswith(" OK"):
                state["n"] += 1
                print("   [%3d] %s" % (state["n"], line), flush=True)
            else:
                print("         %s" % line, flush=True)

    th = threading.Thread(target=pump, daemon=True)
    th.start()
    t0 = time.time()
    while proc.poll() is None:
        time.sleep(1)
        if time.time() - state["last"] >= 30:
            print("         ... still working (%d screens done, %d s elapsed)"
                  % (state["n"], time.time() - t0), flush=True)
            state["last"] = time.time()
    th.join()
    if proc.returncode != 0:
        raise SystemExit("texture build failed (exit %d); see the lines above"
                         % proc.returncode)
    written = []
    slots = _screen_slots(apply_py)
    for name in IMAGE_FILES:
        src_p = os.path.join(disc_root, name)
        out_p = os.path.join(out_dir, name)
        if not os.path.isfile(out_p):
            raise SystemExit("texture build did not produce %s" % name)
        a = open(src_p, "rb").read()
        b = open(out_p, "rb").read()
        if len(a) != len(b):
            raise SystemExit("%s: built size %d != disc size %d; refusing to install it"
                             % (name, len(b), len(a)))
        if name == "IMAGE1.DAT" and a[:IMAGE1_CERT_LEN] != b[:IMAGE1_CERT_LEN]:
            raise SystemExit("IMAGE1.DAT: the certificate area (first %#x bytes) "
                             "changed; refusing to install it" % IMAGE1_CERT_LEN)
        # Only the screens' own texture slots may change: headers, layout tables,
        # the IMAGE1 certificate and every untouched texture stay byte-exact.
        pos = 0
        for fo, end in sorted(slots.get(name, [])) + [(len(a), len(a))]:
            if a[pos:fo] != b[pos:fo]:
                off = pos + next(i for i in range(fo - pos) if a[pos + i] != b[pos + i])
                raise SystemExit("%s: byte %#x outside every texture slot changed; "
                                 "refusing to install it" % (name, off))
            pos = max(pos, end)
        written.append(name)
    print("   %d screens in %d s" % (state["n"], time.time() - t0), flush=True)
    return written


def textures_wanted(a):
    """English textures are ON whenever the translation is (--translate), unless
    --no-textures. --translate-images (old flag) forces them on by itself."""
    return bool((a.translate or a.translate_images) and not a.no_textures)


def stage_images(a, dest_dir):
    """Put the IMAGE*.DAT the install should carry into dest_dir: the English
    builds when textures are wanted and the deps are there, else the disc's stock
    copies. Returns (names, english)."""
    if textures_wanted(a):
        ok, missing, have_cv2 = texture_deps()
        if not ok:
            print("== translation: WARNING: English images SKIPPED -- missing Python "
                  "package(s): %s (pip install Pillow numpy opencv-python-headless). "
                  "The menus keep their Japanese images; text is still English."
                  % ", ".join(missing), flush=True)
        else:
            if not have_cv2:
                print("== translation: note: OpenCV (cv2) not installed; images are "
                      "built without it (flatter inpaint, not the reference bytes). "
                      "pip install opencv-python-headless for the shipped result.",
                      flush=True)
            print("== translation: building the English IMAGE.DAT + IMAGE1.DAT + IMAGE3.DAT from "
                  "the disc (takes several minutes)", flush=True)
            tex = os.path.join(a.work, "_textures")
            names = images_en(a.disc, tex)
            for n in names:
                shutil.copyfile(os.path.join(tex, n), os.path.join(dest_dir, n))
            shutil.rmtree(tex, ignore_errors=True)
            print("== translation: English images ready (%s)" % ", ".join(names),
                  flush=True)
            return names, True
    names = []
    for n in IMAGE_FILES:
        src = os.path.join(a.disc, n)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(dest_dir, n))
            names.append(n)
    return names, False


# ---- served-vs-sealed guard ---------------------------------------------------
#
# The loader serves ONE HDD ID; the game decrypts its sealed containers
# (MODULES/*.IRX, BLJA-00010) with that ID + the four, and checks the drive
# tail tag. A loader that serves a different ID than the containers were sealed
# to boots to a black screen (plan gate 6; the 2026-10-07 regression: a
# --loader-swap served the per-drive mint over psbb-sealed containers). So
# before any loader is written into an existing install, one sealed container
# is read back from the drive and must decrypt under the ID about to be served.

SEAL_EXIT = 3                    # exit status of a served-vs-sealed refusal
SEAL_PROBE = "MODULES/SIO2MAN.IRX"   # fully decrypted (small)
# Every sealed file the install writes; each gets the cheap tail-tag check.
SEALED_FILES = ["BLJA-00010"] + ["MODULES/%s.IRX" % m for m in MODULE_NAMES]


def _helper_dir(a_helper):
    h = a_helper or os.path.dirname(os.path.dirname(HERE))   # helper/popn/tools -> helper
    if h not in sys.path:
        sys.path.insert(0, h)
    return h


def _apa_subs(f, main_lba):
    """{sub index: start} of the APA sub-partitions of the main at main_lba."""
    subs, seen, lba = {}, set(), 0
    while lba not in seen:
        seen.add(lba)
        f.seek(lba * SECTOR)
        hdr = f.read(1024)
        if len(hdr) < 1024 or struct.unpack_from("<I", hdr, 4)[0] != 0x00415041:
            break
        nxt = struct.unpack_from("<I", hdr, 8)[0]
        start = struct.unpack_from("<I", hdr, 0x40)[0]
        main, number = struct.unpack_from("<II", hdr, 0x58)
        if main == main_lba and number:
            subs[number] = start
        if not nxt:
            break
        lba = nxt
    return subs


def read_installed(device, names, helper=None):
    """{name: bytes or None} for files of the EXISTING PP.BLJA-00010, read with
    the toolkit's pure-Python PFS reader. Read-only (the device is opened 'rb');
    works on a drive or on a raw .img the same way."""
    _helper_dir(helper)
    from playonline import apa
    from playonline.lib import polpfsread, polfill
    lba, sectors = apa.find_partition(device, PARTITION)
    out = {}
    with open(device, "rb") as f:
        part, root = polpfsread.mount(f, lba, sectors, _apa_subs(f, lba))
        if part is None:
            raise SystemExit("cannot read the PFS volume of %s on %s" % (PARTITION, device))
        files = []
        polpfsread.walk(part, root, out=files)
        index = {p.lstrip("/").upper(): ino for p, ino in files}
        for n in names:
            ino = index.get(n.upper())
            out[n] = polfill.read_content(part, ino) if ino else None
    return out


def seal_matches(blob, hddid_blob, four, deep=False):
    """(ok, why) for one sealed drive-form container under (hddid, four):
    every section's outer plaintext ends in the drive tail tag; with deep=True
    section 0 also decrypts fully (dnasdec) to an ELF module. (The signed SHA-1
    is not judged: dnasdec's model of it does not hold for disc_to_drive output,
    which the console accepts.)"""
    import dnas2, dnaskey, rc6, dnasdec
    keys = dnas2.keys()
    ata32 = ata_material(hddid_blob)
    r7 = dnas2.unrecord(blob[0:128], keys[7][1], keys[7][2])
    if r7 is None or r7[1] != b"96011a8e95fd1ffc":
        return False, "not a DNAS2 drive-form container"
    k1 = dnaskey.derive_k1(ata32, four)
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200
    first, n = sec, 0
    while sec + 0x300 < len(blob):
        sess = dnas2.unrecord(blob[sec + 0x180:sec + 0x200], keys[11][1], keys[11][2])
        if sess is None:
            return False, "no session record at %#x" % (sec + 0x180)
        h1 = rc6.cbc(blob[sec + 0x280:sec + 0x300], sess[0][:16], sess[0][16:32], True)
        if h1[10:26] != b"a5713c8bdbe8d420":
            return False, "H1 tag miss at %#x" % sec
        sizes = None
        for st in (h1[4], 3):
            if st in keys:
                sizes = dnas2.unrecord(blob[sec + 0x100:sec + 0x180], keys[st][1], keys[st][2])
                if sizes:
                    break
        if sizes is None:
            return False, "no sizes record at %#x" % (sec + 0x100)
        v1 = struct.unpack("<I", sizes[0][:4])[0]
        extent = sizes[0][10] * 16 + v1 + ((0x10 - (v1 & 0xF)) & 0xF) + 0x10
        blk = rc6.cbc(blob[sec + 0x80:sec + 0x100], k1[0:16], k1[16:32], True)
        k2 = dnaskey.derive_k2(blk, ata32, four)
        end = sec + 0x300 + extent
        tail = rc6.cbc(blob[end - 32:end], k2[0:16], k2[16:32], True)[16:32]
        if tail != disc_to_drive.DRIVE_TAIL_TAG:
            return False, "section %d does not decrypt to the drive tail tag" % n
        n += 1
        nxt = end + 0x80
        if nxt + 0x300 >= len(blob):
            break
        sec = nxt
    if not n:
        return False, "no sections"
    if deep:
        try:
            mod, _tag, _nxt, info = dnasdec.section_module(blob, first, ata32, four, k1, keys)
        except Exception as e:
            return False, "section 0 does not decrypt (%s)" % e
        if mod[:4] != b"\x7fELF":
            return False, "section 0 is not an ELF"
    return True, "%d section(s), tail tag ok%s" % (n, ", section 0 decrypts to an ELF" if deep else "")


def _sha8(b):
    import hashlib
    return hashlib.sha1(b).hexdigest()[:8]


def check_seal(device, hddid_blob, four, helper=None, all_files=True):
    """{ok, probe, bad, why, drive_loader_id, drive_loader_ok} for the ID about
    to be served against the containers already on the drive. Read-only."""
    names = SEALED_FILES if all_files else [SEAL_PROBE]
    got = read_installed(device, names + ["dnasload.elf"], helper)
    res = {"served": _sha8(hddid_blob), "bad": [], "probe": SEAL_PROBE}
    probe = got.get(SEAL_PROBE)
    if probe is None:
        raise SystemExit("pfs:/%s is missing from %s on %s; cannot check what the "
                         "install is sealed to" % (SEAL_PROBE, PARTITION, device))
    ok, why = seal_matches(probe, hddid_blob, four, deep=True)
    res["why"] = why
    if not ok:
        res["bad"].append(SEAL_PROBE)
    for n in names:
        if n == SEAL_PROBE or got.get(n) is None:
            continue
        if not seal_matches(got[n], hddid_blob, four)[0]:
            res["bad"].append(n)
    res["ok"] = not res["bad"]
    # What the loader on the drive serves now, and whether the containers are
    # sealed to THAT: the --recover-hddid answer.
    res["drive_loader_id"] = res["drive_loader_ok"] = None
    cur = got.get("dnasload.elf")
    if cur:
        _helper_dir(helper)
        from playonline import loader as pol_loader
        try:
            info = pol_loader.read(cur)
            if info.get("has_hddid"):
                blk = info["hddid"]
                res["drive_loader_id"] = _sha8(blk)
                res["drive_loader_block"] = blk
                res["drive_loader_ok"] = seal_matches(probe, blk, four, deep=True)[0]
        except Exception:
            pass
    return res


def report_seal(res, hddid_path):
    if res["ok"]:
        print("== seal guard: the containers on the drive are sealed to the served "
              "HDD ID %s (%s: %s)" % (res["served"], res["probe"], res["why"]))
        return
    print("== seal guard: MISMATCH -- the loader would serve HDD ID %s (%s), but the "
          "containers on the drive are NOT sealed to it" % (res["served"], hddid_path))
    print("   %s: %s; %d sealed file(s) fail: %s"
          % (res["probe"], res["why"], len(res["bad"]), ", ".join(res["bad"])))
    print("   (the game would decrypt them to noise: black screen after the "
          "loader, plan gate 6)")
    if res["drive_loader_id"]:
        print("   the loader now on the drive serves %s, and the containers %s sealed to it"
              % (res["drive_loader_id"], "ARE" if res["drive_loader_ok"] else "are NOT"))
    print("   choose one:")
    print("     --reseal          re-seal MODULES/*.IRX + BLJA-00010 from the disc to "
          "the served ID %s" % res["served"])
    if res["drive_loader_ok"]:
        print("     --recover-hddid OUT, then --hddid OUT: keep the drive's seal (%s)"
              % res["drive_loader_id"])
    else:
        print("     --recover-hddid OUT only helps if the drive's current loader serves "
              "the seal ID; it does not here")


def reseal_files(a, work):
    """Seal MODULES/*.IRX + BLJA-00010 from the disc to a.hddid into work/;
    returns the pfsshell lines that replace them in the mounted partition."""
    hddid_blob = open(a.hddid, "rb").read()
    ata32 = ata_material(hddid_blob)
    four = bytes.fromhex(a.four)
    os.makedirs(os.path.join(work, "MODULES"), exist_ok=True)
    blob = disc_to_drive.build_drive_form(
        open(os.path.join(a.disc, "MAIN.BIN"), "rb").read(), ata32, four)
    open(os.path.join(work, "BLJA-00010"), "wb").write(blob)
    for m in MODULE_NAMES:
        blob = disc_to_drive.build_drive_form(
            open(os.path.join(a.disc, "MODULES", m + ".ENC"), "rb").read(), ata32, four)
        if m == "SIO2MAN" and not seal_matches(blob, hddid_blob, four, deep=True)[0]:
            raise SystemExit("re-seal self-check failed for %s; nothing written" % m)
        open(os.path.join(work, "MODULES", m + ".IRX"), "wb").write(blob)
    lines = ["lcd %s" % _quote(work.replace("\\", "/")),
             "rm BLJA-00010", "put BLJA-00010", "cd MODULES",
             "lcd %s" % _quote(os.path.join(work, "MODULES").replace("\\", "/"))]
    for m in MODULE_NAMES:
        lines += ["rm %s.IRX" % m, "put %s.IRX" % m]
    lines.append("cd ..")
    print("== reseal: %d containers sealed to %s (+ four %s)"
          % (1 + len(MODULE_NAMES), _sha8(hddid_blob), a.four))
    return lines


def seal_guard(a):
    """Run the guard for --loader-swap / --check-seal. False: the drive is sealed
    to the served ID. True: it is not and --reseal was given (the caller
    re-seals). Otherwise exits SEAL_EXIT: nothing is written."""
    hddid_blob = open(a.hddid, "rb").read()
    res = check_seal(a.device, hddid_blob, bytes.fromhex(a.four), a.helper)
    report_seal(res, a.hddid)
    if res["ok"]:
        return False
    if getattr(a, "reseal", False):
        if not a.disc:
            raise SystemExit("--reseal needs --disc")
        print("== --reseal: the containers will be re-sealed to the served ID")
        return True
    print("== refusing: no loader written (served ID != sealed ID)")
    sys.exit(SEAL_EXIT)


def stage_notice(a, dest_dir):
    """res/notice.png is the caution PSBBN draws over the game art at launch. With
    --translate it is translation/notice.en.png (same 416x196 RGBA, grey text on
    transparent); otherwise the disc's stock BN_RES/NOTICE.PNG. Written to
    dest_dir/notice.png. Returns True when the English one was used."""
    english = bool(a.translate)
    if english:
        toolsdir = os.path.dirname(os.path.abspath(__file__))
        src = os.path.normpath(os.path.join(toolsdir, os.pardir, "translation",
                                            "notice.en.png"))
        if not os.path.isfile(src):
            print("== translation: WARNING: %s missing; keeping the Japanese launch "
                  "notice" % src, flush=True)
            english = False
    if not english:
        src = os.path.join(a.disc, "BN_RES", "NOTICE.PNG")
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copyfile(src, os.path.join(dest_dir, "notice.png"))
    return english


def loader_swap(a):
    """Upgrade in place: fill the spoof loader for THIS drive and replace
    pfs:/dnasload.elf in the EXISTING PP.BLJA-00010, WITHOUT reinstalling. For
    iterating on loader / boot-ELF-patch changes on a drive that already has the
    game -- and, with --translate, also refresh pfs:/IMAGE.DAT + IMAGE1.DAT + IMAGE3.DAT with
    the English textures (so re-running updates an out-of-date translation;
    without it, or with --no-textures, both are restored to the disc's stock
    Japanese). The sealed containers and APA passwords are left untouched; the
    attribute area is written only when the drive has none (installs from
    before the attr fix), so a retitled name is kept.

    Seal guard first: one sealed container is read back from the drive and must
    decrypt under the HDD ID the new loader would serve (seal_guard). On a
    mismatch nothing is written and the exit status is 3, unless --reseal is
    given, which re-seals MODULES/*.IRX + BLJA-00010 from the disc to that ID in
    the same pfsshell pass. After --write the drive is read back and checked
    again."""
    if not a.loader:
        raise SystemExit("--loader-swap requires --loader <polbbnexec-popn.kelf>")
    try:
        lba = part_lba(a.helper, a.device)
    except Exception as e:
        raise SystemExit("%s not found on %s (%r); it is not installed -- use the full "
                         "install, not --loader-swap" % (PARTITION, a.device, e))
    print("== loader-swap: %s present at LBA %d" % (PARTITION, lba))
    # Installs from before the attr fix have none: HDD-OSD and HOSDMenu list
    # them as "Corrupted Data". Add it; an existing area (a retitled name) is kept.
    need_attr = not attr_present(a.device, lba)
    if need_attr:
        area, how = attr_area_for(a)
        check_attr(area)
        print("== attr: none on the drive; will write one (%d B, %s)" % (len(area), how))
    # Gate 6: never write a loader that serves another ID than the drive's
    # containers are sealed to (refuses unless --reseal).
    reseal = seal_guard(a)
    work = a.work
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(work)
    reseal_lines = reseal_files(a, os.path.join(work, "reseal")) if reseal else []
    filled = os.path.join(work, "dnasload.elf")
    fill_loader(a.disc, a.loader, a.hddid, filled, a.helper, a.translate)
    print("== loader: filled %s for this drive -> dnasload.elf (%d B%s)"
          % (os.path.basename(a.loader), os.path.getsize(filled),
             ", English" if a.translate else ""))
    puts = ["dnasload.elf"]
    rms = ["rm dnasload.elf"]
    # IMAGE.DAT + IMAGE1.DAT + IMAGE3.DAT: English textures with --translate (unless
    # --no-textures); otherwise the disc's STOCK files, so a re-swap always leaves
    # the images in a known state that matches the text language.
    names, english = stage_images(a, work)
    if not english:
        print("== images: restoring the stock (Japanese) %s" % " + ".join(names))
    for n in names:
        rms.append("rm %s" % n)
        puts.append(n)
    # res/notice.png follows the text language the same way.
    res_dir = os.path.join(work, "res")
    if not stage_notice(a, res_dir):
        print("== notice: restoring the stock (Japanese) res/notice.png")
    script = "\n".join(
        ["device %s" % a.device, "mount %s" % PARTITION]
        + reseal_lines
        + rms
        + ["lcd %s" % _quote(work.replace("\\", "/"))]
        + ["put %s" % p for p in puts]
        + ["cd res", "rm notice.png", "lcd %s" % _quote(res_dir.replace("\\", "/")),
           "put notice.png", "cd .."]
        + ["ls dnasload.elf", "umount", "exit", ""])
    print("== pfsshell swap script:")
    print("\n".join("   " + ln for ln in script.splitlines() if ln))
    if not a.write:
        print("== dry-run complete; pass --write to swap pfs:/dnasload.elf in place")
        return
    print("== swapping the loader via pfsshell")
    subprocess.run([a.pfsshell], input=script, text=True, check=True)
    if need_attr:
        write_attr(a.device, lba, area)
        print("== attr written and read back (%d B at main +0x1000)" % len(area))
    # Read back: the drive must now be sealed to the ID its new loader serves.
    after = check_seal(a.device, open(a.hddid, "rb").read(), bytes.fromhex(a.four), a.helper)
    if not after["ok"] or after["drive_loader_id"] != after["served"]:
        report_seal(after, a.hddid)
        print("== READ-BACK FAILED: the drive's loader serves %s, the containers %s; "
              "do not boot this, re-run with --reseal"
              % (after["drive_loader_id"], "match" if after["ok"] else "do not match"))
        sys.exit(SEAL_EXIT)
    print("== read-back: loader serves %s and the containers are sealed to it"
          % after["served"])
    print("== done: swapped pfs:/dnasload.elf in %s on %s" % (PARTITION, a.device))


def recover_hddid(a):
    """New machine, drive already installed: the PlayOnline step never ran here,
    so games/POL/playonline.hddid is missing -- but the 512-byte HDD ID the
    install was keyed to is embedded verbatim in the spoof loader that is already
    on the drive. Read pfs:/dnasload.elf back from PP.BLJA-00010 and lift the
    block out, so the install/swap can proceed WITHOUT re-running PlayOnline or
    guessing a seed.

    (The block is not in a normal addressable sector -- a genuine Sony drive
    returns it over a proprietary ATA command, and a minted one is otherwise only
    in the .hddid file -- but the loader carries it so its atad shim can serve it,
    which is exactly the copy we read here. It is saved only after a sealed
    container on the drive is checked to decrypt under it: a loader on the drive
    is not proof of the seal, a bad --loader-swap can leave one that serves
    another ID. Exits 3 when it does not match.)"""
    out = a.recover_hddid
    try:
        lba = part_lba(a.helper, a.device)
    except Exception as e:
        raise SystemExit("%s not found on %s (%r); the game is not installed on "
                         "this drive, so there is no loader to recover the HDD ID "
                         "from." % (PARTITION, a.device, e))
    print("== recover-hddid: %s present at LBA %d" % (PARTITION, lba))
    blob = None
    try:
        # Read-only, no pfsshell: the same PFS reader the seal guard uses.
        got = read_installed(a.device, ["dnasload.elf", SEAL_PROBE], a.helper)
        blob, probe = got["dnasload.elf"], got[SEAL_PROBE]
        print("== read pfs:/dnasload.elf + pfs:/%s back (PFS reader)" % SEAL_PROBE)
    except SystemExit:
        raise
    except Exception as e:
        print("   PFS reader failed (%r); falling back to pfsshell" % (e,))
        probe = None
    if blob is None:
        work = a.work
        if os.path.exists(work):
            shutil.rmtree(work)
        os.makedirs(work)
        script = "\n".join(
            ["device %s" % a.device, "mount %s" % PARTITION,
             "lcd %s" % _quote(work.replace("\\", "/")),
             "get dnasload.elf", "umount", "exit", ""])
        print("== reading pfs:/dnasload.elf back via pfsshell")
        subprocess.run([a.pfsshell], input=script, text=True, check=True)
        got = os.path.join(work, "dnasload.elf")
        if not os.path.isfile(got):
            raise SystemExit("pfsshell did not copy dnasload.elf out of %s; cannot "
                             "recover the HDD ID" % PARTITION)
        blob = open(got, "rb").read()
    _helper_dir(a.helper)
    from playonline import loader as pol_loader
    try:
        info = pol_loader.read(blob)
    except Exception as e:
        raise SystemExit("could not parse the loader on %s (%r); it may be a stock "
                         "dnasload, not our spoof loader -- the HDD ID can only be "
                         "recovered from a filled loader." % (PARTITION, e))
    if not info["has_hddid"]:
        raise SystemExit("the loader on %s serves no HDD ID block (a genuine Sony "
                         "drive, or an unfilled loader); nothing to recover."
                         % PARTITION)
    block = info["hddid"]
    # The loader on the drive is NOT proof of the seal: a bad --loader-swap
    # (2026-10-07) left a loader serving another ID than the containers. Check.
    if probe is not None:
        ok, why = seal_matches(probe, block, bytes.fromhex(a.four), deep=True)
        if not ok:
            print("== the drive's loader serves %s, but the containers are NOT sealed "
                  "to it (%s: %s); not saving it" % (_sha8(block), SEAL_PROBE, why))
            print("   fix: --loader-swap --reseal with the ID you want served")
            sys.exit(SEAL_EXIT)
        print("== the containers are sealed to it (%s: %s)" % (SEAL_PROBE, why))
    else:
        print("   (seal not verified: the containers could not be read)")
    d = os.path.dirname(os.path.abspath(out))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    open(out, "wb").write(block)
    print("== recovered the drive's HDD ID %s -> %s (%d B)" % (_sha8(block), out, len(block)))
    print("   key material: %s" % (block[0x40:0x48] + block[0x50:0x60]).hex())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("device", help="target drive (a device pfsshell's `device` gets)")
    ap.add_argument("--disc", help="extracted disc root (required to install or swap)")
    ap.add_argument("--hddid", help="512-byte hddid block (playonline.hddid); required to "
                    "install or swap, produced by --recover-hddid on a new machine")
    ap.add_argument("--attr", help="a prebuilt attr-area.bin to write instead of the one "
                    "built from the disc's PAT_EXT/NORMAL.ICO (English title with --translate, "
                    "else Japanese); --loader-swap writes it only when the drive has none")
    ap.add_argument("--loader", help="the pre-signed spoof loader KELF (polbbnexec-popn.kelf) to "
                    "install as pfs:/dnasload.elf in place of the disc's stock dnasload (which "
                    "cannot pass the dead DNAS console binding). FILLED here for this drive from "
                    "the drive's HDD ID + the player's own patched boot ELF and DNAS280.IMG carved "
                    "from the disc; no re-signing, so no PS2 keys are needed. Without it the stock "
                    "dnasload is kept and the install will NOT boot disc-less past the DNAS check.")
    ap.add_argument("--translate", help="apply the English translation: an elf.en.tsv "
                    "(popn/translation/elf.en.tsv). The boot ELF is rebuilt with the translated "
                    "strings and the English-release patches (patch_boot_elf ENGLISH_PATCHES: O/X "
                    "swap, English keyboard, date/time, gender, birthdate) before it is embedded in "
                    "the loader (that part requires --loader), AND the menu/dialog textures in "
                    "IMAGE.DAT + IMAGE1.DAT + IMAGE3.DAT are rebuilt in English from the disc's originals "
                    "(translation/apply_textures_nat.py; needs Pillow + numpy, OpenCV recommended; "
                    "several minutes). See --no-textures.")
    ap.add_argument("--no-textures", dest="no_textures", action="store_true",
                    help="with --translate: keep the disc's stock Japanese IMAGE.DAT / IMAGE1.DAT / IMAGE3.DAT "
                    "(English text only; skips the slow image build)")
    ap.add_argument("--translate-images", dest="translate_images", action="store_true",
                    help="build the English images even without --translate (images only; the "
                    "boot ELF text stays Japanese)")
    ap.add_argument("--four", default=FOUR)
    ap.add_argument("--part-mib", type=int, default=DEFAULT_MIB)
    ap.add_argument("--pfsshell", default="pfsshell")
    ap.add_argument("--helper", default=None,
                    help="toolkit scripts/helper (for fit/jail check and polhdd)")
    ap.add_argument("--work", default=os.path.join(HERE, "_popn_stage"))
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--loader-swap", dest="loader_swap", action="store_true",
                    help="UPGRADE IN PLACE: the partition already exists; do NOT reinstall. "
                    "Only fill the spoof loader for this drive and replace pfs:/dnasload.elf "
                    "(iterate on loader/ELF-patch changes without a full reinstall). Requires "
                    "--loader, --disc, --hddid.")
    ap.add_argument("--recover-hddid", dest="recover_hddid", metavar="OUT",
                    help="NEW MACHINE, drive already installed: read the HDD ID the "
                    "install was keyed to back out of the spoof loader already on the "
                    "drive (pfs:/dnasload.elf in %s) and write it here as a "
                    "playonline.hddid, so the install/swap can proceed without "
                    "re-running the PlayOnline step. Saved only if the drive's sealed "
                    "containers decrypt under it (else exit 3)." % PARTITION)
    ap.add_argument("--check-seal", dest="check_seal", action="store_true",
                    help="read-only: check that the containers already on the drive are "
                    "sealed to --hddid (the ID a loader filled now would serve). Exit 0 "
                    "match, 3 mismatch. --loader-swap runs the same check first and "
                    "refuses on a mismatch.")
    ap.add_argument("--reseal", action="store_true",
                    help="with --loader-swap: if the drive's containers are not sealed to "
                    "--hddid, re-seal MODULES/*.IRX + BLJA-00010 from --disc to it in the "
                    "same pfsshell pass, instead of refusing")
    a = ap.parse_args()
    # The installer pipes us through tee; line-buffer so progress shows live.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    if a.recover_hddid:
        recover_hddid(a)
        return

    if a.check_seal:
        if not a.hddid:
            raise SystemExit("--check-seal requires --hddid")
        seal_guard(a)
        return

    if a.loader_swap:
        if not (a.disc and a.hddid):
            raise SystemExit("--loader-swap requires --disc and --hddid")
        loader_swap(a)
        return

    if not (a.disc and a.hddid):
        raise SystemExit("installing requires --disc and --hddid (on a new machine "
                         "with the drive already installed, get the HDD ID with "
                         "--recover-hddid first)")

    precheck(a.device, a.helper)
    if a.check_only:
        print("== check-only: exiting without writes")
        return

    hddid_blob = open(a.hddid, "rb").read()
    ata32 = ata_material(hddid_blob)
    four = bytes.fromhex(a.four)
    staged = os.path.join(a.work, PARTITION)

    print("== seal disc -> drive form (target: %s + four %s)" % (a.hddid, a.four))
    if os.path.exists(a.work):
        shutil.rmtree(a.work)
    os.makedirs(staged)
    n_s, n_p = seal_tree(a.disc, staged, ata32, four)
    print("   sealed %d containers, copied %d plaintext files" % (n_s, n_p))

    # Replace the disc's stock dnasload (copied by seal_tree) with the spoof
    # loader, filled for this drive. The stock dnasload cannot pass the dead
    # DNAS console binding; the filled loader serves this drive's HDD ID, boots
    # the patched game ELF, and reboots the IOP with DNAS280.IMG. Without
    # --loader the install stays on stock dnasload and will not boot disc-less.
    dnasload = os.path.join(staged, "dnasload.elf")
    if a.loader:
        had = os.path.exists(dnasload)
        fill_loader(a.disc, a.loader, a.hddid, dnasload, a.helper, a.translate)
        print("== loader: filled %s for this drive -> dnasload.elf (%s stock%s)"
              % (os.path.basename(a.loader), "replaced" if had else "no",
                 ", English" if a.translate else ""))
    else:
        print("== loader: NONE given; keeping the disc's stock dnasload.elf "
              "(install will NOT boot disc-less past the DNAS check without --loader)")

    # English textures: with --translate (unless --no-textures) rebuild the staged
    # IMAGE.DAT + IMAGE1.DAT + IMAGE3.DAT (copied stock by seal_tree) from the disc's originals
    # with the translated menu/logo/dialog text; the put below writes them.
    if textures_wanted(a):
        stage_images(a, staged)
    if a.translate and stage_notice(a, os.path.join(staged, "res")):
        print("== translation: English launch notice -> res/notice.png")

    script = pfsshell_script(a.device, staged, a.part_mib)
    lines = script.splitlines()
    print("== pfsshell script (%d lines):" % len(lines))
    print("\n".join("   " + ln for ln in lines[:5]))
    puts = sum(1 for ln in lines if ln.startswith("put"))
    print("   ... (%d put lines)" % puts)

    # Built before any write so a missing icon stops the install early.
    area, how = attr_area_for(a)
    check_attr(area)
    print("== attr: %d B, %s" % (len(area), how))

    if not a.write:
        print("== dry-run complete; pass --write to apply (mkpart + put + attr + pwd)")
        return

    print("== mkpart + put via pfsshell")
    subprocess.run([a.pfsshell], input=script, text=True, check=True)
    lba = part_lba(a.helper, a.device)
    print("== attr / passwords: PP main LBA = %d" % lba)
    write_attr(a.device, lba, area)
    print("   attr written and read back (%d B)" % len(area))
    pwd = write_passwords(a.device, lba, a.helper)
    print("   passwords set: POPNPUZZ (%s)" % pwd.hex())
    netcnf_install.netcnf_step(a.device, a.pfsshell, a.work)
    print("== done: pop'n installed to %s on %s" % (PARTITION, a.device))


if __name__ == "__main__":
    main()
