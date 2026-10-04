"""Drive-neutral Nobunaga install bundle: decrypt once, seal per target drive.

A Koei DNAS2 container splits into (a) drive-independent plaintext - the
decrypted K1-block and outer layer - and (b) cross-drive-constant RSA records
(session/sizes/sig/static) that copy verbatim. `neutralize()` rewrites a
container so sec+0x80 / sec+0x300 hold the plaintext instead of the drive's
ciphertext, leaving every RSA record intact. `seal()` turns a neutral
container back into a drive-form one for a target drive, deriving all section
geometry from the intact RSA records - so sealing needs no decryption key,
only the target drive's identity (ATA IDENTIFY page + __net four).

This is how a tester without the disc can install: we ship the
neutral tree (produced once from a known-good install), and the installer
`seal()`s each container to the tester's own drive. The clean path - decrypt
the tester's own disc - needs the 24-byte physical disc ID (see the
disc-form decrypt notes); until that capture exists, the neutral bundle is
the interim, and it carries decrypted game modules, so it is shared directly
with testers, not baked into the public toolkit.

    # build the neutral tree once, from our own install:
    python3 dnasbundle.py neutralize <install-tree> <out-tree> --hddid HDD_ID.bin
    # seal it to a target drive's identity (what the installer does):
    python3 dnasbundle.py seal <neutral-tree> <out-tree> --hddid TARGET_ID.bin
    # prove a round-trip (seal(neutralize(x)) == x) on our own drive:
    python3 dnasbundle.py verify <install-tree> --hddid HDD_ID.bin
"""
import argparse
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dnas2                                     # noqa: E402
import dnaskey                                   # noqa: E402
import rc6                                       # noqa: E402
from dnasdec import ata_material                 # noqa: E402

FOUR = bytes.fromhex("00001301")                 # the __net title constant
CONTAINER_EXT = (".ERX", ".EBN")


def is_container(blob):
    keys = dnas2.keys()
    r = dnas2.unrecord(blob[0:128], keys[7][1], keys[7][2])
    return bool(r and r[1] == b"96011a8e95fd1ffc")


def _sections(blob):
    """Walk section geometry from the INTACT RSA records only (no key)."""
    keys = dnas2.keys()
    r7 = dnas2.unrecord(blob[0:128], keys[7][1], keys[7][2])[0]
    sec = int.from_bytes(r7[0x20:0x24], "little") + 0x200
    out = []
    while sec + 0x300 < len(blob):
        sess = dnas2.unrecord(blob[sec + 0x180:sec + 0x200], keys[11][1], keys[11][2])[0]
        h1 = rc6.cbc(blob[sec + 0x280:sec + 0x300], sess[:16], sess[16:32], True)
        if h1[10:26] != b"a5713c8bdbe8d420":
            raise ValueError("H1 tag mismatch at %#x" % sec)
        sizes = dnas2.unrecord(blob[sec + 0x100:sec + 0x180], keys[3][1], keys[3][2])[0]
        v1 = struct.unpack("<I", sizes[:4])[0]
        d10 = sizes[10] * 16
        pad = (0x10 - (v1 & 0xF)) & 0xF
        extent = d10 + v1 + pad + 0x10
        nxt = sec + 0x300 + extent + 0x80
        out.append((sec, extent))
        if nxt + 0x300 >= len(blob):
            break
        sec = nxt
    return out


def neutralize(blob, ata32, four):
    """Drive-form -> neutral: put decrypted blk/outer at sec+0x80 / sec+0x300."""
    K1 = dnaskey.derive_k1(ata32, four)
    buf = bytearray(blob)
    for sec, extent in _sections(blob):
        blk_plain = rc6.cbc(blob[sec + 0x80:sec + 0x100], K1[0:16], K1[16:32], True)
        K2 = dnaskey.derive_k2(blk_plain, ata32, four)
        outer_plain = rc6.cbc(blob[sec + 0x300:sec + 0x300 + extent],
                              K2[0:16], K2[16:32], True)
        buf[sec + 0x80:sec + 0x100] = blk_plain
        buf[sec + 0x300:sec + 0x300 + extent] = outer_plain
    return bytes(buf)


def seal(neutral, ata32, four):
    """Neutral -> drive-form for the target: re-encrypt blk/outer, no key needed."""
    K1 = dnaskey.derive_k1(ata32, four)
    buf = bytearray(neutral)
    for sec, extent in _sections(neutral):
        blk_plain = neutral[sec + 0x80:sec + 0x100]
        K2 = dnaskey.derive_k2(blk_plain, ata32, four)
        buf[sec + 0x80:sec + 0x100] = rc6.cbc(blk_plain, K1[0:16], K1[16:32], False)
        buf[sec + 0x300:sec + 0x300 + extent] = rc6.cbc(
            neutral[sec + 0x300:sec + 0x300 + extent], K2[0:16], K2[16:32], False)
    return bytes(buf)


def _walk(tree):
    for dp, _, fs in os.walk(tree):
        for f in fs:
            yield os.path.join(dp, f), os.path.relpath(os.path.join(dp, f), tree)


def _map_tree(src, dst, fn):
    n_c = n_f = 0
    for path, rel in _walk(src):
        out = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        blob = open(path, "rb").read()
        looks_container = (rel.upper().endswith(CONTAINER_EXT)
                           or os.path.basename(rel) == "SLPM-65197")
        if looks_container and is_container(blob):
            open(out, "wb").write(fn(blob))
            n_c += 1
        else:
            shutil.copyfile(path, out)
            n_f += 1
    return n_c, n_f


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=("neutralize", "seal", "verify"))
    ap.add_argument("src")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--hddid", required=True, help="ATA IDENTIFY page of the source/target drive")
    ap.add_argument("--four", default="00001301")
    a = ap.parse_args()
    ata32 = ata_material(open(a.hddid, "rb").read())
    four = bytes.fromhex(a.four)

    if a.mode == "verify":
        bad = same = 0
        for path, rel in _walk(a.src):
            blob = open(path, "rb").read()
            if not (rel.upper().endswith(CONTAINER_EXT)
                    or os.path.basename(rel) == "SLPM-65197") or not is_container(blob):
                continue
            if seal(neutralize(blob, ata32, four), ata32, four) == blob:
                same += 1
            else:
                bad += 1
                print("  ROUND-TRIP FAILS:", rel)
        print("round-trip: %d containers OK, %d bad" % (same, bad))
        return

    if not a.out:
        raise SystemExit("neutralize/seal need an output tree")
    fn = (lambda b: neutralize(b, ata32, four)) if a.mode == "neutralize" \
        else (lambda b: seal(b, ata32, four))
    n_c, n_f = _map_tree(a.src, a.out, fn)
    print("%sd %d containers, copied %d other files -> %s" % (a.mode, n_c, n_f, a.out))


if __name__ == "__main__":
    main()
