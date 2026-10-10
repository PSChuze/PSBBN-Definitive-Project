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


def write_spoof_netcnf(device, pfsshell, work, partition="__sysconf",
                       remote_dir="etc/bnnetwork", name="netcnf000.dat"):
    """Write the spoof-keyed DHCP netcnf into __sysconf. Raises on a put error."""
    stage = os.path.join(work, "ncstage")
    os.makedirs(stage, exist_ok=True)
    with open(os.path.join(stage, name), "wb") as f:
        f.write(netcnf.build(NETCNF_SPOOF_ID))
    base = ["device %s" % device, "mount %s" % partition,
            'lcd "%s"' % stage.replace("\\", "/")]
    for part in remote_dir.split("/"):
        if part:
            base.append("cd %s" % part)
    for tail in (["rm %s" % name], ["put %s" % name]):   # rm is best-effort
        script = "\n".join(base + tail + ["umount", "exit", ""])
        proc = subprocess.run([pfsshell], input=script, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if tail[0].startswith("put") and ("Exit code is" in (proc.stdout or "")
                                          or proc.returncode):
            raise RuntimeError(proc.stdout or "")


def netcnf_step(device, pfsshell, work):
    """write_spoof_netcnf, but never fatal: prints a line and swallows errors."""
    try:
        write_spoof_netcnf(device, pfsshell, work)
        print("== netcnf: wrote spoof-keyed DHCP config to __sysconf (network fix)")
    except Exception as e:
        print("== netcnf: could not write __sysconf config (%r); run Fix network "
              "settings from the HDD Games menu" % e)
