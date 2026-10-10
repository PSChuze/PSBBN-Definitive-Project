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
  python netcnf.py decode  <file.dat> <ilink-id-hex16>
  python netcnf.py encode  <plain.txt> <ilink-id-hex16> <out.dat>
  python netcnf.py build   <ilink-id-hex16> <out.dat>   # DHCP profile for a console
  python netcnf.py recover <existing.dat>               # print the console i.Link
  python netcnf.py fix     <existing.dat> <out.dat>      # DHCP config for the same console
"""
import base64
import struct
import sys

MAGIC = b"# <Sony Computer Entertainment Inc.>"

# Every SCE netcnf begins with the magic comment, a blank line, then a [device]
# section, so the first 48 bytes of plaintext are fixed. 48 bytes = 24 16-bit
# words = the 24 key slots that cover all 8 i.Link bytes, which lets us recover
# a console's i.Link from a config it wrote -- no on-console lookup needed.
KNOWN = MAGIC + b"\n\n[device]\nt"

# A known-good DHCP-over-Ethernet profile (auto IP + auto DNS negotiation),
# decoded from a real PSBBN netcnf. `build` re-scrambles it for a target
# console's i.Link so that console reads it as its own -- this is what clears
# the game's "PlayStation BB Unit may have been connected to another
# PlayStation 2 / redo network settings" screen without the on-console setup
# tool. Works on any normal home router/LAN (DHCP). 287 bytes decoded.
DHCP_PROFILE = base64.b64decode(
    "IyA8U29ueSBDb21wdXRlciBFbnRlcnRhaW5tZW50IEluYy4+CgpbZGV2aWNlXQp0eXBlIG5pYwp2"
    "ZW5kb3IgIlNDRSIKcHJvZHVjdCAiRXRoZXJuZXQgKE5ldHdvcmsgQWRhcHRvcikiCgpbbmV0d29y"
    "a10KdHlwZSBuaWMKZGhjcAp3YW50LmRuczFfbmVnbwp3YW50LmRuczJfbmVnbwojIG5vYnVuYWdh"
    "IGRldjogZGhjcCBwcm9maWxlIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMj"
    "IyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIwo=")


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


def dns_profile(dns):
    """A DHCP-over-Ethernet profile that takes its IP from the router but uses a
    STATIC DNS server (`nameserver add <dns>`). Pointing DNS at the revival's
    own server is what lets the games resolve the service hostnames to our
    servers; with the default auto DNS the console asks the router (its ISP) and
    reaches the dead original services. `dns` is a dotted-quad string."""
    text = ("# <Sony Computer Entertainment Inc.>\n\n"
            "[device]\n"
            "type nic\n"
            "vendor \"SCE\"\n"
            "product \"Ethernet (Network Adaptor)\"\n\n"
            "[network]\n"
            "type nic\n"
            "dhcp\n"
            "nameserver add %s\n" % dns)
    return text.encode("ascii")


def build(ilink, dns=None):
    """A DHCP netcnf000.dat scrambled for the given console i.Link. With `dns`
    set (a dotted-quad), the config uses that static DNS server instead of the
    router's; otherwise DNS is auto-negotiated (DHCP_PROFILE)."""
    plain = dns_profile(dns) if dns else DHCP_PROFILE
    ct = encode(plain, ilink)
    assert decode(ct, ilink) == plain
    return ct


def _clean(bs):
    return all(32 <= x < 127 or x in (9, 10, 13) for x in bs)


def recover(cipher):
    """Recover the console i.Link from a netcnf000.dat it wrote, or None.

    Each i.Link byte b owns the key triplet ((b>>5)+1, ((b>>2)&7)+1, (b&3)+1),
    which scrambles three consecutive words. The first 48 bytes of plaintext are
    the fixed KNOWN prefix, so each byte is pinned by matching its triplet
    against those words; we then decode the whole file and require clean text,
    which rejects anything that is not actually that console's config.
    """
    if len(cipher) < len(KNOWN):
        return None
    found = []
    for i in range(8):
        cands = []
        for b in range(256):
            triplet = ((b >> 5) + 1, ((b >> 2) & 7) + 1, (b & 3) + 1)
            ok = True
            for j, kv in enumerate(triplet):
                wi = 3 * i + j
                c, = struct.unpack_from("<H", cipher, wi * 2)
                p, = struct.unpack_from("<H", KNOWN, wi * 2)
                if _rot16(c ^ 0xFFFF, kv, True) != p:
                    ok = False
                    break
            if ok:
                cands.append(b)
        if len(cands) != 1:
            return None
        found.append(cands[0])
    ilink = bytes(found)
    pt = decode(cipher, ilink)
    if pt.startswith(MAGIC) and _clean(pt):
        return ilink
    return None


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "build":
        if len(sys.argv) < 4:
            raise SystemExit("usage: netcnf.py build <ilink-hex16> <out.dat>")
        ilink = bytes.fromhex(sys.argv[2])
        if len(ilink) != 8:
            raise SystemExit("i.Link ID must be 16 hex digits (8 bytes)")
        open(sys.argv[3], "wb").write(build(ilink))
        print(f"wrote {sys.argv[3]} (DHCP netcnf for i.Link {sys.argv[2]})", file=sys.stderr)
        return
    if cmd == "recover":
        # Print the console i.Link a netcnf000.dat was written for. Exit 3 if it
        # cannot be recovered (not a valid SCE config / truncated).
        if len(sys.argv) < 3:
            raise SystemExit("usage: netcnf.py recover <existing.dat>")
        ilink = recover(open(sys.argv[2], "rb").read())
        if ilink is None:
            print("could not recover i.Link from this file", file=sys.stderr)
            raise SystemExit(3)
        print(ilink.hex())
        return
    if cmd == "fix":
        # Replace an existing netcnf with a DHCP config keyed to the SAME console
        # (its i.Link recovered from the old file), clearing the game's "connected
        # to another PlayStation 2" screen without the on-console setup tool.
        if len(sys.argv) < 4:
            raise SystemExit("usage: netcnf.py fix <existing.dat> <out.dat>")
        ilink = recover(open(sys.argv[2], "rb").read())
        if ilink is None:
            print("could not recover i.Link from this file", file=sys.stderr)
            raise SystemExit(3)
        open(sys.argv[3], "wb").write(build(ilink))
        print(ilink.hex())
        print(f"wrote {sys.argv[3]} (DHCP netcnf for i.Link {ilink.hex()})", file=sys.stderr)
        return
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    src, ilink = sys.argv[2], bytes.fromhex(sys.argv[3])
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
