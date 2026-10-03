"""Koei DNAS2 K1/K2 derivation (dnasload FUN_00207f50 / FUN_00207c20).

The engine is PlayOnline polkey's (0x001b32c8) verbatim: 168-byte working
buffer, an 8-entry DES-CBC program walked as a linked list, round keys =
DES-CBC-encrypt of a 128-byte input under (rkgen_key, rkgen_iv), handlers
{0: ata-dec then ENC, 5: ata-enc then DEC, 1-3: ENC, 4,6,7: DEC}, final
CBC-encrypt under (final_key, final_iv), result = bytes [136:168).

Only the constant blocks differ.  Each = 5 x 8 bytes at:
  K1 (drive key, decrypts the K1-block):  0x2ce050..0x2ce078
  K2 (bulk key, from the K1-block):       0x2ce028..0x2ce050
The 5th block = the program, DES-ECB-encrypted under 8f7d7c5ece1db8d0:
  K1: d20a0c98f8b8fefd -> 06 04 03 05 00 07 02 01
  K2: bbe412587f0feb8c -> 04 06 03 00 01 07 05 02

ata32 = the 24 ATA IDENTIFY bytes (HDD ID [0x40:0x48] + [0x50:0x60]) + 8 zero
bytes, exactly polkey's.  four = the 4 bytes from the decoded __net record.
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
    """The 0x2084e8 interpreter.  ata32 = the 32-byte ATA block (24 + 8 zeros);
    the case-0/5 handlers use ata32[16:24]/[8:16] and [8:16]/[0:8] -- the same
    slices polkey's engine takes from its ata32."""
    w = bytearray(w)
    i = prog[0]
    while True:
        if i < 8:
            enc = None
            if i == 0:
                w[:] = cbc_dec(w, ata32[16:24], ata32[8:16])
                enc = True                       # falls through into ENC
            elif i == 5:
                w[:] = cbc_enc(w, ata32[8:16], ata32[0:8])
                enc = False                      # falls through into DEC
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
    """FUN_00207f50's buffer, transcribed store by store."""
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
    """FUN_00207c20's buffer -- identical to polkey._w_k2."""
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
    rk = cbc_enc(w[:128], c["rkgen_key"], c["rkgen_iv"])
    out = engine(w, rk, ata32, program(c), c["final_key"], c["final_iv"])
    return bytes(out[136:168])

def derive_k2(blk128, ata32, four):
    c = K2_CONSTS
    w = _w_k2(blk128, ata32, four)
    rk = cbc_enc(blk128, c["rkgen_key"], c["rkgen_iv"])
    out = engine(w, rk, ata32, program(c), c["final_key"], c["final_iv"])
    return bytes(out[136:168])
