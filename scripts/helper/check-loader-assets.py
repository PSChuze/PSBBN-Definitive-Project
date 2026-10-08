#!/usr/bin/env python3
"""Audit every shipped loader asset against the hardware contract.

    python3 scripts/helper/check-loader-assets.py [--hwaudit PATH] [--keys PS2KEYS.dat]
                                                  [--report-only TITLE ...] [--json OUT]

Runs nobunaga/tools/hwaudit.py --loader (read-only) on each loader the
toolkit ships:

    scripts/assets/nobunaga/*.kelf
    scripts/assets/popn/*.kelf
    scripts/assets/mingol/*.kelf
    scripts/assets/bomb/bootfiles/bombload.elf, bombload.kelf

(.bak-* copies are skipped) and prints, per file: DRIVERS mode, IOPRP
version (an unfilled polbbnexec has an empty slot: the installer fills the
title's own image per drive), the sceCdRI spoof id, the scefix version
(Bomberman), the fill-time trace slot (TRACELBA, polbbnexec v4) and, for
Minna, the ROM SYSMEM splice state.

Exit status 1 when any rule fails (PLAN-hw-boot-all-titles section 2):
  - Nobunaga, pop'n: not DRIVERS=4 (ps2sdk atad, no genuine-drive gate)
  - Bomberman: scefix older than 1.2, or no sceCdRI spoof
  - Minna: the BIOS-ROM SYSMEM splice enabled (it hung on real hardware on
    2026-10-08). Detected by the "splice DISABLED" string: a ROM_SYSMEM=0
    build carries it (the splice code itself is compiled out), an enabled
    build does not (and carries "walking ROMDIR" instead)
  - a polbbnexec loader without exactly one TRACELBA slot (bombload is a
    different loader family with no fill-time slot: reported, not failed)
--report-only TITLE turns that title's failures into notes (e.g. an asset
another session is rebuilding). hwaudit.py lives in the Nobunaga project
(nobunaga/tools); --hwaudit or $HWAUDIT points at it.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ASSETS = os.path.join(SCRIPTS, "assets")
TOOLKIT = os.path.dirname(SCRIPTS)

HWAUDIT_CANDIDATES = [
    os.environ.get("HWAUDIT"),
    os.path.join(TOOLKIT, "..", "..", "Nobunaga Online", "nobunaga", "tools", "hwaudit.py"),
    r"D:\Code\Nobunaga Online\nobunaga\tools\hwaudit.py",
    r"E:\Code\Nobunaga Online\nobunaga\tools\hwaudit.py",
    "/mnt/d/Code/Nobunaga Online/nobunaga/tools/hwaudit.py",
    "/mnt/e/Code/Nobunaga Online/nobunaga/tools/hwaudit.py",
]
KEYS_CANDIDATES = [os.environ.get("PS2KEYS"), os.path.expanduser("~/PS2KEYS.dat"),
                   r"D:\PS2HDDs\PS2KEYS.dat", r"E:\ps2hdd\PS2KEYS.dat",
                   "/mnt/d/PS2HDDs/PS2KEYS.dat", "/mnt/e/ps2hdd/PS2KEYS.dat"]

TRACE_MAGIC = b"TRACELBA"
SPLICE_OFF = b"splice DISABLED"
SPLICE_ON = b"walking ROMDIR"


def assets():
    out = []
    for title, pattern in (("nobunaga", "nobunaga/*.kelf"), ("popn", "popn/*.kelf"),
                           ("mingol", "mingol/*.kelf"),
                           ("bomb", "bomb/bootfiles/bombload.elf"),
                           ("bomb", "bomb/bootfiles/bombload.kelf")):
        for p in sorted(glob.glob(os.path.join(ASSETS, pattern))):
            out.append((title, p))
    return out


def first(paths, what):
    for p in paths:
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


def plain_body(blob):
    """The bytes the string checks run on. Every loader we ship is an ELF or a
    polkelf 2-block KELF, whose content is plaintext after its first 32 bytes,
    so the file itself is searched."""
    return blob


def audit(hwaudit, path, keys):
    cmd = [sys.executable, hwaudit, "--loader", path, "--helper", HERE]
    if keys:
        cmd += ["--keys", keys]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("hwaudit failed: %s" % r.stderr.decode("utf-8", "replace")[-300:])
    return json.loads(r.stdout.decode("utf-8"))


def drivers_mode(s):
    s = (s or "").strip()
    return s.split()[0] if s else "?"


def check(title, path, a, blob):
    """(row dict, [failures])"""
    fails = []
    fam = a.get("family") or "?"
    drv = drivers_mode(a.get("drivers"))
    io = a.get("ioprp") or {}
    if io.get("version"):
        iov = io["version"]
    elif io.get("error") == "IOPRP slot empty" or io.get("len") == 0:
        iov = "slot empty (filled per drive)"
    else:
        iov = io.get("error") or "?"
    spoof = [k for k, v in (a.get("spoof_ilink") or {}).items() if v]
    sce = a.get("scefix") or {}
    scev = sce.get("version")
    ntrace = blob.count(TRACE_MAGIC)
    row = dict(title=title, file=os.path.relpath(path, SCRIPTS).replace(os.sep, "/"),
               sha1=(a.get("sha1") or "")[:8], form=(a.get("form") or "?").split(" (")[0],
               family=fam, drivers=drv, ioprp=iov, spoof=", ".join(spoof) or "none",
               scefix=scev or "-", trace_slots=ntrace)
    baked = [c["lba"] for c in (a.get("trace") or {}).get("constants_found", [])]
    if baked:
        row["trace_baked_lba"] = baked

    if title in ("nobunaga", "popn") and drv != "4":
        fails.append("DRIVERS=%s, must be 4 (ps2sdk atad; gate 4)" % drv)
    if title == "bomb":
        if not scev or tuple(int(x) for x in scev.split(".")) < (1, 2):
            fails.append("scefix %s, must be >= 1.2 (console-ID split)" % (scev or "missing"))
        if not sce.get("spoof_cdri") or not spoof:
            fails.append("no sceCdRI spoof (gate 7)")
    if title == "mingol":
        on, off = SPLICE_ON in blob, SPLICE_OFF in blob
        row["rom_sysmem"] = "off" if off and not on else "ON (no splice-DISABLED string)"
        if not off:
            fails.append("ROM SYSMEM splice enabled or undetectable (no '%s'; hung on HW "
                         "2026-10-08, build with ROM_SYSMEM=0)" % SPLICE_OFF.decode())
    if fam == "polbbnexec":
        if ntrace != 1:
            fails.append("%d TRACELBA slot(s), want exactly 1 (v4 fill-time trace slot)%s"
                         % (ntrace, "; trace LBA baked in: %s" % baked if baked else ""))
        row["trace"] = "slot ok" if ntrace == 1 else "MISSING" if not ntrace else "x%d" % ntrace
    else:
        row["trace"] = "n/a (%s)" % fam
    return row, fails


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--hwaudit", help="nobunaga/tools/hwaudit.py")
    ap.add_argument("--keys", help="PS2KEYS.dat (KELF signature check); optional")
    ap.add_argument("--report-only", action="append", default=[], metavar="TITLE",
                    choices=("nobunaga", "popn", "mingol", "bomb"),
                    help="report this title's failures without failing the run")
    ap.add_argument("--json", help="write the rows here")
    a = ap.parse_args(argv)
    hw = first([a.hwaudit] + HWAUDIT_CANDIDATES, "hwaudit")
    if not hw:
        raise SystemExit("hwaudit.py not found: pass --hwaudit or set HWAUDIT")
    keys = first([a.keys] + KEYS_CANDIDATES, "keys")
    rows, bad = [], 0
    for title, path in assets():
        blob = open(path, "rb").read()
        try:
            au = audit(hw, path, keys)
        except Exception as e:
            print("FAIL %-8s %s: %s" % (title, path, e))
            bad += 1
            continue
        row, fails = check(title, path, au, plain_body(blob))
        rows.append(dict(row, failures=fails))
        verdict = "ok  " if not fails else ("NOTE" if title in a.report_only else "FAIL")
        print("%s %-8s %-48s %s" % (verdict, title, row["file"], row["sha1"]))
        print("       %s %s | DRIVERS %s | IOPRP %s | spoof %s | scefix %s | trace %s%s"
              % (row["form"], row["family"], row["drivers"], row["ioprp"], row["spoof"],
                 row["scefix"], row["trace"],
                 " | rom sysmem %s" % row["rom_sysmem"] if "rom_sysmem" in row else ""))
        for f in fails:
            print("       - %s" % f)
        if fails and title not in a.report_only:
            bad += 1
    if a.json:
        with open(a.json, "w") as f:
            json.dump(rows, f, indent=1)
    print("%d loader asset(s), %d failing%s" % (len(rows), bad,
          " (report-only: %s)" % ", ".join(a.report_only) if a.report_only else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
