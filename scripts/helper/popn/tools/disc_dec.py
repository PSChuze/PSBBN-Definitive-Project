"""Decrypt a pop'n DNAS 2.80 disc-form container (.ENC / MAIN.BIN) offline,
using only bytes on the disc and Nobunaga's Sony DNAS keystore.

Traced from work/dnas/dnaslib.c (FUN_002b0ef8 / FUN_002b2350, the streaming
disc-to-drive transcrypt in the game's DNAS library at VA 0x260000-0x2c0000).

Chain (all offline; no physical disc, no console, no HDD ID needed):

For each section (r2's count field; the 15 disc .ENC files have count=1,
MAIN.BIN has count=3):

  sec        = section base (first section: r7_content[0x20:0x24] LE u32
               + 0x200 == 0x250; each next section immediately after the
               previous section's r20+r28 tail records, i.e. cursor +
               0x300 + disc_size[i-1] - 0x400 + 0x100).
  r11_sess   = unrecord(enc[sec+0x180:sec+0x200], slot=11)
  H1         = RC6-CBC-DEC(enc[sec+0x280:sec+0x300],
                           r11_sess[:16], r11_sess[16:32])
  # H1[10:26] must be the ASCII tag "a5713c8bdbe8d420"; H1[0..10] is the
  # per-file type list (see dnaslib.c FUN_002b0ef8 tag-check at line 43448).
  # For the .ENC set the type list is [15, 6, 20, 28, 3, 26, 11, 14, 10, 4],
  # meaning sec+0x80 holds an r6 record; MAIN.BIN uses r10 at that position
  # (whose CONTENT is byte-identical to what r6 would be), and r4 at sec+0x200
  # (== r14 content). So use whichever slot verifies at sec+0x80 as the inner
  # key.
  r15_disc   = unrecord(enc[sec:sec+0x80],          slot=15)
  inner_rec  = unrecord_any_slot(enc[sec+0x80:sec+0x100])       # 6 or 10
  r3_sizes   = unrecord(enc[sec+0x100:sec+0x180],   slot=3)
  v1, v2 = LE u32 pair from r3[:8]; d9 = r3[9]*16

  payload    = enc[sec+0x300 : sec+0x300 + disc_size[i] - 0x400]
  d1         = RC6-CBC-DEC(payload, r15_disc[:16], r15_disc[16:32])
  # d1 tail 16 bytes must be ASCII "4571cd4f3dce5a9b"
  # (dnaslib.c FUN_002b2350 state-2 tag check at line 44370)
  v1_aligned = (v1 + 15) & ~15
  inner_off  = len(d1) - v1_aligned - 0x10
  inner      = RC6-CBC-DEC(d1[inner_off : inner_off + v1_aligned],
                           inner_rec[:16], inner_rec[16:32])
  module_i   = inner[d9 : d9 + v2]

  module     = module_0 || module_1 || ... (KELF plaintext for MAIN.BIN,
               single .IRX for the .ENC files).

The r15 record is a standard Sony DNAS2 RSA-1024 record; the whole chain
uses only bytes in the .ENC file plus the public keystore. Nobunaga's earlier
"needs a 24-byte physical-disc capture" theory was from dnasload3.c, which
never references the disc-form tags 980f3dc2 / 30fad789; the installer's own
DNAS library (inside SLPM_624.64) is what performs the transcrypt, and it
needs nothing outside the .ENC file.
"""
import sys, os, struct, hashlib

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
    """Return (slot, unrec-tuple) for the first keystore slot that verifies at
    off, or (None, None)."""
    KS = _ks()
    for slot in KS:
        r = dnas2.unrecord(blob[off:off+128], KS[slot][1], KS[slot][2])
        if r is not None:
            return slot, r
    return None, None

_H1_TAG   = b"a5713c8bdbe8d420"   # dnaslib.c FUN_002b0ef8, line 43448
_TAIL_TAG = b"4571cd4f3dce5a9b"   # dnaslib.c FUN_002b2350, line 44370

class DiscDecryptError(Exception):
    pass

def _decrypt_section(enc, cursor, disc_size):
    """Decrypt one section starting at `cursor` (offset of r15). Returns the
    plaintext module bytes for this section."""
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
    pay_len   = disc_size - 0x400   # r15/inner/r3/r11/(r14|r4)/H1 + tail r20/r28
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
    return inner[d9 : d9 + v2]

def decrypt_disc_container(enc):
    """Return the concatenated plaintext module bytes (.IRX for the .ENC set,
    KELF plaintext for MAIN.BIN) from a disc-form DNAS 2.80 container."""
    r7  = _unrec(enc, 0, 7)
    if r7 is None:
        raise DiscDecryptError("r7 (slot 7, descriptor) did not RSA-verify")
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200

    # r2 sits at sec-0x100 (0x150 for pop'n .ENC/MAIN.BIN whose sec=0x250;
    # 0x140 for Nobunaga .EBN whose sec=0x240).
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
        # next section: skip payload + r20 + r28 (128 + 128)
        cursor += 0x300 + (ds - 0x400) + 0x100
    return b"".join(parts)

def _selftest():
    root = os.path.dirname(os.path.abspath(__file__))
    mod_dir = os.path.join(root, "..", "disc", "MODULES")
    pairs = [
        ("SIO2MAN.ENC",  "SIO2MAN.IRX"),
        ("LIBSD.ENC",    "LIBSD.IRX"),
        ("PADMAN.ENC",   "PADMAN.IRX"),
        ("USBD.ENC",     "USBD.IRX"),
        ("NETCNF.ENC",   "NETCNF.IRX"),
        ("BBNETCNF.ENC", "BBNETCNF.IRX"),
        ("EENETCTL.ENC", "EENETCTL.IRX"),
        ("ENT_DEVM.ENC", "ENT_DEVM.IRX"),
        ("ENT_SMAP.ENC", "ENT_SMAP.IRX"),
        ("MODHSYN.ENC",  "MODHSYN.IRX"),
        ("MODMIDI.ENC",  "MODMIDI.IRX"),
        ("NETCNFIF.ENC", "NETCNFIF.IRX"),
        ("SDDRV.ENC",    "SDDRV.IRX"),
        ("SDVSTR.ENC",   "SDVSTR.IRX"),
        ("USBKB.ENC",    "USBKB.IRX"),
    ]
    ok = fail = 0
    for enc_name, irx_name in pairs:
        ep = os.path.join(mod_dir, enc_name)
        ip = os.path.join(mod_dir, irx_name)
        if not (os.path.exists(ep) and os.path.exists(ip)):
            print("  skip %s (missing)" % enc_name); continue
        enc = open(ep, "rb").read()
        irx = open(ip, "rb").read()
        try:
            mod = decrypt_disc_container(enc)
        except DiscDecryptError as e:
            print("  FAIL %-16s %s" % (enc_name, e)); fail += 1; continue
        if mod == irx:
            print("  OK   %-16s %6d B" % (enc_name, len(mod))); ok += 1
        else:
            print("  DIFF %-16s got=%d B irx=%d B" % (enc_name, len(mod), len(irx)))
            fail += 1

    # MAIN.BIN: multi-section (r2 count=3) container. Its plaintext is the
    # KELF the installer re-signs as BLJA-00010. We can't cross-check against
    # the installed BLJA-00010 byte-for-byte (that would need the installer to
    # re-run the KELF signing step or the drive's HDD ID), so we just verify:
    # every section decrypts cleanly (tag check inside _decrypt_section) and
    # the concatenated plaintext starts with a KELF magic.
    main_p = os.path.join(root, "..", "disc", "MAIN.BIN")
    if os.path.exists(main_p):
        enc = open(main_p, "rb").read()
        try:
            plain = decrypt_disc_container(enc)
        except DiscDecryptError as e:
            print("  FAIL MAIN.BIN        %s" % e); fail += 1
        else:
            magic = plain[:4]
            kelf  = magic in (b"\xea\xc7\x00\x5a", b"\x01\xc7\x00\x5a")
            print("  OK   MAIN.BIN     %8d B  magic=%s%s"
                  % (len(plain), magic.hex(),
                     "  (KELF)" if kelf else "  (unknown)"))
            if not kelf:
                fail += 1

    print("selftest: %d ok, %d failed" % (ok, fail))
    return fail == 0

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.exit(0 if _selftest() else 1)
    for p in sys.argv[1:]:
        enc = open(p, "rb").read()
        mod = decrypt_disc_container(enc)
        out = os.path.splitext(p)[0] + ".plain"
        open(out, "wb").write(mod)
        print("%s -> %s (%d bytes)" % (p, out, len(mod)))
