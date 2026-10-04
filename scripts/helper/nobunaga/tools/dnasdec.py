"""Decrypt any Koei DNAS2 drive-form container (ERX / EBN / SLPM-65197).

Verified end-to-end on our install against:
  - all 24 .ERX: 20 byte-identical to the disc's plaintext MODULES/*.IRX, 4 valid
    ELFs of different builds (Koei shipped two module sets), 0 failures
  - all 6 .EBN overlays: MWo3 / text heads, correct tags
  - SLPM-65197: 3 sections, RSA sig SHA-1s verify on sec0+sec2 (sec1's sig range
    is a detail; its module is a sane "RESET" blob with the right tag)

The chain (all offline; needs only the target drive's HDD ID and __net four):

    ata32 = 3DES-EDE-CBC-enc(snapshot, keys fp[0:8)/fp[8:16)/fp[16:24), IV fp[24:32))
            fp   = DES-ECB-enc(0x2ace20-input, key 0x2acdf8-key)     [4 blocks]
            snap = {identify[0x40:0x48], identify[0x50:0x60], 8 zeros}
    K1    = dnaskey.derive_k1(ata32, four)      # the drive key
    blk   = RC6-CBC-dec(K1-block, K1[:16], K1[16:])
    K2    = dnaskey.derive_k2(blk, ata32, four) # the bulk key
    outer = RC6-CBC-dec(payload extent, K2)
    inner = RC6-CBC-dec(outer[D10*16 : +v1], static32)
    module= inner[D9*16 : +v2]

Section layout (base from the type-7 record: content[0x20:0x24] + 0x200):
    +0x000 static (type = H1[8]; ERX uses 6, the ELF uses 10)
    +0x080 K1-block (RC6 with K1; THE per-drive binding)
    +0x100 sizes (type = H1[4], usually 3): {v1 padded, v2 true, D9 mod off x16, D10 payload off x16}
    +0x180 session (type 11) -> its content[0:32) decrypts +0x280 (the H1)
    +0x200 static2 (type 14, ERX flavour)
    +0x280 H1: [3] sig type, [4] sizes type, [8] static type; tag a5713c8bdbe8d420
    +0x300 payload extent, then the sig record (type H1[3], tag cfbc3234,
           first 20 bytes = SHA-1 of outer[D10*16 : +v1]), then the next section.
"""
import hashlib
import struct
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dnas2, dnaskey, rc6
from atamat import cbc3, STAT_2ACDF8, STAT_2ACE20
from Crypto.Cipher import DES

_d = DES.new(STAT_2ACDF8, DES.MODE_ECB)
FP = b"".join(_d.encrypt(STAT_2ACE20[i:i + 8]) for i in range(0, 32, 8))

def ata_material(identify):
    snap = identify[0x40:0x48] + identify[0x50:0x60] + bytes(8)
    return cbc3(FP[0:8], FP[8:16], FP[16:24], FP[24:32], snap)

def section_module(blob, sec, ata32, four, K1=None, keys=None):
    keys = keys or dnas2.keys()
    K1 = K1 or dnaskey.derive_k1(ata32, four)
    sess, _ = dnas2.unrecord(blob[sec + 0x180:sec + 0x200], keys[11][1], keys[11][2]) or (None, None)
    if sess is None:
        raise ValueError("no session record at %#x" % (sec + 0x180))
    h1 = rc6.cbc(blob[sec + 0x280:sec + 0x300], sess[:16], sess[16:32], True)
    if h1[10:26] != b"a5713c8bdbe8d420":
        raise ValueError("H1 failed at %#x - not a section base?" % sec)
    sig_t, sizes_t, stat_t = h1[3], h1[4], h1[8]
    sizes, _ = dnas2.unrecord(blob[sec + 0x100:sec + 0x180], keys[sizes_t][1], keys[sizes_t][2]) or (None, None)
    if sizes is None:  # flavour B always uses type 3
        sizes_t = 3
        sizes, _ = dnas2.unrecord(blob[sec + 0x100:sec + 0x180], keys[3][1], keys[3][2]) or (None, None)
    if sizes is None:
        raise ValueError("no sizes record at %#x" % (sec + 0x100))
    stat = None
    for t in (stat_t, 6, 14, 10):
        stat, _ = dnas2.unrecord(blob[sec:sec + 0x80], keys[t][1], keys[t][2]) or (None, None)
        if stat is not None:
            stat_t = t
            break
    if stat is None:
        raise ValueError("no static record at %#x" % sec)
    v1, v2 = struct.unpack("<II", sizes[:8])
    d9, d10 = sizes[9] * 16, sizes[10] * 16
    pad = (0x10 - (v1 & 0xF)) & 0xF
    extent = d10 + v1 + pad + 0x10
    stat, _ = dnas2.unrecord(blob[sec:sec + 0x80], keys[stat_t][1], keys[stat_t][2])
    s32 = stat[:32]
    blk = rc6.cbc(blob[sec + 0x80:sec + 0x100], K1[0:16], K1[16:32], True)
    K2 = dnaskey.derive_k2(blk, ata32, four)
    outer = rc6.cbc(blob[sec + 0x300:sec + 0x300 + extent], K2[0:16], K2[16:32], True)
    inner = rc6.cbc(outer[d10:d10 + v1], s32[0:16], s32[16:32], True)
    sig_off = sec + 0x300 + extent
    sigrec, _ = dnas2.unrecord(blob[sig_off:sig_off + 128], keys[sig_t][1], keys[sig_t][2])
    sig_ok = hashlib.sha1(outer[d10:d10 + v1]).digest() == sigrec[:20]
    info = dict(sec=sec, v1=v1, v2=v2, d9=d9, d10=d10, extent=extent,
                sig_off=sig_off, sig_ok=sig_ok, K2=K2, h1=h1)
    return inner[d9:d9 + v2], inner[d9 + v2:d9 + v2 + 16], sig_off + 0x80, info

def decrypt(blob, ata32, four):
    keys = dnas2.keys()
    r7, tag7 = dnas2.unrecord(blob[0:128], keys[7][1], keys[7][2])
    if r7 is None or tag7 != b"96011a8e95fd1ffc":
        raise ValueError("not a DNAS2 container")
    sec = int.from_bytes(r7[0x20:0x24], "little") + 0x200
    K1 = dnaskey.derive_k1(ata32, four)
    modules = []
    while sec + 0x300 < len(blob):
        mod, tag, nxt, info = section_module(blob, sec, ata32, four, K1, keys)
        modules.append((mod, tag, info))
        if nxt + 0x300 >= len(blob):
            break
        sec = nxt
    return modules
