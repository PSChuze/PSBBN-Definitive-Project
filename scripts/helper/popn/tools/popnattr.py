"""Build a pop'n Puzzle Dama Online attr-area.bin for PP.BLJA-00010 + 0x1000.

Uses the disc's own icon (ICON/NORMAL.ICO) and a boot block pointing at
`pfs:/dnasload.elf` with product `BLJA-00010`, exactly like the retail
install and Nobunaga's OSD title tool.

    python3 popnattr.py --disc <disc-root> --out popn-attr-area.bin \\
        [--helper <toolkit>/scripts/helper] \\
        [--title0 "pop'n Puzzle Dama Online"] [--title1 ""]

Requires the PlayOnline toolkit's `playonline.attrarea` on the import path,
either through --helper or PYTHONPATH.
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_TITLE0 = "pop'n Puzzle Dama Online"
DEFAULT_TITLE1 = ""

def _load_attrarea(helper):
    if helper and helper not in sys.path:
        sys.path.insert(0, helper)
    for _p in (r"E:\Code\PlayOnline Project\psbbn-playonline\scripts\helper",
               "/mnt/e/Code/PlayOnline Project/psbbn-playonline/scripts/helper"):
        if os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(0, _p)
    from playonline import attrarea
    return attrarea

def build(disc_root, title0, title1, attrarea):
    icon_path = os.path.join(disc_root, "ICON", "NORMAL.ICO")
    icon = open(icon_path, "rb").read()
    boot = attrarea.build_boot_block("BLJA-00010", "1.00", "pfs:/dnasload.elf")
    # ASCII for the Latin title; the FFXI/POL family uses UTF-8 for Japanese
    # titles but ASCII is compatible everywhere for a Latin string.
    icon_sys = attrarea.build_icon_sys(title0, title1, encoding="ascii", spaced=True)
    area = attrarea.build_area(boot, icon_sys, icon)
    return area, len(boot), len(icon_sys), len(icon)

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--disc", required=True, help="extracted disc root (must contain ICON/NORMAL.ICO)")
    ap.add_argument("--out", default=os.path.join(_HERE, "popn-attr-area.bin"))
    ap.add_argument("--helper", default=None, help="toolkit scripts/helper for playonline.attrarea")
    ap.add_argument("--title0", default=DEFAULT_TITLE0)
    ap.add_argument("--title1", default=DEFAULT_TITLE1)
    a = ap.parse_args()
    attrarea = _load_attrarea(a.helper)
    area, n_boot, n_icon_sys, n_icon = build(a.disc, a.title0, a.title1, attrarea)
    open(a.out, "wb").write(area)
    print("wrote %s (%d bytes)  title0=%r" % (a.out, len(area), a.title0))
    print("  boot=%d B  icon_sys=%d B  icon=%d B" % (n_boot, n_icon_sys, n_icon))

if __name__ == "__main__":
    main()
