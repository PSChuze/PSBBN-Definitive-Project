#!/usr/bin/env python3
"""bombkelf.py - sign a KELF with the same block layout Sony's dnasload uses.

polkelf.build_kelf produces a 128-byte-header KELF with a two-block content
table (32-byte signed head + rest plaintext). Stock HDD-OSD launches a
partition's BOOT2 only when the header is the size a real dnasload has,
928 bytes with a 52-block table -- HANDOFF-bombload-osd.md documents the
bounce. This module builds that shape.

The layout mirrors the one in Nobunaga's `dnasload.elf` on the operator's
drive, verified by parsing that KELF:

    4x (1024, SIGNED|ENCRYPTED)                       head, 4096 bytes
    1x (17872, 0)                                     first body unit
    N x [(16, SIGNED|ENCRYPTED), (17856, 0)]          middle units
    1x (16, SIGNED|ENCRYPTED)                         tail marker
    1x (tail, 0)                                      tail unsigned
    1x (32, SIGNED|ENCRYPTED)                         final marker

The per-block signature is XOR of the block's 8-byte words then EDE2-CBC
under (MG_SIG_MASTER_KEY || MG_SIG_HASH_KEY) with NULL IV -- the same MAC
build_kelf already uses for its single signed block (proven by re-computing
every signed block of the operator's dnasload.elf and matching the stored
sigs).

    python3 bombkelf.py <template.kelf> --encrypt bombload.elf -o bombload.kelf
        [--keys PS2KEYS.dat] [--zones 0xff]

Same signature as polkelf.py's --encrypt, just with the multi-block layout.
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_PSBBN = os.environ.get(
    "PSBBN_HELPER",
    r"E:\Code\PlayOnline Project\psbbn-playonline\scripts\helper",
)
sys.path.insert(0, os.path.join(_PSBBN, "playonline", "lib"))
import polkelf  # noqa: E402

BIT_BLOCK_ENCRYPTED = polkelf.BIT_BLOCK_ENCRYPTED
BIT_BLOCK_SIGNED = polkelf.BIT_BLOCK_SIGNED


def dnasload_layout(size):
    """Match Sony's dnasload.elf block layout, scaled to `size` bytes.

    Returns a list of (block_size, flags) tuples that sum to `size`. The
    smallest content this can carry is 4*1024 + 17872 + 16 + 0 + 32 = 22016
    bytes; below that there is no room for the tail unit and the caller
    should stick with polkelf.build_kelf.
    """
    HEAD_COUNT, HEAD_SIZE = 4, 1024
    UNIT = 17872
    MARKER = 16
    TAIL_MARKER = 32
    SIG_ENC = BIT_BLOCK_SIGNED | BIT_BLOCK_ENCRYPTED
    if size < HEAD_COUNT * HEAD_SIZE + UNIT + MARKER + TAIL_MARKER:
        raise ValueError("content too small for the dnasload layout")
    layout = [(HEAD_SIZE, SIG_ENC)] * HEAD_COUNT
    remaining = size - HEAD_COUNT * HEAD_SIZE
    # First body block: a single unsigned unit sits right after the head.
    layout.append((UNIT, 0))
    remaining -= UNIT
    # Middle units: (16 marker, 17856 body) each, until only one unit-plus-tail
    # would be left. The exit condition mirrors Nobunaga's file: stop while the
    # remainder is still bigger than one full middle unit plus the tail marker,
    # so the tail always has at least (16 marker + 32 trailing marker).
    while remaining > UNIT + MARKER + TAIL_MARKER:
        layout.append((MARKER, SIG_ENC))
        layout.append((UNIT - MARKER, 0))
        remaining -= UNIT
    layout.append((MARKER, SIG_ENC))
    remaining -= MARKER
    tail = remaining - TAIL_MARKER
    if tail < 0:
        raise ValueError("no room for the tail")
    layout.append((tail, 0))
    layout.append((TAIL_MARKER, SIG_ENC))
    if sum(s for s, _ in layout) != size:
        raise AssertionError("layout does not cover content")
    return layout


def _block_sig(ks, blk):
    h = bytes(8)
    for j in range(0, len(blk), 8):
        chunk = blk[j:j + 8].ljust(8, b"\x00")
        h = bytes(a ^ b for a, b in zip(h, chunk))
    key = ks["MG_SIG_MASTER_KEY"] + ks["MG_SIG_HASH_KEY"]
    return polkelf.cbc_encrypt(h, key, 2, polkelf.NULL_IV)


def build_kelf_layout(content, template, ks, layout, zones=None):
    """Sign+encrypt `content` as a KELF, chunked per `layout`.

    `template` supplies the 16-byte UserDefined/system/app_type/flags/zones
    prefix; ContentSize, HeaderSize and BitCount are recomputed from
    `layout`. `zones` (if given) replaces the template's MGZones.
    """
    hdr = bytearray(template[:32])
    if zones is not None:
        struct.pack_into("<I", hdr, 28, zones)
    _cs, _hs, _st, _at, flags, _bc, _mz = struct.unpack_from("<IHBBHHI", hdr, 16)
    keycount = flags >> 4 & 3
    if keycount not in (1, 2, 3):
        raise SystemExit("template flags 0x%X give keycount %d" % (flags, keycount))
    block_count = len(layout)
    header_size = 32 + 8 + 16 + 16 + (block_count * 2 + 1) * 8 + 8 + 8
    struct.pack_into("<I", hdr, 16, len(content))
    struct.pack_into("<H", hdr, 20, header_size)
    struct.pack_into("<H", hdr, 26, 0)                       # BitCount
    hdr = bytes(hdr)

    kbit = b"\xAA" * 16
    kc = b"\xBB" * 16

    # walk `layout`, cutting `content` into blocks, signing SIGNED ones and
    # encrypting ENCRYPTED ones. The IV resets per block (matches Kelf.content).
    table = bytearray(struct.pack("<II", header_size, block_count))
    out_content = bytearray()
    signed_sigs = []
    off = 0
    for size, bflags in layout:
        blk = bytes(content[off:off + size])
        if len(blk) != size:
            raise SystemExit("layout runs past the content")
        off += size
        sig = bytes(8)
        if bflags & BIT_BLOCK_SIGNED:
            sig = _block_sig(ks, blk)
            signed_sigs.append(sig)
        if bflags & BIT_BLOCK_ENCRYPTED:
            blk = polkelf.cbc_encrypt(blk, kc, keycount, ks["MG_CONTENT_IV"])
        out_content += blk
        table += struct.pack("<II", size, bflags) + sig
    if off != len(content):
        raise SystemExit("layout does not cover the whole content (%d of %d)"
                         % (off, len(content)))
    table = bytes(table)

    hsig = polkelf._header_sig(ks, hdr)
    bsig = polkelf._bit_table_sig(ks, kbit, kc, table, block_count)
    sigs = hsig + bsig + b"".join(signed_sigs)               # only SIGNED blocks
    enc = polkelf.cbc_encrypt(sigs, ks["MG_ROOTSIG_MASTER_KEY"], 1, polkelf.NULL_IV)
    rootsig = polkelf.cbc_decrypt(enc[-8:], ks["MG_ROOTSIG_HASH_KEY"], 2, polkelf.NULL_IV)

    kek_seed = bytes(a ^ b for a, b in zip(hdr[:8], hdr[8:16]))
    a = polkelf.cbc_encrypt(
        bytes(x ^ y for x, y in zip(ks["MG_KBIT_IV"], kek_seed)),
        ks["MG_KBIT_MASTER_KEY"], 2, polkelf.NULL_IV)
    b = polkelf.cbc_encrypt(
        bytes(x ^ y for x, y in zip(ks["MG_KC_IV"], kek_seed)),
        ks["MG_KC_MASTER_KEY"], 2, polkelf.NULL_IV)
    kek = a + b
    kbit_enc = (polkelf.cbc_encrypt(kbit[:8], kek, 2, polkelf.NULL_IV)
                + polkelf.cbc_encrypt(kbit[8:], kek, 2, polkelf.NULL_IV))
    kc_enc = (polkelf.cbc_encrypt(kc[:8], kek, 2, polkelf.NULL_IV)
              + polkelf.cbc_encrypt(kc[8:], kek, 2, polkelf.NULL_IV))
    table_enc = polkelf.cbc_encrypt(table, kbit, 2, ks["MG_CONTENT_TABLE_IV"])

    return hdr + hsig + kbit_enc + kc_enc + table_enc + bsig + rootsig + bytes(out_content)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("template", help="a signed KELF whose 32-byte header prefix "
                    "supplies UserDefined/system/app_type/flags/zones "
                    "(the shipped dnasload.elf is the safe choice)")
    ap.add_argument("--encrypt", required=True, metavar="ELF",
                    help="the plaintext ELF to sign")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--keys")
    ap.add_argument("--zones", type=lambda s: int(s, 0),
                    help="MGZones mask (default: template's)")
    a = ap.parse_args()

    ks = polkelf.load_keys(a.keys)
    template = open(a.template, "rb").read()
    content = open(a.encrypt, "rb").read()
    layout = dnasload_layout(len(content))
    out = build_kelf_layout(content, template, ks, layout, a.zones)
    open(a.out, "wb").write(out)

    k = polkelf.Kelf(out, ks).parse(verify=True)
    if k.content() != content:
        raise SystemExit("selftest: content does not round-trip")
    signed = sum(1 for _s, f, _x in k.blocks if f & BIT_BLOCK_SIGNED)
    print("signed %s (%d B) -> %s (%d B), header %d, %d blocks (%d SIGNED)"
          % (os.path.basename(a.encrypt), len(content),
             a.out, len(out), k.header_size, k.block_count, signed))
    print("  selftest: header/bit-table/root signatures verify, "
          "content round-trips byte-exact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
