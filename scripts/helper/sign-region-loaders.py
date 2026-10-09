#!/usr/bin/env python3
"""Sign the US and all-regions copies of every shipped title loader.

    python3 scripts/helper/sign-region-loaders.py [--keys PS2KEYS.dat] [--check]

A KELF's header carries a MagicGate region mask (MGZones, +0x1C), and a
console opens a KELF only when its own region's bit is set there. Every title
loader in this toolkit was signed with the header of Nobunaga's own
dnasload.elf (AppType 0x0B, MGZones 0x01): it opens on a Japanese console and
nowhere else. A US or European console drops it back to the browser with
nothing drawn.

The PlayOnline step solved the same problem with one loader per console
region (PlayOnline-Installer.sh, the console question): the Japanese build,
polbbnexec-us.kelf signed with the header of Square Enix's US dnasload.elf
(AppType 0x0B, MGZones 0x02, proven on a US console), and
polbbnexec-all.kelf, the Japanese header with all eight region bits
(AppType 0x01, MGZones 0xFF, proven on a console from outside the US and
Japan). This signs each title loader the same way, from the content the
shipped Japanese file already carries:

    <name>.kelf        Japanese console (unchanged)
    <name>-us.kelf     US console        header of assets/playonline/polbbnexec-us.kelf
    <name>-all.kelf    any other console header of assets/playonline/polbbnexec-all.kelf

Only the 32-byte header (and the signatures and wrapped keys that follow from
it) differs; the content, filled per drive by each title's installer, is
byte-identical. Every output is verified with the same keys before it is
written, and --check writes nothing: it fails when a variant is missing or
was signed from other content.
"""
import argparse
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ASSETS = os.path.join(SCRIPTS, "assets")
sys.path.insert(0, os.path.join(HERE, "playonline", "lib"))
import polkelf  # noqa: E402

# The Japanese loader of each title: the one the installers already pick.
LOADERS = [
    "nobunaga/polbbnexec-inputpatch.kelf",
    "nobunaga/polbbnexec-nobu-verbose.kelf",
    "nobunaga/polbbnexec-nobu-ja.kelf",
    "nobunaga/polbbnexec-nobu-ja-verbose.kelf",
    "popn/polbbnexec-popn.kelf",
    "popn/polbbnexec-popn-verbose.kelf",
    "mingol/polbbnexec-mingol.kelf",
    "mingol/polbbnexec-mingol-verbose.kelf",
    "bomb/bootfiles/bombload.kelf",
    "bomb/bootfiles-debug/bombload.kelf",
]
# region -> (header template, MGZones the result must carry)
TEMPLATES = {
    "us": ("playonline/polbbnexec-us.kelf", 0x02),
    "all": ("playonline/polbbnexec-all.kelf", 0xFF),
}
KEYS_CANDIDATES = [os.environ.get("PS2KEYS"), os.path.expanduser("~/PS2KEYS.dat"),
                   r"D:\PS2HDDs\PS2KEYS.dat", r"E:\ps2hdd\PS2KEYS.dat",
                   "/mnt/d/PS2HDDs/PS2KEYS.dat", "/mnt/e/ps2hdd/PS2KEYS.dat"]


def variant(path, region):
    base, ext = os.path.splitext(path)
    return "%s-%s%s" % (base, region, ext)


def header(blob):
    _cs, _hs, _st, app, _fl, _bc, zones = struct.unpack_from("<IHBBHHI", blob, 16)
    return app, zones


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--keys", help="PS2KEYS.dat (or $PS2KEYS)")
    ap.add_argument("--check", action="store_true",
                    help="verify the variants on disk, write nothing")
    a = ap.parse_args(argv)
    keys = next((p for p in [a.keys] + KEYS_CANDIDATES if p and os.path.isfile(p)), None)
    if not keys:
        raise SystemExit("PS2KEYS.dat not found: pass --keys or set PS2KEYS")
    ks = polkelf.load_keys(keys)
    # A selftest with the keys just signed with cannot catch a wrong keyset:
    # the PlayOnline loaders are console-proven, so they must verify first.
    for tpl, _z in TEMPLATES.values():
        polkelf.Kelf(open(os.path.join(ASSETS, tpl), "rb").read(), ks).parse(verify=True)
    bad = 0
    for rel in LOADERS:
        src = os.path.join(ASSETS, rel)
        blob = open(src, "rb").read()
        content = polkelf.Kelf(blob, ks).parse(verify=True).content()
        app, zones = header(blob)
        if polkelf.build_kelf(content, blob, ks) != blob:
            print("FAIL %s: does not re-sign to itself" % rel)
            bad += 1
            continue
        print("%-44s jp   AppType 0x%02X zones 0x%02X %s"
              % (rel, app, zones, hashlib.sha1(blob).hexdigest()[:8]))
        for region, (tpl, want) in sorted(TEMPLATES.items(), reverse=True):
            out_path = variant(src, region)
            template = open(os.path.join(ASSETS, tpl), "rb").read()
            out = polkelf.build_kelf(content, template, ks)
            if a.check:
                have = open(out_path, "rb").read() if os.path.isfile(out_path) else None
                if have != out:
                    print("FAIL %s: %s" % (os.path.relpath(out_path, ASSETS).replace(os.sep, "/"),
                                           "missing" if have is None else "not signed from this content"))
                    bad += 1
                    continue
            k = polkelf.Kelf(out, ks).parse(verify=True)
            vapp, vzones = header(out)
            if k.content() != content or vzones != want:
                raise SystemExit("selftest failed for %s" % out_path)
            if not a.check:
                with open(out_path, "wb") as f:
                    f.write(out)
            print("%-44s %-4s AppType 0x%02X zones 0x%02X %s"
                  % (os.path.relpath(out_path, ASSETS).replace(os.sep, "/"), region,
                     vapp, vzones, hashlib.sha1(out).hexdigest()[:8]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
