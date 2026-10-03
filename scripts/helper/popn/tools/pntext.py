#!/usr/bin/env python3
"""pntext.py - English translation extract/rebuild for pop'n Taisen Puzzle-dama Online.

The client UI/system/error text lives as NUL-terminated cp932 strings in the game
EXEC ELF (carved from MAIN.BIN, loads at VA 0x100000). Each string sits in a
fixed slot (string + trailing NUL padding); English must fit the slot.

  python pntext.py elf-x  <game.elf> <out.tsv>              # extract text -> TSV
  python pntext.py elf-b  <game.elf> <in.tsv> <out.elf>     # rebuild ELF with en
  python pntext.py lint   <tsv>                             # cp932 + byte-budget check
  python pntext.py roundtrip <game.elf>                     # extract->build == identical

TSV columns: id  max  jp  en  note   (max = hard cp932 byte cap = slot - 1).
Empty `en` keeps the Japanese. Escapes: \\n \\t \\\\ \\xNN .
Set PYTHONUTF8=1 when printing.
"""
import os, re, sys, struct

# ---------------------------------------------------------------- escapes / cp932

def esc(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\": out.append("\\\\")
        elif ch == "\n": out.append("\\n")
        elif ch == "\t": out.append("\\t")
        elif o < 0x20 or o == 0x7f: out.append("\\x%02x" % o)
        else: out.append(ch)
    return "".join(out)

def unesc(s):
    out = []; i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "\\": out.append("\\"); i += 2; continue
            if n == "n": out.append("\n"); i += 2; continue
            if n == "t": out.append("\t"); i += 2; continue
            if n == "x" and re.match(r"[0-9a-fA-F]{2}", s[i + 2:i + 4]):
                out.append(chr(int(s[i + 2:i + 4], 16))); i += 4; continue
        out.append(ch); i += 1
    return "".join(out)

def dec(b):
    s = b.decode("cp932")
    if s.encode("cp932") != b:
        raise ValueError("cp932 round-trip fails")
    return s

def enc(s):
    return s.encode("cp932")

HEADER = ["id", "max", "jp", "en", "note"]

def write_tsv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(HEADER) + "\n")
        for r in rows:
            f.write("\t".join([r["id"], str(r["max"]), esc(r["jp"]),
                               esc(r.get("en", "")), r.get("note", "")]) + "\n")

def read_tsv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("\t")
        if head[:4] != HEADER[:4]:
            raise SystemExit("%s: bad header %r" % (path, head))
        for ln, line in enumerate(f, 2):
            line = line.rstrip("\n").rstrip("\r")
            if not line: continue
            p = line.split("\t")
            while len(p) < 5: p.append("")
            rows.append({"id": p[0], "max": int(p[1]) if p[1] else 0,
                         "jp": unesc(p[2]), "en": unesc(p[3]), "note": p[4], "line": ln})
    return rows

# ---------------------------------------------------------------- ELF segment

def load_seg(elf):
    """Return (data, file_offset, vaddr, size) of the first PT_LOAD with filesz>0."""
    assert elf[:4] == b"\x7fELF"
    e_phoff = struct.unpack_from("<I", elf, 0x1c)[0]
    e_phentsize = struct.unpack_from("<H", elf, 0x2a)[0]
    e_phnum = struct.unpack_from("<H", elf, 0x2c)[0]
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz = struct.unpack_from("<6I", elf, off)
        if p_type == 1 and p_filesz > 0:
            return p_offset, p_vaddr, p_filesz
    raise SystemExit("no PT_LOAD segment")

# text classifier: real JP UI text only (no code false positives)

def is_text(t):
    """Real pop'n UI text, not code bytes that happen to decode as cp932.

    Discriminators learned from the data: genuine text uses HALF-width ASCII for
    latin/digits ("DNAS", "ID", "TCP", "5730") and FULL-width kana; code noise is
    the opposite - half-width katakana and full-width latin letters. Button glyphs
    (maru/batsu/...) and JP punctuation are allowed. A string qualifies on a
    hiragana, or on a pure full-width katakana word.
    """
    if not t:
        return False
    if any(ord(c) < 0x20 for c in t):
        return False  # control bytes -> code, not a single-line UI string
    if any(0x80 <= ord(c) <= 0x9f or 0xe000 <= ord(c) <= 0xf8ff for c in t):
        return False  # C1 controls / private-use (cp932 gaiji) -> code noise
    hira = sum(1 for c in t if 0x3040 <= ord(c) <= 0x309f)
    kata = sum(1 for c in t if 0x30a0 <= ord(c) <= 0x30ff)
    kanji = sum(1 for c in t if 0x4e00 <= ord(c) <= 0x9fff)
    # code-noise markers: genuine text uses half-width ASCII + full-width kana,
    # code noise is the opposite (half-width kana, full-width latin/digits).
    hkata = sum(1 for c in t if 0xff61 <= ord(c) <= 0xff9f)
    fwlatin = sum(1 for c in t if 0xff10 <= ord(c) <= 0xff5a)
    if hkata or fwlatin:
        return False
    jp = sum(1 for c in t if ord(c) >= 0x80)   # kana + kanji + JP punct + glyphs
    if jp < 2:
        return False  # a lone JP char amid ASCII is code, not text
    if hira >= 1:
        return True
    if kata >= 2 and kanji == 0:
        return True
    return False

def walk_strings(elf):
    """Yield (vaddr, raw_bytes, slot) for every NUL-terminated string in the seg."""
    foff, va, sz = load_seg(elf)
    i, end = foff, foff + sz
    while i < end:
        if elf[i] == 0:
            i += 1; continue
        j = i
        while j < end and elf[j] != 0:
            j += 1
        raw = elf[i:j]
        k = j
        while k < end and elf[k] == 0:
            k += 1
        yield (i - foff + va, raw, k - i)   # vaddr, bytes, slot (incl trailing NULs)
        i = j

def elf_extract(elf):
    rows = []
    for vaddr, raw, slot in walk_strings(elf):
        try:
            t = dec(raw)
        except (UnicodeDecodeError, ValueError):
            continue
        if not is_text(t):
            continue
        if slot <= len(raw):
            continue  # no NUL terminator room; skip (segment edge)
        rows.append({"id": "elf:%08x" % vaddr, "max": slot - 1, "jp": t,
                     "note": "len %d slot %d" % (len(raw), slot)})
    return rows

def cmd_elf_x(elf_path, out):
    elf = open(elf_path, "rb").read()
    rows = elf_extract(elf)
    write_tsv(out, rows)
    print("%s: %d strings" % (out, len(rows)))

def _read_cstr(elf, off, limit):
    j = off
    while j < limit and elf[j] != 0:
        j += 1
    return elf[off:j], j            # bytes (no NUL), index of the NUL


def patch_prefectures(elf, pref_rows):
    """Repack the 47-prefecture name table into romaji and repoint its pointer
    array. The names are pure kanji (e.g. 北海道), which is_text() rejects, so the
    extractor never sees them; they arrive as TSV rows with a `pref:` id, in
    table order. The names live in a packed rodata blob reached through a 47-entry
    char* array. Romaji needs more room than some original 8-byte slots give, so
    we repack the whole blob (it still fits the original region) and rewrite every
    pointer. Self-locating: the array is found by matching the 47 targets against
    the JP (or already-applied EN) names, so no file offset is hard-coded.
    Returns the count of names given an English form (0 = nothing to do)."""
    en_list = [r["en"] for r in pref_rows]
    jp_list = [r["jp"] for r in pref_rows]
    if not any(en_list):
        return 0
    n = len(pref_rows)
    foff, va, sz = load_seg(elf)
    end = foff + sz

    def va2off(aa):
        return foff + (aa - va) if va <= aa < va + sz else None

    def target(aa):
        o = va2off(aa)
        if o is None:
            return None
        raw, _ = _read_cstr(elf, o, end)
        try:
            return raw.decode("cp932")
        except UnicodeDecodeError:
            return None

    want = [(jp_list[k], en_list[k] or jp_list[k]) for k in range(n)]
    arr = None
    for off in range(foff, end - n * 4, 4):
        if target(struct.unpack_from("<I", elf, off)[0]) not in want[0]:
            continue
        if all(target(struct.unpack_from("<I", elf, off + 4 * k)[0]) in want[k]
               for k in range(n)):
            arr = off
            break
    if arr is None:
        raise SystemExit("prefecture pointer array not found")

    ptrs = [struct.unpack_from("<I", elf, arr + 4 * k)[0] for k in range(n)]
    base = va2off(min(ptrs))
    pos = base                               # walk the blob to find its extent
    for _ in range(n):
        _, nul = _read_cstr(elf, pos, end)
        pos = nul
        while pos < end and elf[pos] == 0:
            pos += 1
    region_end = pos
    avail = region_end - base

    packed = bytearray(); new_ptrs = []; cur_va = va + (base - foff)
    for k in range(n):
        use_en = bool(en_list[k])
        s = en_list[k] if use_en else jp_list[k]
        try:
            b = s.encode("ascii") if use_en else s.encode("cp932")
        except UnicodeEncodeError as e:
            raise SystemExit("prefecture %r: %s" % (s, e))
        new_ptrs.append(cur_va)
        packed += b + b"\x00"
        cur_va += len(b) + 1
    if len(packed) > avail:
        raise SystemExit("prefecture repack %d B > region %d B" % (len(packed), avail))

    elf[base:base + len(packed)] = packed
    for i in range(base + len(packed), region_end):
        elf[i] = 0
    for k in range(n):
        struct.pack_into("<I", elf, arr + 4 * k, new_ptrs[k])
    return sum(1 for e in en_list if e)


def cmd_elf_b(elf_path, tsv, out):
    elf = bytearray(open(elf_path, "rb").read())
    foff, va, sz = load_seg(elf)
    rows = read_tsv(tsv)
    pref_rows = [r for r in rows if r["id"].startswith("pref:")]
    rows = [r for r in rows if not r["id"].startswith("pref:")]
    # index extracted slots by vaddr for budget lookup
    slots = {}
    for vaddr, raw, slot in walk_strings(bytes(elf)):
        slots[vaddr] = (foff + (vaddr - va), len(raw), slot)
    n = 0; errs = 0
    for r in rows:
        if not r["en"]:
            continue
        vaddr = int(r["id"].split(":")[1], 16)
        if vaddr not in slots:
            print("ERROR %s: vaddr not found" % r["id"]); errs += 1; continue
        pos, origlen, slot = slots[vaddr]
        try:
            b = enc(r["en"])
        except UnicodeEncodeError as e:
            print("ERROR %s: not cp932: %s" % (r["id"], e)); errs += 1; continue
        if len(b) > slot - 1:
            print("ERROR %s: %d bytes > max %d" % (r["id"], len(b), slot - 1)); errs += 1; continue
        elf[pos:pos + slot] = b + b"\x00" * (slot - len(b))
        n += 1
    if errs:
        raise SystemExit("%d errors; not written" % errs)
    npref = patch_prefectures(elf, pref_rows) if pref_rows else 0
    open(out, "wb").write(bytes(elf))
    print("%s: %d strings replaced%s" % (
        out, n, (", %d prefectures" % npref) if npref else ""))

_FMT = re.compile(r"%[-0-9.]*[sdDuxXc]")

def cmd_lint(tsv):
    rows = read_tsv(tsv); probs = 0; done = 0
    for r in rows:
        if not r["en"]:
            continue
        done += 1
        try:
            b = enc(r["en"])
        except UnicodeEncodeError as e:
            print("%d %s: not cp932: %s" % (r["line"], r["id"], e)); probs += 1; continue
        if len(b) > r["max"]:
            print("%d %s: %d > max %d: %r" % (r["line"], r["id"], len(b), r["max"], r["en"])); probs += 1
        if sorted(_FMT.findall(r["jp"])) != sorted(_FMT.findall(r["en"])):
            print("%d %s: format specifiers differ jp=%s en=%s" % (
                r["line"], r["id"], _FMT.findall(r["jp"]), _FMT.findall(r["en"]))); probs += 1
        if "—" in r["en"] or "–" in r["en"]:
            print("%d %s: em/en dash" % (r["line"], r["id"])); probs += 1
    print("%s: %d rows, %d translated, %d problems" % (tsv, len(rows), done, probs))
    return probs

def cmd_roundtrip(elf_path):
    import tempfile
    elf = open(elf_path, "rb").read()
    rows = elf_extract(elf)
    tmp = tempfile.mktemp(suffix=".tsv")
    write_tsv(tmp, rows)
    # force en = jp, rebuild, compare
    for r in read_tsv(tmp):
        pass
    rows2 = read_tsv(tmp)
    for r in rows2:
        r["en"] = r["jp"]
    write_tsv(tmp, rows2)
    out = tempfile.mktemp(suffix=".elf")
    cmd_elf_b(elf_path, tmp, out)
    rebuilt = open(out, "rb").read()
    print("IDENTICAL" if rebuilt == elf else "DIFFERS (%d bytes)" % sum(
        1 for a, b in zip(rebuilt, elf) if a != b))

def main(a):
    c = a[0]
    if c == "elf-x": cmd_elf_x(a[1], a[2])
    elif c == "elf-b": cmd_elf_b(a[1], a[2], a[3])
    elif c == "lint": sys.exit(1 if cmd_lint(a[1]) else 0)
    elif c == "roundtrip": cmd_roundtrip(a[1])
    else: raise SystemExit(__doc__)

if __name__ == "__main__":
    main(sys.argv[1:])
