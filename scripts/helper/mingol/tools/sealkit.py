"""sealkit.py -- split a neutral container into a small SEAL KIT (no game code) and rebuild it
from the kit plus the player's own disc plaintext (ZZBIN/<name>).

The neutral form (nobunaga/tools/dnasbundle.py) holds, per section, the decrypted K1-block at
sec+0x80 and the K2-decrypted "outer" layer at sec+0x300. Inside outer, [d10 : d10+v1] is the
module wrapped by the static key: RC6-CBC-enc(inner), inner = prefix(d9) + module(v2) + tail.
The module is byte-identical to the disc's plaintext overlay, so the kit keeps everything EXCEPT
the module bytes, and rebuild() re-encrypts prefix + disc module + tail with the static key.

    python sealkit.py make    <neutral_dir> <kit_dir>
    python sealkit.py rebuild <kit_dir> <disc_zzbin_dir> <out_neutral_dir>
    python sealkit.py verify  <neutral_dir> <disc_zzbin_dir>
"""
import json
import os
import struct
import sys

# dnas2 / rc6 are borrowed in place from the Nobunaga repo (see PROJECT-MAP).
_NOBU_DEFAULT = ('/mnt/e/Code/Nobunaga Online/nobunaga/tools' if os.name == 'posix'
                 else 'E:/Code/Nobunaga Online/nobunaga/tools')
sys.path.insert(0, os.environ.get('NOBU_TOOLS', _NOBU_DEFAULT))
import dnas2  # noqa: E402
import rc6    # noqa: E402

KEYS = dnas2.keys()


def _rec(blk, types):
    for t in types:
        r = dnas2.unrecord(blk, KEYS[t][1], KEYS[t][2])
        if r:
            return r[0]
    return None


def geometry(neutral):
    """One section per ZZENC file (checked); read everything from the intact RSA records."""
    r7 = _rec(neutral[:128], (7,))
    sec = int.from_bytes(r7[0x20:0x24], 'little') + 0x200
    sess = _rec(neutral[sec + 0x180:sec + 0x200], (11,))
    h1 = rc6.cbc(neutral[sec + 0x280:sec + 0x300], sess[:16], sess[16:32], True)
    assert h1[10:26] == b'a5713c8bdbe8d420', 'H1 tag'
    sizes = _rec(neutral[sec + 0x100:sec + 0x180], (h1[4], 3))
    v1, v2 = struct.unpack('<II', sizes[:8])
    d9, d10 = sizes[9] * 16, sizes[10] * 16
    extent = d10 + v1 + ((0x10 - (v1 & 0xF)) & 0xF) + 0x10
    stat = _rec(neutral[sec:sec + 0x80], (h1[8], 6, 14, 10))[:32]
    assert sec + 0x300 + extent + 0x80 == len(neutral), 'expected exactly one section'
    return dict(sec=sec, v1=v1, v2=v2, d9=d9, d10=d10, extent=extent, stat=stat)


def split(neutral):
    g = geometry(neutral)
    o = g['sec'] + 0x300
    outer = neutral[o:o + g['extent']]
    inner = rc6.cbc(outer[g['d10']:g['d10'] + g['v1']], g['stat'][:16], g['stat'][16:], True)
    module = inner[g['d9']:g['d9'] + g['v2']]
    kit = {
        'head': neutral[:o + g['d10']].hex(),                       # records + blk + outer prefix
        'inner_prefix': inner[:g['d9']].hex(),
        'inner_tail': inner[g['d9'] + g['v2']:].hex(),
        'outer_tail': outer[g['d10'] + g['v1']:].hex(),
        'trailer': neutral[o + g['extent']:].hex(),                  # sig record
        'v2': g['v2'],
    }
    return kit, module


def rebuild(kit, module):
    assert len(module) == kit['v2'], 'module length differs from the signed size'
    head = bytes.fromhex(kit['head'])
    r7 = _rec(head[:128], (7,))
    sec = int.from_bytes(r7[0x20:0x24], 'little') + 0x200
    sess = _rec(head[sec + 0x180:sec + 0x200], (11,))
    h1 = rc6.cbc(head[sec + 0x280:sec + 0x300], sess[:16], sess[16:32], True)
    stat = _rec(head[sec:sec + 0x80], (h1[8], 6, 14, 10))[:32]
    inner = bytes.fromhex(kit['inner_prefix']) + module + bytes.fromhex(kit['inner_tail'])
    wrapped = rc6.cbc(inner, stat[:16], stat[16:], False)
    return head + wrapped + bytes.fromhex(kit['outer_tail']) + bytes.fromhex(kit['trailer'])


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == 'make':
        os.makedirs(a[2], exist_ok=True)
        for n in sorted(os.listdir(a[1])):
            kit, _ = split(open(os.path.join(a[1], n), 'rb').read())
            json.dump(kit, open(os.path.join(a[2], n + '.kit.json'), 'w'))
            print('%-12s kit %6d bytes' % (n, sum(len(v) // 2 for k, v in kit.items() if k != 'v2')))
    elif a[0] == 'rebuild':
        os.makedirs(a[3], exist_ok=True)
        for k in sorted(os.listdir(a[1])):
            n = k[:-len('.kit.json')]
            kit = json.load(open(os.path.join(a[1], k)))
            out = rebuild(kit, open(os.path.join(a[2], n), 'rb').read())
            open(os.path.join(a[3], n), 'wb').write(out)
            print('rebuilt', n, len(out))
    elif a[0] == 'verify':
        ok = 0
        names = sorted(os.listdir(a[1]))
        for n in names:
            neutral = open(os.path.join(a[1], n), 'rb').read()
            kit, module = split(neutral)
            disc = open(os.path.join(a[2], n), 'rb').read()
            same_mod = module == disc
            rt = rebuild(kit, disc) == neutral
            kb = sum(len(v) // 2 for k, v in kit.items() if k != 'v2')
            print('%-12s module==disc %-5s rebuild(kit, disc)==neutral %-5s kit %6d B / file %8d B'
                  % (n, same_mod, rt, kb, len(neutral)))
            ok += same_mod and rt
        print('%d/%d OK' % (ok, len(names)))


if __name__ == '__main__':
    main()
