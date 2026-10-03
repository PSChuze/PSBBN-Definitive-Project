"""Minimal ISO9660 walker for the Puzzle-dama disc.

Reads the Redump .bin (raw MODE2/2352, one track) directly, or a plain 2048-byte
.iso. The sector size is detected from the first sync pattern.

Usage:
  python iso.py list <disc.bin|disc.iso>
  python iso.py x    <disc.bin|disc.iso> <outdir> [--skip NAME ...]
"""
import os
import struct
import sys

SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


class Disc:
    def __init__(self, path):
        self.f = open(path, "rb")
        raw = self.f.read(12) == SYNC
        # MODE2/2352 form 1: 12 sync + 4 header + 8 subheader, then 2048 user bytes.
        self.stride, self.skip = (2352, 24) if raw else (2048, 0)

    def read(self, lba, size):
        out = bytearray()
        for i in range((size + 2047) // 2048):
            self.f.seek((lba + i) * self.stride + self.skip)
            out += self.f.read(2048)
        return bytes(out[:size])


def walk(disc, lba, size, path=""):
    d = disc.read(lba, size)
    i = 0
    while i < len(d):
        n = d[i]
        if n == 0:
            i = (i // 2048 + 1) * 2048
            continue
        r = d[i:i + n]
        i += n
        ext, = struct.unpack("<I", r[2:6])
        sz, = struct.unpack("<I", r[10:14])
        flags, nl = r[25], r[32]
        name = r[33:33 + nl]
        if name in (b"\0", b"\1"):
            continue
        name = name.decode("latin1").split(";")[0]
        full = f"{path}/{name}"
        is_dir = bool(flags & 2)
        yield full, ext, sz, is_dir
        if is_dir:
            yield from walk(disc, ext, sz, full)


def entries(disc):
    pvd = disc.read(16, 2048)
    if pvd[1:6] != b"CD001":
        sys.exit("no ISO9660 primary volume descriptor at sector 16")
    root = pvd[156:190]
    return walk(disc, struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0])


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("list", "x"):
        sys.exit(__doc__)
    disc = Disc(sys.argv[2])
    if sys.argv[1] == "list":
        for full, ext, sz, is_dir in entries(disc):
            print(f"{ext:8d} {sz:10d} {full}{'/' if is_dir else ''}")
        return
    out = sys.argv[3]
    skip = set(sys.argv[sys.argv.index("--skip") + 1:]) if "--skip" in sys.argv else set()
    for full, ext, sz, is_dir in entries(disc):
        if is_dir or os.path.basename(full) in skip:
            continue
        dst = os.path.join(out, *full.strip("/").split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as g:
            g.write(disc.read(ext, sz))
        print(f"{sz:10d} {full}")


if __name__ == "__main__":
    main()
