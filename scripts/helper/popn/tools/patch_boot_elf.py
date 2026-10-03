"""Reproduce the three disc-less-boot patches on pop'n's boot ELF, from any
player's own disc, offline and reproducibly.

The game's boot executable is the EXEC ELF carried inside the BLJA-00010 KELF
plaintext (what `disc_dec.decrypt_disc_container(MAIN.BIN)` returns). It loads
at EE VA 0x100000, so file offset = VA - 0x100000 + phdr0_off (0x80).

Three one-word patches turn it into the disc-less boot ELF (see
`popn/SOLUTION-disc-less-boot.md` §B). Words are MIPS instructions stored
little-endian; the "orig"/"new" encodings below are the big-endian instruction
words reversed to their on-disk byte order:

  | VA       | file off | orig (word) | new (word)  | effect                      |
  |----------|----------|-------------|-------------|-----------------------------|
  | 0x2154f0 | 0x115570 | 0c0818e0    | 24020000    | startup DNAS auth skip      |
  | 0x1cf3c8 | 0x0cf448 | 0c081998    | 24020000    | in-game DNAS auth skip      |
  | 0x1cfddc | 0x0cfe5c | 24020014    | 2402000a    | login disc-ownership skip   |

Every write is GUARDED, the same discipline as `playonline.loader.gate_patch`:
the word is replaced only where it currently equals the documented "orig".
A word already equal to "new" is left alone (idempotent re-run). Any other
value aborts the whole patch -- a disc whose ELF does not match this layout is
not SLPM-62464/BLJA-00010 and must not be blindly poked.

Patches 1-2 are the DNAS online-auth bypass; patch 3 is the disc-ownership
bypass. Both are operator-approved for this title family (Rule 3); no disc data
is read, kept, or sent. The patched ELF is fed to the loader fill step
(`playonline.loader --elf ...`), never re-signed on the player's machine.

A fourth, separate patch (RELAY_PATCHES, on by default; --no-relay to skip)
makes online battles work without port forwarding. Battles are console-to-
console over TCP 5730: the room owner LISTENS and the guest CONNECTS, then they
swap on retry, so one player always needs inbound 5730. The patch turns the
role branch in the P2P setup (FUN_001d5890 in the disc build = 0x1d442c here)
into an unconditional branch to the connector path, so BOTH consoles wait 45
frames and connect out, to whatever address the server put in 0x440b -- the
server's relay, which pairs the two connections. The per-frame exchange
(FUN_001c94e0) is symmetric and never reads the stored mode, so nothing else
changes. A relay-patched console can only battle through the relay
(server/popn/relay.py); see popn/re/RE-match-45xx.md for the P2P code.

  | VA       | file off | orig (word) | new (word)  | effect                      |
  |----------|----------|-------------|-------------|-----------------------------|
  | 0x1d442c | 0x0d44ac | 16200010    | 10000010    | P2P: both roles connect out |

Usage:
    # from a disc extract (decrypt MAIN.BIN, carve, patch):
    python3 patch_boot_elf.py --main <disc>/MAIN.BIN -o blja-game.patched.elf
    # from an already-carved EXEC ELF:
    python3 patch_boot_elf.py --elf blja-game.elf   -o blja-game.patched.elf
    # self-test against the reference artifacts:
    python3 patch_boot_elf.py --selftest
"""
import argparse
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# EXEC ELF identity inside the KELF plaintext (SLPM-62464 / BLJA-00010).
EXEC_ENTRY = 0x00100008      # e_entry of the game EXEC ELF
LOAD_VA_BASE = 0x00100000    # phdr0 p_vaddr
PHDR0_OFF = 0x80             # phdr0 p_offset -> file off = VA - base + 0x80

# The IOP reboot image (DNAS280.IMG, version "2800") the game requires. It sits
# at a fixed offset in the KELF plaintext, begins with the RESET romdir, and is
# byte-identical to the disc's MODULES/DNAS280.IMG. The game asks the IOP
# loadfile for its version and only accepts "2800"; Nobunaga's 2710 image makes
# every sceSifLoadModule fail and the init loop retries forever. Length is
# fixed for this title.
IOPRP_OFF = 0x6100
IOPRP_LEN = 272705

# (va, file_off, orig_bytes_LE, new_bytes_LE, description)
PATCHES = [
    (0x2154f0, 0x115570, b"\xe0\x18\x08\x0c", b"\x00\x00\x02\x24",
     "startup DNAS auth skip (sceDNAS2Init+authStart+GetStatus -> return 0)"),
    (0x1cf3c8, 0x0cf448, b"\x98\x19\x08\x0c", b"\x00\x00\x02\x24",
     "in-game DNAS auth skip (other auth call site -> return 0)"),
    (0x1cfddc, 0x0cfe5c, b"\x14\x00\x02\x24", b"\x0a\x00\x02\x24",
     "login disc-check skip (next-scene state 20 begin-disc-check -> 10 login-connect)"),
]

# bnez $s1, connector-path -> beq $zero,$zero, connector-path (same target; the
# delay-slot store runs either way).
RELAY_PATCHES = [
    (0x1d442c, 0x0d44ac, b"\x10\x00\x20\x16", b"\x10\x00\x00\x10",
     "P2P relay: listener role takes the connector path (both connect out)"),
]


class PatchError(Exception):
    pass


def _u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def find_exec_elf(buf):
    """Return the file offset of the EXEC game ELF inside `buf` (a KELF
    plaintext). Identifies it by ELF32/LE/MIPS, ET_EXEC, and e_entry ==
    EXEC_ENTRY -- the KELF also carries an IOPRP image and other blobs, so a
    plain `\\x7fELF` scan is not enough."""
    start = 0
    while True:
        i = buf.find(b"\x7fELF", start)
        if i < 0:
            raise PatchError("no EXEC ELF (entry %#010x) found in %d bytes"
                             % (EXEC_ENTRY, len(buf)))
        start = i + 4
        if i + 52 > len(buf):
            continue
        ei_class, ei_data = buf[i + 4], buf[i + 5]
        if ei_class != 1 or ei_data != 1:        # ELF32, little-endian
            continue
        e_type = _u16(buf, i + 16)
        e_machine = _u16(buf, i + 18)
        e_entry = _u32(buf, i + 24)
        if e_type == 2 and e_machine == 8 and e_entry == EXEC_ENTRY:
            return i
    # unreachable


def elf_span(buf, off):
    """Total on-file byte length of the ELF whose header is at `off`, from its
    program and section headers (max end of any non-NOBITS region)."""
    if buf[off:off + 4] != b"\x7fELF":
        raise PatchError("no ELF magic at %#x" % off)
    e_phoff = _u32(buf, off + 28)
    e_shoff = _u32(buf, off + 32)
    e_phentsize = _u16(buf, off + 42)
    e_phnum = _u16(buf, off + 44)
    e_shentsize = _u16(buf, off + 46)
    e_shnum = _u16(buf, off + 48)
    end = 0
    if e_phoff:
        end = max(end, e_phoff + e_phnum * e_phentsize)
        for k in range(e_phnum):
            p = off + e_phoff + k * e_phentsize
            end = max(end, _u32(buf, p + 4) + _u32(buf, p + 16))   # p_offset + p_filesz
    if e_shoff:
        end = max(end, e_shoff + e_shnum * e_shentsize)
        for k in range(e_shnum):
            s = off + e_shoff + k * e_shentsize
            if _u32(buf, s + 4) == 8:            # SHT_NOBITS occupies no file space
                continue
            end = max(end, _u32(buf, s + 16) + _u32(buf, s + 20))  # sh_offset + sh_size
    return end


def carve_game_elf(kelf_plain):
    """Return the EXEC game ELF bytes carved out of a KELF plaintext."""
    off = find_exec_elf(kelf_plain)
    span = elf_span(kelf_plain, off)
    if off + span > len(kelf_plain):
        raise PatchError("ELF span %#x at %#x overruns plaintext (%d B)"
                         % (span, off, len(kelf_plain)))
    return kelf_plain[off:off + span]


def patch_game_elf(elf, relay=True):
    """Apply the guarded patches to an EXEC game ELF: the three disc-less-boot
    patches, plus the P2P relay patch unless relay=False. Returns
    (patched_bytes, report) where report is a list of (desc, status) with
    status in {"patched", "already"}. Raises PatchError if any site matches
    neither the orig nor the new word, or if the ELF is not the expected one."""
    if elf[:4] != b"\x7fELF":
        raise PatchError("input is not an ELF (no magic)")
    if _u32(elf, 24) != EXEC_ENTRY:
        raise PatchError("entry %#010x != expected %#010x; not pop'n's boot ELF"
                         % (_u32(elf, 24), EXEC_ENTRY))
    out = bytearray(elf)
    report = []
    for va, off, orig, new, desc in PATCHES + (RELAY_PATCHES if relay else []):
        # Cross-check the documented VA->offset mapping, so a wrong table is
        # caught instead of corrupting the file.
        if off != va - LOAD_VA_BASE + PHDR0_OFF:
            raise PatchError("table bug: off %#x != va %#x mapping" % (off, va))
        if off + 4 > len(out):
            raise PatchError("offset %#x past end of ELF (%d B)" % (off, len(out)))
        cur = bytes(out[off:off + 4])
        if cur == new:
            report.append((desc, "already"))
            continue
        if cur != orig:
            raise PatchError(
                "guard failed at %#x (VA %#x): found %s, expected orig %s or new %s"
                % (off, va, cur.hex(), orig.hex(), new.hex()))
        out[off:off + 4] = new
        report.append((desc, "patched"))
    return bytes(out), report


def carve_ioprp(kelf_plain):
    """Return the DNAS280.IMG IOP reboot image (version "2800") carved from a
    KELF plaintext. Guarded by the RESET romdir magic at the fixed offset."""
    if kelf_plain[IOPRP_OFF:IOPRP_OFF + 6] != b"RESET\x00":
        raise PatchError("no RESET romdir at %#x; not pop'n's KELF plaintext"
                         % IOPRP_OFF)
    if IOPRP_OFF + IOPRP_LEN > len(kelf_plain):
        raise PatchError("IOPRP span overruns plaintext (%d B)" % len(kelf_plain))
    return kelf_plain[IOPRP_OFF:IOPRP_OFF + IOPRP_LEN]


def patch_from_main(main_bin, relay=True):
    """Decrypt a disc MAIN.BIN, carve the EXEC ELF, and patch it. Returns
    (patched_bytes, report)."""
    import disc_dec
    plain = disc_dec.decrypt_disc_container(main_bin)
    elf = carve_game_elf(plain)
    return patch_game_elf(elf, relay)


def boot_sections_from_main(main_bin, relay=True):
    """Decrypt a disc MAIN.BIN once and return (ioprp, patched_elf) -- the two
    inputs the loader fill step needs, both carved from the player's own disc.
    Nothing Konami or Sony is shipped; the disc supplies everything."""
    import disc_dec
    plain = disc_dec.decrypt_disc_container(main_bin)
    ioprp = carve_ioprp(plain)
    patched, _report = patch_game_elf(carve_game_elf(plain), relay)
    return ioprp, patched


def _selftest():
    work = os.path.join(_HERE, "..", "..", "work")
    snaps = os.path.join(work, "pcsx2-hang-snapshots")
    ref_plain = os.path.join(snaps, "blja-game.elf")
    ref_patched = os.path.join(snaps, "blja-game.dnasskip.disc.elf")
    main_bin = os.path.join(work, "disc", "MAIN.BIN")
    ok = True

    if os.path.exists(ref_plain) and os.path.exists(ref_patched):
        elf = open(ref_plain, "rb").read()
        want = open(ref_patched, "rb").read()
        got, report = patch_game_elf(elf, relay=False)
        for desc, status in report:
            print("  %-9s %s" % (status, desc))
        if got == want:
            print("  OK   patch(blja-game.elf) == blja-game.dnasskip.disc.elf (%d B)"
                  % len(got))
        else:
            print("  FAIL patched output differs from reference artifact")
            ok = False
        # idempotence: patching the patched ELF changes nothing
        again, rep2 = patch_game_elf(got, relay=False)
        if again == got and all(s == "already" for _, s in rep2):
            print("  OK   re-patch is idempotent")
        else:
            print("  FAIL re-patch not idempotent")
            ok = False
        # the relay patch: exactly one word differs from the boot-only output
        rel, _ = patch_game_elf(elf)
        diff = [i for i in range(len(rel)) if rel[i] != got[i]]
        _va, roff, _o, rnew, _d = RELAY_PATCHES[0]
        if diff and min(diff) >= roff and max(diff) < roff + 4 and rel[roff:roff + 4] == rnew:
            print("  OK   relay patch changes only the role branch at %#x" % roff)
        else:
            print("  FAIL relay patch diff unexpected: %s" % [hex(i) for i in diff[:8]])
            ok = False
    else:
        print("  skip patch test (reference artifacts missing)")

    if os.path.exists(main_bin):
        got, _ = patch_from_main(open(main_bin, "rb").read(), relay=False)
        if os.path.exists(ref_patched):
            want = open(ref_patched, "rb").read()
            tag = "== reference" if got == want else "!= reference"
            print("  %s carve+patch(MAIN.BIN) %s (%d B)"
                  % ("OK  " if got == want else "FAIL", tag, len(got)))
            ok = ok and got == want
        else:
            print("  OK   carve+patch(MAIN.BIN) produced %d B" % len(got))
    else:
        print("  skip carve test (work/disc/MAIN.BIN missing)")

    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--main", help="disc MAIN.BIN (decrypt + carve + patch)")
    src.add_argument("--elf", help="already-carved EXEC game ELF to patch")
    ap.add_argument("-o", "--out", help="write the patched ELF here")
    ap.add_argument("--selftest", action="store_true",
                    help="verify against the reference artifacts")
    ap.add_argument("--no-relay", dest="relay", action="store_false",
                    help="skip the P2P relay patch (battles then need inbound TCP 5730)")
    a = ap.parse_args()

    if a.selftest:
        sys.exit(0 if _selftest() else 1)
    if not (a.main or a.elf):
        ap.error("give --main, --elf, or --selftest")

    if a.main:
        patched, report = patch_from_main(open(a.main, "rb").read(), a.relay)
    else:
        patched, report = patch_game_elf(open(a.elf, "rb").read(), a.relay)
    for desc, status in report:
        print("  %-9s %s" % (status, desc))
    if a.out:
        open(a.out, "wb").write(patched)
        print("wrote %s (%d bytes)" % (a.out, len(patched)))
    else:
        print("(%d bytes; pass -o to write)" % len(patched))


if __name__ == "__main__":
    main()
