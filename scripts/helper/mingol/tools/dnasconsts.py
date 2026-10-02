"""Baked DNAS2 crypto constants, extracted from dnasload once (dnas-consts.bin).

The container crypto needs a handful of fixed tables from Sony/Koei's dnasload:
the 100-entry RSA keystore and three DES constant windows. Rather than ship the
2 MB loader, `dnas-consts.bin` carries only those bytes (public-key material +
cipher constants, no loader code). Layout (name, offset, length):

    keystore     0      20000   (100 entries x 200 B, the RSA type table)
    STAT_2ACDD8  20000     32
    STAT_2ACDF8  20032      8
    STAT_2ACE20  20040     32

Regenerate with tools/extract-dnas-consts (from dnasload.unpacked.bin) if ever
needed; the sha1 of the shipped blob is recorded in the Nobunaga handoff.
"""
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dnas-consts.bin")
_BLOB = open(_PATH, "rb").read()

KEYSTORE = _BLOB[0:20000]
STAT_2ACDD8 = _BLOB[20000:20032]
STAT_2ACDF8 = _BLOB[20032:20040]
STAT_2ACE20 = _BLOB[20040:20072]

assert len(KEYSTORE) == 20000 and len(STAT_2ACE20) == 32, "dnas-consts.bin truncated"
