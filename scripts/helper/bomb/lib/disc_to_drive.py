"""Build a pop'n drive-form DNAS 2.80 container from a disc-form .ENC and a
target drive's identity (ATA32 + four).

The chain, all offline:

  1. Parse disc-form records (r7, r21, r2, and per-section r15/r6/r3/r11/r14/H1).
     Every RSA-signed record is copied verbatim to the drive form. r28 also
     copies verbatim -- disc-form and drive-form r28 are byte-identical
     (verified across the .ENC set and MAIN.BIN).
  2. Decrypt the disc payload to recover the SAME inner-encoded region the
     installer's transcrypt would produce (0x2050 bytes = v1 bytes, RC6-CBC
     with r6/r10 as the key/iv). This is the only piece the game actually
     validates in the outer plaintext -- the outer's leading and trailing
     padding are ignored.
  3. Choose ANY 128-byte K1-block plaintext (`blk_plain`). The game reads sec+0x80,
     decrypts with K1 = derive_k1(ata32, four) to recover blk_plain, then
     derives K2 = derive_k2(blk_plain, ata32, four) and uses K2 to decrypt the
     outer. Whatever blk_plain we pick is fine as long as we consistently
     produce sec+0x80 = RC6-enc(blk_plain, K1) and sec+0x300... =
     RC6-enc(outer_plain, K2). PROVEN by round-trip on Nobunaga's
     `PP.SLPM-65197.KOEI.NOBUON\\DBCMAN.ERX`: substituting blk with 0x00*128
     and zeroing the outer's leading + trailing still yields byte-identical
     modules after decrypt.
  4. Emit the drive form:
       [0:0x250]     header (r7 + r21 + r2, copied)
       sec+0..0x80   r6 record (moved from disc's sec+0x80)
       sec+0x80..   RC6-enc(blk_plain, K1)         # 128 B, K1-encrypted
       sec+0x100    r3 record (copied)
       sec+0x180    r11 record (copied)
       sec+0x200    r14 record (copied)
       sec+0x280    H1 encrypted block (copied verbatim)
       sec+0x300    RC6-enc(outer_plain, K2)       # `extent` bytes
       end-0x80     r28 signature record (copied)

     extent = d10 + v1 + pad + 0x10, per Nobunaga's dnasdec.section_module.
     outer_plain[d10:d10+v1] = inner_encoded from disc.
     outer_plain outside [d10:d10+v1] = zero-padded.

For MAIN.BIN (r2 count > 1) the same per-section body applies, and each section
is laid out contiguously with its r28 at end-of-section (except the last, which
uses the file-level r28 at end-0x80). NB: MAIN.BIN's inner-key record is at
sec+0x80 as slot 10, not 6; its content equals disc r6/r14 so the game reads
it as an inner-layer key just the same. This module leaves that record in
place; a caller wanting the "drive form" that matches the installer bit-for-bit
should replace it with slot 6 (same content). See below.

This module reuses Nobunaga's `dnasenc`/`dnaskey`/`dnas2`/`rc6` for the target
drive's K1/K2 derivation -- the derivation is title-independent (same
family).

Sony key material never leaves work/. All bytes we emit are: the disc's own
RSA-signed records + RC6-encrypted data. No Sony private key is used.
"""
import os, sys, struct

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import disc_dec
import dnas2, dnaskey, rc6

_KS = None
def _ks():
    global _KS
    if _KS is None: _KS = dnas2.keys()
    return _KS

class DriveBuildError(Exception): pass

# The 128-byte K1-block plaintext to use for every section. Any value works
# (the game only feeds it into K2 derivation). Zero is chosen for
# reproducibility -- a given (disc, target drive) pair always produces
# byte-identical output.
_BLK_ZERO = b"\x00" * 128

# The last 16 bytes of every drive-form outer plaintext. Koei's genuine installed
# containers all end in this ASCII tag, and the game's DNAS lib carries it next
# to the disc-form tail tag (4571cd4f3dce5a9b): it is the post-decrypt sanity
# check. Zeros there make the game treat the decrypt as failed and retry forever.
DRIVE_TAIL_TAG = b"cfe9b0068e5c24d4"

def _decrypt_section_outer(enc, cursor, disc_size):
    """Return (v1, d9, d10, r6_body, r14_raw, r6_raw, r3_raw, r11_raw, h1_encblob,
    inner_encoded, r15_raw). Reads one disc-form section starting at `cursor`."""
    KS = _ks()
    r15 = dnas2.unrecord(enc[cursor:cursor+128], KS[15][1], KS[15][2])
    if r15 is None:
        raise DriveBuildError("r15 missing at %#x" % cursor)

    # inner key record (slot 6 for .ENC, slot 10 for MAIN.BIN); content is
    # what we'll copy to drive-form sec+0.
    inner_rec = inner_slot = None
    for slot in KS:
        r = dnas2.unrecord(enc[cursor+0x80:cursor+0x100], KS[slot][1], KS[slot][2])
        if r is not None:
            inner_slot, inner_rec = slot, r; break
    if inner_rec is None:
        raise DriveBuildError("no inner-key record verifies at %#x" % (cursor+0x80))

    r3 = dnas2.unrecord(enc[cursor+0x100:cursor+0x180], KS[3][1], KS[3][2])
    r11 = dnas2.unrecord(enc[cursor+0x180:cursor+0x200], KS[11][1], KS[11][2])

    # static2 (slot 14 for .ENC, slot 4 for MAIN.BIN)
    static2_slot = None
    for slot in KS:
        r = dnas2.unrecord(enc[cursor+0x200:cursor+0x280], KS[slot][1], KS[slot][2])
        if r is not None:
            static2_slot = slot; break

    h1 = rc6.cbc(enc[cursor+0x280:cursor+0x300], r11[0][:16], r11[0][16:32], True)
    if h1[10:26] != b"a5713c8bdbe8d420":
        raise DriveBuildError("H1 tag miss at %#x" % cursor)

    v1, v2 = struct.unpack("<II", r3[0][:8])
    d9 = r3[0][9] * 16
    d10 = r3[0][10] * 16
    if v1 & 0xF:
        raise DriveBuildError("v1 %#x is not 16-aligned; extra work needed" % v1)

    disc_payload_start = cursor + 0x300
    disc_payload = enc[disc_payload_start : disc_payload_start + (disc_size - 0x400)]
    d1 = rc6.cbc(disc_payload, r15[0][:16], r15[0][16:32], True)
    if d1[-16:] != b"4571cd4f3dce5a9b":
        raise DriveBuildError("disc-outer tail tag miss at %#x" % cursor)
    # inner-encoded region inside d1 (last v1a bytes before the tail tag)
    v1a = (v1 + 15) & ~0xF
    inner_off = len(d1) - v1a - 0x10
    inner_encoded = d1[inner_off : inner_off + v1]

    return dict(
        cursor       = cursor,
        v1           = v1, v2 = v2, d9 = d9, d10 = d10,
        r6_raw       = enc[cursor+0x80:cursor+0x100],   # slot 6 or 10
        r6_slot      = inner_slot,
        r3_raw       = enc[cursor+0x100:cursor+0x180],
        r11_raw      = enc[cursor+0x180:cursor+0x200],
        r14_raw      = enc[cursor+0x200:cursor+0x280],  # slot 14 or 4
        r14_slot     = static2_slot,
        h1_encblob   = enc[cursor+0x280:cursor+0x300],
        inner_encoded= inner_encoded,
    )

def build_drive_form(enc, ata32, four, blk_plain=_BLK_ZERO):
    """Return the drive-form container bytes for `enc` (a disc-form .ENC /
    MAIN.BIN) sealed to a drive whose identity is (ata32, four).

    `blk_plain` is the 128-byte K1-block plaintext to bake in. Any value works;
    the default is 128 zero bytes (byte-reproducible output)."""
    if len(blk_plain) != 128:
        raise DriveBuildError("blk_plain must be exactly 128 bytes")
    KS = _ks()
    K1 = dnaskey.derive_k1(ata32, four)
    K2 = dnaskey.derive_k2(blk_plain, ata32, four)
    blk_ct = rc6.cbc(blk_plain, K1[:16], K1[16:32], False)

    # Header records
    r7 = dnas2.unrecord(enc[:128], KS[7][1], KS[7][2])
    if r7 is None:
        raise DriveBuildError("r7 (slot 7) does not verify at 0")
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200
    r2 = dnas2.unrecord(enc[sec-0x100:sec-0x80], KS[2][1], KS[2][2])
    if r2 is None:
        raise DriveBuildError("r2 (slot 2) does not verify at sec-0x100=%#x" % (sec-0x100))
    body = r2[0]
    count = int.from_bytes(body[:4], "little")
    disc_sizes = [int.from_bytes(body[4+i*4:8+i*4], "little") for i in range(count)]
    drive_sizes = [int.from_bytes(body[4+count*4+i*4:8+count*4+i*4], "little")
                   for i in range(count)]

    # Build the output buffer piece by piece.
    out = bytearray()
    out += enc[:sec]     # r7, r21, r2 fixed prelude (0x250 bytes)

    cursor = sec
    for i in range(count):
        s = _decrypt_section_outer(enc, cursor, disc_sizes[i])
        v1, d9, d10 = s["v1"], s["d9"], s["d10"]
        pad = (0x10 - (v1 & 0xF)) & 0xF
        extent = d10 + v1 + pad + 0x10

        # outer_plain: leading zeros, inner-encoded in the middle, pad, tail tag
        outer_plain = bytearray(extent)
        outer_plain[d10:d10+v1] = s["inner_encoded"]
        outer_plain[extent-16:extent] = DRIVE_TAIL_TAG

        # Encrypt outer with K2
        outer_ct = rc6.cbc(bytes(outer_plain), K2[:16], K2[16:32], False)

        # Assemble the section
        # sec+0: r6 record (== disc r6/r14; slot 6 for .ENC family, 10 for MAIN.BIN)
        # For maximum compatibility we always use slot 6's format if the disc's
        # inner-key record is already slot 6, else slot 10 (as it appears on disc).
        out += s["r6_raw"]                       # sec+0
        out += blk_ct                            # sec+0x80  (K1-encrypted blk)
        out += s["r3_raw"]                       # sec+0x100
        out += s["r11_raw"]                      # sec+0x180
        out += s["r14_raw"]                      # sec+0x200
        out += s["h1_encblob"]                   # sec+0x280
        out += outer_ct                          # sec+0x300 : sec+0x300+extent

        # r28 for this section: for the last section it comes from file-tail;
        # for intermediate sections it comes from BETWEEN sections (immediately
        # after each section's payload and BEFORE the next section's records).
        # In the disc-form, each intermediate section's tail has r20+r28 at
        # sec+0x300+(disc_size-0x400)..+0x100. Copy the r28 verbatim (game does
        # not enforce the signature per Nobunaga's tests, but retail installers
        # do rewrite/omit r20 -- drive form has NO r20 record, only r28).
        disc_payload_end = cursor + 0x300 + (disc_sizes[i] - 0x400)
        disc_r28 = enc[disc_payload_end + 0x80 : disc_payload_end + 0x100]
        out += disc_r28

        # advance cursor for next disc section
        cursor = disc_payload_end + 0x100

    return bytes(out)
