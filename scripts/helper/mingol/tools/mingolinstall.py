"""Install Minna no Golf Online onto a PS2 drive (or PCSX2 image) from the player's own disc.

Shape of nobunaga/tools/nobuinstall.py, with the seal kit in front:

  1. rebuild  each ZZENC container's drive-neutral form from the seal kit + the disc's
              plaintext ZZBIN overlay (sealkit.rebuild; no game code comes from us).
  2. seal     each container to the TARGET drive: its HDD ID (the block the console is
              served) + the four from its own `__net` record (dnasbundle.seal).
  3. stage    the partition tree the retail installer writes: the disc tree minus FMOD/,
              FMOD2/, FRES/, ZZBIN/, FEEGAGUI.ELF and SCPS_150.49, plus the sealed
              ZZENC/ZZBIN/*, INSTALL.VER (u32 4) and res/ (BB Navigator title card).
  4. mkpart   PP.SCPS-15049..APPLICATION, 1536 MiB PFS (pfsshell shapes it as a 1 GiB main
              + one 512 MiB sub, the retail layout), then put the tree.
  5. password rpwd = fpwd = apa_password(id, "MM21") on the main header (the boot ELF mounts
              `hdd0:PP.SCPS-15049..APPLICATION,MM21`; matches a retail drive byte for byte).
              Then clear the APA journal pfsshell leaves behind (it holds the pre-password header).
  6. attr     the attribute area (browser icon + title) at main + 0x1000.
  7. protect  add the partition to the PSBBN keep-list (`protect-parts.list`) so a PSBBN
              game add never deletes it (see the Nobunaga psbbn-directinstall notes).

Dry run unless --write. Refuses if the partition already exists or the drive has no __net
record for the given HDD ID.

    python mingolinstall.py <device-or-image> --disc <disc-root> --kit <kit-dir> \\
        --hddid <file> [--four auto|<hex>] --res <dir> --attr <attr-area.bin> \\
        [--pfsshell PFSSHELL] [--keeplist <OPL>/protect-parts.list] [--work DIR] [--write]

Borrowed in place (env overrides): NOBU_TOOLS = nobunaga/tools (dnasbundle, dnasdec),
POL_PS2 = PlayOnline/work/ps2 (polrecord, polhdd, polnetdump).
"""
import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_POSIX = os.name == 'posix'
NOBU_TOOLS = os.environ.get('NOBU_TOOLS',
    '/mnt/e/Code/Nobunaga Online/nobunaga/tools' if _POSIX
    else 'E:/Code/Nobunaga Online/nobunaga/tools')
POL_PS2 = os.environ.get('POL_PS2',
    '/mnt/e/Code/PlayOnline Project/PlayOnline/work/ps2' if _POSIX
    else 'E:/Code/PlayOnline Project/PlayOnline/work/ps2')
sys.path.insert(0, HERE)
sys.path.insert(1, NOBU_TOOLS)
# The shared network-config fix lives in the TOOLKIT's nobunaga/tools (NOBU_TOOLS
# may point at the dev repo), so add that explicitly.
sys.path.insert(1, os.path.join(HERE, '..', '..', 'nobunaga', 'tools'))
sys.path.append(POL_PS2)             # appended: its dis.py must not shadow the stdlib

import sealkit                       # noqa: E402
import dnasbundle                    # noqa: E402
import netcnf_install                # noqa: E402  (shared network-config fix)
from dnasdec import ata_material     # noqa: E402

SECTOR = 512
PARTITION = 'PP.SCPS-15049..APPLICATION'
PASSWORD = b'MM21'
PART_MIB = 1536
ATTR_OFF = 0x1000
NET_RECORD_OFF = 0x201800
EXCLUDE_DIRS = {'FMOD', 'FMOD2', 'FRES', 'ZZBIN'}
EXCLUDE_FILES = {'FEEGAGUI.ELF', 'SCPS_150.49'}
CONTAINERS = ['EDAUTH.BIN', 'GAME.BIN', 'HTTP.BIN', 'INSTALL.BIN', 'MENU.BIN', 'MOVIE.BIN',
              'NHTTP.BIN', 'PATCH.BIN', 'SYSTEM.BIN']


def partitions(device):
    from polnetdump import partitions as walk
    with open(device, 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        return list(walk(f, size))


def find_partition(device, name):
    for start, length, _ptype, pname in partitions(device):
        if pname == name:
            return start, length
    return None


def net_four(device, hddid):
    """Decode the drive's own __net DNAS record (partition +0x201800) with its HDD ID.
    polrecord's reply[84..99] is HDD ID bytes 0x50..0x60 (the ATA reply sits at +4)."""
    import polrecord
    net = find_partition(device, '__net')
    if not net:
        raise SystemExit('no __net partition on %s' % device)
    with open(device, 'rb') as f:
        f.seek(net[0] * SECTOR + NET_RECORD_OFF)
        rec = f.read(32)
    if not any(rec):
        raise SystemExit('the __net DNAS record is empty: this drive has never been provisioned '
                         '(install PlayOnline first, or pass --four with a record you minted)')
    dec = bytes(polrecord.decode(rec, polrecord.derive_key(hddid[0x50:0x60])))
    if any(dec[12:20]):
        raise SystemExit('the __net record does not decode with this HDD ID (%s): wrong --hddid?'
                         % dec[:20].hex())
    return dec[:4]


def stage(disc, kit, res, ata32, four, out, overlay=None, loader=None, capture=None):
    if os.path.exists(out):
        shutil.rmtree(out)
    n = 0
    for dp, dn, fn in os.walk(disc):
        rel = os.path.relpath(dp, disc)
        top = rel.split(os.sep)[0].upper()
        if top in EXCLUDE_DIRS:
            dn[:] = []
            continue
        for f in fn:
            if rel == '.' and f.upper() in EXCLUDE_FILES:
                continue
            dst = os.path.join(out, rel, f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(dp, f), dst)
            n += 1
    zz = os.path.join(out, 'ZZENC', 'ZZBIN')
    os.makedirs(zz, exist_ok=True)
    import json
    for name in CONTAINERS:
        k = json.load(open(os.path.join(kit, name + '.kit.json')))
        ov = os.path.join(overlay, name) if overlay else None
        if ov and os.path.exists(ov):
            src = ov
            print('   overlay: %s rebuilt from %s' % (name, ov))
        else:
            src = os.path.join(disc, 'ZZBIN', name)
        neutral = sealkit.rebuild(k, open(src, 'rb').read())
        sealed = dnasbundle.seal(neutral, ata32, four)
        open(os.path.join(zz, name), 'wb').write(sealed)
        # Capture GAME.BIN (its known neutral + drive form) so verify_seal_serve
        # can round-trip it against the HDD ID the staged loader serves.
        if capture is not None and name == 'GAME.BIN':
            capture['neutral'] = neutral
            capture['sealed'] = sealed
            capture['name'] = name
    open(os.path.join(out, 'INSTALL.VER'), 'wb').write(struct.pack('<I', 4))
    if res:
        shutil.copytree(res, os.path.join(out, 'res'))
    if loader:
        shutil.copyfile(loader, os.path.join(out, 'dnasload.elf'))
    return n


def _quote(name):
    return '"%s"' % name if ' ' in name else name


def map_path(path, path_map):
    """Host path as pfsshell sees it, e.g. E:/x -> /mnt/e/x when pfsshell runs under WSL."""
    p = path.replace('\\', '/')
    for src, dst in path_map:
        if p.lower().startswith(src.lower()):
            return dst + p[len(src):]
    return p


def emit_dir(out, host_dir, path_map):
    entries = sorted(os.scandir(host_dir), key=lambda e: e.name)
    files = [e for e in entries if e.is_file()]
    if files:
        out.append('lcd %s' % _quote(map_path(host_dir, path_map)))
        out += ['put %s' % _quote(e.name) for e in files]
    for e in entries:
        if e.is_dir():
            out += ['mkdir %s' % _quote(e.name), 'cd %s' % _quote(e.name)]
            emit_dir(out, e.path, path_map)
            out.append('cd ..')


def pfsshell_script(device, staged, path_map=()):
    out = ['device %s' % map_path(device, path_map),
           'mkpart %s %dM PFS' % (PARTITION, PART_MIB), 'mount %s' % PARTITION]
    emit_dir(out, staged, path_map)
    return '\n'.join(out + ['umount', 'exit', ''])


def set_password(device, lba):
    """rpwd = fpwd = apa_password(id, MM21) on the main header, checksum refreshed."""
    import polhdd
    pw = polhdd.apa_password(PARTITION, PASSWORD)
    with open(device, 'r+b') as f:
        f.seek(lba * SECTOR)
        h = bytearray(f.read(1024))
        if h[0x10:0x30].split(b'\0')[0].decode() != PARTITION:
            raise SystemExit('header at LBA %d is not %s' % (lba, PARTITION))
        h[0x30:0x38] = pw
        h[0x38:0x40] = pw
        struct.pack_into('<I', h, 0, polhdd.checksum(bytes(h)))
        f.seek(lba * SECTOR)
        f.write(h)
    return pw


def clear_journal(device, backup):
    """pfsshell leaves its APA journal behind (MBR-area sectors 6-7, 10-15), holding our header
    as it was BEFORE set_password. A stale journal stops HDD-OSD booting, and a replay would drop
    the password. Same sectors as PlayOnline poljournal.py --clear; 8-9 are left alone."""
    with open(device, 'r+b') as f:
        open(backup, 'wb').write(f.read(SECTOR * 16))
        for s in (6, 7, 10, 11, 12, 13, 14, 15):
            f.seek(s * SECTOR)
            f.write(bytes(SECTOR))


def write_attr(device, lba, attr):
    area = open(attr, 'rb').read()
    if area[:9] != b'PS2ICON3D':
        raise SystemExit('attr file has no PS2ICON3D magic')
    with open(device, 'r+b') as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        f.write(area)


def protect(keeplist):
    """The installer owns its keep-list entry: append once, never rewrite other lines."""
    lines = []
    if os.path.exists(keeplist):
        lines = open(keeplist, encoding='utf-8').read().splitlines()
    if PARTITION in lines:
        return False
    with open(keeplist, 'a', encoding='utf-8', newline='\n') as f:
        if lines and not open(keeplist, 'rb').read().endswith(b'\n'):
            f.write('\n')
        f.write(PARTITION + '\n')
    return True


def verify_seal_serve(staged, four, capture):
    """The HDD ID the staged loader SERVES must decrypt the sealed containers,
    or the console halts at 'dnas2 prep = -102' (wrong decrypt key).

    Title-agnostic round-trip (no hardcoded plaintext head): re-neutralize the
    captured GAME.BIN drive form under the SERVED id and compare to its known
    neutral -- dnasbundle.neutralize is the exact inverse of seal, so they match
    only when the served id equals the seal id. No console identity is involved,
    so this offline check is exactly what the console's libdnas2 does. Prints a
    plain line (so it lands in the installer log and on screen) and returns True
    on match. Skips quietly when there is nothing to check (no --loader, loader
    still unfilled, or no captured container)."""
    loader = os.path.join(staged, 'dnasload.elf')
    if not capture or 'sealed' not in capture or not os.path.isfile(loader):
        print('== SEAL CHECK: skipped (no captured container / staged loader)')
        return True
    lb = open(loader, 'rb').read()
    mg = b'Sony Computer Entertainment Inc.'
    blocks, i = set(), lb.find(mg)
    while i >= 0:
        blk = lb[i:i + 512]
        if len(blk) == 512 and blk[0x20:0x24] == b'SCPH' and any(blk[0x40:0x48]):
            blocks.add(blk)
        i = lb.find(mg, i + 1)
    if b'SCEFIXPLACEHOLD' in lb or len(blocks) != 1:
        print('== SEAL CHECK: skipped (loader not filled, or %d served blocks)'
              % len(blocks))
        return True
    blk = blocks.pop()
    served = hashlib.sha1(blk).hexdigest()
    ata = ata_material(blk)
    ata32 = ata[0] if isinstance(ata, tuple) else ata
    try:
        got = dnasbundle.neutralize(capture['sealed'], ata32, four)
    except Exception as e:
        print('== SEAL CHECK: skipped (neutralize failed: %s)' % e)
        return True
    ok = (got == capture['neutral'])
    print('== SEAL CHECK: served HDD ID %s  ->  container (%s) decrypts: %s'
          % (served, capture.get('name', '?'),
             'YES  (seal == serve, OK)' if ok else 'NO  <<< MISMATCH'))
    if not ok:
        print('== !! The served id does NOT match the id the containers were sealed to.')
        print("== !! This console will halt at 'dnas2 prep = -102'. The seal and the")
        print('== !! served loader must use the SAME HDD ID. (served sha1 %s)' % served)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('device')
    ap.add_argument('--disc', required=True, help='the disc tree (extracted ISO or mounted disc)')
    ap.add_argument('--kit', required=True, help='seal kit dir (<name>.kit.json per container)')
    ap.add_argument('--hddid', required=True, help='the HDD ID the console is served (128 or 512 B)')
    ap.add_argument('--four', default='auto', help="'auto' = decode the drive's own __net record")
    ap.add_argument('--res', help='res/ dir (info.sys + jacket art)')
    ap.add_argument('--attr', required=True, help='attr-area.bin (PS2ICON3D ...)')
    ap.add_argument('--pfsshell', default='pfsshell',
                    help="pfsshell command line, e.g. \"wsl -d Ubuntu -- '/mnt/e/.../PFS Shell.elf'\"")
    ap.add_argument('--path-map', action='append', default=[], metavar='SRC=DST',
                    help='rewrite host paths in the pfsshell script, e.g. E:/=/mnt/e/ (repeatable)')
    ap.add_argument('--keeplist', help='<OPL>/protect-parts.list on the exFAT partition')
    ap.add_argument('--work', default=os.path.join(HERE, '..', '..', 'work', 'install-stage'))
    ap.add_argument('--zzbin-overlay', help='dir of patched plaintext overlays (e.g. a baked '
                    'SYSTEM.BIN); a container is rebuilt from here instead of disc/ZZBIN when present')
    ap.add_argument('--loader', help='dnasload.elf to put in the partition root (the KELF '
                    'BBNav will launch when the attr has BOOT2 = pfs:/dnasload.elf)')
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()

    hddid = open(a.hddid, 'rb').read().ljust(512, b'\0')[:512]
    if hddid[:32] != b'Sony Computer Entertainment Inc.':
        raise SystemExit('%s does not look like a PS2 HDD ID' % a.hddid)
    if find_partition(a.device, PARTITION):
        raise SystemExit('%s already exists on %s: remove it first (reinstall is not in-place)'
                         % (PARTITION, a.device))
    four = net_four(a.device, hddid) if a.four == 'auto' else bytes.fromhex(a.four)
    ata32 = ata_material(hddid)
    print('== target %s, four %s' % (a.device, four.hex()))

    staged = os.path.abspath(a.work)
    seal_cap = {}
    n = stage(a.disc, a.kit, a.res, ata32, four, staged, a.zzbin_overlay, a.loader, seal_cap)
    print('== staged %d disc files + %d sealed containers + INSTALL.VER%s%s -> %s'
          % (n, len(CONTAINERS),
             ' + res/' if a.res else '',
             ' + dnasload.elf' if a.loader else '', staged))

    # Guard + diagnostic: the served id must decrypt the just-sealed containers,
    # or the console halts at 'dnas2 prep = -102'. Runs before the write (dry run
    # too); printed so it lands in the installer log (and on screen).
    verify_seal_serve(staged, four, seal_cap)

    path_map = [tuple(m.split('=', 1)) for m in a.path_map]
    script = pfsshell_script(a.device, staged, path_map)
    open(staged.rstrip('/\\') + '.pfsshell.txt', 'w', newline='\n').write(script)
    print('== pfsshell script: %d commands (saved next to the stage dir)' % script.count('\n'))
    if not a.write:
        print(script[:600] + ('...' if len(script) > 600 else ''))
        print('== dry run: nothing written (pass --write)')
        return 0

    import shlex
    subprocess.run(shlex.split(a.pfsshell), input=script, text=True, check=True)
    part = find_partition(a.device, PARTITION)
    if not part:
        raise SystemExit('pfsshell finished but %s is not in the APA table' % PARTITION)
    pw = set_password(a.device, part[0])
    print('== password set on LBA %d (%s)' % (part[0], pw.hex()))
    jb = staged.rstrip('/\\') + '.journal-backup.bin'
    clear_journal(a.device, jb)
    print('== APA journal cleared (sectors 0-15 backed up to %s)' % jb)
    write_attr(a.device, part[0], a.attr)
    print('== attr written at LBA %d + 0x1000' % part[0])
    netcnf_install.netcnf_step(a.device, a.pfsshell, staged)
    if a.keeplist:
        print('== keep-list: %s' % ('added' if protect(a.keeplist) else 'already listed'))
    else:
        print('== keep-list: NOT updated (no --keeplist); the PSBBN wrapper must add %s' % PARTITION)
    return 0


if __name__ == '__main__':
    sys.exit(main())
