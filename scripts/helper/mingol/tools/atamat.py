"""The ata-material pipeline (FUN_00208430 -> FUN_0020d720) + the LCG + the seed brute.

d720(snapshot32, lcg1, lcg2, lcg3) -> 56-byte OUT:
    dyn[0]     = (2 + lcg2[0]*4) & 0xff          marker
    dyn[1:8)   = lcg2[1:8)
    dyn[8:40)  = snapshot32
    dyn[40:48) = EDE3(lcg1 ^ iv2, k@0x2acdd8)     one CBC block
    dyn[48:56) = lcg3
    fp[0:32)   = DES-ECB-enc(0x2ace20[0:32), key 0x2acdf8[0:8))
    dyn[8:56)  = 3DES-EDE-CBC-enc(dyn[8:56), fp[0:8)/fp[8:16)/fp[16:24), IV fp[24:32))
    OUT = dyn
The W/engine material = OUT[24:56).

LCG (FUN_00240548): state = state*0x5851f42d4c957f2d + 1 (64-bit); a draw returns
(state>>32)&0x7fffffff; the byte = its top 8 bits.  The seed (FUN_00208690) =
clock[5] | clock[3]<<8 | clock[2]<<16 | clock[1]<<24 of the sceCdRC reply.

Draw sequence from the reseed (the session-record read, FUN_00203830 step 1):
    200  d978's success wipe
    176  da68's epilogue wipe (0xb0)
    128  the session-record buffer wipe
    128  the H1-plaintext wipe
    24   K1's 08430: lcg1, lcg2, lcg3
     32  the drive-key wipe
    24   K2's 08430: lcg1', lcg2', lcg3'
"""
import sys
from Crypto.Cipher import DES

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dnasconsts import STAT_2ACDD8, STAT_2ACDF8, STAT_2ACE20  # noqa: F401

class LCG:
    M = 0x5851f42d4c957f2d
    __slots__ = ("s",)
    def __init__(self, seed32):
        self.s = seed32 & 0xFFFFFFFF
    def byte(self):
        self.s = (self.s * LCG.M + 1) & 0xFFFFFFFFFFFFFFFF
        return ((self.s >> 32) & 0x7FFFFFFF) >> 23

def ede3(k1, k2, k3, blk):
    d1 = DES.new(k1, DES.MODE_ECB)
    d2 = DES.new(k2, DES.MODE_ECB)
    d3 = DES.new(k3, DES.MODE_ECB)
    return d3.encrypt(d2.decrypt(d1.encrypt(blk)))

def cbc3(k1, k2, k3, iv, data):
    prev = iv
    out = bytearray()
    for i in range(0, len(data), 8):
        c = ede3(k1, k2, k3, bytes(x ^ y for x, y in zip(data[i:i + 8], prev)))
        out += c
        prev = c
    return bytes(out)

def d720(snapshot32, lcg1, lcg2, lcg3):
    dyn = bytearray(56)
    dyn[0] = (2 + lcg2[0] * 4) & 0xFF
    dyn[1:8] = lcg2[1:8]
    dyn[8:40] = snapshot32
    dyn[40:48] = ede3(STAT_2ACDD8[0:8], STAT_2ACDD8[8:16], STAT_2ACDD8[16:24],
                      bytes(x ^ y for x, y in zip(lcg1, STAT_2ACDD8[24:32])))
    dyn[48:56] = lcg3
    d = DES.new(STAT_2ACDF8, DES.MODE_ECB)
    fp = b"".join(d.encrypt(STAT_2ACE20[i:i + 8]) for i in range(0, 32, 8))
    dyn[8:56] = cbc3(fp[0:8], fp[8:16], fp[16:24], fp[24:32], bytes(dyn[8:56]))
    return bytes(dyn)

def material(lcg, skip):
    """Skip `skip` draws, then return the two 24-byte lcg triples for K1/K2."""
    for _ in range(skip):
        lcg.byte()
    t1 = bytes(lcg.byte() for _ in range(24))
    for _ in range(32):
        lcg.byte()
    t2 = bytes(lcg.byte() for _ in range(24))
    return t1, t2
