"""Transcrypt: write a Koei DNAS2 drive-form container for a target drive.

The drive-independent plaintext of a container = the decrypted outer layer and
the decrypted K1-block (both are cross-drive constants; extract them from any
existing install with plain_parts()). Given those and a target drive's identity
(ATA IDENTIFY page + __net four):

    blk_ct   = RC6-CBC-enc(blk_plain, K1[:16], K1[16:])
    K2       = dnaskey.derive_k2(blk_plain, ata32, four)
    outer_ct = RC6-CBC-enc(outer_plain, K2[:16], K2[16:])
    file     = every RSA record copied verbatim, blk_ct at sec+0x80,
               outer_ct at sec+0x300

Verified: re-transcrypting our install's own content for our own drive
reproduces all 30 containers (.ERX + .EBN + SLPM-65197) byte-identically.

For CHANGED module bytes (translation patches): swap_module() replaces the
module inside the plaintext and rebuilds. The module must keep its exact
length (v2 lives in the RSA-signed sizes record, which we cannot re-sign);
pad it. The sig record's SHA-1 (over the decrypted outer[d10:+v1]) then no
longer matches - whether the game's .ERX/.EBN loader enforces the sig is
untested; dnasload's ELF loader does check it. Keep edits same-length and
test on the rig first, exactly as SE's ci_transcrypt does.
"""
import struct
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dnas2, dnaskey, rc6
from dnasdec import ata_material, section_module

def plain_parts(blob, ata32, four):
    """-> list of per-section dicts with the drive-independent plaintexts."""
    keys = dnas2.keys()
    r7, _ = dnas2.unrecord(blob[0:128], keys[7][1], keys[7][2])
    K1 = dnaskey.derive_k1(ata32, four)
    out = []
    sec = int.from_bytes(r7[0x20:0x24], "little") + 0x200
    while sec + 0x300 < len(blob):
        mod, tag, nxt, info = section_module(blob, sec, ata32, four, K1, keys)
        blk_plain = rc6.cbc(blob[sec + 0x80:sec + 0x100], K1[0:16], K1[16:32], True)
        outer_plain = rc6.cbc(blob[sec + 0x300:sec + 0x300 + info["extent"]],
                              info["K2"][0:16], info["K2"][16:32], True)
        out.append(dict(sec=sec, extent=info["extent"], d10=info["d10"], v1=info["v1"],
                        d9=info["d9"], v2=info["v2"], static_t=info.get("stat_t", 6),
                        blk=blk_plain, outer=outer_plain, nxt=nxt))
        if nxt + 0x300 >= len(blob):
            break
        sec = nxt
    return out

def swap_module(blob, parts, index, module):
    """Replace section `index`'s module bytes inside the drive-independent
    plaintext (exact length only - v2 is RSA-signed)."""
    p = parts[index]
    if len(module) != p["v2"]:
        raise ValueError("module must be exactly v2=%d bytes (pad or truncate)" % p["v2"])
    keys = dnas2.keys()
    # the static record that keys the inner layer
    for t in (p["static_t"], 6, 14, 10):
        stat, _ = dnas2.unrecord(blob[p["sec"]:p["sec"] + 0x80], keys[t][1], keys[t][2]) or (None, None)
        if stat is not None:
            break
    if stat is None:
        raise ValueError("no static record at %#x" % p["sec"])
    d9, d10, v1 = p["d9"], p["d10"], p["v1"]
    inner = bytearray(rc6.cbc(p["outer"][d10:d10 + v1], stat[:16], stat[16:32], True))
    inner[d9:d9 + p["v2"]] = module
    outer = bytearray(p["outer"])
    outer[d10:d10 + v1] = rc6.cbc(bytes(inner), stat[:16], stat[16:32], False)
    p["outer"] = bytes(outer)
    return p

def transcrypt(blob, parts, ata32, four):
    """Rebuild `blob`'s drive-form bytes for the target drive."""
    K1 = dnaskey.derive_k1(ata32, four)
    buf = bytearray(blob)
    for p in parts:
        sec, ext = p["sec"], p["extent"]
        blk_ct = rc6.cbc(p["blk"], K1[0:16], K1[16:32], False)
        K2 = dnaskey.derive_k2(p["blk"], ata32, four)
        outer_ct = rc6.cbc(p["outer"], K2[0:16], K2[16:32], False)
        buf[sec + 0x80:sec + 0x100] = blk_ct
        buf[sec + 0x300:sec + 0x300 + ext] = outer_ct
    return bytes(buf)
