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
        [--loader polbbnexec-popn.kelf] \
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
    ioprp, elf = patch_boot_elf.boot_sections_from_main(main_bin)
    tmp = tempfile.mkdtemp(prefix="popnloader-")
    try:
        ep = os.path.join(tmp, "boot.elf"); ip = os.path.join(tmp, "ioprp.img")
        open(ep, "wb").write(elf); open(ip, "wb").write(ioprp)
        # Optional English translation: rebuild the boot-patched ELF with the
        # translated strings (the text lives in the ELF's rodata; pntext.py elf-b
        # fits each English string into its cp932 slot). The loader then embeds
        # the English ELF. No other file changes -- the menus-as-textures work is
        # separate (see popn/HANDOFF-translation.md).
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

def image_en(disc_root, out_image):
    """Render the English menu/logo/dialog/room textures onto the disc's IMAGE.DAT
    (21 screens). Prefers apply_textures_nat.py - the natural, atlas-safe editor
    (glyph-mask + background inpaint, with a hard assertion that nothing changes
    outside each element so a shared sprite sheet is never corrupted); falls back
    to the older apply_textures.py (flat box+overlay) when the new one is absent.
    Needs Pillow + numpy; OpenCV (cv2) is used when present for cleaner inpaint but
    is optional. The text face is the bundled Comic Neue Bold (ComicNeue-Bold.ttf,
    a free SIL-OFL rounded Comic-Sans-alike) unless POPN_TEX_FONT overrides -- so
    it renders the same on any OS without a proprietary font. Writes out_image."""
    toolsdir = os.path.dirname(os.path.abspath(__file__))
    apply_py = next((p for p in (os.path.join(toolsdir, "apply_textures_nat.py"),
                                 os.path.join(toolsdir, "apply_textures.py"))
                     if os.path.isfile(p)), None)
    src = os.path.join(disc_root, "IMAGE.DAT")
    if apply_py is None:
        raise SystemExit("apply_textures(_nat).py not found in %s (texture translation unavailable)" % toolsdir)
    if not os.path.isfile(src):
        raise SystemExit("IMAGE.DAT not found in the disc at %s" % src)
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = toolsdir + os.pathsep + env.get("PYTHONPATH", "")
    for _name in ("ComicNeue-Bold.ttf", "DejaVuSans-Bold.ttf"):
        _f = os.path.join(toolsdir, _name)
        if os.path.isfile(_f):
            env.setdefault("POPN_TEX_FONT", _f)
            break
    subprocess.run([sys.executable, apply_py, src, out_image], check=True, env=env)
    return out_image


def loader_swap(a):
    """Upgrade in place: fill the spoof loader for THIS drive and replace
    pfs:/dnasload.elf in the EXISTING PP.BLJA-00010, WITHOUT reinstalling. For
    iterating on loader / boot-ELF-patch changes on a drive that already has the
    game -- and, with --translate, also refresh pfs:/IMAGE.DAT with the English
    textures (so re-running updates an out-of-date translation). The sealed
    containers, attr and APA passwords are left untouched."""
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
    # IMAGE.DAT: with --translate-images, render the (experimental) English
    # textures; otherwise restore the disc's STOCK IMAGE.DAT, so a re-swap always
    # leaves the images in a known state -- and so a drive that got the old
    # low-fidelity English textures is put back to clean Japanese. ELF text
    # (--translate) is independent of this.
    img = os.path.join(work, "IMAGE.DAT")
    if a.translate_images:
        image_en(a.disc, img)
        print("== translation: EXPERIMENTAL English IMAGE.DAT textures prepared for swap")
        rms.append("rm IMAGE.DAT")
        puts.append("IMAGE.DAT")
    else:
        src_img = os.path.join(a.disc, "IMAGE.DAT")
        if os.path.isfile(src_img):
            shutil.copy(src_img, img)
            print("== images: restoring the stock (Japanese) IMAGE.DAT")
            rms.append("rm IMAGE.DAT")
            puts.append("IMAGE.DAT")
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
    ap.add_argument("--translate", help="apply the English TEXT translation: an elf.en.tsv "
                    "(popn/translation/elf.en.tsv). The boot ELF is rebuilt with the translated "
                    "strings before it is embedded in the loader. Requires --loader. (Images are "
                    "left as the stock Japanese IMAGE.DAT; see --translate-images.)")
    ap.add_argument("--translate-images", dest="translate_images", action="store_true",
                    help="EXPERIMENTAL: also render the English menu/logo/dialog/room textures onto "
                    "IMAGE.DAT (apply_textures_nat.py; needs Pillow + numpy, cv2 optional). Uses the "
                    "natural, atlas-safe renderer (per-glyph erase + background inpaint, asserts it "
                    "never writes outside each element, so shared sprite sheets are not disturbed) -- "
                    "a rewrite of the old flat-box renderer that corrupted title/character art. Still "
                    "off by default pending a real-hardware validation pass. Without it, IMAGE.DAT "
                    "stays/restores to stock Japanese.")
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

    # English textures (EXPERIMENTAL, --translate-images only): rebuild the staged
    # IMAGE.DAT (copied plaintext by seal_tree) with the translated menu/logo text.
    # Off by default -- the current renderer is low fidelity and can disturb other
    # textures; the stock IMAGE.DAT seal_tree copied is used otherwise. ELF text
    # (--translate) is applied regardless and is the normal English experience.
    if a.translate_images:
        staged_image = os.path.join(staged, "IMAGE.DAT")
        if os.path.isfile(staged_image):
            image_en(a.disc, staged_image)
            print("== translation: EXPERIMENTAL English textures applied to IMAGE.DAT")
        else:
            print("== translation: IMAGE.DAT not staged; textures skipped")

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
