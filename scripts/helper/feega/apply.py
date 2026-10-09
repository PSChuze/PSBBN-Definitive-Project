"""Write en.tsv into PSBBN's edclient (Feega) screen XMLs.

    python apply.py [SRC_DIR] [OUT_DIR]        (defaults: orig-drive -> out)

Every edclient/*.xml carries its own copy of the same <TEXT id=... value=...> table; each row
gets the English from en.tsv. Only the value attribute changes, everything else is byte-identical.
Refuses to write if an id has no English, if the printf codes differ from the Japanese original,
or if the English contains the row's own quote character. \\n in en.tsv is written as-is (the XMLs
use a literal backslash-n for line breaks).
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "orig-drive")
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "out")
ROW = re.compile(r'(<TEXT\s+id="([^"]+)"\s+value=)(["\'])(.*?)\3', re.S)
FMT = re.compile(r'%[-0-9.]*[sdx]')
JP = re.compile(r'[぀-ヿ一-鿿]')
PAD_HELP = {"新規登録": "Register", "詳細表示": "Details", "詳細": "Details"}

en = {}
with open(os.path.join(HERE, "en.tsv"), encoding="utf-8") as f:
    next(f)
    for line in f:
        line = line.rstrip("\n")
        if line:
            i, v = line.split("\t", 1)
            en[i] = v

errors = []
os.makedirs(out, exist_ok=True)
total = 0
for path in sorted(glob.glob(os.path.join(src, "*.xml"))):
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")

    def sub(m):
        global total
        head, i, q, old = m.group(1), m.group(2), m.group(3), m.group(4)
        if i not in en:
            errors.append("%s: no English for %s" % (os.path.basename(path), i))
            return m.group(0)
        new = en[i]
        if JP.search(old) and FMT.findall(old) != FMT.findall(new):
            errors.append("%s: format codes differ: %r vs %r" % (i, FMT.findall(old), FMT.findall(new)))
        if q in new:
            errors.append("%s: English contains the row quote %s" % (i, q))
        total += 1
        return "%s%s%s%s" % (head, q, new, q)

    new_text = ROW.sub(sub, text)
    # Button hints on <pad_help .../> are inline attributes, not TEXT rows.
    for ja, e in PAD_HELP.items():
        new_text = re.sub(r'(<pad_help\b[^>]*=")%s(")' % re.escape(ja), r"\g<1>%s\g<2>" % e, new_text)
    open(os.path.join(out, os.path.basename(path)), "wb").write(new_text.encode("utf-8"))

left = []
for path in sorted(glob.glob(os.path.join(out, "*.xml"))):
    body = re.sub(r"<!--.*?-->", "", open(path, encoding="utf-8").read(), flags=re.S)
    for n, line in enumerate(body.splitlines(), 1):
        if JP.search(line.replace("・", "")):
            left.append("%s:%d" % (os.path.basename(path), n))
if errors:
    for e in sorted(set(errors)):
        print("ERROR", e)
    for p in glob.glob(os.path.join(out, "*.xml")):
        os.remove(p)
    sys.exit(1)
print("wrote %d rows into %s; Japanese left: %d %s" % (total, out, len(set(left)), sorted(set(left))[:5]))
