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
"""RC6-32/20 (the libtomcrypt flavour) with CBC helpers, for the DNAS2 containers."""
import struct

P32 = 0xB7E15163
Q32 = 0x9E3779B9
M32 = 0xFFFFFFFF
R = 20


def rotl(x, n):
    n &= 31
    return ((x << n) | (x >> (32 - n))) & M32


def rotr(x, n):
    n &= 31
    return ((x >> n) | (x << (32 - n))) & M32


def expand_key(key):
    """The round keys S[2R+4] for `key` (16 bytes here)."""
    c = max(1, (len(key) + 3) // 4)
    L = [0] * c
    kb = key + b"\x00" * (4 * c - len(key))
    for i in range(c):
        L[i] = struct.unpack_from("<I", kb, 4 * i)[0]
    t = 2 * R + 4
    S = [0] * t
    S[0] = P32
    for i in range(1, t):
        S[i] = (S[i - 1] + Q32) & M32
    A = B = i = j = 0
    for _ in range(3 * max(t, c)):
        A = S[i] = rotl((S[i] + A + B) & M32, 3)
        B = L[j] = rotl((L[j] + A + B) & M32, (A + B) & 31)
        i = (i + 1) % t
        j = (j + 1) % c
    return S


def enc_block(S, blk):
    A, B, C, D = struct.unpack("<4I", blk)
    B = (B + S[0]) & M32
    D = (D + S[1]) & M32
    for i in range(1, R + 1):
        t = rotl((B * (2 * B + 1)) & M32, 5)
        u = rotl((D * (2 * D + 1)) & M32, 5)
        A = (rotl(A ^ t, u) + S[2 * i]) & M32
        C = (rotl(C ^ u, t) + S[2 * i + 1]) & M32
        A, B, C, D = B, C, D, A
    A = (A + S[2 * R + 2]) & M32
    C = (C + S[2 * R + 3]) & M32
    return struct.pack("<4I", A, B, C, D)


def dec_block(S, blk):
    A, B, C, D = struct.unpack("<4I", blk)
    C = (C - S[2 * R + 3]) & M32
    A = (A - S[2 * R + 2]) & M32
    for i in range(R, 0, -1):
        A, B, C, D = D, A, B, C
        u = rotl((D * (2 * D + 1)) & M32, 5)
        t = rotl((B * (2 * B + 1)) & M32, 5)
        C = rotr((C - S[2 * i + 1]) & M32, t) ^ u
        A = rotr((A - S[2 * i]) & M32, u) ^ t
    B = (B - S[0]) & M32
    D = (D - S[1]) & M32
    return struct.pack("<4I", A, B, C, D)


def cbc(data, key, iv, decrypt=True):
    """RC6-CBC over the whole 16-byte blocks of `data`."""
    S = expand_key(key)
    f = dec_block if decrypt else enc_block
    prev = iv
    out = bytearray()
    for i in range(0, len(data) - len(data) % 16, 16):
        blk = data[i:i + 16]
        if decrypt:
            p = f(S, blk)
            out += bytes(x ^ y for x, y in zip(p, prev))
            prev = blk
        else:
            p = bytes(x ^ y for x, y in zip(blk, prev))
            out += f(S, p)
            prev = out[-16:]
    return bytes(out)
