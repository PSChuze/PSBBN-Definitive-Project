"""Overwrite ONLY the attribute area of an existing install partition on a
live drive. Nothing else on the drive is touched (no pfs, no password, no
INSTALL.VER, no ZZENC). Use this to fix a wrong BOOT2 without a full reinstall.

    sudo python3 attr_write_only.py /dev/sdg \
        --attr work/attr-area-hddboot.bin

The partition is located by name in the APA table and the attr is written to
partition_LBA * 512 + 0x1000, the same slot mingolinstall.write_attr uses.
"""
import argparse
import os
import struct
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
sys.path.append(POL_PS2)

import mingolinstall as M       # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('device')
    ap.add_argument('--attr', required=True)
    ap.add_argument('--part', default=M.PARTITION,
                    help='partition name (default: %s)' % M.PARTITION)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    part = M.find_partition(a.device, a.part)
    if not part:
        raise SystemExit('%s not found on %s' % (a.part, a.device))
    lba = part[0]
    print('== %s at LBA %d' % (a.part, lba))
    area = open(a.attr, 'rb').read()
    if area[:9] != b'PS2ICON3D':
        raise SystemExit('%s has no PS2ICON3D magic' % a.attr)
    print('== attr: %d B, first bytes %r' % (len(area), area[:16]))
    off = lba * M.SECTOR + M.ATTR_OFF
    print('== target byte offset on %s: 0x%x (LBA %d + 0x%x)' % (a.device, off, lba, M.ATTR_OFF))
    if a.dry_run:
        print('== dry run: nothing written')
        return 0
    with open(a.device, 'r+b') as f:
        f.seek(off)
        f.write(area)
    print('== wrote %d B' % len(area))
    return 0


if __name__ == '__main__':
    sys.exit(main())
