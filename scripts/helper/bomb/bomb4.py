"""bomb4.py -- list and extract DATA/FULL.BIN, the "BOMB4" HDD install archive.

Layout (all little-endian):
  0x00  "BOMB4\\0\\0\\0"
  0x08  u32 header size (0x14), where the entry table starts
  0x0c  u32 offset of the name table (NUL-separated, entry order)
  0x10  u32 offset of the data area
  0x14  24-byte entries, one per name: csize, rsize, check, flag, offset (from data area), index

Every entry is a zlib stream. flag 0 = compressed plaintext data; flag 1 = a
stored (level 0) zlib stream whose payload is DNAS2-encrypted code (MAIN.BIN,
MODULE.BIN, the DATA0 overlays). `check` is not zlib's crc32 of the output; its
algorithm is still unknown.

Usage:
  python bomb4.py list <FULL.BIN>
  python bomb4.py x    <FULL.BIN> <outdir>
"""
import os
import struct
import sys
import zlib

MAGIC = b"BOMB4\0\0\0"


def entries(d):
    assert d[:8] == MAGIC, "not a BOMB4 archive"
    table_at, names_at, data_at = struct.unpack_from("<III", d, 8)
    names = [n.decode("ascii") for n in d[names_at:data_at].split(b"\0") if n]
    for i, name in enumerate(names):
        csize, rsize, check, flag, off, idx = struct.unpack_from("<6I", d, table_at + i * 24)
        assert idx == i, f"{name}: entry index {idx} != {i}"
        yield name, csize, rsize, check, flag, data_at + off


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, path = argv[0], argv[1]
    with open(path, "rb") as f:
        d = f.read()
    for name, csize, rsize, check, flag, at in entries(d):
        if cmd == "list":
            kind = "code(enc)" if flag else "data"
            print(f"{name:22s} {kind:9s} c={csize:#10x} r={rsize:#10x} check={check:08x}")
        elif cmd == "x":
            raw = zlib.decompress(d[at:at + csize])
            assert len(raw) == rsize, f"{name}: {len(raw):#x} != {rsize:#x}"
            dst = os.path.join(argv[2], name)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            with open(dst, "wb") as o:
                o.write(raw)
            print(name)
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
