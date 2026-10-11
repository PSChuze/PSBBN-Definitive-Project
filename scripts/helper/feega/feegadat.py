"""feega.dat codec: the saved feega-ID and password the games' Load button reads.

Bomberman Online reads pfs2:/etc/feega/feega.dat (pfs2 = hdd0:__sysconf) with Sony's "Billing-System
Data Format" library (MAIN.BIN 0x43b010; FEEGAGUI.ELF carries the same library with the writer).
Layout (1024 bytes, read in full):

  +0x000  00 01 00 00                 format tag (anything else: -101)
  +0x040  32 B DES-CBC(key C1[0:8], iv C1[8:16]) of: 16 B secret S, then C2 (else -102)
  +0x060  816 B DES-CBC(key K[0:8], iv K[8:16]) of: 32 B filler, 768 B record, C3 (else -103)
          K = SHA-1(C4 || key24 || S)[0:16], each byte XOR SHA-1[16 + i % 4]
  the rest is filler.

key24 is the console's i.Link ID (sceCdRI) spread 3 values per byte, as netcnf does:
(b >> 5) + 1, ((b >> 2) & 7) + 1, (b & 3) + 1. In game every reader gets the loader's psbb ID
(scefix 1.4), so files built for 07 00 00 1a d5 91 0c 10 load on every console.

Record (768 B): "Billing-System Data Format:" + 5 decimal digits (0x1b), feega-ID at 0x20 (64 B),
password at 0x60 (32 B), NUL padded.
"""
import hashlib
import os

from Crypto.Cipher import DES

C1 = bytes.fromhex("b7f71ae57aa73d0e17e3f14fbd9fda71")
C2 = bytes.fromhex("f2fe366da625ebb6b25ec925ea9876ab")
C3 = bytes.fromhex("5ffeb4fc926b4a34a8b72f1ab8ecb614")
C4 = bytes.fromhex("7f0085847f560914c0f407416fa6be5b8f6f88a4865e5653f76b89f1aafd0f29"
                   "fd95ae7debb892acac99ee1b3fac77cf1bff73a25dcaf655368046e07d560a7a")
MAGIC = b"Billing-System Data Format:"
PSBB_ILINK = bytes.fromhex("0700001ad5910c10")
SIZE = 1024


def key24(ilink):
    out = bytearray()
    for b in ilink:
        out += bytes([(b >> 5) + 1, ((b >> 2) & 7) + 1, (b & 3) + 1])
    return bytes(out)


def _file_key(ilink, secret):
    h = hashlib.sha1(C4 + key24(ilink) + secret).digest()
    return bytes(h[i] ^ h[16 + i % 4] for i in range(16))


def _des(key16, data, enc):
    c = DES.new(key16[:8], DES.MODE_CBC, iv=key16[8:16])
    return c.encrypt(data) if enc else c.decrypt(data)


def record(feega_id, password, number=0):
    rec = bytearray(768)
    head = MAGIC + b"%05d" % number
    rec[:len(head)] = head
    fid, pw = feega_id.encode("ascii"), password.encode("ascii")
    if not 0 < len(fid) < 64 or not 0 < len(pw) < 32:
        raise ValueError("feega-ID must be 1..63 characters and the password 1..31")
    rec[0x20:0x20 + len(fid)] = fid
    rec[0x60:0x60 + len(pw)] = pw
    return bytes(rec)


def build(feega_id, password, ilink=PSBB_ILINK, rand=os.urandom):
    secret = rand(16)
    out = bytearray(rand(SIZE))
    out[0:4] = b"\x00\x01\x00\x00"
    out[0x40:0x60] = _des(C1, secret + C2, True)
    out[0x60:0x60 + 816] = _des(_file_key(ilink, secret), rand(32) + record(feega_id, password) + C3, True)
    return bytes(out)


def parse(data, ilink=PSBB_ILINK):
    """(feega-ID, password) or raise ValueError with the game's error stage."""
    if data[0:4] != b"\x00\x01\x00\x00":
        raise ValueError("not a feega.dat (-101)")
    head = _des(C1, data[0x40:0x60], False)
    if head[16:] != C2:
        raise ValueError("bad header block (-102)")
    body = _des(_file_key(ilink, head[:16]), data[0x60:0x60 + 816], False)
    if body[800:816] != C3:
        raise ValueError("wrong console i.Link ID or damaged file (-103)")
    rec = body[32:800]
    if rec[:27] != MAGIC:
        raise ValueError("record header missing")
    cut = lambda b: b.split(b"\0", 1)[0].decode("ascii", "replace")
    return cut(rec[0x20:0x60]), cut(rec[0x60:0x80])
