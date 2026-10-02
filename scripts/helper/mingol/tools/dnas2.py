"""DNAS2 container toolkit (scratch): RSA record keystore + record recovery.

Type table: dnasload.unpacked.bin @ 0x2af390, 100 entries x 200 bytes.
Entry: [0..8) DES key, [8..16) DES-CBC IV, [16..200) DES-CBC ciphertext ->
       {u32 magic, u32 der_len BE, DER rsaEncryption pubkey}.

Record: 128-byte RSA-1024 signature block. Public-op (c^65537 mod n)
recovers PKCS#1 v1.5: 00 01 ff..ff 00 | sha1(20) | 00 | field(12) | pad |
ascii-hex tag (last 16 bytes).
"""
import sys
from Crypto.Cipher import DES
from Crypto.PublicKey import RSA

BASE = 0x200000
TABLE = 0x2af390
NTYPES = 100

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import dnasconsts

def raw_entry(t):
    # the keystore table, extracted to dnas-consts.bin (see dnasconsts.py)
    return dnasconsts.KEYSTORE[200 * t:200 * t + 200]

def desc(t):
    """DES-CBC-decrypt entry -> (magic u32, der bytes) or None."""
    e = raw_entry(t)
    p = DES.new(e[0:8], DES.MODE_CBC, e[8:16]).decrypt(e[16:200])
    magic = int.from_bytes(p[0:4], "big")
    ln = int.from_bytes(p[4:8], "big")
    if ln < 0xb1 and p[8] == 0x30 and p[9] in (0x81, 0x82):
        return magic, p[8:8 + ln]
    return None

def keys():
    out = {}
    for t in range(NTYPES):
        try:
            r = desc(t)
            if r:
                k = RSA.import_key(r[1])
                out[t] = (r[0], k.n, k.e, r[1])
        except Exception:
            pass
    return out

def unrecord(blk, n, e):
    """RSA public-op a 128-byte block; returns (sha1(20), field(12), tag(16)) or None."""
    m = pow(int.from_bytes(blk, "big"), e, n)
    b = m.to_bytes(128, "big")
    if b[0] != 0 or b[1] != 1:
        return None
    i = 2
    while i < len(b) and b[i] == 0xff:
        i += 1
    if i >= len(b) or b[i] != 0:
        return None
    body = b[i + 1:]
    tag = body[-16:]
    return body[:-16], tag

if __name__ == "__main__":
    ks = keys()
    print("types with valid RSA DER:", len(ks))
    for t in sorted(ks):
        magic, n, e, _ = ks[t]
        print("type %2d magic %08x  n=%d bits e=%d" % (t, magic, n.bit_length(), e))
