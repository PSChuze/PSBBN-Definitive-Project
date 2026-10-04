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
  4. attr   Write an English browser-title attribute area at PP main +0x1000
            (optional -- browser shows the title in HDD-OSD; skip -> "Corrupted
            Data").
  5. passwords  Set fpwd/rpwd on the APA header (PSBBN's pfsshell mkpart leaves
                them zero; the game refuses to mount if they don't match).

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
import disc_to_drive                              # noqa: E402
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

def write_attr(device, lba, attr_path):
    area = open(attr_path, "rb").read()
    if area[:9] != b"PS2ICON3D":
        raise SystemExit("attr file has no PS2ICON3D magic")
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        f.write(area)

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


def loader_swap(a):
    """Upgrade in place: fill the spoof loader for THIS drive and replace
    pfs:/dnasload.elf in the EXISTING PP.BLJA-00010, WITHOUT reinstalling. For
    iterating on loader / boot-ELF-patch changes on a drive that already has the
    game -- and, with --translate, also refresh pfs:/IMAGE.DAT + IMAGE1.DAT + IMAGE3.DAT with
    the English textures (so re-running updates an out-of-date translation;
    without it, or with --no-textures, both are restored to the disc's stock
    Japanese). The sealed containers, attr and APA passwords are left untouched."""
    if not a.loader:
        raise SystemExit("--loader-swap requires --loader <polbbnexec-popn.kelf>")
    try:
        lba = part_lba(a.helper, a.device)
    except Exception as e:
        raise SystemExit("%s not found on %s (%r); it is not installed -- use the full "
                         "install, not --loader-swap" % (PARTITION, a.device, e))
    print("== loader-swap: %s present at LBA %d" % (PARTITION, lba))
    work = a.work
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(work)
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
    script = "\n".join(
        ["device %s" % a.device, "mount %s" % PARTITION]
        + rms
        + ["lcd %s" % _quote(work.replace("\\", "/"))]
        + ["put %s" % p for p in puts]
        + ["ls dnasload.elf", "umount", "exit", ""])
    print("== pfsshell swap script:")
    print("\n".join("   " + ln for ln in script.splitlines() if ln))
    if not a.write:
        print("== dry-run complete; pass --write to swap pfs:/dnasload.elf in place")
        return
    print("== swapping the loader via pfsshell")
    subprocess.run([a.pfsshell], input=script, text=True, check=True)
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
    which is exactly the copy we read here. This is the exact identity the sealed
    containers decrypt against, so it is correct even if the original mint was
    random/unseeded.)"""
    out = a.recover_hddid
    try:
        lba = part_lba(a.helper, a.device)
    except Exception as e:
        raise SystemExit("%s not found on %s (%r); the game is not installed on "
                         "this drive, so there is no loader to recover the HDD ID "
                         "from." % (PARTITION, a.device, e))
    print("== recover-hddid: %s present at LBA %d" % (PARTITION, lba))
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
    if a.helper and a.helper not in sys.path:
        sys.path.insert(0, a.helper)
    from playonline import loader as pol_loader
    blob = open(got, "rb").read()
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
    d = os.path.dirname(os.path.abspath(out))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    open(out, "wb").write(block)
    print("== recovered the drive's HDD ID -> %s (%d B)" % (out, len(block)))
    print("   key material: %s" % (block[0x40:0x48] + block[0x50:0x60]).hex())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("device", help="target drive (a device pfsshell's `device` gets)")
    ap.add_argument("--disc", help="extracted disc root (required to install or swap)")
    ap.add_argument("--hddid", help="512-byte hddid block (playonline.hddid); required to "
                    "install or swap, produced by --recover-hddid on a new machine")
    ap.add_argument("--attr", help="attr-area.bin (English title + icon); optional")
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
                    "re-running the PlayOnline step. Requires --helper." % PARTITION)
    a = ap.parse_args()
    # The installer pipes us through tee; line-buffer so progress shows live.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    if a.recover_hddid:
        recover_hddid(a)
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

    script = pfsshell_script(a.device, staged, a.part_mib)
    lines = script.splitlines()
    print("== pfsshell script (%d lines):" % len(lines))
    print("\n".join("   " + ln for ln in lines[:5]))
    puts = sum(1 for ln in lines if ln.startswith("put"))
    print("   ... (%d put lines)" % puts)

    if not a.write:
        print("== dry-run complete; pass --write to apply (mkpart + put + attr + pwd)")
        return

    print("== mkpart + put via pfsshell")
    subprocess.run([a.pfsshell], input=script, text=True, check=True)
    lba = part_lba(a.helper, a.device)
    print("== attr / passwords: PP main LBA = %d" % lba)
    if a.attr:
        write_attr(a.device, lba, a.attr)
        print("   attr written")
    else:
        print("   attr skipped (no --attr; browser will show 'Corrupted Data')")
    pwd = write_passwords(a.device, lba, a.helper)
    print("   passwords set: POPNPUZZ (%s)" % pwd.hex())
    print("== done: pop'n installed to %s on %s" % (PARTITION, a.device))


if __name__ == "__main__":
    main()
