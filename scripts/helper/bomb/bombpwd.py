#!/usr/bin/env python3
"""Check or set the APA passwords on an already-installed Bomberman partition.

BOMBBOOT and MAIN.BIN mount the partition as
"hdd0:PP.SLPS-20343.NET.BOMB,T3nheNY3" (bombboot-spec.md 2.2). Sony HDD.IRX
checks the password against the header's rpwd/fpwd fields. pfsshell's mkpart
leaves them zero, the mount fails silently, and BOMBBOOT spins in its lseek
retry: the symptom is "launches, then nothing", MAIN.BIN never at 0x300000.

This writes the bytes a retail install's header carries (APA passwords are
derived from constants, the same on every drive) and recomputes the header
checksum. 16 bytes + a checksum; no reinstall. Works on a device node or an
image file.

    python3 bombpwd.py <device-or-image>            # show current fields
    python3 bombpwd.py <device-or-image> --write    # set them
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_PSBBN = os.environ.get(
    "PSBBN_HELPER",
    r"E:\Code\PlayOnline Project\psbbn-playonline\scripts\helper")
sys.path.insert(0, _PSBBN)

SECTOR = 512
PART = "PP.SLPS-20343.NET.BOMB"
# Only fpwd is set; rpwd stays ZERO. The mount checks fpwd; a nonzero rpwd
# blocks HOSDMenu from reading the partition for the PATINFO launch (POL rule,
# see bombinstall.py). fpwd = apa_password(PART, b"T3nheNY3").
APA_FPWD = bytes.fromhex("02373c11a0a32358")


def checksum(hdr):
    total = 0
    for off in range(4, 0x400, 4):
        total = (total + struct.unpack_from("<I", hdr, off)[0]) & 0xFFFFFFFF
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("device")
    ap.add_argument("--part", default=PART)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    from playonline import apa
    lba, _sectors = apa.find_partition(a.device, a.part)
    mode = "r+b" if a.write else "rb"
    with open(a.device, mode) as f:
        f.seek(lba * SECTOR)
        hdr = bytearray(f.read(0x400))
        if hdr[4:8] != b"APA\x00":
            raise SystemExit("%s: no APA magic at LBA %d" % (a.part, lba))
        stored = struct.unpack_from("<I", hdr, 0)[0]
        print("%s at LBA %d" % (a.part, lba))
        print("  rpwd %s  fpwd %s  checksum %08x (%s)"
              % (hdr[0x30:0x38].hex(), hdr[0x38:0x40].hex(), stored,
                 "ok" if stored == checksum(hdr) else "STALE"))
        ok = hdr[0x38:0x40] == APA_FPWD and hdr[0x30:0x38] == bytes(8)
        print("  fpwd %s, rpwd %s"
              % ("correct" if hdr[0x38:0x40] == APA_FPWD else "NOT set",
                 "zero (good)" if hdr[0x30:0x38] == bytes(8) else "NONZERO (would block HOSDMenu)"))
        if not a.write:
            if not ok:
                print("  (re-run with --write to fix)")
            return 0
        hdr[0x30:0x38] = bytes(8)            # force rpwd zero
        hdr[0x38:0x40] = APA_FPWD
        struct.pack_into("<I", hdr, 0, checksum(hdr))
        f.seek(lba * SECTOR)
        f.write(bytes(hdr))
        f.flush()
        f.seek(lba * SECTOR)
        v = f.read(0x400)
        print("  wrote: rpwd %s  fpwd %s  checksum %s"
              % (v[0x30:0x38].hex(), v[0x38:0x40].hex(), v[:4].hex()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
