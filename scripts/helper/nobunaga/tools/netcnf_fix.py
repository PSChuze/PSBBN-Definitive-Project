#!/usr/bin/env python3
"""Repair the network config on a PSBBN/HOSDMenu drive so the games stop showing
the "PlayStation BB Unit may have been connected to another PlayStation 2 / redo
network settings" screen.

The config (__sysconf/etc/bnnetwork/netcnf000.dat) is scrambled with a key
derived from the console's i.Link ID; the games refuse it when the recorded ID
does not match the console. We read the config the console already wrote,
recover its i.Link from the fixed SCE header (netcnf.recover), and write back a
plain DHCP-over-Ethernet config scrambled for that SAME i.Link. Nothing about
the console changes -- the config is simply re-keyed to a known-good DHCP body.

If no config exists yet, or it is too damaged to recover, pass --ilink with the
console's i.Link (16 hex digits) and a DHCP config is built for it directly.

The drive is touched only with --apply; without it the plan is printed. The
original config is copied to <work>/netcnf000.dat.bak before it is replaced.

  python netcnf_fix.py --device /dev/sdX --pfsshell "<PFS Shell.elf>" \
      --work /tmp/ncfix [--ilink 0700001ad5910c10] [--apply]

Exit codes: 0 ok, 3 config present but i.Link unrecoverable, 4 no config on the
drive (both mean: ask the user for --ilink).
"""
import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netcnf  # noqa: E402  (sibling module, same directory)


def run_pfsshell(pfsshell, cwd, lines):
    """Feed one command script to PFS Shell; raise on its error marker."""
    script = "\n".join(lines + ["exit", ""])
    proc = subprocess.run(
        [pfsshell], input=script, text=True, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout or ""
    if "Exit code is" in out or proc.returncode != 0:
        raise RuntimeError("PFS Shell error:\n" + out)
    return out


def cd_lines(device, partition, remote_dir, local_dir):
    # This PFS Shell build writes get/reads put from the dir set by `lcd`, not
    # the process cwd (see popninstall.py), so set it explicitly. Then cd into
    # the remote directory one level at a time (the proven idiom in
    # bombinstall.py's pfsshell_jobs).
    lines = ["device %s" % device, "mount %s" % partition,
             'lcd "%s"' % local_dir.replace("\\", "/")]
    for part in remote_dir.split("/"):
        if part:
            lines.append("cd %s" % part)
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", required=True, help="PS2 HDD block device, e.g. /dev/sdb")
    ap.add_argument("--pfsshell", default="pfsshell", help="path to PFS Shell.elf")
    ap.add_argument("--partition", default="__sysconf")
    ap.add_argument("--remote-dir", default="etc/bnnetwork")
    ap.add_argument("--name", default="netcnf000.dat")
    ap.add_argument("--work", required=True, help="scratch dir (must be space-free)")
    ap.add_argument("--ilink", help="console i.Link (16 hex digits); skips recovery")
    ap.add_argument("--apply", action="store_true", help="actually write to the drive")
    a = ap.parse_args()

    if " " in a.work:
        raise SystemExit("--work must be a space-free path (PFS Shell splits on whitespace)")
    os.makedirs(a.work, exist_ok=True)
    local = os.path.join(a.work, a.name)

    ilink = None
    if a.ilink:
        ilink = bytes.fromhex(a.ilink)
        if len(ilink) != 8:
            raise SystemExit("--ilink must be 16 hex digits (8 bytes)")

    # 1) Pull the config the console wrote (unless an i.Link was supplied).
    if ilink is None:
        if os.path.exists(local):
            os.remove(local)
        try:
            run_pfsshell(a.pfsshell, a.work,
                         cd_lines(a.device, a.partition, a.remote_dir, a.work) +
                         ["get %s" % a.name, "umount"])
        except RuntimeError as e:
            print(e, file=sys.stderr)
            print("could not read %s from %s on %s" % (a.name, a.remote_dir, a.partition),
                  file=sys.stderr)
            raise SystemExit(4)
        if not os.path.exists(local) or os.path.getsize(local) == 0:
            print("no %s on the drive" % a.name, file=sys.stderr)
            raise SystemExit(4)
        shutil.copyfile(local, local + ".bak")
        ilink = netcnf.recover(open(local, "rb").read())
        if ilink is None:
            print("found %s but could not recover the console i.Link from it" % a.name,
                  file=sys.stderr)
            raise SystemExit(3)

    print(ilink.hex())  # the recovered/accepted i.Link, for the caller to show

    # 2) Build a DHCP config keyed to that console and stage it.
    with open(local, "wb") as f:
        f.write(netcnf.build(ilink))
    # sanity: it must decode back to the known-good DHCP body on that console
    assert netcnf.decode(open(local, "rb").read(), ilink) == netcnf.DHCP_PROFILE

    if not a.apply:
        print("DRY RUN: staged %s (DHCP, i.Link %s). Re-run with --apply to write it."
              % (local, ilink.hex()), file=sys.stderr)
        return

    # 3) Write it back, replacing the old file in place. The rm is best-effort:
    # on the --ilink path there may be no file to remove, and put then creates it.
    try:
        run_pfsshell(a.pfsshell, a.work,
                     cd_lines(a.device, a.partition, a.remote_dir, a.work) + ["rm %s" % a.name, "umount"])
    except RuntimeError:
        pass
    run_pfsshell(a.pfsshell, a.work,
                 cd_lines(a.device, a.partition, a.remote_dir, a.work) + ["put %s" % a.name, "umount"])
    print("wrote %s to %s/%s on %s" % (a.name, a.remote_dir, a.name, a.partition),
          file=sys.stderr)


if __name__ == "__main__":
    main()
