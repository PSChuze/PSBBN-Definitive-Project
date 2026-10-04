"""NOBUON.LWZ - the PS2 install image on the Hiryuu no Shou disc (INSTIMG/NOBUON.LWZ).

Layout (big-endian unless noted):
  archive header  16 bytes : "LA" u16 hdr_len(=16) u32 ? u32 ? u32 ?
  entry           "LF" u16 flags|path_len (bit15 = stored)  u64 filetime_a  u64 filetime_b  u32 data_len
                  path (cp932, no NUL, relative to the build tree, e.g. ..\\patch\\recentver\\data\\...)
                  data (data_len bytes):
                     "BILZ" u32le usize u32le csize + zlib stream   -> compressed
                     anything else                                   -> stored raw

Usage:
  python lwz.py list  <NOBUON.LWZ | disc.iso>
  python lwz.py x     <NOBUON.LWZ | disc.iso> <outdir>

Given the ISO it locates the archive itself (first "LA\\x00\\x10" sector-aligned).
"""
import mmap
import os
import struct
import sys
import zlib


def open_archive(path):
    f = open(path, "rb")
    m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    if m[:4] == b"LA\x00\x10":
        return m, 0
    off = 0
    while True:
        off = m.find(b"LA\x00\x10\x00", off)
        if off < 0:
            raise SystemExit("no LA header found")
        if off % 2048 == 0 and m[off + 16:off + 18] == b"LF":
            return m, off
        off += 1


def entries(m, base):
    p = base + struct.unpack(">H", m[base + 2:base + 4])[0]
    while m[p:p + 2] == b"LF":
        plen, = struct.unpack(">H", m[p + 2:p + 4])
        plen &= 0x7FFF  # bit 15 is set on stored (uncompressed) entries
        ft_a, ft_b, dlen = struct.unpack(">QQI", m[p + 4:p + 24])
        name = bytes(m[p + 24:p + 24 + plen]).decode("cp932", "backslashreplace")
        q = p + 24 + plen
        yield name, ft_a, ft_b, q, dlen
        p = q + dlen
    if p < len(m) and any(m[p:p + 16]):
        print(f"warning: stopped at +{p - base:#x} on {bytes(m[p:p + 8])!r}", file=sys.stderr)


def payload(m, q, dlen):
    if m[q:q + 4] == b"BILZ":
        usize, csize = struct.unpack("<II", m[q + 4:q + 12])
        data = zlib.decompress(m[q + 12:q + 12 + csize])
        if len(data) != usize:
            raise ValueError(f"size mismatch {len(data)} != {usize}")
        return data, "z"
    return bytes(m[q:q + dlen]), "raw"


def clean(name):
    parts = [x for x in name.replace("\\", "/").split("/") if x not in ("..", ".", "")]
    return os.path.join(*parts)


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    cmd, src = sys.argv[1], sys.argv[2]
    m, base = open_archive(src)
    n = total = 0
    for name, _, _, q, dlen in entries(m, base):
        n += 1
        if cmd == "list":
            kind = "z" if m[q:q + 4] == b"BILZ" else "raw"
            usize = struct.unpack("<I", m[q + 4:q + 8])[0] if kind == "z" else dlen
            total += usize
            print(f"{kind:3} {usize:10d} {name}")
        elif cmd == "x":
            data, _ = payload(m, q, dlen)
            total += len(data)
            out = os.path.join(sys.argv[3], clean(name))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as fh:
                fh.write(data)
    print(f"{n} entries, {total} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
