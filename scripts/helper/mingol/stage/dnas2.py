#
# Minna no Golf Online installer for the PSBBN Definitive Project
# Copyright (C) 2026 PrettyOpenLobby
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""DNAS2 records: the RSA keystore and recovering a record's content.

Keystore entry (100 of them, 200 bytes each): [0:8) DES key, [8:16) DES-CBC
IV, [16:200) DES-CBC ciphertext of {u32 magic, u32 DER length (BE), a DER
rsaEncryption public key}.

A record is a 128-byte RSA-1024 signature block. The public operation
(c^e mod n) recovers PKCS#1 v1.5: 00 01 ff..ff 00 | content | 16-byte ASCII
hex tag. Only public keys are involved; nothing here can sign.
"""
from Crypto.Cipher import DES
from Crypto.PublicKey import RSA

from . import dnasconsts

NTYPES = 100
_KEYS = None


def raw_entry(t):
    return dnasconsts.KEYSTORE[200 * t:200 * t + 200]


def desc(t):
    """(magic, DER bytes) for keystore entry `t`, or None if it holds no key."""
    e = raw_entry(t)
    p = DES.new(e[0:8], DES.MODE_CBC, e[8:16]).decrypt(e[16:200])
    magic = int.from_bytes(p[0:4], "big")
    ln = int.from_bytes(p[4:8], "big")
    if ln < 0xb1 and p[8] == 0x30 and p[9] in (0x81, 0x82):
        return magic, p[8:8 + ln]
    return None


def keys():
    """{type: (magic, n, e, der)} for every entry that holds a key (cached)."""
    global _KEYS
    if _KEYS is None:
        out = {}
        for t in range(NTYPES):
            try:
                r = desc(t)
                if r:
                    k = RSA.import_key(r[1])
                    out[t] = (r[0], k.n, k.e, r[1])
            except Exception:                    # a slot without a usable key
                pass
        _KEYS = out
    return _KEYS


def unrecord(blk, n, e):
    """RSA public-op a 128-byte block: (content, tag) or None."""
    m = pow(int.from_bytes(blk, "big"), e, n)
    b = m.to_bytes(128, "big")
    if b[0] != 0 or b[1] != 1:
        return None
    i = 2
    while i < len(b) and b[i] == 0xff:
        i += 1
    if i >= len(b) or b[i] != 0:
        return None
    body = b[i + 1:]
    return body[:-16], body[-16:]


def is_container(blob):
    """True when `blob` starts with a DNAS2 container descriptor record."""
    if len(blob) < 128:
        return False
    k = keys()[7]
    r = unrecord(blob[0:128], k[1], k[2])
    return bool(r and r[1] == b"96011a8e95fd1ffc")
