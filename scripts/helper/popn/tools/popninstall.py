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

def fill_loader(disc_root, kelf, hddid, out_path, helper):
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

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("device", help="target drive (a device pfsshell's `device` gets)")
    ap.add_argument("--disc", required=True, help="extracted disc root")
    ap.add_argument("--hddid", required=True, help="512-byte hddid block (playonline.hddid)")
    ap.add_argument("--attr", help="attr-area.bin (English title + icon); optional")
    ap.add_argument("--loader", help="the pre-signed spoof loader KELF (polbbnexec-popn.kelf) to "
                    "install as pfs:/dnasload.elf in place of the disc's stock dnasload (which "
                    "cannot pass the dead DNAS console binding). FILLED here for this drive from "
                    "the drive's HDD ID + the player's own patched boot ELF and DNAS280.IMG carved "
                    "from the disc; no re-signing, so no PS2 keys are needed. Without it the stock "
                    "dnasload is kept and the install will NOT boot disc-less past the DNAS check.")
    ap.add_argument("--four", default=FOUR)
    ap.add_argument("--part-mib", type=int, default=DEFAULT_MIB)
    ap.add_argument("--pfsshell", default="pfsshell")
    ap.add_argument("--helper", default=None,
                    help="toolkit scripts/helper (for fit/jail check and polhdd)")
    ap.add_argument("--work", default=os.path.join(HERE, "_popn_stage"))
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

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
        fill_loader(a.disc, a.loader, a.hddid, dnasload, a.helper)
        print("== loader: filled %s for this drive -> dnasload.elf (%s stock)"
              % (os.path.basename(a.loader), "replaced" if had else "no"))
    else:
        print("== loader: NONE given; keeping the disc's stock dnasload.elf "
              "(install will NOT boot disc-less past the DNAS check without --loader)")

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
