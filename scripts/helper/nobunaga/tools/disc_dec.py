"""Decrypt a Sony DNAS 2.80 disc-form container (.ERX / .EBN / boot ELF) offline.

Title-independent: works on any Sony DNAS 2.80 disc container, verified across
Nobunaga (23 .ERX + 6 .EBN + AUTH/BIN/SLPM_651.97 = 30 containers, all
byte-identical to the neutral bundle's modules), and pop'n Puzzle Dama Online
(15 .ENC + MAIN.BIN, all byte-identical to disc plaintext .IRX twins).

Traced from pop'n's dnaslib.c FUN_002b0ef8 / FUN_002b2350 (the streaming
disc-to-drive transcrypt inside SLPM_624.64's DNAS library at VA
0x260000-0x2c0000). The same chain applies to Nobunaga's SLPM_657.83.

Chain (offline; needs only the container bytes + the public DNAS keystore):

  sec        = r7_content[0x20:0x24] LE u32 + 0x200
               (0x250 for .ERX / .ENC / MAIN.BIN, 0x240 for .EBN)
  r2         = unrecord(enc[sec-0x100:sec-0x80], slot=2)
  disc_sizes = r2 body [4..4+count*4] as LE u32
  For each section i (r2 count field; single-section for .ERX/.ENC,
  multi-section for MAIN.BIN and SLPM_651.97):

    r15_disc   = unrecord(enc[cursor:cursor+0x80], slot=15)     # disc-form
    inner_rec  = unrecord_any_slot(enc[cursor+0x80:cursor+0x100])   # 6 or 10
    r3_sizes   = unrecord(enc[cursor+0x100:cursor+0x180], slot=3)
    r11_sess   = unrecord(enc[cursor+0x180:cursor+0x200], slot=11)
    H1         = RC6-CBC-DEC(enc[cursor+0x280:cursor+0x300],
                             r11[:16], r11[16:32])
    # H1[10:26] must be ASCII "a5713c8bdbe8d420"

    v1, v2  = LE u32 pair from r3[:8]; d9 = r3[9]*16

    payload = enc[cursor+0x300 : cursor+0x300 + disc_size[i] - 0x400]
    d1      = RC6-CBC-DEC(payload, r15[:16], r15[16:32])
              # d1[-16:] must be ASCII "4571cd4f3dce5a9b"
    v1a     = (v1 + 15) & ~15
    inner_off = len(d1) - v1a - 0x10
    inner   = RC6-CBC-DEC(d1[inner_off : inner_off + v1a],
                          inner_rec[:16], inner_rec[16:32])
    module_i = inner[d9 : d9 + v2]

    # next section (multi-section only): skip r20+r28 tail (0x100 B) after
    # this section's payload
    cursor += 0x300 + (disc_size[i] - 0x400) + 0x100

  module = module_0 || module_1 || ...
"""
import sys, os, struct

# Reuse the sibling constants / RSA / RC6 already in this tools/ dir.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dnas2, rc6

_KS = None
def _ks():
    global _KS
    if _KS is None:
        _KS = dnas2.keys()
    return _KS

def _unrec(blob, off, slot):
    KS = _ks()
    return dnas2.unrecord(blob[off:off+128], KS[slot][1], KS[slot][2])

def _unrec_any(blob, off):
    KS = _ks()
    for slot in KS:
        r = dnas2.unrecord(blob[off:off+128], KS[slot][1], KS[slot][2])
        if r is not None:
            return slot, r
    return None, None

_H1_TAG   = b"a5713c8bdbe8d420"
_TAIL_TAG = b"4571cd4f3dce5a9b"

class DiscDecryptError(Exception):
    pass

def _decrypt_section(enc, cursor, disc_size, tag=False):
    r15 = _unrec(enc, cursor, 15)
    if r15 is None:
        raise DiscDecryptError("r15 did not RSA-verify at %#x" % cursor)
    _, inner_rec = _unrec_any(enc, cursor + 0x80)
    if inner_rec is None:
        raise DiscDecryptError("no keystore slot verifies at %#x (inner key)"
                               % (cursor + 0x80))
    r3 = _unrec(enc, cursor + 0x100, 3)
    if r3 is None:
        raise DiscDecryptError("r3 (sizes) did not verify at %#x" % (cursor + 0x100))
    r11 = _unrec(enc, cursor + 0x180, 11)
    if r11 is None:
        raise DiscDecryptError("r11 (session) did not verify at %#x" % (cursor + 0x180))
    h1 = rc6.cbc(enc[cursor+0x280:cursor+0x300],
                 r11[0][:16], r11[0][16:32], True)
    if h1[10:10+16] != _H1_TAG:
        raise DiscDecryptError("H1 tag mismatch at %#x: got %r"
                               % (cursor, h1[10:10+16]))

    v1, v2 = struct.unpack("<II", r3[0][:8])
    d9 = r3[0][9] * 16

    pay_start = cursor + 0x300
    pay_len   = disc_size - 0x400
    payload   = enc[pay_start : pay_start + pay_len]

    d1 = rc6.cbc(payload, r15[0][:16], r15[0][16:32], True)
    if d1[-16:] != _TAIL_TAG:
        raise DiscDecryptError("disc-outer tail tag mismatch at %#x: got %r"
                               % (cursor, d1[-16:]))

    v1a = (v1 + 15) & ~0xf
    inner_off = len(d1) - v1a - 0x10
    if inner_off < 0:
        raise DiscDecryptError("v1_aligned %d > len(d1) %d" % (v1a, len(d1)))
    inner = rc6.cbc(d1[inner_off : inner_off + v1a],
                    inner_rec[0][:16], inner_rec[0][16:32], True)
    # tag=True also returns the 16-byte trailer that follows the module in the
    # plaintext (the drive-form decrypt keeps it too); the boot-loader fill uses
    # it so the embedded ELF/IOPRP match the proven loader byte for byte.
    return inner[d9 : d9 + v2 + (16 if tag else 0)]

def sections(enc):
    """Yield (cursor, disc_size, v1, v2, d9) per section without decrypting.
    Useful when the caller wants to build a drive-form container from disc."""
    r7 = _unrec(enc, 0, 7)
    if r7 is None:
        raise DiscDecryptError("r7 did not verify at 0")
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200
    r2 = _unrec(enc, sec - 0x100, 2)
    if r2 is None:
        raise DiscDecryptError("r2 did not verify at sec-0x100=%#x" % (sec - 0x100))
    body = r2[0]
    count = int.from_bytes(body[:4], "little")
    disc_sizes = [int.from_bytes(body[4+i*4:8+i*4], "little") for i in range(count)]
    cursor = sec
    for i, ds in enumerate(disc_sizes):
        r3 = _unrec(enc, cursor + 0x100, 3)
        v1, v2 = struct.unpack("<II", r3[0][:8])
        d9 = r3[0][9] * 16
        yield i, cursor, ds, v1, v2, d9
        cursor += 0x300 + (ds - 0x400) + 0x100

def decrypt_disc_container(enc):
    """Return the concatenated plaintext module bytes (single .IRX for the
    .ERX/.ENC set; KELF plaintext for MAIN.BIN and boot-ELF containers)."""
    r7 = _unrec(enc, 0, 7)
    if r7 is None:
        raise DiscDecryptError("r7 (slot 7, descriptor) did not RSA-verify")
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200
    r2 = _unrec(enc, sec - 0x100, 2)
    if r2 is None:
        raise DiscDecryptError("r2 (slot 2, section list) did not RSA-verify")
    body = r2[0]
    count = int.from_bytes(body[:4], "little")
    if count < 1 or 4 + count * 8 > len(body):
        raise DiscDecryptError("r2 count %d does not fit in body %d B"
                               % (count, len(body)))
    disc_sizes = [int.from_bytes(body[4 + i*4 : 8 + i*4], "little")
                  for i in range(count)]
    cursor = sec
    parts  = []
    for i, ds in enumerate(disc_sizes):
        parts.append(_decrypt_section(enc, cursor, ds))
        cursor += 0x300 + (ds - 0x400) + 0x100
    return b"".join(parts)

def is_disc_container(blob):
    """Cheap check: does `blob` look like a disc-form DNAS 2.80 container?"""
    if len(blob) < 0x300:
        return False
    return _unrec(blob, 0, 7) is not None

if __name__ == "__main__":
    for p in sys.argv[1:]:
        enc = open(p, "rb").read()
        mod = decrypt_disc_container(enc)
        out = os.path.splitext(p)[0] + ".plain"
        open(out, "wb").write(mod)
        print("%s -> %s (%d bytes)" % (p, out, len(mod)))
