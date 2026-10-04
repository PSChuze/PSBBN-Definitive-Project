"""bombtext - extract (and in-place rebuild) the client-side Japanese text of Net de Bomberman (PS2, SLPS-20343).

Read-only on every input; writes only the output paths you give it.
Details and evidence: handoffs/HANDOFF-translation.md in the project root (outside the repo).

Formats (little-endian):

FILES.BIN (installed pfs1:/FILES.BIN, 128 entries; disc \\FILES.BIN;1, 10 entries)
    header 0x8000 bytes: entry[i] = {u32 sector, u32 bytes}, file offset = sector * 0x800,
    list ends at the first {0,0}. Entry = chain of chunks:
        u32 id | u32 size (payload, padded to 16) | u32 real (unpadded length) | u32 0 | payload
    next chunk = this + 0x10 + size; id 0xffffffff ends the chain.
    The game keeps loaded entries on a list and finds a chunk by id (MAIN.BIN 0x375000).

Message chunk (a chunk whose payload is text), read by MAIN.BIN 0x324a38(group=chunk id, id):
    every payload byte is bitwise NOT-ed (b ^ 0xff). After NOT: cp932 strings, each ended by
    00 00; message id = BYTE OFFSET of the string inside the payload. Padding after the last
    string is raw 00 (0xff after NOT). Escapes (MAIN.BIN 0x324b28..0x324b8c): '\\0'..'\\9' =
    runtime buffer 0x6535d0 + n*0x100, '\\R' = buffer 0x746600, '\\U' = 0x7465f0 ("ユーザー").

TSV (UTF-8, header line):  source  id  jp  en  max  note
    Escapes in jp/en as in Nobunaga's nbtext: \\\\ backslash, \\n newline, \\t tab, \\xNN other
    control bytes. So the game's own escape "\\1" shows as "\\\\1" in the TSV.
    max = bytes available IN PLACE (message: up to the next string's offset minus the 00 00
    terminator; code string: up to the next non-zero byte minus the NUL). Empty en = keep jp.

Usage:
    python bombtext.py extract   <outdir>                       # all TSVs (paths below are defaults)
    python bombtext.py roundtrip                                # rebuild every message chunk from its TSV jp, compare
    python bombtext.py msg-build <FILES.BIN> <msg tsv> <out FILES.BIN>   # in-place, refuses overflows
"""

import os
import re
import struct
import sys

ROOT = r"E:\Code\Net de Bomberman\work"
INST = os.path.join(ROOT, "install", "PP.SLPS-20343.NET.BOMB")
FILES_INST = os.path.join(INST, "FILES.BIN")
FILES_DISC = os.path.join(ROOT, "disc", "FILES.BIN")
MAIN = os.path.join(ROOT, "dec", "MAIN.BIN")
DEC_DATA0 = os.path.join(ROOT, "dec", "DATA0")
DISC = os.path.join(ROOT, "disc")

MAIN_BASE = 0x300000     # VA = file offset + 0x300000
OVL_BASE = 0xAC0000      # installed DATA0 overlays
ELF_DELTA = 0xFF000      # SLPS_203.43 / FEEGACD.ELF: VA = file offset + 0xff000


# ------------------------------------------------------------------ escapes

def esc(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif o < 0x20 or o == 0x7f:
            out.append("\\x%02x" % o)
        else:
            out.append(ch)
    return "".join(out)


def unesc(s):
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "\\":
                out.append("\\"); i += 2; continue
            if n == "n":
                out.append("\n"); i += 2; continue
            if n == "t":
                out.append("\t"); i += 2; continue
            if n == "x":
                out.append(chr(int(s[i + 2:i + 4], 16))); i += 4; continue
        out.append(c)
        i += 1
    return "".join(out)


def enc(s):
    return s.encode("cp932")


# ------------------------------------------------------------------ FILES.BIN

class FilesBin:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        hdr = self.f.read(0x8000)
        self.ents = []
        for i in range(0x1000):
            a, b = struct.unpack_from("<II", hdr, i * 8)
            if a == 0 and b == 0:
                break
            self.ents.append((a, b))

    def entry(self, i):
        a, b = self.ents[i]
        self.f.seek(a * 0x800)
        return self.f.read(b)


def chunks(d):
    o = 0
    out = []
    while o + 16 <= len(d):
        cid, sz, real, z = struct.unpack_from("<IIII", d, o)
        if cid == 0xFFFFFFFF:
            break
        out.append((o, cid, sz, real, z))
        o += 0x10 + sz
    return out


def _textish(b):
    try:
        u = b.decode("cp932")
    except UnicodeDecodeError:
        return False
    return not any(ord(c) < 0x20 and c not in "\n\t\r" for c in u)


def is_msg(p):
    t = bytes(255 - b for b in p).rstrip(b"\xff")
    if len(t) < 4 or not t.endswith(b"\x00\x00"):
        return False
    return all(_textish(x) for x in t[:-2].split(b"\x00\x00"))


def msg_split(p):
    """-> [(offset, cp932 bytes)], end offset of the last terminator."""
    inv = bytes(255 - b for b in p)
    res = []
    o = 0
    while o < len(inv) and inv[o] != 0xFF:
        e = inv.find(b"\x00\x00", o)
        res.append((o, inv[o:e]))
        o = e + 2
    return res, o


def msg_pack(strs, size):
    """strs: [(offset, bytes)] -> payload of `size` bytes (raw, NOT-ed)."""
    buf = bytearray(b"\xff" * size)          # plaintext 0xff == raw 0x00 padding
    for off, b in strs:
        buf[off:off + len(b)] = b
        buf[off + len(b):off + len(b) + 2] = b"\x00\x00"
    return bytes(255 - x for x in buf)


def collect_msgs(path):
    fb = FilesBin(path)
    out = []
    for i in range(len(fb.ents)):
        base = fb.ents[i][0] * 0x800
        d = fb.entry(i)
        for o, cid, sz, real, z in chunks(d):
            p = d[o + 16:o + 16 + sz]
            if is_msg(p):
                out.append(dict(entry=i, cid=cid, off=base + o, size=sz, real=real, payload=p))
    return out


def msg_rows(msgs, source, skip_payloads=()):
    """Unique chunks by (id, payload); every copy listed in the note."""
    groups = {}
    order = []
    for m in msgs:
        k = (m["cid"], m["payload"])
        if m["payload"] in skip_payloads:
            continue
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(m)
    rows = []
    for k in order:
        ms = groups[k]
        m = ms[0]
        strs, end = msg_split(m["payload"])
        copies = " ".join("e%d@0x%x" % (x["entry"], x["off"]) for x in ms)
        for j, (off, b) in enumerate(strs):
            nxt = strs[j + 1][0] if j + 1 < len(strs) else m["size"]
            cap = nxt - off - 2
            rows.append([source, "0x%03x:0x%04x" % (m["cid"], off), esc(b.decode("cp932")), "", str(cap),
                         "chunk 0x%x size 0x%x real 0x%x; copies %s" % (m["cid"], m["size"], m["real"], copies)])
    return rows


# ------------------------------------------------------------------ code strings

_PAT = re.compile(rb"(?:[\x81-\x9f\xe0-\xfc][\x40-\x7e\x80-\xfc]|[\x20-\x7e\n\t\r])+")


def _kana(c):
    o = ord(c)
    return 0x3040 <= o <= 0x30FF or 0xFF10 <= o <= 0xFF5A


def _good(u):
    jp = [c for c in u if ord(c) > 0x7F]
    if not jp or any(0xE000 <= ord(c) <= 0xF8FF for c in u):
        return False
    k = sum(1 for c in jp if _kana(c))
    asc = [c for c in u if ord(c) <= 0x7F]
    if len(u) <= 2 and len(jp) == 2 and not all(0x3040 <= ord(c) <= 0x30FF for c in jp):
        return None          # 2-char non-kana: decided by the caller (alignment)
    if len(jp) >= 2 and k * 2 >= len(jp):
        return True
    if len(jp) >= 4 and k >= 2:
        return True
    if not asc and len(jp) >= 2 and all(0x4E00 <= ord(c) <= 0x9FFF or _kana(c) or 0x3000 <= ord(c) <= 0x30FF for c in jp):
        return True          # short kanji labels (注意)
    if len(re.findall(r"[A-Za-z]", u)) >= 6 and k >= 1:
        return True          # '"PlayStation BB Unit"と'
    return False


JUNK = {"娯レ]"}   # passes the filter but is instruction bytes (PATCH.BIN 0xac8)


def code_strings(d, lo=0, hi=None, single_kanji_aligned=True):
    hi = len(d) if hi is None else hi
    out = []
    for m in _PAT.finditer(d, lo, hi):
        st, en = m.start(), m.end()
        if en >= len(d) or d[en] != 0:
            continue
        s = d[st:en]
        # strip a short ASCII prefix that is really the tail of preceding data (floats etc.)
        if st % 4:
            al = (st + 3) & ~3
            if al < en and all(b < 0x80 for b in d[st:al]) and d[al] >= 0x81:
                st = al
                s = d[st:en]
        try:
            u = s.decode("cp932")
        except UnicodeDecodeError:
            continue
        ok = _good(u)
        if ok is None:
            # 2-char label (注意 ...): only at a 4-aligned, NUL-preceded slot, JIS level-1 kanji/kana
            ok = st % 4 == 0 and d[st - 1] == 0 and all(0x81 <= b <= 0x98 for b in s[0::2])
        if not ok and single_kanji_aligned and len(s) == 2 and st % 8 == 0 and d[st - 1] == 0 \
                and u in ("日", "月", "火", "水", "木", "金", "土"):
            ok = True            # day names in an 8-byte table (MAIN.BIN 0x74a440)
        if not ok or u in JUNK:
            continue
        cap = en
        while cap < len(d) and d[cap] == 0:
            cap += 1
        cap = cap - st - 1
        if u.endswith("未定義です") and len(u) == 6:
            cap = 0xFF           # escape buffers \0..\9 are 0x100 each (MAIN.BIN 0x324b70)
        out.append((st, s, u, cap))
    return out


def code_rows(path, source, base, lo=0, hi=None, note=""):
    d = open(path, "rb").read()
    rows = []
    for st, s, u, cap in code_strings(d, lo, hi):
        rid = "va 0x%06x" % (st + base) if base is not None else "off 0x%x" % st
        if base is not None:
            rid += " / off 0x%x" % st
        rows.append([source, rid, esc(u), "", str(cap), note])
    return rows


# ------------------------------------------------------------------ misc UTF-8 metadata

def meta_rows():
    rows = []
    for rel, keys in (("res/info.sys", ("title", "note", "genre")),
                      ("DATA0/HDDICON1.DAT", ("title0", "title1", "uninstallmes0", "uninstallmes1", "uninstallmes2"))):
        p = os.path.join(INST, rel) if rel.startswith("res") else os.path.join(ROOT, "dec", rel)
        txt = open(p, "rb").read().decode("utf-8", "replace")
        for line in txt.splitlines():
            if " = " in line:
                k, v = line.split(" = ", 1)
                if k.strip() in keys and v.strip():
                    rows.append([rel, k.strip(), esc(v), "", "", "UTF-8, PS2 HDD browser metadata"])
    return rows


# ------------------------------------------------------------------ TSV io

HDR = ["source", "id", "jp", "en", "max", "note"]


def write_tsv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(HDR) + "\n")
        for r in rows:
            assert not any("\t" in c or "\n" in c for c in r)
            f.write("\t".join(r) + "\n")
    print("%-28s %5d rows" % (os.path.basename(path), len(rows)))


def read_tsv(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    rows = []
    for ln in lines[1:]:
        if ln:
            rows.append(dict(zip(HDR, ln.split("\t"))))
    return rows


# ------------------------------------------------------------------ commands

def cmd_extract(out):
    os.makedirs(out, exist_ok=True)
    inst = collect_msgs(FILES_INST)
    write_tsv(os.path.join(out, "msg_FILES_install.tsv"), msg_rows(inst, "install/FILES.BIN"))
    disc = collect_msgs(FILES_DISC)
    known = {m["payload"] for m in inst}
    write_tsv(os.path.join(out, "msg_FILES_disc.tsv"), msg_rows(disc, "disc/FILES.BIN", skip_payloads=known))
    write_tsv(os.path.join(out, "main_direct.tsv"),
              code_rows(MAIN, "dec/MAIN.BIN", MAIN_BASE, lo=0x350000))
    rows = []
    for fn in sorted(os.listdir(DEC_DATA0)):
        if fn.endswith(".BIN"):
            rows += code_rows(os.path.join(DEC_DATA0, fn), "dec/DATA0/" + fn, OVL_BASE)
    write_tsv(os.path.join(out, "overlays_install.tsv"), rows)
    rows = code_rows(os.path.join(DISC, "SLPS_203.43"), "disc/SLPS_203.43", ELF_DELTA, lo=0x1F0000)
    for fn in sorted(os.listdir(os.path.join(DISC, "DATA0"))):
        if fn.endswith(".BIN"):
            rows += code_rows(os.path.join(DISC, "DATA0", fn), "disc/DATA0/" + fn, None,
                              note="disc overlay, load address not established")
    write_tsv(os.path.join(out, "disc_loader.tsv"), rows)
    write_tsv(os.path.join(out, "feegacd.tsv"),
              code_rows(os.path.join(DISC, "FEEGACD.ELF"), "disc/FEEGACD.ELF", ELF_DELTA,
                        lo=0x780000, hi=0x795000, note="Sony Finance Feega client (third-party)"))
    write_tsv(os.path.join(out, "metadata_utf8.tsv"), meta_rows())


def cmd_roundtrip():
    bad = 0
    n = 0
    for path in (FILES_INST, FILES_DISC):
        for m in collect_msgs(path):
            strs, end = msg_split(m["payload"])
            if end != m["real"]:
                print("real-size mismatch", hex(m["cid"]), hex(end), hex(m["real"]))
                bad += 1
            # decode -> escape -> unescape -> encode, then repack
            strs2 = [(o, enc(unesc(esc(b.decode("cp932"))))) for o, b in strs]
            if msg_pack(strs2, m["size"]) != m["payload"]:
                print("MISMATCH", path, hex(m["cid"]))
                bad += 1
            n += 1
    print("message chunks rebuilt: %d, mismatches: %d" % (n, bad))
    return bad


def cmd_msg_build(src, tsv, dst):
    rows = read_tsv(tsv)
    fb = FilesBin(src)
    msgs = collect_msgs(src)
    by_cid = {}
    for r in rows:
        cid, off = [int(x, 16) for x in r["id"].split(":")]
        by_cid.setdefault(cid, {})[off] = r
    data = bytearray(open(src, "rb").read())
    errors = 0
    for m in msgs:
        if m["cid"] not in by_cid:
            continue
        strs, _ = msg_split(m["payload"])
        new = []
        for j, (off, b) in enumerate(strs):
            r = by_cid[m["cid"]].get(off)
            nb = b
            if r and r["en"]:
                nb = enc(unesc(r["en"]))
                nxt = strs[j + 1][0] if j + 1 < len(strs) else m["size"]
                if len(nb) > nxt - off - 2:
                    print("TOO LONG 0x%x:0x%x %d > %d" % (m["cid"], off, len(nb), nxt - off - 2))
                    errors += 1
                    nb = b
            new.append((off, nb))
        p = msg_pack(new, m["size"])
        last_off, last_b = new[-1]
        real = last_off + len(last_b) + 2
        a = m["off"]
        data[a + 8:a + 12] = struct.pack("<I", real)
        data[a + 16:a + 16 + m["size"]] = p
    if errors:
        print("%d strings over budget - nothing written" % errors)
        return 1
    with open(dst, "wb") as f:
        f.write(data)
    print("wrote", dst)
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    c = argv[1]
    if c == "extract":
        cmd_extract(argv[2] if len(argv) > 2 else os.path.dirname(os.path.abspath(__file__)))
        return 0
    if c == "roundtrip":
        return 1 if cmd_roundtrip() else 0
    if c == "msg-build":
        return cmd_msg_build(argv[2], argv[3], argv[4])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
