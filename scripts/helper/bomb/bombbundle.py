#!/usr/bin/env python3
"""bombbundle.py - drive-neutral <-> drive-form for Net de Bomberman containers.

Same engine as Nobunaga's dnasbundle (the DNAS2 record layout is shared), but
this title's containers are named *.BIN (MAIN.BIN, MODULE.BIN, DATA0/*.BIN),
which dnasbundle's extension filter does not match.

    python3 bombbundle.py neutralize <tree> <out> --hddid FILE
    python3 bombbundle.py seal       <tree> <out> --hddid FILE
    python3 bombbundle.py verify     <tree>       --hddid FILE
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The DNAS2 container engine: Nobunaga's tools, carried with this package
# (same record layout; see bomb/HANDOFF and FACTS.md for the verification).
_LIB = os.environ.get("NOBU_TOOLS") or os.path.join(HERE, "lib")
sys.path.insert(0, _LIB)
import dnasbundle  # noqa: E402

FOUR = "00001301"


def is_bomb_container(blob):
    return dnasbundle.is_container(blob)


def _walk(tree):
    for dp, _, fs in os.walk(tree):
        for f in fs:
            yield os.path.join(dp, f), os.path.relpath(os.path.join(dp, f), tree)


def map_tree(src, dst, fn):
    n_c = n_f = 0
    for path, rel in _walk(src):
        out = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        blob = open(path, "rb").read()
        if is_bomb_container(blob):
            open(out, "wb").write(fn(blob))
            n_c += 1
        else:
            shutil.copyfile(path, out)
            n_f += 1
    return n_c, n_f


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=("neutralize", "seal", "verify"))
    ap.add_argument("src")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--hddid", required=True)
    ap.add_argument("--four", default=FOUR)
    a = ap.parse_args()
    from dnasdec import ata_material
    ata32 = ata_material(open(a.hddid, "rb").read())
    four = bytes.fromhex(a.four)

    if a.mode == "verify":
        bad = same = 0
        for path, rel in _walk(a.src):
            blob = open(path, "rb").read()
            if not is_bomb_container(blob):
                continue
            if dnasbundle.seal(dnasbundle.neutralize(blob, ata32, four), ata32, four) == blob:
                same += 1
            else:
                bad += 1
                print("  ROUND-TRIP FAILS:", rel)
        print("round-trip: %d containers OK, %d bad" % (same, bad))
        return

    if not a.out:
        raise SystemExit("neutralize/seal need an output tree")
    fn = (lambda b: dnasbundle.neutralize(b, ata32, four)) if a.mode == "neutralize" \
        else (lambda b: dnasbundle.seal(b, ata32, four))
    n_c, n_f = map_tree(a.src, a.out, fn)
    print("%sd %d containers, copied %d other files -> %s" % (a.mode, n_c, n_f, a.out))


if __name__ == "__main__":
    main()
