#!/usr/bin/env python3
"""Mint a hardware-faithful HDD ID block for pop'n, without touching PlayOnline.

The shared PlayOnline minter (`playonline.hddid.mint`) is correct where it
counts: the 24 key bytes it derives from a seed - `blk[0x40:0x48]` and
`blk[0x50:0x60]` - are what module transcryption reads, and they reproduce
from the seed. It leaves three presentation fields shaped for its own minimal
needs rather than to match a genuine Sony block:

    0x30 capacity   "40  " (left-justified)   real drives store "  40"
    0x4c retail mrk  01 11 03 01               real drives store 01 03 11 01
    0x60-0x7f        zero                       real drives carry entropy here

None of these are key bytes, so a genuine drive and a minted one decrypt the
same modules. They only matter for *fidelity* - a title or emulator that reads
those fields (the reliquary `.hddid` test rig, or pop'n if it inspects the
retail marker) sees a block that looks genuine.

This wrapper mints through the untouched helper, then patches those three
fields to real-drive shape. It asserts the 24 key bytes are unchanged, so the
drive identity - and therefore any modules already transcrypted against the
same seed - is preserved.

    python3 hddid_faithful.py OUT.hddid --seed TEXT [--capacity 40] [--dex] [--fill-tail]
    python3 hddid_faithful.py OUT.hddid --from EXISTING.hddid [--fill-tail]

The `--from` form upgrades an existing minted block in place (no seed needed):
it copies every byte, keeps the key windows exactly, and only rewrites the
presentation fields.
"""
import argparse
import hashlib
import os
import struct
import sys

# Import the shared PlayOnline helper without modifying it.
_HELPER = os.environ.get(
    "PLAYONLINE_HELPER",
    r"E:/Code/PlayOnline Project/psbbn-playonline/scripts/helper",
)
if _HELPER not in sys.path:
    sys.path.insert(0, _HELPER)
from playonline import hddid  # noqa: E402

CAP = slice(0x30, 0x34)
RETAIL = slice(0x4C, 0x50)
TAIL = slice(0x60, 0x80)
KEY_A = slice(0x40, 0x48)
KEY_B = slice(0x50, 0x60)

RETAIL_MARK = bytes.fromhex("01031101")  # on-disk bytes of a genuine retail drive
DEX_MARK = bytes.fromhex("00031101")


def _key_bytes(blk):
    return bytes(blk[KEY_A]) + bytes(blk[KEY_B])


def make_faithful(base, capacity_gb=40, retail=True, seed=None, fill_tail=False):
    """Patch a minted block's presentation fields to real-drive shape.

    The 24 key bytes (0x40:0x48, 0x50:0x60) are left exactly as `base` has
    them, so the identity is unchanged.
    """
    before = _key_bytes(base)
    blk = bytearray(base)

    # 0x30: right-justified capacity, e.g. "  40" not "40  ".
    blk[CAP] = ("%4s" % capacity_gb).encode("ascii")[:4]

    # 0x4c: the retail/DEX marker as it sits on a genuine drive.
    blk[RETAIL] = RETAIL_MARK if retail else DEX_MARK

    # 0x60-0x7f: genuine drives carry entropy here; the helper leaves it zero.
    # Off by default so the block is byte-for-byte compatible with modules
    # already built against a zero tail. When on, derive it from the seed so
    # the block stays reproducible; without a seed, fall back to the block's
    # own key bytes as the derivation input.
    if fill_tail:
        material = seed.encode("utf-8") if isinstance(seed, str) else seed
        if material is None:
            material = before
        blk[TAIL] = hashlib.sha256(material + b"|hddid-tail").digest()[:0x20]

    after = _key_bytes(blk)
    if after != before:
        raise AssertionError(
            "key material changed: %s -> %s" % (before.hex(), after.hex()))
    return bytes(blk)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", help="write the faithful 512-byte block here")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--seed", help="mint from this seed (reproducible identity)")
    src.add_argument("--from", dest="src", metavar="EXISTING.hddid",
                     help="upgrade an existing minted block, keeping its key bytes")
    ap.add_argument("--capacity", type=int, default=40, help="capacity GB (default 40)")
    ap.add_argument("--model", default="SCPH-20400", help="model string")
    ap.add_argument("--dex", action="store_true", help="DEX marker instead of retail")
    ap.add_argument("--fill-tail", action="store_true",
                    help="populate 0x60-0x7f with seed-derived entropy (identity-safe "
                         "only where a title does not key off those bytes)")
    args = ap.parse_args()

    if args.src:
        base = hddid.load(args.src)
        seed = None
    else:
        base = hddid.mint(seed=args.seed, model=args.model,
                          capacity_gb=args.capacity, retail=not args.dex)
        seed = args.seed

    blk = make_faithful(base, capacity_gb=args.capacity, retail=not args.dex,
                        seed=seed, fill_tail=args.fill_tail)
    with open(args.out, "wb") as f:
        f.write(blk)
    print("wrote %s" % args.out)
    print(hddid.describe(blk))
    print("  key material preserved: %s" % _key_bytes(blk).hex())


if __name__ == "__main__":
    main()
