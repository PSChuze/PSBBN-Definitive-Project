"""PS2 netcnf .dat codec (BB Navigator network config, __sysconf/etc/bnnetwork/netcnf000.dat).

The encoding is keyed by the console's i.Link ID (sceCdRI), so a config written on one PS2
decodes only on a console reporting the same ID. Port of ps2sdk iop/network/netcnf/src/netcnf.c
(do_init_xor_magic / do_read_netcnf_decode / do_write_netcnf_encode):

  key[2 + 3*i .. 4 + 3*i] = (id[i] >> 5) + 1, ((id[i] >> 2) & 7) + 1, (id[i] & 3) + 1   for i in 0..7
  each little-endian u16:  plain = ror16(~cipher, key[k + 2]);  k cycles 0..23
  odd trailing byte:       plain = ror8(~cipher, key[k + 2])

ps2sdk's port loops i + 1 < 8 (7 ID bytes) and so leaves key[23..25] wrong; Sony's module uses all
8 ID bytes. Proved on a real BB Navigator file: with 7 bytes every 23rd-25th word is garbage,
with 8 the whole file decodes to clean text.

Decoded text starts with "# <Sony Computer Entertainment Inc.>".

Usage:
  python netcnf.py decode <file.dat> <ilink-id-hex16>
  python netcnf.py encode <plain.txt> <ilink-id-hex16> <out.dat>
"""
import struct
import sys

MAGIC = b"# <Sony Computer Entertainment Inc.>"


def keybuf(ilink):
    mem = bytearray(26)
    for i in range(8):
        b = ilink[i]
        mem[i * 3 + 2] = (b >> 5) + 1
        mem[i * 3 + 3] = ((b >> 2) & 7) + 1
        mem[i * 3 + 4] = (b & 3) + 1
    return mem


def _rot16(v, n, right):
    n %= 16
    return ((v >> n) | (v << (16 - n))) & 0xFFFF if right else ((v << n) | (v >> (16 - n))) & 0xFFFF


def _rot8(v, n, right):
    n %= 8
    return ((v >> n) | (v << (8 - n))) & 0xFF if right else ((v << n) | (v >> (8 - n))) & 0xFF


def decode(data, ilink):
    mem, out, k = keybuf(ilink), bytearray(), 0
    for i in range(0, len(data) - 1, 2):
        w, = struct.unpack_from("<H", data, i)
        out += struct.pack("<H", _rot16(w ^ 0xFFFF, mem[k + 2], True))
        k = (k + 1) % 24
    if len(data) & 1:
        out.append(_rot8(data[-1] ^ 0xFF, mem[k + 2], True))
    return bytes(out)


def encode(plain, ilink):
    mem, out, k = keybuf(ilink), bytearray(), 0
    for i in range(0, len(plain) - 1, 2):
        w, = struct.unpack_from("<H", plain, i)
        out += struct.pack("<H", _rot16(w, mem[k + 2], False) ^ 0xFFFF)
        k = (k + 1) % 24
    if len(plain) & 1:
        out.append(_rot8(plain[-1], mem[k + 2], False) ^ 0xFF)
    return bytes(out)


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    cmd, src, ilink = sys.argv[1], sys.argv[2], bytes.fromhex(sys.argv[3])
    data = open(src, "rb").read()
    if cmd == "decode":
        pt = decode(data, ilink)
        print("magic OK" if pt.startswith(MAGIC) else "magic MISMATCH", file=sys.stderr)
        sys.stdout.buffer.write(pt)
    elif cmd == "encode":
        ct = encode(data, ilink)
        assert decode(ct, ilink) == data
        open(sys.argv[4], "wb").write(ct)
        print(f"wrote {len(ct)} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
