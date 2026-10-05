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
"""The DNAS2 drive key (K1) and bulk key (K2) for a container section.

The engine is the same as PlayOnline's (playonline.lib.polkey): a 168-byte
working buffer, an 8-entry DES-CBC program walked as a linked list, round keys
made by DES-CBC-encrypting a 128-byte input, and a final CBC encryption whose
bytes [136:168) are the key. Only the constant blocks differ between K1 and
K2. The program byte list is stored DES-ECB-encrypted under PROG_KEY.

ata32 is the 24 ATA IDENTIFY bytes the drive identity yields plus 8 zero
bytes (see dnasdec.ata_material); `four` is the 4 bytes from the decoded
__net record (00001301 for this game).
"""
from Crypto.Cipher import DES

K1_CONSTS = dict(
    final_key=bytes.fromhex("129a35361203a75e"),
    final_iv=bytes.fromhex("d08150be79666317"),
    rkgen_key=bytes.fromhex("a2d07180423db64f"),
    rkgen_iv=bytes.fromhex("13e954690507aa95"),
    prog_ct=bytes.fromhex("d20a0c98f8b8fefd"),
)
K2_CONSTS = dict(
    final_key=bytes.fromhex("abc05183c491aac0"),
    final_iv=bytes.fromhex("7170ad139b2b6509"),
    rkgen_key=bytes.fromhex("758ad4088ba4fccd"),
    rkgen_iv=bytes.fromhex("185a69b9f03c6021"),
    prog_ct=bytes.fromhex("bbe412587f0feb8c"),
)
PROG_KEY = bytes.fromhex("8f7d7c5ece1db8d0")


def program(consts):
    return DES.new(PROG_KEY, DES.MODE_ECB).decrypt(consts["prog_ct"])


def cbc_enc(src, key, iv):
    return DES.new(key, DES.MODE_CBC, iv).encrypt(src)


def cbc_dec(src, key, iv):
    return DES.new(key, DES.MODE_CBC, iv).decrypt(src)


def engine(w, rk, ata32, prog, final_key, final_iv):
    """Run the program over `w`. Steps 0 and 5 first mix in the ATA block."""
    w = bytearray(w)
    i = prog[0]
    while True:
        if i < 8:
            enc = None
            if i == 0:
                w[:] = cbc_dec(w, ata32[16:24], ata32[8:16])
                enc = True                       # then falls through into ENC
            elif i == 5:
                w[:] = cbc_enc(w, ata32[8:16], ata32[0:8])
                enc = False                      # then falls through into DEC
            k = rk[i * 16 + 8:i * 16 + 16]
            iv = rk[i * 16:i * 16 + 8]
            if enc is True or i in (1, 2, 3):
                w[:] = cbc_enc(w, k, iv)
            elif enc is False or i in (4, 6, 7):
                w[:] = cbc_dec(w, k, iv)
        if i == 0:
            break
        i = prog[i]
    return cbc_enc(w, final_key, final_iv)


def _w_k1(ata32, four):
    """The K1 working buffer, store by store."""
    w = bytearray(168)
    w[0:2] = four[0:2]
    w[2:6] = ata32[0:4]
    w[6:8] = four[2:4]
    w[8:12] = ata32[4:8]
    w[12] = four[3]
    w[13:17] = ata32[8:12]
    w[17] = four[2]
    w[18:22] = ata32[12:16]
    w[22] = four[1]
    w[23:27] = ata32[16:20]
    w[27] = four[0]
    w[28:32] = ata32[20:24]
    w[32:36] = four
    w[36:40] = ata32[24:28]
    w[40:42] = four[2:4]
    w[42:46] = ata32[28:32]
    w[46:78] = ata32[0:32]
    w[78:82] = four
    w[82:122] = w[40:80]
    w[122:162] = w[0:40]
    w[162:168] = ata32[8:14]
    return w


def _w_k2(blk, ata32, four):
    """The K2 working buffer (the same layout as polkey's)."""
    w = bytearray(176)
    w[0:32] = blk[0:32]
    w[32:36] = four
    w[36:68] = blk[32:64]
    w[68:100] = ata32
    w[100:132] = blk[64:96]
    w[132:136] = four
    w[136:168] = blk[96:128]
    return w


def derive_k1(ata32, four):
    c = K1_CONSTS
    w = _w_k1(ata32, four)
    rk = cbc_enc(bytes(w[:128]), c["rkgen_key"], c["rkgen_iv"])
    out = engine(w, rk, ata32, program(c), c["final_key"], c["final_iv"])
    return bytes(out[136:168])


def derive_k2(blk128, ata32, four):
    c = K2_CONSTS
    w = _w_k2(blk128, ata32, four)
    rk = cbc_enc(blk128, c["rkgen_key"], c["rkgen_iv"])
    out = engine(w, rk, ata32, program(c), c["final_key"], c["final_iv"])
    return bytes(out[136:168])
