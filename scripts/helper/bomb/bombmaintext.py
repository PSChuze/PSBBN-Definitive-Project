"""bombmaintext - English for Net de Bomberman's MAIN.BIN and DATA0 overlay strings, applied in memory.

MAIN.BIN and the overlays are DNAS-sealed on the drive, so their text cannot be edited there.
The loader (bombload, textapply.S) carries a text table in a tagged slot and writes it into memory:
once over MAIN.BIN before the game starts, and again after every container load (overlays).
This tool builds that table from the translation TSVs and fills the slot in a loader ELF or KELF
(the KELF signs only its first 32 content bytes, so the slot can be filled after signing).

Table entry: u32 dest | u16 len | u16 glen | guard[glen] | data[len], padded to 4, ended by dest 0.
guard = the original bytes at dest (up to 16); data = English + NUL, padded with NULs to cover the
whole original string. An entry is only written while its original bytes are in memory.

Slot in the loader: [0:16] "BOMBTEXTSLOT0001" | [16:20] u32 table bytes | [32:] table (64 KB).

Besides text, a TSV whose header is `va  guard  data  note` adds raw guarded byte patches (hex,
guard may be empty = always written), e.g. main_patches.en.tsv: the Circle/Cross swap.

Usage:
    python bombmaintext.py build <out.bin> [main_direct.en.tsv overlays_install.en.tsv] [--main MAIN.BIN]
    python bombmaintext.py fill  <loader.elf|.kelf> [table.bin | TSVs...]   # in place
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(HERE, "..", "translation")
DEFAULT_TSVS = [os.path.join(TR, "main_direct.en.tsv"), os.path.join(TR, "overlays_install.en.tsv")]
TAG = b"BOMBTEXTSLOT0001"
SLOT_SIZE = 0x10000
GUARD_MAX = 16
MAIN_BASE = 0x300000


def unesc(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "n":
                out.append("\n"); i += 2; continue
            if n == "t":
                out.append("\t"); i += 2; continue
            if n == "\\":
                out.append("\\"); i += 2; continue
            if n == "x" and i + 3 < len(s):
                out.append(chr(int(s[i + 2:i + 4], 16))); i += 4; continue
        out.append(c)
        i += 1
    return "".join(out)


def patch_rows(path):
    """(va, guard, data) from a patch TSV (header `va guard data note`), else None."""
    lines = open(path, encoding="utf-8").read().replace("\r", "").split("\n")
    if not lines or lines[0].split("\t")[:3] != ["va", "guard", "data"]:
        return None
    out = []
    for l in lines[1:]:
        f = l.split("\t")
        if len(f) < 3 or not f[0]:
            continue
        out.append((int(f[0], 16), bytes.fromhex(f[1]), bytes.fromhex(f[2])))
    return out


def rows(tsvs):
    for path in tsvs:
        if patch_rows(path) is not None:
            continue
        lines = open(path, encoding="utf-8").read().split("\n")
        for l in lines[1:]:
            f = l.split("\t")
            if len(f) < 5 or not f[3]:
                continue
            va = int(f[1].split()[1], 16)
            yield path, va, unesc(f[2]), unesc(f[3]), int(f[4])


def build(tsvs, main_bin=None):
    main = open(main_bin, "rb").read() if main_bin else None
    out = bytearray()
    n = 0
    for path, va, jp, en, mx in rows(tsvs):
        jb = jp.encode("cp932")
        eb = b"" if en.strip() == "" else en.encode("cp932")
        if len(eb) > mx:
            raise SystemExit("%s 0x%x: English is %d bytes, %d available" % (os.path.basename(path), va, len(eb), mx))
        if main is not None and MAIN_BASE <= va < MAIN_BASE + len(main):
            o = va - MAIN_BASE
            if main[o:o + len(jb)] != jb:
                raise SystemExit("0x%x: MAIN.BIN bytes differ from the TSV's Japanese" % va)
        ln = max(len(eb), len(jb)) + 1
        data = eb + b"\0" * (ln - len(eb))
        guard = jb[:GUARD_MAX]
        ent = struct.pack("<IHH", va, ln, len(guard)) + guard + data
        ent += b"\0" * (-len(ent) % 4)
        out += ent
        n += 1
    for path in tsvs:
        for va, guard, data in patch_rows(path) or ():
            if len(guard) > GUARD_MAX:
                raise SystemExit("0x%x: guard over %d bytes" % (va, GUARD_MAX))
            ent = struct.pack("<IHH", va, len(data), len(guard)) + guard + data
            ent += b"\0" * (-len(ent) % 4)
            out += ent
            n += 1
    out += b"\0" * 4
    if len(out) > SLOT_SIZE - 32:
        raise SystemExit("table is %d bytes, the slot holds %d" % (len(out), SLOT_SIZE - 32))
    return bytes(out), n


def fill(path, table):
    d = bytearray(open(path, "rb").read())
    at = d.find(TAG)
    if at < 0 or d.find(TAG, at + 1) >= 0:
        raise SystemExit("%s: expected exactly one %s slot" % (path, TAG.decode()))
    if len(d) < at + SLOT_SIZE:
        raise SystemExit("%s: slot runs past the end of the file" % path)
    slot = bytearray(SLOT_SIZE)
    slot[:16] = TAG
    struct.pack_into("<I", slot, 16, len(table))
    slot[32:32 + len(table)] = table
    d[at:at + SLOT_SIZE] = slot
    with open(path, "wb") as f:
        f.write(d)
    return at


def main(argv):
    if len(argv) < 3 or argv[1] not in ("build", "fill"):
        print(__doc__)
        return 2
    args = argv[2:]
    main_bin = None
    if "--main" in args:
        i = args.index("--main")
        main_bin = args[i + 1]
        del args[i:i + 2]
    target, rest = args[0], args[1:]
    if argv[1] == "build":
        table, n = build(rest or DEFAULT_TSVS, main_bin)
        with open(target, "wb") as f:
            f.write(table)
        print("%d strings, %d table bytes -> %s" % (n, len(table), target))
    else:
        if len(rest) == 1 and rest[0].endswith(".bin"):
            table, n = open(rest[0], "rb").read(), -1
        else:
            table, n = build(rest or DEFAULT_TSVS, main_bin)
        at = fill(target, table)
        print("slot at 0x%x filled with %d table bytes (%s strings) -> %s" % (at, len(table), n, target))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
