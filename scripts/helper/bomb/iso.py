"""Minimal ISO9660 walker for the Net de Bomberman disc, raw bin or plain ISO.

The Redump image is a raw MODE2/2352 bin (one data track). This reads the
2048-byte user data of each sector in place, so no bin->iso conversion is needed.
Plain 2048-byte ISOs work too.

Usage:
  python iso.py list <disc.bin|disc.iso>
  python iso.py x    <disc.bin|disc.iso> <outdir> [--skip NAME ...]
  python iso.py iso  <disc.bin> <out.iso>          # write a plain 2048-byte ISO
"""
import os
import struct
import sys

SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


class Disc:
    def __init__(self, path):
        self.f = open(path, "rb")
        head = self.f.read(16)
        self.raw = head[:12] == SYNC
        self.sector = 2352 if self.raw else 2048
        self.nsect = os.path.getsize(path) // self.sector

    def user(self, lba):
        """User data of one sector: +24 for MODE2 form 1, +16 for MODE1."""
        self.f.seek(lba * self.sector)
        s = self.f.read(self.sector)
        if not self.raw:
            return s
        return s[24:24 + 2048] if s[15] == 2 else s[16:16 + 2048]

    def read(self, lba, size):
        out = bytearray()
        while len(out) < size:
            out += self.user(lba)
            lba += 1
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


def root(disc):
    pvd = disc.user(16)
    assert pvd[1:6] == b"CD001", "no ISO9660 primary volume descriptor at sector 16"
    rec = pvd[156:156 + 34]
    return struct.unpack("<I", rec[2:6])[0], struct.unpack("<I", rec[10:14])[0]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, path = argv[0], argv[1]
    disc = Disc(path)
    if cmd == "list":
        for full, ext, sz, is_dir in walk(disc, *root(disc)):
            print(f"{'D' if is_dir else ' '} lba={ext:7d} size={sz:11d} {full}")
    elif cmd == "x":
        out = argv[2]
        skip = set(argv[argv.index("--skip") + 1:]) if "--skip" in argv else set()
        for full, ext, sz, is_dir in walk(disc, *root(disc)):
            dst = os.path.join(out, full.lstrip("/"))
            if is_dir:
                os.makedirs(dst, exist_ok=True)
                continue
            if os.path.basename(full) in skip:
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as o:
                lba, left = ext, sz
                while left > 0:
                    chunk = disc.read(lba, min(left, 2048 * 512))
                    o.write(chunk)
                    lba += 512
                    left -= len(chunk)
            print(full)
    elif cmd == "iso":
        with open(argv[2], "wb") as o:
            for lba in range(disc.nsect):
                o.write(disc.user(lba))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
