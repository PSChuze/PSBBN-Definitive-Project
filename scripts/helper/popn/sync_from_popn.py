#!/usr/bin/env python3
"""Refresh the toolkit's bundled pop'n tools/translation from the pop'n repo.

    python3 scripts/helper/popn/sync_from_popn.py "<...>/Pop'N Puzzle Dama Online/popn"
    python3 scripts/helper/popn/sync_from_popn.py <popn> --check   # report only

Copies the files the installer's English path runs (texture codec + renderer,
screen modules, boot-ELF patcher, string table) into helper/popn/ with the same
tools/ + translation/ layout, converting CRLF to LF (the repo stores *.py as LF).
translation/screens/ is mirrored: a .py removed upstream is removed here too.
The string table is also copied to assets/popn/elf.en.tsv, the copy
Popn-Installer.sh passes to --translate. Prints what changed; never commits.
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))           # scripts/helper/popn
ASSETS = os.path.normpath(os.path.join(HERE, "..", "..", "assets", "popn"))

TOOLS = ["pntexnat.py", "pnimage.py", "patch_boot_elf.py", "pntext.py"]
TRANSLATION = ["apply_textures_nat.py", "apply_textures.py", "elf.en.tsv"]


def plan(popn):
    pairs = [(os.path.join(popn, "tools", f), os.path.join(HERE, "tools", f)) for f in TOOLS]
    pairs += [(os.path.join(popn, "translation", f), os.path.join(HERE, "translation", f))
              for f in TRANSLATION]
    pairs.append((os.path.join(popn, "translation", "elf.en.tsv"),
                  os.path.join(ASSETS, "elf.en.tsv")))
    src_screens = os.path.join(popn, "translation", "screens")
    for p in sorted(glob.glob(os.path.join(src_screens, "*.py"))
                    + glob.glob(os.path.join(src_screens, "README.md"))):
        pairs.append((p, os.path.join(HERE, "translation", "screens", os.path.basename(p))))
    upstream = {os.path.basename(p) for p in glob.glob(os.path.join(src_screens, "*.py"))}
    stale = [p for p in glob.glob(os.path.join(HERE, "translation", "screens", "*.py"))
             if os.path.basename(p) not in upstream]
    return pairs, stale


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("popn", help="the pop'n repo's popn/ folder (has tools/ and translation/)")
    ap.add_argument("--check", action="store_true", help="only report differences")
    a = ap.parse_args()
    if not os.path.isfile(os.path.join(a.popn, "translation", "apply_textures_nat.py")):
        sys.exit("%s does not look like the popn/ folder" % a.popn)
    pairs, stale = plan(a.popn)
    changed = 0
    for src, dst in pairs:
        if not os.path.isfile(src):
            sys.exit("missing upstream: %s" % src)
        data = open(src, "rb").read().replace(b"\r\n", b"\n")
        old = open(dst, "rb").read() if os.path.isfile(dst) else None
        if old == data:
            continue
        changed += 1
        print("%s %s" % ("new    " if old is None else "update ", os.path.relpath(dst, HERE)))
        if not a.check:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(data)
    for p in stale:
        changed += 1
        print("remove  %s" % os.path.relpath(p, HERE))
        if not a.check:
            os.remove(p)
    print("%d file(s) %s" % (changed, "differ" if a.check else "synced"))


if __name__ == "__main__":
    main()
