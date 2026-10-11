#!/usr/bin/env python3
"""Shared installer step: write the spoof-keyed BB network config to __sysconf.

The games decode __sysconf/etc/bnnetwork/netcnf000.dat with the i.Link the
loader serves to the EE's sceCdRI read at the network stage. Our loaders spoof
that read to the fixed psbb console id on every console, so a netcnf keyed to it
decodes anywhere and the game stops reporting "connected to another
PlayStation 2 / redo network settings" (confirmed on a tester's hardware,
2026-10-10). Each game installer calls write_spoof_netcnf on both the fresh and
the update path (a reinstall is almost always an update). The config is shared
in __sysconf, so every title writes the same psbb-keyed file; it is idempotent.

The installers run as root, so PFS Shell needs no sudo here (matching the game
partition writes). NETCNF_SPOOF_ID must match the loaders' SPOOF_ID
(work/launcher/scefix/scefix.c and the atadpatch loaders).
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netcnf  # noqa: E402  (sibling module)

NETCNF_SPOOF_ID = bytes.fromhex("0700001ad5910c10")


def _pfs(pfsshell, lines):
    proc = subprocess.run([pfsshell], input="\n".join(lines + ["umount", "exit", ""]),
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.stdout or ""


def write_spoof_netcnf(device, pfsshell, work, partition="__sysconf",
                       remote_dir="etc/bnnetwork", name="netcnf000.dat"):
    """Write the spoof-keyed DHCP netcnf into __sysconf, then read it back.

    Creates etc/bnnetwork when the drive has none (a drive whose network was
    never set up from PSBBN): without it a failed `cd` left the put in the
    parent directory, where no game looks, and the step still reported
    success. Raises unless the file read back from <remote_dir>/<name> is
    byte-identical and decodes with NETCNF_SPOOF_ID."""
    stage = os.path.join(work, "ncstage")
    back = os.path.join(work, "ncverify")
    os.makedirs(stage, exist_ok=True)
    os.makedirs(back, exist_ok=True)
    want = netcnf.build(NETCNF_SPOOF_ID)
    with open(os.path.join(stage, name), "wb") as f:
        f.write(want)
    path = ["device %s" % device, "mount %s" % partition]
    for part in remote_dir.split("/"):
        if part:
            path += ["mkdir %s" % part, "cd %s" % part]   # mkdir fails harmlessly if present
    _pfs(pfsshell, path + ['lcd "%s"' % stage.replace("\\", "/"), "rm %s" % name])   # best-effort
    out = _pfs(pfsshell, path + ['lcd "%s"' % stage.replace("\\", "/"), "put %s" % name])
    got_path = os.path.join(back, name)
    if os.path.exists(got_path):
        os.remove(got_path)
    cd = ["device %s" % device, "mount %s" % partition] + \
         ["cd %s" % p for p in remote_dir.split("/") if p]
    _pfs(pfsshell, cd + ['lcd "%s"' % back.replace("\\", "/"), "get %s" % name])
    got = open(got_path, "rb").read() if os.path.exists(got_path) else None
    if got != want or not netcnf.decode(got, NETCNF_SPOOF_ID).startswith(netcnf.MAGIC):
        raise RuntimeError("read-back of %s/%s %s; pfsshell said: %s" % (
            remote_dir, name, "missing" if got is None else "differs", out[-400:]))


def netcnf_step(device, pfsshell, work):
    """write_spoof_netcnf, but never fatal: prints a line and swallows errors."""
    try:
        write_spoof_netcnf(device, pfsshell, work)
        print("== netcnf: wrote spoof-keyed DHCP config to __sysconf and read it back (network fix)")
    except Exception as e:
        print("== netcnf: could not write __sysconf config (%r); run Fix network "
              "settings from the HDD Games menu" % e)
