#!/usr/bin/env python3
"""Set, show or clear the fill-time trace slot in a polbbnexec loader.

The v4 loader (work/loader/src, shared by Nobunaga, pop'n and Minna) keeps the
trace sector's LBA in a 16-byte slot inside the embedded atadpatch.irx:

    +0  "TRACELBA"   magic, occurs exactly once in a v4 loader
    +8  u32 lba      absolute LBA of trace.bin's first sector, 0 = trace off
    +12 u32 flags    bit 0 = set by this tool
    +16 .. +48       runtime mailbox, zero in the file (the loader writes it
                     into its in-RAM copy; this tool only reports it)

The IRX is embedded raw, so the slot is found by its magic in the unsigned ELF,
in the signed KELF (the content past the 32 signed bytes is one unsigned
plaintext block) and in the filled dnasload.elf alike. No re-signing: the KELF
signatures do not cover the content block, which is also how
playonline.loader fills the HDD ID and the boot ELF.

The loader only WRITES the sector if it already carries the POLTRACE magic
(trace-setup.sh / repro-trace-arm.sh put a tagged trace.bin there), so a wrong
LBA costs one harmless read. --check verifies that before you boot.

    traceslot.py dnasload.elf --show
    traceslot.py dnasload.elf --set 19984128 [--check IMAGE_OR_DEVICE] [-o OUT]
    traceslot.py dnasload.elf --clear
"""
import argparse
import hashlib
import os
import struct
import sys

MAGIC = b"TRACELBA"
F_SET = 0x1
MB_MAGIC = 0x584F424D            # "MBOX"
POLTRACE = b"POLTRACE"           # POLTRACE_MAGIC0/1 as bytes ("POLT" "RACE")
FORK_MAGIC = b"POLBBNFORKHDR1"
O_ARGV0, O_HDDID = 44, 236       # playonline.loader's install-header offsets


def locate(blob):
    hits = []
    i = blob.find(MAGIC)
    while i >= 0:
        hits.append(i)
        i = blob.find(MAGIC, i + 1)
    if not hits:
        raise SystemExit("no %s slot in this file: not a v4 polbbnexec loader "
                         "(built before the fill-time trace slot?)" % MAGIC.decode())
    if len(hits) > 1:
        raise SystemExit("%d %s slots at %s: refusing to guess"
                         % (len(hits), MAGIC.decode(), ", ".join(hex(h) for h in hits)))
    return hits[0]


def read_slot(blob, off):
    w = struct.unpack_from("<12I", blob, off)
    return {"offset": off, "lba": w[2], "flags": w[3], "mb_magic": w[4], "mb_cmd": w[5],
            "nonce": w[9], "kver": w[10], "reboot_res": w[11]}


def install_header(blob):
    """The playonline.loader install header, if this is a polbbnexec loader."""
    h = blob.find(FORK_MAGIC)
    if h < 0 or blob.find(FORK_MAGIC, h + 1) >= 0:
        return None
    argv0 = blob[h + O_ARGV0:h + O_ARGV0 + 192].split(b"\0")[0].decode("latin-1")
    hddid = blob[h + O_HDDID:h + O_HDDID + 512]
    elf_len = struct.unpack_from("<I", blob, h + 24)[0]
    ioprp_len = struct.unpack_from("<I", blob, h + 32)[0]
    return {"argv0": argv0, "hddid": hddid, "elf_len": elf_len, "ioprp_len": ioprp_len}


def check_sector(path, lba):
    """Read the sector at `lba` of an image or device; True if trace.bin's magic is there."""
    with open(path, "rb") as f:
        f.seek(lba * 512)
        sec = f.read(512)
    if len(sec) < 512:
        print("  check: %s has no sector %d (%d bytes read)" % (path, lba, len(sec)))
        return False
    ok = sec[:8] == POLTRACE
    tail = sec[8:16]
    print("  check: sector %d of %s starts %r -> %s"
          % (lba, path, sec[:16], "POLTRACE magic present (armable)" if ok else
             "NO POLTRACE magic: the loader will refuse to write here"))
    if ok and tail[:4] == struct.pack("<I", 0x00040000):
        print("         (already holds a v4 trace record)")
    return ok


def show(blob, path):
    off = locate(blob)
    s = read_slot(blob, off)
    print("%s" % path)
    print("  sha1      %s" % hashlib.sha1(blob).hexdigest())
    print("  slot      at file offset 0x%x" % off)
    print("  lba       %d%s" % (s["lba"], "  (trace OFF)" if s["lba"] == 0 else ""))
    print("  flags     0x%x%s" % (s["flags"], "  (set by traceslot.py)" if s["flags"] & F_SET else ""))
    if s["mb_magic"] or s["mb_cmd"] or s["nonce"] or s["kver"] or s["reboot_res"]:
        print("  WARNING   runtime mailbox is not zero in the file (mb_magic=0x%x cmd=%d)"
              % (s["mb_magic"], s["mb_cmd"]))
    h = install_header(blob)
    if h:
        filled = h["elf_len"] != 0
        print("  install   argv0=%r, boot ELF %d B, IOPRP %d B%s"
              % (h["argv0"], h["elf_len"], h["ioprp_len"], "" if filled else "  (NOT FILLED)"))
        print("  hddid     sha1 %s%s" % (hashlib.sha1(h["hddid"]).hexdigest(),
                                         "" if h["hddid"][:3] == b"Son" else "  (no Sony magic: unfilled)"))
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("loader", help="POLBBNEXEC.ELF, a signed .kelf or a filled dnasload.elf")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--show", action="store_true", help="print the slot (default action)")
    g.add_argument("--set", type=lambda v: int(v, 0), metavar="LBA",
                   help="absolute LBA of trace.bin's first sector (decimal or 0x..)")
    g.add_argument("--clear", action="store_true", help="LBA 0: trace off")
    ap.add_argument("--check", metavar="IMAGE_OR_DEVICE",
                    help="with --set/--show: verify the sector there carries the POLTRACE magic")
    ap.add_argument("--force", action="store_true",
                    help="with --set --check: write the slot even if the magic is absent")
    ap.add_argument("-o", "--output", help="write the patched loader here (default: in place)")
    a = ap.parse_args()

    blob = bytearray(open(a.loader, "rb").read())
    off = locate(blob)

    if a.show:
        s = show(blob, a.loader)
        if a.check and s["lba"]:
            check_sector(a.check, s["lba"])
        return 0

    if a.set is not None:
        if not 0 < a.set < (1 << 32):
            raise SystemExit("LBA %d out of range (use --clear for 0)" % a.set)
        if a.check and not check_sector(a.check, a.set) and not a.force:
            raise SystemExit("refusing: sector %d is not an armed trace.bin (use --force)" % a.set)
        lba, flags = a.set, F_SET
    else:
        lba, flags = 0, 0
    struct.pack_into("<II", blob, off + 8, lba, flags)
    out = a.output or a.loader
    tmp = out + ".tmp-traceslot"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, out)
    print("%s: trace slot at 0x%x -> lba %d flags 0x%x" % (out, off, lba, flags))
    show(bytes(blob), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
