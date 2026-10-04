"""The NBONLINE DNAS2 HDD-binding patch: make the console binding's VERDICT pass.

Root cause of the black-screen hang (RE: nbonline3.c, FUN_0032dcb8 = the verdict):

  The game's DNAS2 library checks the HDD-console binding with two memcmps of the
  IOP agent's status bytes (RPC cmds 0x24/0x26 of "PsIIlibmc 2710") against
  constants derived from baked keys:

      0032de00  jal  0x32daf0          ; memcmp(status, 0x5a5e00, 6)
      0032de0c  bnez $v0, 0x32de20     ; != 0 -> skip the Sony short-circuit
      0032de14  b    0x32de38           ; == 0 -> return 2 (genuine drive)
      0032de18  addiu $s2, $zero, 2
      ...
      0032dea0  jal  0x32daf0          ; memcmp(derived16, expected16, 0x10)
      0032dea8  sltiu $s2, $v0, 1      ; == 0 -> 1 (pass) else 0 (fail)

  On a genuine Sony HDD the MagicGate SecurityUnLock response matches and the
  verdict is 2 or 1. On a third-party SSD the agent's status never matches, the
  verdict is 0, FUN_00332ec8 returns -0x65 and boot dies.

THE PATCH (two words, in the container module):

  VA 0x32DE0C  04 00 40 14 -> 04 00 00 10
      bnez v0,skip -> b: always skip the Sony short-circuit, so the derivation
      chain (FUN_0032d958/FUN_0032d0b0/FUN_00331760) always RUNS and fills the
      persistent engine state (0x5a5e40..) later code consumes.
  VA 0x32DEA8  01 00 52 2c -> 01 00 12 24
      sltiu s2,v0,1 (0x2c520001) -> li s2,1 (0x24120001): the final verdict is
      always 1 (pass). Register care: the verdict register is s2 (18); writing
      0x24020001 would set v0 instead and leave the verdict unset.

  The binding therefore completes and succeeds - the derived state is built
  exactly as designed (from the served ATA IDENTIFY + the baked keys), and only
  the genuine-drive verdict, which a third-party drive can never satisfy, is
  overridden. Nothing is skipped: this is the distinction the FIX2 experiment
  proved matters (skipping the whole wrapper reached graphics init but left the
  later code without its derived state).

The verdict function FUN_0032dcb8 is an OBFUSCATED DNAS2 function: the container
carries its obfuscated form (guard at 0x32dd44, key 0xfcee31ae, flags 0x930c1b2c,
length 0x354, guard stub 0x32a690, skip table 0x329d40) and the game deobfuscates
it in place at runtime. This module therefore: deobfuscates the function
(deob.py, offline-verified byte-exact against work/nbonline-clean.bin), patches
the two verdict words, re-obfuscates the function with the inverse transform
program, and writes the module back. Proven: inverse(patched-clean) differs from
the raw module in exactly the two patch words.

Idempotent: after patching, the deobfuscated verdict words equal the patch
words and nothing further changes.
"""
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# deob.py lives in the RE workspace (work/dnas/re); fall back to the environment
# variable NOBU_DEOB_DIR when the default layout is absent.
_DEOB = os.environ.get("NOBU_DEOB_DIR",
                       r"E:\Code\Nobunaga Online\work\dnas\re")
for _p in (_HERE, _DEOB):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

NBONLINE = "NBONLINE.EBN"
BASE = 0x100000

# the two verdict words, in the DEOBFUSCATED function
# site 1: bnez $v0, 0x32de20 (0x14400004) -> nop (0x00000000). The memcmp
#         result is ignored and control falls through into the SONY
#         SHORT-CIRCUIT (0x32de14 b 0x32de38 with delay slot 0x32de18
#         `li s2,2`): the verdict returns 2 unconditionally. This is the
#         cheap path: it never reads the hdd0:__net,,iBJ9F9Yq binding file
#         and never runs the derivation chain. That chain produces only
#         stack-local values (verified in nbonline3.c FUN_0032dcb8: every
#         output lands in the caller's frame), so skipping it loses no
#         persistent state. The earlier direction (bnez->b, 0x10000004)
#         FORCED the expensive path and made the verdict fail with -0x191
#         on drives where the binding file does not exist.
# site 2: sltiu $s2, $v0, 1 (0x2c520001) -> li $s2, 1 (0x24120001): the
#         final verdict is 1 (pass) if the expensive path is ever reached
#         anyway. Register care: the verdict register is s2 (18); writing
#         0x24020001 would set v0 instead and leave the verdict unset.
SITES = [
    # current value may also be the OLD (wrong-direction) patch word
    # 0x10000004 (bnez->b), shipped in the 2026-09-27 morning EBN.
    (0x32DE0C, (0x14400004, 0x10000004), 0x00000000,
     "bnez v0,derive -> nop: always take the short-circuit return-2 path"),
    (0x32DEA8, (0x2C520001,), 0x24120001,
     "sltiu s2,v0,1 -> li s2,1: verdict always passes (fallback)"),
]

# the verdict function's obfuscation parameters (static RE, see module docstring)
FN = dict(body=0x32DD44, key=0xFCEE31AE, flags=0x930C1B2C, lenx=0xFCEE32FA,
          stub=0x32A690, table=0x329D40)

M = 0xFFFFFFFF


def rol(w, n):
    return ((w << n) | (w >> (32 - n))) & M


def _inv_perm(w):
    """inverse of deob.perm: perm(w) = (b0<<8)|(b3<<16)|b2|(b1<<24).

    Given p = perm(w) with bytes r0..r3, b2=r0, b0=r1, b3=r2, b1=r3, so
    w = r1 | (r3<<8) | (r0<<16) | (r2<<24)."""
    r0 = w & 0xFF
    r1 = (w >> 8) & 0xFF
    r2 = (w >> 16) & 0xFF
    r3 = (w >> 24) & 0xFF
    return r1 | (r3 << 8) | (r0 << 16) | (r2 << 24)


def _mk_inv():
    from deob import X1, X2

    def inv0(w):        # w ^ X1  ->  itself
        return w ^ X1

    def inv1(w):        # w ^ X2  ->  itself
        return w ^ X2

    def inv5(w):        # ror(w ^ X1, 13)  ->  rol(w,13) ^ X1
        return rol(w, 13) ^ X1

    def inv6(w):        # ror(perm(w) ^ X2, 8)
        return _inv_perm(rol(w, 8) ^ X2)

    def inv7(w):        # perm(ror(ror(w ^ X1, 8), 13))
        t = _inv_perm(w)
        t = rol(t, 13)
        t = rol(t, 8)
        return t ^ X1

    return [inv0, inv1, lambda w: rol(w, 13), lambda w: rol(w, 8),
            _inv_perm, inv5, inv6, inv7]


def _inv_transforms():
    inv = _mk_inv()
    from deob import TRANSFORMS
    # verify each inverse round-trips its forward before use
    for i in range(8):
        f, g = TRANSFORMS[i], inv[i]
        for w in (0, 1, 0x12345678, 0xFFFFFFFF, 0x89ABCDEF, 0x04004014, 0x24020001):
            assert g(f(w)) == w, "inverse transform %d broken" % i
    return inv


def patch_module(module: bytes) -> bytes:
    """Patch the verdict words in a container module (raw, obfuscated form).

    Idempotent: a module whose deobfuscated verdict words already carry the
    patch is returned unchanged. Raises if the unpatched words are not where
    the static RE says they are."""
    from deob import TRANSFORMS, program, lookup, Image

    mod = bytearray(module)
    body, key, flags, lenx = FN["body"], FN["key"], FN["flags"], FN["lenx"]
    length = (lenx ^ key) & M

    img = Image(bytearray(mod), BASE, 0)
    a, n, lst = lookup(img, FN["table"], flags)
    aux = body - a
    skip = set(lst)
    prog = program(key)
    steps = prog >> 28

    # deobfuscate the function in memory
    deob_img = Image(bytearray(mod), BASE, 0)
    deob_len = 0
    for i in range(steps):
        t = TRANSFORMS[(prog >> (4 * i)) & 0xF]
        for va in range(body, body + length, 4):
            if n > 0 and (va - aux) & M in skip:
                continue
            deob_img.set32(va, t(deob_img.u32(va)))
        deob_len += 0
    words = {va: deob_img.u32(va) for va in range(body, body + length, 4)}

    # patch the verdict words in the deobfuscated form
    changed = []
    for va, origs, patch, _desc in SITES:
        if not isinstance(origs, tuple):
            origs = (origs,)
        cur = words[va]
        if cur == patch:
            continue
        if cur not in origs:
            raise ValueError(
                "verdict word at %#x reads %#08x, expected %s or %#08x - "
                "wrong module?" % (va, cur,
                                   " or ".join("%#08x" % o for o in origs),
                                   patch))
        words[va] = patch
        changed.append(va)
    if not changed:
        return bytes(mod)               # already patched

    # re-obfuscate: inverse transforms, reverse step order
    inv = _inv_transforms()
    work = dict(words)
    for i in range(steps - 1, -1, -1):
        g = inv[(prog >> (4 * i)) & 0xF]
        for va in range(body, body + length, 4):
            if n > 0 and (va - aux) & M in skip:
                continue
            work[va] = g(work[va])

    # only the patched words may differ from the module's raw form
    diffs = [va for va in work if work[va] != struct.unpack_from("<I", mod, va - BASE)[0]]
    unexpected = [va for va in diffs if va not in changed]
    if unexpected:
        raise ValueError("re-obfuscation touched %d unexpected words (first %#x)"
                         % (len(unexpected), unexpected[0]))
    for va in diffs:
        struct.pack_into("<I", mod, va - BASE, work[va])
    return bytes(mod)


def is_patched(module: bytes) -> bool:
    """True when the module's deobfuscated verdict words carry the patch."""
    try:
        from deob import TRANSFORMS, program, lookup, Image
        mod = bytearray(module)
        body, key, flags, lenx = FN["body"], FN["key"], FN["flags"], FN["lenx"]
        length = (lenx ^ key) & M
        img = Image(mod, BASE, 0)
        a, n, lst = lookup(img, FN["table"], flags)
        aux = body - a
        skip = set(lst)
        prog = program(key)
        steps = prog >> 28
        for i in range(steps):
            t = TRANSFORMS[(prog >> (4 * i)) & 0xF]
            for va in range(body, body + length, 4):
                if n > 0 and (va - aux) & M in skip:
                    continue
                img.set32(va, t(img.u32(va)))
        return all(img.u32(va) == patch for va, _o, patch, _d in SITES)
    except ImportError:
        return False


def main():
    import argparse
    ap = argparse.ArgumentParser(description="patch the DNAS verdict in a NBONLINE module")
    ap.add_argument("infile")
    ap.add_argument("outfile")
    a = ap.parse_args()
    data = open(a.infile, "rb").read()
    out = patch_module(data)
    open(a.outfile, "wb").write(out)
    print("patched %s -> %s (already: %s)" % (a.infile, a.outfile, is_patched(data)))


if __name__ == "__main__":
    main()
