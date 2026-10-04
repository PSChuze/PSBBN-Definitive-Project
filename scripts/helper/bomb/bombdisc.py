#!/usr/bin/env python3
"""bombdisc.py - turn the user's Net de Bomberman disc into an install tree.

The disc carries the whole HDD install as DATA/FULL.BIN, a BOMB4 archive (see
bomb4.py). This reads it straight out of the disc image (the Redump raw
MODE2/2352 .bin, or a plain 2048-byte .iso; an already-extracted disc folder
works too) and lays it out the way the retail installer does:

  - every FULL.BIN entry at its own path. The 28 DNAS2 code containers stay
    in disc form; `bombinstall --disc` seals them to the target drive with
    disc_to_drive (offline: no console, no disc ID).
  - patch_version.bin = "10200\\n0\\n", which the retail install writes (1.02.00).
  - optional overlays: --pem replaces FRES/BOMBREG.PEM (the CA our login
    server's certificate chains to), --tsv rebuilds FILES.BIN's messages in
    English (bombtext msg-build, refuses any string over its byte budget).

With both overlays the plaintext files match the old neutral bundle byte for
byte; the containers differ only in their drive sealing.

    python3 -m bomb.bombdisc <disc.bin|disc.iso|disc dir> <out tree>
        [--pem BOMBREG.PEM] [--tsv msg_FILES_install.en.tsv]
"""
import argparse
import os
import shutil
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bomb4  # noqa: E402
import bombtext  # noqa: E402
import iso  # noqa: E402

PATCH_VERSION = b"10200\n0\n"
N_CONTAINERS = 28


def read_full_bin(src):
    """FULL.BIN's bytes from a disc image or an extracted disc folder."""
    if os.path.isdir(src):
        for dp, _, fs in os.walk(src):
            for f in fs:
                if f.upper() == "FULL.BIN" and os.path.basename(dp).upper() == "DATA":
                    return open(os.path.join(dp, f), "rb").read()
        raise SystemExit("no DATA/FULL.BIN under %s" % src)
    disc = iso.Disc(src)
    try:
        entries = list(iso.walk(disc, *iso.root(disc)))
    except AssertionError as ex:
        raise SystemExit("%s is not a PS2 disc image: %s" % (src, ex))
    for full, ext, sz, is_dir in entries:
        if not is_dir and full.upper() == "/DATA/FULL.BIN":
            return disc.read(ext, sz)
    raise SystemExit("%s has no DATA/FULL.BIN; is it the Net de Bomberman disc "
                     "(SLPS-20343)?" % src)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("disc", help="disc image (.bin/.iso) or extracted disc folder")
    ap.add_argument("out", help="install tree to write (replaced if present)")
    ap.add_argument("--pem", help="replacement FRES/BOMBREG.PEM")
    ap.add_argument("--tsv", help="FILES.BIN message translation (bombtext TSV)")
    a = ap.parse_args()

    print("== read DATA/FULL.BIN from %s" % a.disc)
    d = read_full_bin(a.disc)
    if d[:8] != bomb4.MAGIC:
        raise SystemExit("DATA/FULL.BIN is not a BOMB4 archive")

    if os.path.exists(a.out):
        shutil.rmtree(a.out)
    n_code = n_data = 0
    for name, csize, rsize, _check, flag, at in bomb4.entries(d):
        raw = zlib.decompress(d[at:at + csize])
        if len(raw) != rsize:
            raise SystemExit("%s: unpacked %d bytes, archive says %d"
                             % (name, len(raw), rsize))
        dst = os.path.join(a.out, name)
        os.makedirs(os.path.dirname(dst) or a.out, exist_ok=True)
        with open(dst, "wb") as o:
            o.write(raw)
        n_code += bool(flag)
        n_data += not flag
    if n_code != N_CONTAINERS:
        raise SystemExit("expected %d code containers in FULL.BIN, found %d"
                         % (N_CONTAINERS, n_code))
    with open(os.path.join(a.out, "patch_version.bin"), "wb") as o:
        o.write(PATCH_VERSION)
    print("   %d code containers (disc form), %d data files, patch_version.bin"
          % (n_code, n_data))

    if a.pem:
        shutil.copyfile(a.pem, os.path.join(a.out, "FRES", "BOMBREG.PEM"))
        print("   FRES/BOMBREG.PEM <- %s" % a.pem)
    if a.tsv:
        files_bin = os.path.join(a.out, "FILES.BIN")
        tmp = files_bin + ".en"
        if bombtext.cmd_msg_build(files_bin, a.tsv, tmp) != 0:
            raise SystemExit("FILES.BIN translation failed")
        os.replace(tmp, files_bin)
        print("   FILES.BIN messages <- %s" % a.tsv)
    print("== install tree ready: %s" % a.out)


if __name__ == "__main__":
    main()
