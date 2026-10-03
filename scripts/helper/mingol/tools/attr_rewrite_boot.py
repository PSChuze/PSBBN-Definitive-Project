"""Rewrite the SYSTEM.CNF section of an attribute-area file so BBNav launches
the title from HDD (pfs:/dnasload.elf) instead of demanding the disc.

The donor's attr carries the retail SYSTEM.CNF (BOOT2 = cdrom0:\\SCPS_150.49;1),
which makes BBNav show "A disc is required to start the software" - the title
never gets a chance to launch our KELF. Nobunaga's HDD-launch pattern instead
uses:

    BOOT2 = pfs:/dnasload.elf
    DNASBOOT2 = pfs:/SCPS_150.49
    VER = 1.01
    VMODE = NTSC
    HDDUNITPOWER= NICHDD

The attr header at +0x10 is (u32 offset, u32 size) pairs; the first pair points
at SYSTEM.CNF at 0x200. We rewrite the CNF, update its size, and leave every
other section (title, icon, jacket) untouched.

    python attr_rewrite_boot.py attr-in.bin attr-out.bin
        [--dnas-boot pfs:/SCPS_150.49] [--boot pfs:/dnasload.elf]

The default DNASBOOT2 is the Minna boot ELF name; --dnas-boot lets you point it
elsewhere. --boot is only there if some other launcher expects hdd0:... form.
"""
import argparse
import struct
import sys

MAGIC = b'PS2ICON3D'
CNF_OFF = 0x200            # header offset+size fields describe this
CNF_LEN_FIELD = 0x14       # u32 at header+0x14 = SYSTEM.CNF size
NEXT_SECTION_MIN = 0x400   # SYSTEM.CNF must not overrun this


def build_cnf(boot, dnas_boot):
    """The retail-shape SYSTEM.CNF, laid out with CRLF like the disc's."""
    lines = [
        b'BOOT2 = ' + boot.encode('latin-1'),
        b'DNASBOOT2 = ' + dnas_boot.encode('latin-1'),
        b'VER = 1.01',
        b'VMODE = NTSC',
        b'HDDUNITPOWER= NICHDD',
    ]
    return b'\r\n'.join(lines) + b'\r\n'


def rewrite(blob, boot, dnas_boot):
    if not blob.startswith(MAGIC):
        raise SystemExit('attr does not start with PS2ICON3D')
    cnf = build_cnf(boot, dnas_boot)
    if CNF_OFF + len(cnf) > NEXT_SECTION_MIN:
        raise SystemExit('new SYSTEM.CNF is %d B; the 0x400 section starts too '
                         'close - the layout would overflow' % len(cnf))
    out = bytearray(blob)
    old_len = struct.unpack_from('<I', out, CNF_LEN_FIELD)[0]
    # Clear the whole old CNF area so we do not leave stale bytes behind.
    end = CNF_OFF + max(old_len, len(cnf))
    for i in range(CNF_OFF, end):
        out[i] = 0
    out[CNF_OFF:CNF_OFF + len(cnf)] = cnf
    struct.pack_into('<I', out, CNF_LEN_FIELD, len(cnf))
    return bytes(out), old_len, len(cnf)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('inp')
    ap.add_argument('outp')
    ap.add_argument('--boot', default='pfs:/dnasload.elf')
    ap.add_argument('--dnas-boot', default='pfs:/SCPS_150.49')
    a = ap.parse_args()

    blob = open(a.inp, 'rb').read()
    out, old_len, new_len = rewrite(blob, a.boot, a.dnas_boot)
    open(a.outp, 'wb').write(out)
    print('SYSTEM.CNF %d -> %d B' % (old_len, new_len))
    print('  BOOT2 = %s' % a.boot)
    print('  DNASBOOT2 = %s' % a.dnas_boot)
    print('wrote %s (%d B, same as input)' % (a.outp, len(out)))


if __name__ == '__main__':
    sys.exit(main())
