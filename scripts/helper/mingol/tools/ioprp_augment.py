"""Augment an IOP reboot image (ROMDIR / IOPRP) with extra IRX modules.

The stock IOPRP270.IMG on Minna's disc holds only the base IOP kernel (LOADCORE,
SIFCMD, THREADMAN, IOMAN, MODLOAD, FILEIO, CDVDMAN, CDVDFSV, ...); the game
loads DEV9/ATAD/HDD/PFS from cdrom0:\\FMOD\\ at runtime. On an HDD/BBNav launch
there is no disc, so those four IRXs must be resident after the IOP reboot.
This script rebuilds IOPRP270.IMG with them added to its ROMDIR.

    python ioprp_augment.py IOPRP270.IMG -o IOPRP270-augmented.IMG \
        --add DEV9=FMOD/DEV9.IRX --add ATAD=FMOD/ATAD.IRX \
        --add HDD=FMOD/HDD.IRX --add PFS=FMOD/PFS.IRX

Format (romdir.h in ps2sdk):
    - ROMDIR entries: 10-byte name (NUL-padded) + u16 extinfo_size + u32 size
    - The first three entries are always RESET, ROMDIR, EXTINFO
    - After all entries a terminating 16-byte zero entry ends the table
    - EXTINFO holds the concatenated per-file metadata records (may be zero
      bytes for modules we add; retail modules use 24-40 bytes each)
    - After EXTINFO come the module blobs, each padded to a 16-byte boundary
      except the last

Round-trip: `roundtrip` mode reads the image and writes it back unchanged, to
validate the parser and serializer against the retail image byte-for-byte.
"""
import argparse
import os
import struct
import sys


HEAD_ENTRIES = ('RESET', 'ROMDIR', 'EXTINFO')


def parse(blob):
    off = 0
    entries = []
    while off + 16 <= len(blob):
        name = blob[off:off + 10].rstrip(b'\0').decode('latin-1')
        ext_sz = struct.unpack_from('<H', blob, off + 10)[0]
        size = struct.unpack_from('<I', blob, off + 12)[0]
        if not name and ext_sz == 0 and size == 0:
            break
        entries.append({'name': name, 'ext_sz': ext_sz, 'size': size})
        off += 16
    else:
        raise ValueError('ROMDIR is not terminated by a zero entry')
    romdir_bytes = (len(entries) + 1) * 16
    if len(entries) < 3 or [e['name'] for e in entries[:3]] != list(HEAD_ENTRIES):
        raise ValueError('the first three entries are not RESET/ROMDIR/EXTINFO: %s'
                         % [e['name'] for e in entries[:3]])
    if entries[1]['size'] != romdir_bytes:
        raise ValueError('ROMDIR entry says %d bytes; the table is %d'
                         % (entries[1]['size'], romdir_bytes))
    extinfo_total = entries[2]['size']
    if sum(e['ext_sz'] for e in entries) != extinfo_total:
        raise ValueError('EXTINFO entry says %d bytes; per-entry sizes sum to %d'
                         % (extinfo_total, sum(e['ext_sz'] for e in entries)))
    # Slice extinfo per module
    p = romdir_bytes
    for e in entries:
        e['extinfo'] = blob[p:p + e['ext_sz']]
        p += e['ext_sz']
    # Slice data per module (RESET/ROMDIR/EXTINFO have no data blob in the file body)
    data_start = (romdir_bytes + extinfo_total + 15) & ~15
    p = data_start
    for e in entries[3:]:
        e['data'] = blob[p:p + e['size']]
        p = (p + e['size'] + 15) & ~15
    return entries


def serialize(entries):
    """Write ROMDIR, EXTINFO, and the module data in the retail layout.

    Inter-module padding is 16-byte, but the last module does not get trailing
    padding (matches the retail IOPRP270.IMG byte for byte)."""
    # ROMDIR
    out = bytearray()
    romdir_bytes = (len(entries) + 1) * 16
    extinfo_total = sum(e['ext_sz'] for e in entries)
    # entries 0/1/2 (RESET/ROMDIR/EXTINFO) have fixed sizes that reflect the
    # table itself: RESET.size=0, ROMDIR.size=romdir_bytes, EXTINFO.size=extinfo_total
    if entries[0]['name'] != 'RESET':
        raise ValueError('first entry must be RESET')
    entries[0]['size'] = 0
    entries[1]['size'] = romdir_bytes
    entries[2]['size'] = extinfo_total
    for e in entries:
        name = e['name'].encode('latin-1')
        if len(name) > 10:
            raise ValueError('name %r > 10 bytes' % e['name'])
        out += name.ljust(10, b'\0')
        out += struct.pack('<H', e['ext_sz'])
        out += struct.pack('<I', e['size'])
    out += b'\0' * 16  # terminator
    assert len(out) == romdir_bytes, (len(out), romdir_bytes)
    # EXTINFO
    for e in entries:
        blob = e.get('extinfo', b'')
        if len(blob) != e['ext_sz']:
            raise ValueError('%s: extinfo len %d != ext_sz %d'
                             % (e['name'], len(blob), e['ext_sz']))
        out += blob
    # pad to 16 before the data section
    pad = (-len(out)) & 15
    out += b'\0' * pad
    # data blobs
    data_entries = entries[3:]
    for i, e in enumerate(data_entries):
        blob = e.get('data', b'')
        if len(blob) != e['size']:
            raise ValueError('%s: data len %d != size %d'
                             % (e['name'], len(blob), e['size']))
        out += blob
        if i != len(data_entries) - 1:
            out += b'\0' * ((-e['size']) & 15)
    return bytes(out)


def add_module(entries, name, data, extinfo=b''):
    if any(e['name'] == name for e in entries):
        raise ValueError('a %r entry already exists' % name)
    if len(name) > 10:
        raise ValueError('name %r > 10 bytes' % name)
    entries.append({'name': name, 'ext_sz': len(extinfo), 'size': len(data),
                    'extinfo': extinfo, 'data': data})


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('image', help='input IOPRP image (ROMDIR)')
    ap.add_argument('-o', '--out', help='output image; omit for a dry run')
    ap.add_argument('--add', action='append', default=[], metavar='NAME=PATH',
                    help='add an IRX; NAME is the ROMDIR entry (<=10 chars)')
    ap.add_argument('--roundtrip', action='store_true',
                    help='parse and re-serialize with no changes; must match byte-for-byte')
    ap.add_argument('--list', action='store_true', help='print the ROMDIR and exit')
    args = ap.parse_args(argv)

    blob = _read(args.image)
    entries = parse(blob)

    if args.list:
        print('%-11s %-9s %-6s' % ('name', 'ext_sz', 'size'))
        for e in entries:
            print('%-11s %-9d %-6d' % (e['name'], e['ext_sz'], e['size']))
        return 0

    if args.roundtrip:
        out = serialize(entries)
        if out != blob:
            first = next((i for i in range(min(len(out), len(blob))) if out[i] != blob[i]), -1)
            raise SystemExit('roundtrip differs (in %d bytes vs out %d bytes; first diff at %d)'
                             % (len(blob), len(out), first))
        print('roundtrip OK (%d bytes)' % len(blob))
        if args.out:
            open(args.out, 'wb').write(out)
        return 0

    added = []
    for spec in args.add:
        if '=' not in spec:
            raise SystemExit('--add wants NAME=PATH, got %r' % spec)
        name, path = spec.split('=', 1)
        data = _read(path)
        # Give the added module empty extinfo. If a boot test says the IOP kernel
        # needs it, we can synthesize a minimal record here.
        add_module(entries, name, data, extinfo=b'')
        added.append((name, len(data), path))

    out = serialize(entries)

    print('== base image: %d bytes, %d entries' % (len(blob), len(parse(blob))))
    for name, size, path in added:
        print('   + %-10s %7d bytes  (%s)' % (name, size, path))
    print('== augmented: %d bytes, %d entries' % (len(out), len(entries)))

    if args.out:
        open(args.out, 'wb').write(out)
        # verify by re-parsing
        again = parse(out)
        names = [e['name'] for e in again]
        assert names[-len(added):] == [n for n, _, _ in added], names
        print('   wrote %s (re-parse: %d entries)' % (args.out, len(again)))
    else:
        print('== dry run (pass -o to write)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
