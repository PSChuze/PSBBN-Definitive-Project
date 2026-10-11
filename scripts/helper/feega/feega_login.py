#!/usr/bin/env python3
"""Save a feega-ID and password on a PS2 drive so Net de Bomberman's Load button fills them in.

The game reads pfs2:/etc/feega/feega.dat (pfs2 = __sysconf) and never writes it; on Sony's PSBBN
the feega client's "Save feega-ID and Password" did. The file is keyed to the console i.Link ID the
game sees, which our loaders fix to the psbb spoof on every console (scefix >= 1.4), so one file
works on any console. Format: feegadat.py.

PSBBN's own feega client reads the same path with the console's real ID. A file it saved is kept
on the drive as feega.dat.psbbn; after this, PSBBN's Load no longer reads it.

The feega-ID comes from --id, the password from stdin (never the command line):

  printf '%s' "$pw" | python3 feega_login.py --device /dev/sdX --pfsshell "<PFS Shell.elf>" \\
      --work /tmp/feega --id FG1234567 [--apply] [--no-sudo]
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "nobunaga", "tools"))
import feegadat  # noqa: E402
import netcnf_fix  # noqa: E402  (run_pfsshell / cd_lines: the proven PFS Shell idiom)

PARTITION = "__sysconf"
REMOTE_DIR = "etc/feega"
NAME = "feega.dat"


def pfs(a, cwd, lines):
    return netcnf_fix.run_pfsshell(a.pfsshell, cwd, lines)


def fetch(a, into):
    """The drive's current feega.dat, or None."""
    os.makedirs(into, exist_ok=True)
    path = os.path.join(into, NAME)
    if os.path.exists(path):
        os.remove(path)
    try:
        pfs(a, into, netcnf_fix.cd_lines(a.device, PARTITION, REMOTE_DIR, into) + ["get %s" % NAME, "umount"])
    except RuntimeError:
        return None
    return open(path, "rb").read() if os.path.exists(path) else None


def put(a, stage_dir, name):
    try:
        pfs(a, stage_dir, netcnf_fix.cd_lines(a.device, PARTITION, REMOTE_DIR, stage_dir) + ["rm %s" % name, "umount"])
    except RuntimeError:
        pass
    pfs(a, stage_dir, netcnf_fix.cd_lines(a.device, PARTITION, REMOTE_DIR, stage_dir) + ["put %s" % name, "umount"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", required=True)
    ap.add_argument("--pfsshell", default="pfsshell")
    ap.add_argument("--work", required=True)
    ap.add_argument("--id", required=True, help="feega-ID")
    ap.add_argument("--ilink", help="key to this i.Link (16 hex) instead of the psbb spoof")
    ap.add_argument("--apply", action="store_true", help="actually write to the drive")
    ap.add_argument("--no-sudo", action="store_true", help="PFS Shell without sudo (image files)")
    a = ap.parse_args()
    if a.no_sudo:
        netcnf_fix.USE_SUDO = False

    password = sys.stdin.readline().rstrip("\r\n")
    feega_id = a.id.strip()
    ilink = bytes.fromhex(a.ilink) if a.ilink else feegadat.PSBB_ILINK
    try:
        blob = feegadat.build(feega_id, password, ilink)
    except (ValueError, UnicodeEncodeError) as ex:
        raise SystemExit("cannot save that login: %s" % ex)
    assert feegadat.parse(blob, ilink) == (feega_id, password)

    stage_dir = os.path.join(a.work, "stage")
    os.makedirs(stage_dir, exist_ok=True)
    with open(os.path.join(stage_dir, NAME), "wb") as f:
        f.write(blob)
    if not a.apply:
        print("DRY RUN: staged %s for %s" % (os.path.join(stage_dir, NAME), feega_id), file=sys.stderr)
        return

    old = fetch(a, os.path.join(a.work, "orig"))
    if old:
        try:
            print("replacing the saved login for %s" % feegadat.parse(old, ilink)[0], file=sys.stderr)
        except ValueError:
            # Not ours: PSBBN's own save (its console's real ID). Keep it beside ours.
            keep_dir = os.path.join(a.work, "keep")
            os.makedirs(keep_dir, exist_ok=True)
            with open(os.path.join(keep_dir, NAME + ".psbbn"), "wb") as f:
                f.write(old)
            put(a, keep_dir, NAME + ".psbbn")
            print("kept PSBBN's saved login as %s/%s.psbbn" % (REMOTE_DIR, NAME), file=sys.stderr)

    # A drive where nothing was ever saved has no etc/feega: create each level (an existing
    # level errors, so each is its own best-effort run).
    parts = REMOTE_DIR.split("/")
    for i in range(len(parts)):
        try:
            pfs(a, stage_dir, netcnf_fix.cd_lines(a.device, PARTITION, "/".join(parts[:i]), stage_dir) +
                ["mkdir %s" % parts[i], "umount"])
        except RuntimeError:
            pass
    put(a, stage_dir, NAME)

    got = fetch(a, os.path.join(a.work, "verify"))
    if got != blob:
        raise SystemExit("read-back of %s/%s %s" % (REMOTE_DIR, NAME, "missing" if got is None else "differs"))
    print("saved the feega login for %s to %s:%s/%s" % (feega_id, PARTITION, REMOTE_DIR, NAME), file=sys.stderr)


if __name__ == "__main__":
    main()
