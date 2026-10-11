#!/usr/bin/env python3
"""Repair the network config on a PSBBN/HOSDMenu drive so the games stop showing
the "PlayStation BB Unit may have been connected to another PlayStation 2 / redo
network settings" screen.

The config (__sysconf/etc/bnnetwork/netcnf000.dat) is scrambled with a key
derived from an i.Link ID, and the games decode it with the i.Link the loader
serves to the NETCNF module. Our loaders (scefix >= 1.4 and the other titles'
equivalents) serve the FIXED psbb spoof i.Link to NETCNF on every console -- the
same spoof the DNAS binding check already uses -- so a netcnf keyed to that
spoof decodes on any console. We simply write such a netcnf: a plain
DHCP-over-Ethernet config scrambled for the psbb spoof ID.

This is console-agnostic: no per-console i.Link is needed. (Earlier revisions
tried to recover the console's own i.Link from the existing file and re-key to
it; that was the wrong model -- the file is keyed to whoever BUILT the drive,
not the console it runs on, so it broke the moment a drive moved between
consoles. The loader change is what makes the fixed-spoof key correct.)

Pass --ilink to key the config to a specific i.Link instead of the spoof (for a
loader that still serves a real/other ID to NETCNF). The drive is touched only
with --apply; without it the plan is printed. The existing config, if any, is
backed up to <work>/netcnf000.dat.bak first.

  python netcnf_fix.py --device /dev/sdX --pfsshell "<PFS Shell.elf>" \
      --work /tmp/ncfix [--ilink 0700001ad5910c10] [--apply]
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netcnf  # noqa: E402  (sibling module, same directory)

# The psbb console i.Link the loaders serve to NETCNF on every console. Must
# match scefix's SPOOF_ID (work/launcher/scefix/scefix.c) and the equivalent in
# the other titles' loaders.
SPOOF_ID = bytes.fromhex("0700001ad5910c10")

USE_SUDO = True  # a real /dev/sdX is a block device: pfsshell needs root for it


def run_pfsshell(pfsshell, cwd, lines):
    """Feed one command script to PFS Shell; raise on its error marker."""
    script = "\n".join(lines + ["exit", ""])
    cmd = (["sudo"] if USE_SUDO else []) + [pfsshell]
    proc = subprocess.run(
        cmd, input=script, text=True, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout or ""
    if "Exit code is" in out or proc.returncode != 0:
        raise RuntimeError("PFS Shell error:\n" + out)
    return out


def cd_lines(device, partition, remote_dir, local_dir):
    # This PFS Shell build writes get/reads put from the dir set by `lcd`, not
    # the process cwd (see popninstall.py), so set it explicitly. Then cd into
    # the remote directory one level at a time (the proven idiom in
    # bombinstall.py's pfsshell_jobs). Quoted lcd handles spaces, so a toolkit
    # under ".../PlayOnline Project/..." is fine.
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
    ap.add_argument("--also-dir", default="etc/openlobby",
                    help="more __sysconf dirs to write the same config to, comma "
                    "separated (default: Bomberman's own copy); '' for none")
    ap.add_argument("--work", required=True, help="scratch dir")
    ap.add_argument("--ilink", help="key the config to this i.Link (16 hex) instead "
                    "of the psbb spoof")
    ap.add_argument("--dns", help="static DNS server (dotted-quad) to point the games "
                    "at our DNS; omit for auto DNS (DHCP)")
    ap.add_argument("--apply", action="store_true", help="actually write to the drive")
    ap.add_argument("--no-sudo", action="store_true",
                    help="do not run PFS Shell under sudo (for testing on an image file)")
    a = ap.parse_args()

    global USE_SUDO
    if a.no_sudo:
        USE_SUDO = False

    ilink = SPOOF_ID
    if a.ilink:
        ilink = bytes.fromhex(a.ilink)
        if len(ilink) != 8:
            raise SystemExit("--ilink must be 16 hex digits (8 bytes)")

    # The fetched backup and the staged file live in separate dirs: PFS Shell
    # runs under sudo, so a file it `get`s is root-owned and building over it
    # would EACCES; separate dirs also keep the basename `put` needs without a
    # collision.
    orig_dir = os.path.join(a.work, "orig")
    stage_dir = os.path.join(a.work, "stage")
    os.makedirs(orig_dir, exist_ok=True)
    os.makedirs(stage_dir, exist_ok=True)
    staged = os.path.join(stage_dir, a.name)

    # Best-effort backup of whatever is on the drive now (never fatal).
    try:
        run_pfsshell(a.pfsshell, orig_dir,
                     cd_lines(a.device, a.partition, a.remote_dir, orig_dir) +
                     ["get %s" % a.name, "umount"])
    except RuntimeError:
        pass

    # Build a DHCP config keyed to the serve-time i.Link and stage it. With
    # --dns, it uses that static DNS server (points the games at our DNS so
    # they resolve the service hostnames to our servers); build() verifies the
    # round-trip internally.
    with open(staged, "wb") as f:
        f.write(netcnf.build(ilink, dns=a.dns))
    print(ilink.hex())

    if not a.apply:
        print("DRY RUN: staged %s (DHCP, i.Link %s). Re-run with --apply to write it."
              % (staged, ilink.hex()), file=sys.stderr)
        return

    # The configured dir (PSBBN's etc/bnnetwork, read by Minna and pop'n) and
    # Bomberman's own copy (its loader points the game at etc/openlobby, so
    # PSBBN's real-keyed file can stay as it is).
    dirs = [a.remote_dir] + [d for d in a.also_dir.split(",") if d and d != a.remote_dir]
    for remote_dir in dirs:
        # A drive whose network was never set up from PSBBN has no etc/bnnetwork,
        # and every cd into it fails. Create each level first; mkdir of a level
        # that exists errors, so each one is its own best-effort run.
        parts = [p for p in remote_dir.split("/") if p]
        for i in range(len(parts)):
            try:
                run_pfsshell(a.pfsshell, stage_dir,
                             cd_lines(a.device, a.partition, "/".join(parts[:i]), stage_dir) +
                             ["mkdir %s" % parts[i], "umount"])
            except RuntimeError:
                pass

        # Write it back, replacing any existing file. The rm is best-effort (there
        # may be none to remove; put then creates it).
        try:
            run_pfsshell(a.pfsshell, stage_dir,
                         cd_lines(a.device, a.partition, remote_dir, stage_dir) + ["rm %s" % a.name, "umount"])
        except RuntimeError:
            pass
        run_pfsshell(a.pfsshell, stage_dir,
                     cd_lines(a.device, a.partition, remote_dir, stage_dir) + ["put %s" % a.name, "umount"])

        # Read it back from where the games look and compare.
        verify_dir = os.path.join(a.work, "verify")
        os.makedirs(verify_dir, exist_ok=True)
        got_path = os.path.join(verify_dir, a.name)
        if os.path.exists(got_path):
            os.remove(got_path)
        run_pfsshell(a.pfsshell, verify_dir,
                     cd_lines(a.device, a.partition, remote_dir, verify_dir) +
                     ["get %s" % a.name, "umount"])
        want = open(staged, "rb").read()
        got = open(got_path, "rb").read() if os.path.exists(got_path) else None
        if got != want:
            raise SystemExit("read-back of %s/%s %s" % (
                remote_dir, a.name, "missing" if got is None else "differs from what was written"))
        print("wrote %s to %s/%s on %s" % (a.name, remote_dir, a.name, a.partition),
              file=sys.stderr)


if __name__ == "__main__":
    main()
