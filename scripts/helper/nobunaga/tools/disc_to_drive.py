"""Build a Sony DNAS 2.80 drive-form container from a disc-form container and a
target drive's identity (ATA32 + four).

Title-independent. Verified across:
  - Nobunaga (23 .ERX + 6 .EBN + AUTH/BIN/SLPM_651.97, 30/30 round-trip through
    dnasenc.plain_parts + dnasdec.section_module)
  - pop'n Puzzle Dama Online (15 .ENC + MAIN.BIN, live install on hardware
    2026-09-29 -- MODULES/SIO2MAN.IRX read back off the drive decrypts
    byte-identical to the disc plaintext).

The chain, all offline:

  1. Parse disc-form records (r7, r21, r2, and per-section r15/r6/r3/r11/r14/H1).
     Every RSA-signed record is copied verbatim to the drive form. r28 also
     copies verbatim -- disc-form and drive-form r28 are byte-identical.
  2. Decrypt the disc payload to recover the SAME inner-encoded region the
     installer's transcrypt would produce (v1 bytes of RC6-CBC output with
     r6/r10 as the key/iv). This is the only piece the game actually validates
     in the outer plaintext -- the outer's leading and trailing padding are
     ignored.
  3. Choose ANY 128-byte K1-block plaintext (`blk_plain`). The game reads
     sec+0x80, decrypts with K1 = derive_k1(ata32, four) to recover blk_plain,
     then derives K2 = derive_k2(blk_plain, ata32, four) and uses K2 to decrypt
     the outer. Any blk_plain works if we use the same one to produce sec+0x80
     and sec+0x300+.
  4. Emit the drive form:
       [0:sec]      header (r7 + r21 + r2 + identity block, copied)
       sec+0..0x80  r6 record (moved from disc's sec+0x80; slot 6 for
                    .ERX/.ENC/.EBN; slot 10 for the game boot ELF containers
                    where content is identical to what slot 6 would carry)
       sec+0x80..   RC6-enc(blk_plain, K1)         # 128 B, K1-encrypted
       sec+0x100    r3 record (copied)
       sec+0x180    r11 record (copied)
       sec+0x200    r14 record (copied; slot 4 for boot ELFs, same content
                    as r14)
       sec+0x280    H1 encrypted block (copied verbatim)
       sec+0x300    RC6-enc(outer_plain, K2)       # `extent` bytes
       end-0x80     r28 signature record (copied)

     extent = d10 + v1 + pad + 0x10, per dnasdec.section_module.
     outer_plain[d10:d10+v1] = inner_encoded from disc (or the caller-supplied
       inner-encoded region, for the module-override variant).
     outer_plain outside [d10:d10+v1] = zero-padded.

`build_drive_form(enc, ata32, four)` seals a container VERBATIM from disc.
`build_drive_form_patched(enc, ata32, four, patcher)` lets a caller patch the
plaintext module bytes before sealing -- used for the NBONLINE.EBN verdict
patch that turns the console-binding into a genuine-drive-independent pass.

This module reuses `dnas2`/`dnaskey`/`rc6` from the same tools/ dir -- no
title-specific state. Nothing here is a Sony key: everything emitted is the
disc's own RSA-signed records + RC6-encrypted data.
"""
import os, sys, struct

# Reuse the sibling helpers already in this tools/ dir.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dnas2, dnaskey, rc6
import disc_dec  # noqa: F401  (kept as an obvious co-dep of the pipeline)

_KS = None
def _ks():
    global _KS
    if _KS is None: _KS = dnas2.keys()
    return _KS

class DriveBuildError(Exception): pass

# Default 128-byte K1-block plaintext. Any value works (the game only feeds it
# into K2 derivation). Zero is chosen for byte-reproducible output.
_BLK_ZERO = b"\x00" * 128

_H1_TAG    = b"a5713c8bdbe8d420"
_TAIL_TAG  = b"4571cd4f3dce5a9b"


# The last 16 bytes of every drive-form outer layer, as the retail installer
# writes them (the drive-form counterpart of the disc form's tail tag). The
# game checks it before it uses the module: with zeros there, every module
# still decrypts correctly on the PC, but the game stops at its first
# container, a black screen right after the IOP drivers load. Found by the
# HippaulInstaller PCSX2 boot test, 2026-10-04.
DRIVE_TAIL_TAG = b"cfe9b0068e5c24d4"


def _decrypt_section_outer(enc, cursor, disc_size):
    """Return every piece the drive-form sealer needs for one disc section."""
    KS = _ks()
    r15 = dnas2.unrecord(enc[cursor:cursor+128], KS[15][1], KS[15][2])
    if r15 is None:
        raise DriveBuildError("r15 missing at %#x" % cursor)

    inner_rec = inner_slot = None
    for slot in KS:
        r = dnas2.unrecord(enc[cursor+0x80:cursor+0x100], KS[slot][1], KS[slot][2])
        if r is not None:
            inner_slot, inner_rec = slot, r; break
    if inner_rec is None:
        raise DriveBuildError("no inner-key record verifies at %#x" % (cursor+0x80))

    r3 = dnas2.unrecord(enc[cursor+0x100:cursor+0x180], KS[3][1], KS[3][2])
    r11 = dnas2.unrecord(enc[cursor+0x180:cursor+0x200], KS[11][1], KS[11][2])

    static2_slot = None
    for slot in KS:
        r = dnas2.unrecord(enc[cursor+0x200:cursor+0x280], KS[slot][1], KS[slot][2])
        if r is not None:
            static2_slot = slot; break

    h1 = rc6.cbc(enc[cursor+0x280:cursor+0x300], r11[0][:16], r11[0][16:32], True)
    if h1[10:26] != _H1_TAG:
        raise DriveBuildError("H1 tag miss at %#x" % cursor)

    v1, v2 = struct.unpack("<II", r3[0][:8])
    d9 = r3[0][9] * 16
    d10 = r3[0][10] * 16
    if v1 & 0xF:
        raise DriveBuildError("v1 %#x is not 16-aligned; extra work needed" % v1)

    disc_payload_start = cursor + 0x300
    disc_payload = enc[disc_payload_start : disc_payload_start + (disc_size - 0x400)]
    d1 = rc6.cbc(disc_payload, r15[0][:16], r15[0][16:32], True)
    if d1[-16:] != _TAIL_TAG:
        raise DriveBuildError("disc-outer tail tag miss at %#x" % cursor)

    v1a = (v1 + 15) & ~0xF
    inner_off = len(d1) - v1a - 0x10
    inner_encoded = d1[inner_off : inner_off + v1]

    return dict(
        cursor       = cursor,
        v1           = v1, v2 = v2, d9 = d9, d10 = d10,
        r6_raw       = enc[cursor+0x80:cursor+0x100],   # slot 6 or 10
        r6_slot      = inner_slot,
        inner_key    = inner_rec[0][:32],               # decrypted content for
                                                        # re-encoding the module
        r3_raw       = enc[cursor+0x100:cursor+0x180],
        r11_raw      = enc[cursor+0x180:cursor+0x200],
        r14_raw      = enc[cursor+0x200:cursor+0x280],  # slot 14 or 4
        r14_slot     = static2_slot,
        h1_encblob   = enc[cursor+0x280:cursor+0x300],
        inner_encoded= inner_encoded,
    )

def _seal(enc, ata32, four, blk_plain, per_section_module=None,
          per_section_patcher=None):
    """The shared body of `build_drive_form` and `build_drive_form_patched`.

    per_section_module: dict {section_index -> replacement module bytes}. The
                       module must be exactly the section's v2 bytes (v2 is
                       RSA-signed via r3 -- cannot be changed). Overrides the
                       disc's plaintext at inner[d9:d9+v2].
    per_section_patcher: callable(section_index, plaintext_module) ->
                       patched_module. Same length constraint. Convenience
                       when you don't want to pre-decrypt.
    """
    if len(blk_plain) != 128:
        raise DriveBuildError("blk_plain must be exactly 128 bytes")
    KS = _ks()
    K1 = dnaskey.derive_k1(ata32, four)
    K2 = dnaskey.derive_k2(blk_plain, ata32, four)
    blk_ct = rc6.cbc(blk_plain, K1[:16], K1[16:32], False)

    r7 = dnas2.unrecord(enc[:128], KS[7][1], KS[7][2])
    if r7 is None:
        raise DriveBuildError("r7 (slot 7) does not verify at 0")
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200
    r2 = dnas2.unrecord(enc[sec-0x100:sec-0x80], KS[2][1], KS[2][2])
    if r2 is None:
        raise DriveBuildError("r2 (slot 2) does not verify at sec-0x100=%#x"
                              % (sec-0x100))
    body = r2[0]
    count = int.from_bytes(body[:4], "little")
    disc_sizes = [int.from_bytes(body[4+i*4:8+i*4], "little")
                  for i in range(count)]

    out = bytearray()
    out += enc[:sec]     # r7 + r21 + r2 + identity block (fixed prelude)

    cursor = sec
    for i in range(count):
        s = _decrypt_section_outer(enc, cursor, disc_sizes[i])
        v1, v2, d9, d10 = s["v1"], s["v2"], s["d9"], s["d10"]
        pad = (0x10 - (v1 & 0xF)) & 0xF
        extent = d10 + v1 + pad + 0x10

        # Decide what inner-encoded region to write.
        inner_encoded = s["inner_encoded"]

        replacement_module = None
        if per_section_module and i in per_section_module:
            replacement_module = per_section_module[i]
        elif per_section_patcher is not None:
            v1a = (v1 + 15) & ~0xF
            inner_off = len(s["inner_encoded"]) + 0     # (unused; kept for clarity)
            # decrypt disc's inner-encoded to plaintext inner, then module
            # note: inner-encoded length is v1 (aligned); we hold v1 bytes.
            inner_plain = rc6.cbc(s["inner_encoded"],
                                  s["inner_key"][:16], s["inner_key"][16:32], True)
            module = inner_plain[d9:d9+v2]
            new_module = per_section_patcher(i, module)
            if new_module is not None and new_module != module:
                if len(new_module) != v2:
                    raise DriveBuildError(
                        "patcher for section %d returned %d bytes but v2=%d "
                        "(module length is RSA-signed via r3 and cannot change)"
                        % (i, len(new_module), v2))
                replacement_module = new_module
        if replacement_module is not None:
            if len(replacement_module) != v2:
                raise DriveBuildError(
                    "replacement module for section %d must be exactly v2=%d "
                    "bytes (got %d)" % (i, v2, len(replacement_module)))
            # Rebuild inner_encoded with the patched module.
            inner_plain = bytearray(rc6.cbc(s["inner_encoded"],
                                            s["inner_key"][:16],
                                            s["inner_key"][16:32], True))
            inner_plain[d9:d9+v2] = replacement_module
            inner_encoded = rc6.cbc(bytes(inner_plain),
                                    s["inner_key"][:16], s["inner_key"][16:32],
                                    False)

        # Build outer plaintext: leading zeros, inner-encoded, trailing zeros.
        outer_plain = bytearray(extent)
        outer_plain[d10:d10+v1] = inner_encoded
        outer_plain[-16:] = DRIVE_TAIL_TAG

        # RC6-CBC encrypt outer with K2.
        outer_ct = rc6.cbc(bytes(outer_plain), K2[:16], K2[16:32], False)

        # Assemble the drive-form section.
        out += s["r6_raw"]                       # sec+0
        out += blk_ct                            # sec+0x80  (K1-encrypted blk)
        out += s["r3_raw"]                       # sec+0x100
        out += s["r11_raw"]                      # sec+0x180
        out += s["r14_raw"]                      # sec+0x200
        out += s["h1_encblob"]                   # sec+0x280
        out += outer_ct                          # sec+0x300 : sec+0x300+extent

        disc_payload_end = cursor + 0x300 + (disc_sizes[i] - 0x400)
        disc_r28 = enc[disc_payload_end + 0x80 : disc_payload_end + 0x100]
        out += disc_r28

        cursor = disc_payload_end + 0x100

    return bytes(out)

def build_drive_form(enc, ata32, four, blk_plain=_BLK_ZERO):
    """Seal a disc-form container to `(ata32, four)` verbatim (no module patch)."""
    return _seal(enc, ata32, four, blk_plain)

def build_drive_form_patched(enc, ata32, four, patcher, blk_plain=_BLK_ZERO):
    """Seal with a module patcher.

    `patcher` is called as `patcher(section_index, plaintext_module)` and must
    return either the same bytes (no change) or a same-length patched module.
    v2 is RSA-signed via r3 so the module length cannot change; the patcher
    should pad/edit in place.
    """
    return _seal(enc, ata32, four, blk_plain, per_section_patcher=patcher)

def sections_info(enc):
    """Yield (section_index, v1, v2, d9, d10) for each section without
    decrypting. Handy for pre-flight checks."""
    KS = _ks()
    r7 = dnas2.unrecord(enc[:128], KS[7][1], KS[7][2])
    if r7 is None:
        raise DriveBuildError("r7 does not verify at 0")
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200
    r2 = dnas2.unrecord(enc[sec-0x100:sec-0x80], KS[2][1], KS[2][2])
    if r2 is None:
        raise DriveBuildError("r2 does not verify at sec-0x100=%#x" % (sec-0x100))
    body = r2[0]
    count = int.from_bytes(body[:4], "little")
    disc_sizes = [int.from_bytes(body[4+i*4:8+i*4], "little") for i in range(count)]
    cursor = sec
    for i, ds in enumerate(disc_sizes):
        r3 = dnas2.unrecord(enc[cursor+0x100:cursor+0x180], KS[3][1], KS[3][2])
        v1, v2 = struct.unpack("<II", r3[0][:8])
        d9 = r3[0][9] * 16
        d10 = r3[0][10] * 16
        yield i, v1, v2, d9, d10
        cursor += 0x300 + (ds - 0x400) + 0x100
