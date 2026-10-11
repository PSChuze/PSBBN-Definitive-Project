#!/usr/bin/env python3
"""hwaudit.py - read-only PS2 drive manifest for the four HDD titles.

PLAN-hw-boot-all-titles.md section 4.3: run before every console boot and
attach the manifest sha to the boot ledger. It reads a block device or a raw
image and reports what the console will meet at each gate of section 2:

  1  APA table walk (names, LBAs, types, rpwd/fpwd vs the known per-title
     passwords, header checksums) and MBR sector 7 (APA_SECTOR_PART_ERROR)
  2  each game partition's attribute area (+0x1000) boot block, verbatim
  3  the partition's PFS root and the BOOT2 loader: sha1, KELF or ELF, KELF
     signature (with PS2KEYS), served HDD ID, IOPRP version, trace LBA, i.Link
     spoof ids, scefix, inferred DRIVERS mode, verbose markers
  4  every sealed drive-form container: drive tail tag + decrypt + signed
     SHA-1 under each candidate HDD ID / four -> 'sealed-to: <id>'
  5  __net: +0x201800 record (decoded per candidate HDD ID: four + console),
     +0x202000 access_flag25 (sha256 vs the shipped psbb record f8268f4e),
     /etc/access_flag*, LBA 0x41000-0x4101f sha
  6  __sysconf/etc/bnnetwork/netcnf000.dat decoded per console i.Link;
     Bomberman's __sysconf/etc/feega/feega.dat
  7  Minna: DNAS.BIN sha (05d0c353 stock / 2e67f5d5 PATCH 1), FMOD/FMOD2
     staged counts, plain vs sealed overlays
  8  verdicts: the section-2 gates applied mechanically where data allows

STRICTLY READ-ONLY. The target is opened 'rb' through a wrapper that has no
write method; nothing in this file opens the target any other way. The only
file ever written is the --json manifest, which must not be the target.

Under WSL, flush the page cache first or the reads can be stale
(memory: wsl-block-device-stale-cache):

    sudo blockdev --flushbufs /dev/sdX
    sudo python3 hwaudit.py /dev/sdX --json /tmp/manifest.json

    python3 hwaudit.py D:/PS2HDDs/popn/popn-test.img --hddid D:/PS2HDDs/popn/popn-test.hddid
    python3 hwaudit.py IMAGE --only PP.BLJA-00010 --json -
    python3 hwaudit.py --loader some-loader.kelf          # audit a loader file alone

Imports (read-only, by sys.path): the sibling DNAS modules in this directory
(dnasdec, dnaskey, dnas2, rc6, netcnf) and the toolkit helper tree
(playonline.lib.polpfsread/polfill/polkelf/polrecord/polhdd, playonline.loader)
at --helper / $HWAUDIT_HELPER / the usual E: and /mnt/e locations.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SECTOR = 512
APA_MAGIC = 0x00415041
HELPER_CANDIDATES = [
    os.environ.get("HWAUDIT_HELPER"),
    r"E:\Code\PlayOnline Project\psbbn-playonline\scripts\helper",
    "/mnt/e/Code/PlayOnline Project/psbbn-playonline/scripts/helper",
    r"D:\Code\PlayOnline Project\psbbn-playonline\scripts\helper",
    "/mnt/d/Code/PlayOnline Project/psbbn-playonline/scripts/helper",
]
KEYS_CANDIDATES = [os.environ.get("PS2KEYS"), os.path.expanduser("~/PS2KEYS.dat"),
                   r"E:\ps2hdd\PS2KEYS.dat", "/mnt/e/ps2hdd/PS2KEYS.dat"]
PSBB_HDDID_FILES = [r"E:\ps2hdd\HDD_ID.bin", "/mnt/e/ps2hdd/HDD_ID.bin"]

# ---------------------------------------------------------------------------
# Known values (PLAN-hw-boot-all-titles.md sections 1/2, project memory)
# ---------------------------------------------------------------------------
DRIVE_TAIL_TAG = b"cfe9b0068e5c24d4"
FOUR_DEFAULT = bytes.fromhex("00001301")
ILINK_PSBB = bytes.fromhex("0700001ad5910c10")       # the records' console (spoof)
ILINK_OPERATOR = bytes.fromhex("070d001a75fc7910")   # the operator's console
ILINKS = {"psbb 0700001ad5910c10": ILINK_PSBB,
          "operator 070d001a75fc7910": ILINK_OPERATOR,
          "zero (PCSX2 default)": bytes(8)}
AF25_PSBB_SHA256 = "f8268f4e"                        # access_flag25.psbb.bin
TRACE_KNOWN = {19264032: "pop'n baked", 103785728: "Nobunaga baked (old NOBUON)",
               58386336: "Minna baked"}
DNASBIN_KNOWN = {"05d0c353": "stock (no PATCH 1)", "2e67f5d5": "DNAS-hwfix (PATCH 1)"}
# HDD ID key material (blk[0x40:0x48] + blk[0x50:0x60]); only these 24 bytes
# feed the container keys. Used when the block files are not reachable.
KNOWN_IDS = {
    "psbb (E:/ps2hdd/HDD_ID.bin, 7c065c76)":
        "b7465001a7040d01" "d16e77755a582a6be19c8b461f699956",
    "FAB0-B80B mint (0ae1754f)":
        "1789cce0539e6d31" "c680660ff0d309bc649cdf71a0ce98a8",
    "FBBF mint (fbbf.hddid, a1fd4147)":
        "49924f860cc231df" "7c7ffb547c82b9db678e4d3ab35b5c11",
    "zero material (placeholder/PCSX2 zero)": "00" * 24,
}
KNOWN_LOADERS = {   # sha1[:8] -> label
    "bf3c61ac": "Koei stock dnasload (work/ourinstall, Koei-signed)",
    "25f4576d": "Koei stock dnasload 1.00 (work/hdd100)",
    "48deeea7": "retail-shape 430144-B dnasload KELF (as on the nobu PCSX2 images)",
    "5e2faf7e": "Nobunaga dnasload-v311-hw.elf (#53 anchor)",
    "8fc3c062": "pop'n anchor loader 8fc3c062 (WE HAVE LOAD)",
    "a15b4245": "toolkit polbbnexec-popn.kelf filled",
    "13b89ed2": "toolkit bombload.elf 13b89ed2 (scefix 1.1, NO spoof)",
    "bd891532": "toolkit bombload.kelf bd891532 (scefix 1.1, NO spoof)",
    "7e2b81d6": "bombload.kelf 7e2b81d6 (f90a335)",
    "9132e6b7": "bombload.elf 9132e6b7 (f90a335)",
    "2d2b0a6b": "Minna DRIVERS=3 kelf 2d2b0a6b",
    "6140dafe": "toolkit polbbnexec-mingol.kelf (unfilled asset)",
    "bffb24a0": "Nobunaga polbbnexec-inputpatch.kelf (work/loader)",
}

TITLES = {
    "PP.SLPM-65197.KOEI.NOBUON": dict(
        title="nobunaga", fpwd=b"NOBUONF", rpwd=b"NOBUONR", ioprp="2710", dnas=True,
        containers=["/*.ERX", "/*.EBN", "/SLPM-65197", "/MODULES/*", "/OVERLAY/*", "/BIN/*"]),
    "PP.BLJA-00010": dict(
        title="popn", fpwd=b"POPNPUZZ", rpwd=b"POPNPUZZ", ioprp="2800", dnas=True,
        containers=["/MODULES/*.IRX", "/BLJA-00010"]),
    "PP.SLPS-20343.NET.BOMB": dict(
        title="bomb", fpwd=b"T3nheNY3", rpwd=None, ioprp="2800", dnas=True,
        containers=["/MAIN.BIN", "/MODULE.BIN", "/DATA0/*.BIN"]),
    "PP.SCPS-15049..APPLICATION": dict(
        title="mingol", fpwd=b"MM21", rpwd=b"MM21", ioprp="2700", dnas=True,
        containers=["/ZZENC/*", "/ZZENC/*/*"]),
    "PC.SLPM-65197.KOEI.NOBUONPATCHB": dict(title="nobunaga-patch", fpwd=None,
                                            rpwd=None, containers=[]),
}
NET_PASSWORDS = (b"Qfk5j1EZ", b"iBJ9F9Yq")   # (fpwd, rpwd), polhdd.PASSWORDS["__net"]


# ---------------------------------------------------------------------------
# Read-only access
# ---------------------------------------------------------------------------
class ReadOnlyTarget(object):
    """The only handle on the target. There is no write path: the file is
    opened 'rb', and this wrapper exposes read/seek/tell only, so a helper
    that tried to write (polfill.Partition.write_zones, ...) would raise."""

    def __init__(self, path):
        self.path = path
        self._f = open(path, "rb")                 # never anything but 'rb'
        assert "b" in self._f.mode and "r" in self._f.mode and "+" not in self._f.mode
        self._f.seek(0, os.SEEK_END)
        self.size = self._f.tell()                 # works for /dev/sdX too
        self._f.seek(0)

    def read(self, n=-1):
        return self._f.read(n)

    def seek(self, off, whence=0):
        return self._f.seek(off, whence)

    def tell(self):
        return self._f.tell()

    def pread(self, off, n):
        self._f.seek(off)
        return self._f.read(n)

    def close(self):
        self._f.close()

    def __getattr__(self, name):
        if name in ("write", "writelines", "truncate", "flush", "fileno"):
            raise PermissionError("hwaudit is read-only: %s() refused" % name)
        raise AttributeError(name)


def h1(b):
    return hashlib.sha1(b).hexdigest()


def h256(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------
# Imports from the toolkit and the sibling DNAS tools
# ---------------------------------------------------------------------------
class Env(object):
    pass


def load_env(helper=None, keys_path=None):
    env = Env()
    env.notes = []
    for p in [helper] + HELPER_CANDIDATES:
        if p and os.path.isdir(os.path.join(p, "playonline")):
            env.helper = p
            break
    else:
        raise SystemExit("toolkit helper tree not found; pass --helper "
                         "<psbbn-playonline>/scripts/helper or set HWAUDIT_HELPER")
    if env.helper not in sys.path:
        sys.path.insert(1, env.helper)
    from playonline.lib import polpfsread, polfill, polrecord, polkelf   # noqa
    from playonline.lib.polhdd import apa_password, checksum          # noqa
    from playonline import loader as polloader                          # noqa
    env.polpfsread, env.polfill, env.polrecord, env.polkelf = polpfsread, polfill, polrecord, polkelf
    env.apa_password, env.apa_checksum, env.polloader = apa_password, checksum, polloader
    try:
        import dnasdec, dnaskey, dnas2, rc6, netcnf                    # noqa
        env.dnasdec, env.dnaskey, env.dnas2, env.rc6, env.netcnf = dnasdec, dnaskey, dnas2, rc6, netcnf
        env.dnaskeys = dnas2.keys()
    except Exception as exc:                                             # pycryptodome etc.
        env.dnasdec = None
        env.notes.append("DNAS modules unavailable (%s): container checks skipped" % exc)
    env.ps2keys = None
    for p in [keys_path] + KEYS_CANDIDATES:
        if p and os.path.isfile(p):
            try:
                env.ps2keys = polkelf.load_keys(p)
                env.ps2keys_path = p
                break
            except BaseException as exc:
                env.notes.append("PS2KEYS %s unreadable: %s" % (p, exc))
    if env.ps2keys is None:
        env.notes.append("no PS2KEYS.dat: KELF signatures not verified; "
                         "polkelf-form bodies are read from their plaintext block")
    return env


# ---------------------------------------------------------------------------
# HDD IDs
# ---------------------------------------------------------------------------
def material_of(blk):
    return blk[0x40:0x48] + blk[0x50:0x60]


def block_from_material(mat):
    blk = bytearray(512)
    blk[0:32] = b"Sony Computer Entertainment Inc."
    blk[0x40:0x48] = mat[:8]
    blk[0x50:0x60] = mat[8:24]
    return bytes(blk)


def id_label(blk, extra):
    """Name an HDD ID block by its key material."""
    mat = material_of(blk)
    for label, m in list(extra.items()) + [(k, bytes.fromhex(v)) for k, v in KNOWN_IDS.items()]:
        if mat == (m if isinstance(m, bytes) else material_of(m)):
            return label
    return "unknown id (sha1 %s, serial %s)" % (h1(blk)[:8], blk[0x40:0x48].hex())


class IdSet(object):
    """Candidate HDD IDs: label -> 512-byte block (material is what counts)."""

    def __init__(self):
        self.blocks = {}

    def add(self, label, blk):
        if blk is None or len(blk) < 0x60:
            return
        blk = bytes(blk[:512]).ljust(512, b"\0")
        for lab, b in self.blocks.items():
            if material_of(b) == material_of(blk):
                return lab
        self.blocks[label] = blk
        return label

    def label_of(self, blk):
        for lab, b in self.blocks.items():
            if material_of(b) == material_of(blk):
                return lab
        return None


def base_ids(user_ids):
    ids = IdSet()
    for p in PSBB_HDDID_FILES:
        if os.path.isfile(p):
            ids.add("psbb (E:/ps2hdd/HDD_ID.bin, 7c065c76)", open(p, "rb").read(512))
            break
    for label, mat in KNOWN_IDS.items():
        ids.add(label, block_from_material(bytes.fromhex(mat)))
    for spec in user_ids or []:
        path, _, label = spec.partition("=")
        blk = open(path, "rb").read(512)
        ids.add("--hddid " + (label or os.path.basename(path)), blk)
    return ids


# ---------------------------------------------------------------------------
# 1. APA
# ---------------------------------------------------------------------------
def apa_walk(t, env):
    out, seen, lba = [], set(), 0
    while lba not in seen and (lba + 2) * SECTOR <= t.size:
        seen.add(lba)
        hdr = t.pread(lba * SECTOR, 1024)
        if len(hdr) < 1024 or struct.unpack_from("<I", hdr, 4)[0] != APA_MAGIC:
            out.append(dict(lba=lba, error="no APA header"))
            break
        nxt, prev = struct.unpack_from("<II", hdr, 8)
        start, length = struct.unpack_from("<II", hdr, 0x40)
        ptype, flags = struct.unpack_from("<HH", hdr, 0x48)
        main, number = struct.unpack_from("<II", hdr, 0x58)
        name = hdr[0x10:0x30].split(b"\0")[0].decode("latin-1")
        csum = struct.unpack_from("<I", hdr, 0)[0]
        e = dict(header_lba=lba, name=name, start=start, sectors=length,
                 mib=length // 2048, type="0x%04x" % ptype, flags=flags,
                 sub=bool(flags & 1) or bool(main and not name), main=main, sub_index=number,
                 next=nxt, prev=prev, rpwd=hdr[0x30:0x38].hex(), fpwd=hdr[0x38:0x40].hex(),
                 checksum_ok=csum == env.apa_checksum(hdr))
        out.append(e)
        if not nxt:
            break
        lba = nxt
    return out


def password_check(e, env):
    """Compare rpwd/fpwd with the per-title rule."""
    name = e["name"]
    rpwd, fpwd = bytes.fromhex(e["rpwd"]), bytes.fromhex(e["fpwd"])
    res = {}
    if name == "__net":
        want_f, want_r = (env.apa_password(name, NET_PASSWORDS[0]),
                          env.apa_password(name, NET_PASSWORDS[1]))
        res = dict(rule="__net PlayOnline constants", fpwd_ok=fpwd == want_f, rpwd_ok=rpwd == want_r)
    elif name in TITLES and "fpwd" in TITLES[name]:
        ti = TITLES[name]
        if ti["fpwd"] is None:
            return dict(rule="none known", fpwd_ok=None, rpwd_ok=None)
        want_f = env.apa_password(name, ti["fpwd"])
        want_r = env.apa_password(name, ti["rpwd"]) if ti["rpwd"] else bytes(8)
        res = dict(rule="fpwd %s / rpwd %s" % (ti["fpwd"].decode(),
                                               ti["rpwd"].decode() if ti["rpwd"] else "ZERO"),
                   fpwd_ok=fpwd == want_f, rpwd_ok=rpwd == want_r,
                   fpwd_want=want_f.hex(), rpwd_want=want_r.hex())
    else:
        res = dict(rule="no rule", fpwd_ok=None, rpwd_ok=None)
    res["rpwd_zero"] = not any(rpwd)
    res["fpwd_zero"] = not any(fpwd)
    return res


def sector7(t):
    s7 = t.pread(7 * SECTOR, SECTOR)
    nz = [i for i in range(0, SECTOR, 4) if any(s7[i:i + 4])]
    return dict(nonzero=bool(nz), sha1=h1(s7),
                words={("+0x%03x" % i): "0x%08x" % struct.unpack_from("<I", s7, i)[0] for i in nz[:16]})


# ---------------------------------------------------------------------------
# 2. attribute area
# ---------------------------------------------------------------------------
def attr_area(t, start):
    raw = t.pread(start * SECTOR + 0x1000, 0x200 + 0x400)
    res = dict(present=raw.startswith(b"PS2ICON3D"))
    if not res["present"]:
        res["head"] = raw[:16].hex()
        return res
    slots = [struct.unpack_from("<II", raw, 0x10 + 8 * i) for i in range(4)]
    res["slots"] = [{"off": "0x%x" % o, "size": s} for o, s in slots]
    off, size = slots[0]
    if 0 < size <= 0x400:
        boot = t.pread(start * SECTOR + 0x1000 + off, size).split(b"\0")[0]
    else:
        boot = raw[0x200:0x400].split(b"\0")[0]
    text = boot.decode("latin-1")
    res["boot_text"] = text
    keys = {}
    for line in re.split(r"\r?\n", text):
        if "=" in line:
            k, v = line.split("=", 1)
            keys[k.strip().upper()] = v.strip()
    res["keys"] = keys
    res["crlf"] = "\r\n" in text
    return res


# ---------------------------------------------------------------------------
# 3. PFS
# ---------------------------------------------------------------------------
def sub_map(apa):
    subs = {}
    for e in apa:
        if e.get("main") and not e.get("name"):
            subs.setdefault(e["main"], {})[e["sub_index"]] = e["start"]
    return subs


def mount(t, env, start, sectors, subs):
    part, root = env.polpfsread.mount(t, start, sectors, subs)
    if part is None:
        return None, None, None
    files, bad = [], []
    env.polpfsread.walk(part, root, out=files, bad=bad)
    return part, dict(files), bad


def file_lba(part, ino):
    if not ino["runs_full"]:
        return None
    n, sub, _c = ino["runs_full"][0]
    try:
        return part.zone_sector(n, sub)
    except ValueError:
        return None


def read_file(part, env, ino, limit=None):
    if limit is not None and ino["size"] > limit:
        return None
    return env.polfill.read_content(part, ino)


def read_head(part, ino, n):
    out = bytearray()
    for number, sub, count in ino["runs_full"]:
        part.f.seek(part.zone_sector(number, sub) * SECTOR)
        out += part.f.read(min(count * part.zone_size, n - len(out)))
        if len(out) >= n:
            break
    return bytes(out[:min(n, ino["size"])])


def superblock_info(t, env, start):
    try:
        sb = env.polpfsread.superblock(t, start)
    except Exception:
        sb = None
    return sb


# ---------------------------------------------------------------------------
# Loader analysis
# ---------------------------------------------------------------------------
def irx_modules(d, lo=0, hi=None):
    """[(offset, size, iopmod name, version)] for every IRX-shaped ELF."""
    out = []
    hi = len(d) if hi is None else hi
    i = d.find(b"\x7fELF", lo)
    while 0 <= i < hi:
        try:
            etype = struct.unpack_from("<H", d, i + 0x10)[0]
            phoff = struct.unpack_from("<I", d, i + 0x1c)[0]
            shoff = struct.unpack_from("<I", d, i + 0x20)[0]
            pes, phn = struct.unpack_from("<HH", d, i + 0x2a)
            shes, shn = struct.unpack_from("<HH", d, i + 0x2e)
            if etype == 0xFF80 and pes == 32 and phn <= 16:
                name, ver, end = "", None, 0
                for k in range(phn):
                    ph = i + phoff + k * pes
                    ptype, poff, _va, _pa, fsz = struct.unpack_from("<5I", d, ph)
                    end = max(end, poff + fsz)
                    if ptype == 0x70000080:
                        name = d[i + poff + 26:i + poff + 26 + 32].split(b"\0")[0].decode("latin-1")
                        ver = struct.unpack_from("<H", d, i + poff + 24)[0]
                if shes == 40 and 0 < shn < 64:
                    end = max(end, shoff + shes * shn)
                out.append(dict(off=i, size=end, name=name,
                                version=("%d.%d" % (ver >> 8, ver & 0xff)) if ver is not None else None))
        except struct.error:
            pass
        i = d.find(b"\x7fELF", i + 4)
    return out


def lui_constants(d, wanted):
    """Offsets where a lui/ori or lui/addiu pair builds one of `wanted`."""
    hits = {}
    n = len(d) // 4
    words = struct.unpack_from("<%dI" % n, d, 0)
    his = {}
    for v in wanted:
        his.setdefault(v >> 16, []).append(v)
        his.setdefault(((v + 0x8000) >> 16) & 0xffff, []).append(v)
    for i, x in enumerate(words):
        if x >> 26 != 0x0F or (x & 0xffff) not in his:
            continue
        rt, hi = (x >> 16) & 31, x & 0xffff
        for j in range(1, 8):
            if i + j >= n:
                break
            y = words[i + j]
            op = y >> 26
            if op in (0x0D, 0x09) and (y >> 21) & 31 == rt:
                lo = y & 0xffff
                v = ((hi << 16) | lo) if op == 0x0D else ((hi << 16) + ((lo ^ 0x8000) - 0x8000)) & 0xffffffff
                if v in wanted:
                    hits.setdefault(v, []).append(i * 4)
                break
    return hits


def ioprp_info(io):
    info = dict(len=len(io), sha1=h1(io)[:8] if io else None)
    if not io.startswith(b"RESET"):
        info["error"] = "does not start RESET"
        return info
    names, pos = [], 0
    while pos + 16 <= len(io):
        nm = io[pos:pos + 10].split(b"\0")[0]
        if not nm:
            break
        names.append(nm.decode("latin-1"))
        pos += 16
    info["romdir"] = names
    m = re.search(rb"conffile,([^,\0]+),", io)
    if m:
        info["conffile"] = m.group(1).decode("latin-1")
        v = re.search(r"(?i)(?:dnas|ioprp)(\d)(\d)(\d)", info["conffile"])
        if v:
            info["version"] = "".join(v.groups()) + "0"
    if "version" not in info:
        v = re.search(rb"(?i)dnas(2[0-9]{2})", io)
        if v:
            info["version"] = v.group(1).decode() + "0"
    return info


def find_sce_blocks(d, lo=0, hi=None):
    out = []
    for m in re.finditer(rb"Sony Computer Entertainment Inc\.", d[lo:hi]):
        o = lo + m.start()
        b = d[o:o + 512]
        model = b[0x20:0x30].split(b"\0")[0]
        if len(b) == 512 and (re.match(rb"^(SCPH-|SCEFIXPLACEHOLD)", model)):
            out.append((o, b))
    return out


def analyze_loader(blob, env, ids, trace_lba=None, part_range=None):
    r = dict(size=len(blob), sha1=h1(blob), known=KNOWN_LOADERS.get(h1(blob)[:8]))
    body = None
    if blob[:4] == b"\x7fELF":
        r["form"] = "plain ELF (PCSX2 Run-ELF only; HDD-OSD/PSBBN will not launch it)"
        body = blob
    elif len(blob) > 0x80:
        hdr_size = struct.unpack_from("<H", blob, 20)[0]
        r["form"] = "KELF"
        r["kelf"] = dict(header_size=hdr_size, flags="0x%x" % struct.unpack_from("<H", blob, 24)[0],
                         content_size=struct.unpack_from("<I", blob, 16)[0])
        if env.ps2keys:
            try:
                k = env.polkelf.Kelf(blob, env.ps2keys)
                r["kelf"]["header_sig_ok"] = blob[32:40] == k.header_signature()
                k.parse(verify=True)
                r["kelf"]["signatures_ok"] = True
                r["kelf"]["blocks"] = len(k.blocks)
                r["kelf"]["layout"] = ("polkelf 2-block" if len(k.blocks) == 2 else
                                       "dnasload-shape %d-block" % len(k.blocks))
                body = k.content()
            except BaseException as exc:          # polkelf raises SystemExit on mismatch
                r["kelf"].setdefault("signatures_ok", False)
                r["kelf"]["error"] = str(exc) or exc.__class__.__name__
        if body is None:
            # polkelf 2-block form: only the first 32 content bytes are
            # encrypted, the rest is one plaintext block.
            tail = blob[hdr_size + 32:]
            if b"POLBBNFORKHDR1" in tail or b"\x00\x00\x00\x00" * 64 in tail[:4096]:
                body = b"\0" * 32 + tail
                r["kelf"]["body"] = "plaintext block read without keys (first 32 bytes unknown)"
            else:
                r["kelf"]["body"] = "encrypted (retail/Sony-signed layout): slots unreadable"
    if body is None:
        return r

    # --- the POLBBNFORKHDR1 install header (polbbnexec family) -------------
    slot_lo = slot_hi = None
    try:
        info = env.polloader.read(body)
        slot_lo, slot_hi = info["elf_at"], info["ioprp_at"] + info["ioprp_capacity"]
        served = info["hddid"]
        elf = body[info["elf_at"]:info["elf_at"] + info["elf_len"]]
        io = body[info["ioprp_at"]:info["ioprp_at"] + info["ioprp_len"]]
        r["install_header"] = dict(
            offset=info["offset"], version=info["version"], argv0=info["argv0"],
            elf_len=info["elf_len"], elf_capacity=info["elf_capacity"],
            boot_elf_sha1=h1(elf)[:8] if elf else None,
            ioprp_len=info["ioprp_len"], ioprp_capacity=info["ioprp_capacity"],
            handover="[0x%08x]=0x%08x" % (info["handover_addr"], info["handover_value"])
            if info["handover_addr"] else None,
            filled=bool(info["elf_len"] and info["ioprp_len"] and info["has_hddid"]))
        r["ioprp"] = ioprp_info(io) if io else dict(len=0, error="IOPRP slot empty")
        if info["has_hddid"]:
            r["served_hddid"] = dict(sha1=h1(served)[:8], serial=served[0x40:0x48].hex(),
                                     model=served[0x20:0x30].split(b"\0")[0].decode("latin-1"),
                                     label=id_label(served, {}), source="install header")
            r["_served_block"] = served
        else:
            r["served_hddid"] = dict(label="NOT FILLED", source="install header")
        r["family"] = "polbbnexec"
    except Exception as exc:
        r["install_header"] = None
        r["install_header_error"] = str(exc)

    region = body if slot_lo is None else body[:slot_lo] + b"\0" * (slot_hi - slot_lo) + body[slot_hi:]
    mods = irx_modules(region)
    r["embedded_irx"] = ["%s %s @%d (%d B)" % (m["name"] or "?", m["version"], m["off"], m["size"])
                         for m in mods]
    strs = set(m.group().decode("latin-1") for m in re.finditer(
        rb"ps2atad|ps2dev9|koei-(?:dev9|atad|hdd|pfs)|atad-gp|atadfix|polnull|poltracechk|scefix|"
        rb"ATA device driver|driver slot|SCEFIXPLACEHOLD|POLTRACE[A-Z0-9]*", region))
    r["markers"] = sorted(strs)

    # --- bombload family: scefix carries the served block -----------------
    if slot_lo is None:
        blocks = find_sce_blocks(region)
        if blocks:
            o, b = blocks[0]
            ph = b[0x20:0x30].startswith(b"SCEFIXPLACEHOLD")
            r["served_hddid"] = dict(sha1=h1(b)[:8], serial=b[0x40:0x48].hex(),
                                     label="SCEFIX PLACEHOLDER (unfilled)" if ph else id_label(b, {}),
                                     source="embedded block @%d" % o)
            if not ph:
                r["_served_block"] = b
        if b"[bb]" in region or b"BOMBBOOT" in region:
            r["family"] = "bombload"
        io_at = region.find(b"RESET\0")
        if io_at >= 0 and r.get("family") == "bombload":
            r["ioprp"] = ioprp_info(region[io_at:io_at + 0x80000])
        sce = [m for m in mods if any(o >= m["off"] and o < m["off"] + max(m["size"], 1)
                                      for o, _b in find_sce_blocks(region))]
        if sce or "scefix" in strs:
            m = sce[0] if sce else None
            img = region[m["off"]:m["off"] + m["size"]] if m else b""
            r["scefix"] = dict(
                version=m["version"] if m else None, size=m["size"] if m else None,
                spoof_cdri=bool(img and (ILINK_PSBB in img or b"spoof" in img.lower()
                                         or b"cdri" in img.lower())),
                note="1.1 = 2026-10-01 build without spoof_cdri_install; 1.2 has it")

    # --- DRIVERS / verbose / spoof / trace ---------------------------------
    if r.get("family") == "polbbnexec" or slot_lo is not None:
        if "koei-dev9" in strs:
            r["drivers"] = "3 (Koei dev9/atad/hdd/pfs preloaded%s)" % (
                "; install-time driver slots, atad-gp" if "driver slot" in strs else "")
        elif "koei-atad" in strs:
            r["drivers"] = "5 (ps2dev9 + Koei atad/hdd/pfs)"
        elif "ps2atad" in strs:
            r["drivers"] = "4 (ps2sdk ps2dev9+ps2atad, atadpatch shim)"
        elif "atadfix" in strs:
            r["drivers"] = "2 (atadpatch shim only, game's own Sony atad)"
        else:
            r["drivers"] = "unknown"
    elif r.get("family") == "bombload":
        r["drivers"] = ("ps2sdk atad embedded" if "ATA device driver" in strs
                        else "Sony atad (no ps2sdk atad strings)")
    r["verbose"] = dict(
        bomb_bb_trace=b"[bb]" in region,
        note="polbbnexec SAY strings are linked in both builds; FORK_VERBOSE is not "
             "visible statically (say_on is an initialised int) - check the screen")
    r["spoof_ilink"] = {lab: (val in region) for lab, val in
                        (("psbb 0700001ad5910c10", ILINK_PSBB), ("operator 070d001a75fc7910", ILINK_OPERATOR))}

    wanted = set(TRACE_KNOWN)
    if trace_lba:
        wanted.add(trace_lba)
    hits = lui_constants(region, wanted)
    raw = {v: region.find(struct.pack("<I", v)) for v in wanted}
    found = sorted(set(hits) | set(v for v, o in raw.items() if o >= 0))
    tr = dict(constants_found=[dict(lba=v, what=TRACE_KNOWN.get(v, "this drive's /trace.bin"),
                                    lui_sites=len(hits.get(v, [])), raw_le=raw[v] >= 0) for v in found],
              trace_bin_lba=trace_lba)
    if found:
        lba = found[0] if not trace_lba or trace_lba not in found else trace_lba
        tr["loader_trace_lba"] = lba
        if part_range:
            tr["inside_game_partition"] = any(a <= lba < b for a, b in part_range)
        tr["armed"] = bool(trace_lba and lba == trace_lba)
    else:
        tr["loader_trace_lba"] = None
        tr["armed"] = False
        tr["note"] = "no known trace constant: trace off (TRACE_LBA 0) or an unlisted LBA"
    r["trace"] = tr
    return r


# ---------------------------------------------------------------------------
# 4. containers
# ---------------------------------------------------------------------------
def container_sections(blob, env):
    """Walk a DNAS2 drive-form container without any HDD-ID-dependent key.
    Returns [(sec, extent)] or raises ValueError('not a DNAS2 container')."""
    keys, dnas2, rc6 = env.dnaskeys, env.dnas2, env.rc6
    r7 = dnas2.unrecord(blob[0:128], keys[7][1], keys[7][2])
    if r7 is None or r7[1] != b"96011a8e95fd1ffc":
        raise ValueError("not a DNAS2 container")
    sec = int.from_bytes(r7[0][0x20:0x24], "little") + 0x200
    out = []
    while sec + 0x300 < len(blob):
        sess = dnas2.unrecord(blob[sec + 0x180:sec + 0x200], keys[11][1], keys[11][2])
        if sess is None:
            raise ValueError("no session record at %#x" % (sec + 0x180))
        h1_ = rc6.cbc(blob[sec + 0x280:sec + 0x300], sess[0][:16], sess[0][16:32], True)
        if h1_[10:26] != b"a5713c8bdbe8d420":
            raise ValueError("H1 tag miss at %#x" % sec)
        sizes = None
        for st in (h1_[4], 3):
            if st in keys:
                sizes = dnas2.unrecord(blob[sec + 0x100:sec + 0x180], keys[st][1], keys[st][2])
                if sizes:
                    break
        if sizes is None:
            raise ValueError("no sizes record at %#x" % (sec + 0x100))
        v1 = struct.unpack("<I", sizes[0][:4])[0]
        d10 = sizes[0][10] * 16
        extent = d10 + v1 + ((0x10 - (v1 & 0xF)) & 0xF) + 0x10
        out.append((sec, extent))
        nxt = sec + 0x300 + extent + 0x80
        if nxt + 0x300 >= len(blob):
            break
        sec = nxt
    return out


def path_match(path, pattern):
    """fnmatch per path segment, so '*' never crosses a '/'."""
    a, b = path.upper().split("/"), pattern.upper().split("/")
    return len(a) == len(b) and all(fnmatch.fnmatch(x, y) for x, y in zip(a, b))


def container_check(blob, env, cands, deep_limit):
    """cands: [(label, ata32, four)]. Per candidate: tail tag on every section
    (two RC6 blocks each); for the first matching candidate (or, if none
    matches, each candidate up to deep_limit) also the full decrypt and the
    signed SHA-1 of section 0."""
    try:
        secs = container_sections(blob, env)
    except ValueError as exc:
        return dict(container=False, note=str(exc))
    except Exception as exc:
        return dict(container=False, note="unparseable: %s" % exc)
    rc6, dnaskey = env.rc6, env.dnaskey
    res = dict(container=True, sections=len(secs), candidates={})
    hit = None
    for label, ata32, four in cands:
        k1 = dnaskey.derive_k1(ata32, four)
        tags = []
        for sec, extent in secs:
            blk = rc6.cbc(blob[sec + 0x80:sec + 0x100], k1[0:16], k1[16:32], True)
            k2 = dnaskey.derive_k2(blk, ata32, four)
            end = sec + 0x300 + extent
            tail = rc6.cbc(blob[end - 32:end], k2[0:16], k2[16:32], True)[16:32]
            tags.append(tail)
        ok = all(t == DRIVE_TAIL_TAG for t in tags)
        res["candidates"][label] = dict(tag_all_sections=ok)
        if ok and hit is None:
            hit = (label, ata32, four)
    deep = []
    if hit:
        deep = [hit]
    elif len(blob) <= deep_limit:
        deep = cands
    for label, ata32, four in deep:
        if len(blob) > deep_limit:
            res["candidates"][label]["sig"] = "not checked (file > --deep-limit)"
            continue
        try:
            mod, _tag, _nxt, info = env.dnasdec.section_module(blob, secs[0][0], ata32, four,
                                                               None, env.dnaskeys)
            res["candidates"][label]["sig_ok"] = bool(info["sig_ok"])
            res["candidates"][label]["module_head"] = mod[:4].hex()
        except Exception as exc:
            res["candidates"][label]["sig_ok"] = False
            res["candidates"][label]["error"] = str(exc)[:80]
    for label, c in res["candidates"].items():
        if c.get("tag_all_sections") and c.get("sig_ok", True):
            c["verdict"] = "decrypts, tag present" + ("" if "sig_ok" not in c else ", signed SHA-1 ok")
        elif c.get("tag_all_sections"):
            c["verdict"] = "decrypts, tag present, SIGNED SHA-1 MISMATCH (modified module)"
        elif c.get("sig_ok"):
            c["verdict"] = "decrypts, TAIL TAG MISSING"
        else:
            c["verdict"] = "no"
    good = [l for l, c in res["candidates"].items() if c["verdict"].startswith("decrypts")]
    res["sealed_to"] = good[0] if good else None
    res["tag_present"] = bool(good) and "TAG MISSING" not in res["candidates"][good[0]]["verdict"]
    res["sig_ok"] = res["candidates"][good[0]].get("sig_ok") if good else None
    return res


# ---------------------------------------------------------------------------
# 5/6. __net, __sysconf
# ---------------------------------------------------------------------------
def net_report(t, env, apa, ids):
    net = [e for e in apa if e.get("name") == "__net" and not e.get("sub")]
    if not net:
        return dict(present=False), {}
    lba = net[0]["start"]
    rec = t.pread(lba * SECTOR + 0x201800, 1024)
    af = t.pread(lba * SECTOR + 0x202000, 1024)
    span = t.pread(0x41000 * SECTOR, 32 * SECTOR)
    r = dict(present=True, lba=lba)
    r["record_0x201800"] = dict(head_36=rec[:36].hex(), empty=not any(rec[:36]),
                                mirror_ok=rec[20:36] == rec[:16] if any(rec[:36]) else None,
                                sha1=h1(rec[:512])[:8])
    decodes, fours = {}, {}
    if any(rec[:32]):
        for label, blk in ids.blocks.items():
            dec = bytes(env.polrecord.decode(rec[:32], env.polrecord.derive_key(blk[0x50:0x60])))
            if not any(dec[12:20]):
                ident = dec[4:12]
                console = struct.pack(">II", *struct.unpack("<II", ident))
                decodes[label] = dict(four=dec[:4].hex(), identity=ident.hex(),
                                      console_ilink=console.hex())
                fours[label] = dec[:4]
    r["record_0x201800"]["decodes_with"] = decodes
    af_sha = h256(af)
    r["access_flag25_0x202000"] = dict(
        sha256=af_sha[:16], nonzero=sum(1 for b in af if b),
        state=("matches shipped psbb record" if af_sha.startswith(AF25_PSBB_SHA256)
               else "EMPTY" if not any(af) else "DIFFERENT from shipped psbb record"))
    r["lba_0x41000_0x4101f_sha1"] = h1(span)
    return r, fours


def netcnf_report(data, env):
    out = dict(size=len(data))
    for label, il in ILINKS.items():
        pt = env.netcnf.decode(data, il)
        if pt.startswith(env.netcnf.MAGIC):
            text = pt.decode("latin-1", "replace")
            fields = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
            out["decodes_with"] = label
            out["fields"] = fields[:12]
            return out
    out["decodes_with"] = None
    # Not keyed to a console we know: name the one it IS keyed to (the
    # fixed plaintext prefix pins every i.Link byte), e.g. a config the
    # console's own network setup rewrote with its real i.Link.
    try:
        il = env.netcnf.recover(data)
        out["keyed_to"] = il.hex() if il else None
    except Exception as exc:
        out["keyed_to_error"] = str(exc)
    return out


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------
def external_loader(args, name):
    """--loader [PART=]FILE: the loader that serves PART (PCSX2 -elf boots).
    Without PART it applies to the one audited title partition."""
    for spec in args.loader_file or []:
        part, sep, f = spec.partition("=")
        if sep and part == name:
            return f
        if not sep and (args.only and name in args.only or
                        (not args.only and name in TITLES)):
            return spec
    return None


def audit(path, env, args):
    t = ReadOnlyTarget(path)
    ids = base_ids(args.hddid)
    m = dict(tool="hwaudit 1", target=path, size=t.size, time=time.strftime("%Y-%m-%d %H:%M:%S"),
             is_block_device=path.startswith("/dev/"), notes=list(env.notes))
    if m["is_block_device"]:
        m["notes"].append("block device: make sure `blockdev --flushbufs %s` ran first" % path)

    # 1. APA + sector 7
    apa = apa_walk(t, env)
    for e in apa:
        if e.get("name") and not e.get("sub"):
            e["passwords"] = password_check(e, env)
        if e.get("start", 0) + e.get("sectors", 0) > t.size // SECTOR:
            e["beyond_image_end"] = True
    m["apa"] = apa
    m["sector7"] = sector7(t)
    m["apa_header_checksums_ok"] = all(e.get("checksum_ok", False) for e in apa if "error" not in e)
    subs = sub_map(apa)

    # 5. __net first: its record names more candidate IDs/fours
    m["net"], net_fours = net_report(t, env, apa, ids)
    if m["net"].get("present"):
        try:
            netpart = [e for e in apa if e.get("name") == "__net" and not e.get("sub")][0]
            part, files, _bad = mount(t, env, netpart["start"], netpart["sectors"], subs.get(netpart["start"]))
            m["net"]["etc_files"] = sorted(p for p in (files or {}) if p.startswith("/etc/"))
        except Exception as exc:
            m["net"]["etc_error"] = str(exc)

    # 6. __sysconf
    sc = [e for e in apa if e.get("name") == "__sysconf" and not e.get("sub")]
    m["sysconf"] = dict(present=bool(sc))
    if sc:
        try:
            part, files, _bad = mount(t, env, sc[0]["start"], sc[0]["sectors"], subs.get(sc[0]["start"]))
            nc = (files or {}).get("/etc/bnnetwork/netcnf000.dat")
            m["sysconf"]["netcnf000"] = netcnf_report(read_file(part, env, nc), env) if nc else dict(present=False)
            if nc:
                m["sysconf"]["netcnf000"]["present"] = True
            # A netcnf anywhere else (a put after a failed `cd bnnetwork`
            # lands in /etc or /) is not read by the games.
            m["sysconf"]["netcnf_files"] = {p: files[p]["size"] for p in (files or {})
                                            if "netcnf" in p.lower()}
            fe = [p for p in (files or {}) if p.lower().startswith("/etc/feega/")]
            m["sysconf"]["feega"] = {p: files[p]["size"] for p in fe}
        except Exception as exc:
            m["sysconf"]["error"] = str(exc)

    # served/known IDs feed the container candidates
    m["games"] = {}
    games = [e for e in apa if e.get("name") and not e.get("sub") and e["name"][:3] in ("PP.", "PC.")]
    for e in games:
        name = e["name"]
        if args.only and name not in args.only:
            continue
        g = dict(start=e["start"], sectors=e["sectors"], passwords=e["passwords"])
        ti = TITLES.get(name, {})
        g["title"] = ti.get("title", "other")
        g["attr"] = attr_area(t, e["start"])
        is_dnas = "DNASBOOT2" in g["attr"].get("keys", {}) or ti.get("dnas")
        if name not in TITLES and not is_dnas:
            g["skipped"] = "not a known title and no DNAS-style attr"
            m["games"][name] = g
            continue
        ranges = [(e["start"], e["start"] + e["sectors"])] + [
            (s, s + x["sectors"]) for x in apa if x.get("main") == e["start"] and not x.get("name")
            for s in [x["start"]]]
        sb = superblock_info(t, env, e["start"])
        g["pfs_superblock"] = dict(zone_size=sb["zone_size"], fsck_stat=sb["fsck"], subs=sb["nsubs"]) if sb else None
        try:
            part, files, bad = mount(t, env, e["start"], e["sectors"], subs.get(e["start"]))
        except Exception as exc:
            part, files, bad = None, None, [("(mount)", str(exc))]
        if part is None:
            g["pfs"] = dict(mounted=False, error="no PFS superblock/root readable %s"
                            % (bad or "(unformatted, or the image is being rewritten)"))
            files = {}
        else:
            root = sorted(p for p in files if p.count("/") == 1)
            dirs = sorted(set(p.split("/")[1] for p in files if p.count("/") > 1))
            g["pfs"] = dict(mounted=True, zone=part.zone_size, files=len(files),
                            root_files={p: files[p]["size"] for p in root}, dirs=dirs,
                            unreadable=[b[0] for b in bad][:20])

        # trace.bin
        tb = files.get("/trace.bin")
        trace_lba = None
        if tb:
            trace_lba = file_lba(part, tb)
            head = read_head(part, tb, 16)
            g["trace_bin"] = dict(lba=trace_lba, magic=head[:16].decode("latin-1", "replace").rstrip("\0"),
                                  armed_magic=head.startswith(b"POLTRACE"))

        # loader
        boot2 = g["attr"].get("keys", {}).get("BOOT2", "")
        lpath = None
        if boot2.lower().startswith("pfs:/"):
            lpath = "/" + boot2[5:]
        else:
            for cand in ("/dnasload.elf", "/bombload.kelf", "/bombload.elf"):
                if cand in files:
                    lpath = cand
                    break
        g["loader_path"] = lpath
        if lpath and lpath in files:
            blob = read_file(part, env, files[lpath])
            g["loader"] = analyze_loader(blob, env, ids, trace_lba, ranges)
            sb_ = g["loader"].pop("_served_block", None)
            if sb_ is not None:
                lab = ids.add("served by loader", sb_)
                g["loader"]["served_hddid"]["candidate_label"] = lab
                if g["loader"]["served_hddid"]["label"].startswith("unknown"):
                    g["loader"]["served_hddid"]["label"] = lab
                g["_served"] = lab
        elif lpath:
            g["loader"] = dict(missing=True)
        ext = external_loader(args, name)
        if ext:
            # A PCSX2 rig boots its loader with -elf from the PC; audit that one
            # as the loader that serves this partition, keep the drive's aside.
            if g.get("loader"):
                g["loader_on_drive"] = g["loader"]
            r = analyze_loader(open(ext, "rb").read(), env, ids, trace_lba, ranges)
            r["source"] = "external --loader %s" % ext
            sb_ = r.pop("_served_block", None)
            g["loader"] = r
            g.pop("_served", None)
            if sb_ is not None:
                lab = ids.add("served by loader", sb_)
                r["served_hddid"]["candidate_label"] = lab
                if r["served_hddid"]["label"].startswith("unknown"):
                    r["served_hddid"]["label"] = lab
                g["_served"] = lab
        # DNAS.BIN, FMOD (Minna)
        if g["title"] == "mingol" and part is not None:
            d = files.get("/DNAS.BIN")
            if d:
                b = read_file(part, env, d)
                s1, s2 = h1(b)[:8], h256(b)[:8]
                g["dnas_bin"] = dict(sha1=s1, sha256=s2, what=DNASBIN_KNOWN.get(s1) or DNASBIN_KNOWN.get(s2) or "unknown")
            g["fmod_staged"] = {k: len([p for p in files if p.upper().startswith("/%s/" % k)])
                                for k in ("FMOD", "FMOD2")}
        if g["title"] == "nobunaga":
            c = files.get("/NBCONNSV.BIN")
            if c:
                g["nbconnsv"] = read_file(part, env, c).decode("latin-1", "replace").strip()
        g["_files"] = files
        g["_part"] = part
        m["games"][name] = g

    # 4. containers
    fours = [FOUR_DEFAULT] + [bytes.fromhex(x) for x in (args.four or [])]
    for name, g in m["games"].items():
        files, part = g.pop("_files", None), g.pop("_part", None)
        served = g.pop("_served", None)
        if not files or env.dnasdec is None or args.no_containers:
            continue
        cands, seen = [], set()
        order = ([served] if served else []) + [l for l in ids.blocks if l != served]
        for lab in order:
            blk = ids.blocks[lab]
            ata32 = env.dnasdec.ata_material(blk)
            fl = ([net_fours[lab]] if lab in net_fours else []) + fours
            for four in fl:
                key = (material_of(blk), four)
                if key in seen:
                    continue
                seen.add(key)
                cands.append(("%s + four %s" % (lab, four.hex()), ata32, four))
        pats = TITLES.get(name, {}).get("containers") or ["/*"]   # other titles: root only
        targets = sorted(p for p in files if any(path_match(p, q) for q in pats)
                         and files[p]["size"] <= args.max_container)
        res = {}
        for p in targets:
            head = read_head(part, files[p], 128)
            if len(head) < 128:
                continue
            try:
                r7 = env.dnas2.unrecord(head, env.dnaskeys[7][1], env.dnaskeys[7][2])
            except Exception:
                r7 = None
            if r7 is None or r7[1] != b"96011a8e95fd1ffc":
                res[p] = dict(container=False, size=files[p]["size"])
                continue
            blob = read_file(part, env, files[p])
            r = container_check(blob, env, cands, args.deep_limit)
            r["size"] = len(blob)
            res[p] = r
        sealed = [r for r in res.values() if r.get("container")]
        g["containers"] = res
        tally = {}
        for r in sealed:
            tally[r.get("sealed_to") or "NOTHING (no candidate decrypts)"] = \
                tally.get(r.get("sealed_to") or "NOTHING (no candidate decrypts)", 0) + 1
        g["containers_summary"] = dict(
            sealed_files=len(sealed), plain_files=len(res) - len(sealed),
            sealed_to=tally,
            tag_missing=sorted(p for p, r in res.items() if r.get("container") and r.get("sealed_to")
                               and not r.get("tag_present")),
            sig_mismatch=sorted(p for p, r in res.items() if r.get("sig_ok") is False and r.get("sealed_to")),
            undecryptable=sorted(p for p, r in res.items() if r.get("container") and not r.get("sealed_to")))
        if g["title"] == "mingol":
            plain = {}
            for p in sorted(x for x in files if x.count("/") == 1 and x.upper().endswith(".BIN")
                            and x.upper() != "/DNAS.BIN"):
                hd = read_head(part, files[p], 128)
                try:
                    r7 = env.dnas2.unrecord(hd, env.dnaskeys[7][1], env.dnaskeys[7][2])
                except Exception:
                    r7 = None
                plain[p] = "sealed (DNAS2)" if r7 and r7[1] == b"96011a8e95fd1ffc" else "plain"
            g["overlays_root"] = plain
    m["candidate_ids"] = {lab: dict(sha1=h1(b)[:8], material=material_of(b).hex())
                          for lab, b in ids.blocks.items()}
    m["verdicts"] = verdicts(m)
    t.close()
    return m


# ---------------------------------------------------------------------------
# 8. verdicts
# ---------------------------------------------------------------------------
def verdicts(m):
    v = []

    def add(gate, level, title, text):
        v.append(dict(gate=gate, level=level, title=title, text=text))

    if m["sector7"]["nonzero"]:
        add(1, "FAIL", "*", "APA sector 7 (part-error record) nonzero %s: the launcher runs fsck "
            "on that partition" % m["sector7"]["words"])
    else:
        add(1, "ok", "*", "APA sector 7 clear")
    if not m["apa_header_checksums_ok"]:
        bad = [e.get("name") or "(sub@%d)" % e.get("start", 0) for e in m["apa"] if not e.get("checksum_ok")]
        add(1, "FAIL", "*", "APA header checksum bad: %s" % ", ".join(bad))
    net = m.get("net", {})
    if not net.get("present"):
        add(7, "FAIL", "*", "no __net partition")
    else:
        pw = [e for e in m["apa"] if e.get("name") == "__net"][0]["passwords"]
        if not (pw.get("fpwd_ok") and pw.get("rpwd_ok")):
            add(5, "FAIL", "__net", "__net passwords are not the PlayOnline constants")
        af = net["access_flag25_0x202000"]
        if af["state"].startswith("matches"):
            add(7, "ok", "*", "access_flag25 = shipped psbb record (needs psbb i.Link spoof for DNAS callers)")
        else:
            add(7, "FAIL", "*", "access_flag25 at __net+0x202000 is %s (sha256 %s)" % (af["state"], af["sha256"]))
        rec = net["record_0x201800"]
        if rec["empty"]:
            add(6, "risk", "*", "__net +0x201800 record empty (never provisioned)")
        elif not rec["decodes_with"]:
            add(6, "risk", "*", "__net +0x201800 record decodes with none of the candidate HDD IDs")
    sc = m.get("sysconf", {})
    nc = sc.get("netcnf000", {})
    if sc.get("present") and not nc.get("present"):
        add(8, "FAIL", "*", "__sysconf/etc/bnnetwork/netcnf000.dat missing (launcher error 0x81020002)")
    elif nc.get("present"):
        # The loaders serve the psbb spoof to the games' i.Link read, so only a
        # psbb-keyed file decodes in-game; anything else shows "connected to
        # another PlayStation 2 / redo network settings".
        who = nc.get("decodes_with")
        add(8, "ok" if who and who.startswith("psbb") else "FAIL", "*",
            "netcnf000.dat decodes with %s" % (
                who or "NO known i.Link, keyed to %s (rewritten by a console's own "
                       "network setup?)" % nc.get("keyed_to")))
    stray = [p for p in sc.get("netcnf_files", {}) if p != "/etc/bnnetwork/netcnf000.dat"]
    if stray:
        add(8, "risk", "*", "netcnf outside /etc/bnnetwork (not read by the games): %s"
            % ", ".join(sorted(stray)))

    for name, g in m.get("games", {}).items():
        if g.get("skipped"):
            continue
        tt = g.get("title", name)
        pw = g["passwords"]
        if pw.get("fpwd_ok") is False:
            add(5, "FAIL", tt, "%s fpwd does not match %s (have %s)" % (name, pw["rule"],
                [e for e in m["apa"] if e.get("name") == name][0]["fpwd"]))
        if pw.get("rpwd_ok") is False:
            if tt == "bomb":
                add(1, "risk", tt, "rpwd NONZERO on Bomberman: HOSDMenu's PATINFO mount is blocked")
            else:
                add(5, "FAIL", tt, "%s rpwd does not match %s" % (name, pw["rule"]))
        if pw.get("fpwd_ok") and pw.get("rpwd_ok") is not False:
            add(5, "ok", tt, "partition passwords match (%s)" % pw["rule"])
        sb = g.get("pfs_superblock")
        if sb and sb.get("fsck_stat"):
            add(1, "risk", tt, "PFS superblock pfsFsckStat = 0x%x" % sb["fsck_stat"])
        at = g["attr"]
        if not at.get("present"):
            add(2, "FAIL", tt, "no attribute area at +0x1000: the browser cannot launch it "
                "(fine for a PCSX2 Run-ELF image only)")
        else:
            k = at.get("keys", {})
            if "BOOT2" not in k:
                add(2, "FAIL", tt, "attr has no BOOT2")
            elif not k["BOOT2"].lower().startswith("pfs:/"):
                add(2, "FAIL", tt, "BOOT2 = %s (not our loader on pfs:)" % k["BOOT2"])
            if "DNASBOOT2" not in k:
                add(2, "risk", tt, "attr has no DNASBOOT2 (the one Bomberman HW launch that worked had it)")
        ld = g.get("loader")
        ondrive = g.get("loader_on_drive", ld)
        if g.get("loader_path") and (not ondrive or ondrive.get("missing")):
            add(2, "FAIL", tt, "BOOT2 target %s is not on the partition" % g["loader_path"])
        known_title = name in TITLES
        od = g.get("loader_on_drive")
        if od and not od.get("missing"):
            add(2, "info", tt, "on-drive BOOT2 %s = %s %s%s (the console runs THIS one, not --loader)"
                % (g["loader_path"], od["sha1"][:8], od.get("form", "")[:10],
                   (" = " + od["known"]) if od.get("known") else ""))
        if ld and not ld.get("missing"):
            form = ld.get("form", "")
            if form.startswith("plain ELF"):
                add(2, "FAIL", tt, "loader is a plain ELF%s: PCSX2 only, the console needs a KELF"
                    % (" (%s)" % ld["source"] if ld.get("source") else ""))
            kelf = ld.get("kelf") or {}
            if kelf.get("header_sig_ok") is False:
                add(2, "FAIL", tt, "KELF signature check failed: %s" % kelf.get("error"))
            elif kelf.get("signatures_ok"):
                add(2, "ok", tt, "KELF signatures verify (%s)" % kelf.get("layout"))
            elif kelf.get("header_sig_ok"):
                add(2, "info", tt, "KELF header signature verifies; body not decodable with PS2KEYS "
                    "(retail Sony-signed layout?)")
            if ld.get("known"):
                add(0, "info", tt, "loader %s = %s" % (ld["sha1"][:8], ld["known"]))
            ih = ld.get("install_header")
            if ih is not None and not ih.get("filled"):
                add(2, "FAIL", tt, "loader install header NOT FILLED (boot ELF/IOPRP/HDD ID missing)")
            if not known_title:
                continue
            io = ld.get("ioprp") or {}
            want = TITLES.get(name, {}).get("ioprp")
            if want and io.get("version"):
                add(3, "ok" if io["version"] == want else "FAIL", tt,
                    "IOPRP %s (%s), title wants %s" % (io["version"], io.get("conffile"), want))
            elif want and ld.get("family"):
                add(3, "risk", tt, "IOPRP version not readable from the loader")
            drv = ld.get("drivers", "")
            if drv.startswith("4"):
                add(4, "ok", tt, "DRIVERS=4 (proven on HW)")
            elif drv.startswith("2"):
                add(4, "risk", tt, "DRIVERS=2: never passed the atad gate on HW")
            elif drv[:1] in ("3", "5"):
                add(4, "risk", tt, "DRIVERS=%s: unproven on HW" % drv[:1])
            elif drv:
                add(4, "info", tt, "driver stack: %s" % drv)
            sp = ld.get("spoof_ilink", {})
            if not sp.get("psbb 0700001ad5910c10"):
                add(7, "risk", tt, "no psbb i.Link spoof id in the loader: access_flag25 (psbb) "
                    "will not match the real console")
            scf = ld.get("scefix")
            if scf and not scf.get("spoof_cdri"):
                add(7, "FAIL", tt, "scefix %s has no sceCdRI spoof: prep -101 -> Exit(-1) on the real console"
                    % scf.get("version"))
            tr = ld.get("trace", {})
            if tr.get("loader_trace_lba") and not tr.get("inside_game_partition", True):
                add(0, "info", tt, "trace LBA %d is outside %s: trace not armed"
                    % (tr["loader_trace_lba"], name))
            elif tr.get("armed"):
                add(0, "info", tt, "trace armed at LBA %d (/trace.bin, POLTRACE magic %s)"
                    % (tr["loader_trace_lba"], g.get("trace_bin", {}).get("armed_magic")))
            else:
                add(0, "info", tt, "trace not armed (%s)" % (tr.get("note") or "LBA != /trace.bin"))
            served = (ld.get("served_hddid") or {}).get("candidate_label")
            cs = g.get("containers_summary")
            if cs:
                st = cs["sealed_to"]
                if served and cs["sealed_files"]:
                    ok = [k for k in st if k.startswith(served + " ")]
                    if ok and sum(st[k] for k in ok) == cs["sealed_files"]:
                        add(6, "ok", tt, "all %d containers decrypt under the SERVED id (%s)"
                            % (cs["sealed_files"], ", ".join(ok)))
                    else:
                        add(6, "FAIL", tt, "served HDD ID (%s) != sealed ID %s"
                            % (ld["served_hddid"]["label"], st))
                if cs["tag_missing"]:
                    add(6, "FAIL", tt, "drive tail tag missing on %d files: %s"
                        % (len(cs["tag_missing"]), ", ".join(cs["tag_missing"][:5])))
                if cs["sig_mismatch"]:
                    # dnasdec's signed-SHA-1 model is incomplete: the golden
                    # work/ourinstall (booted on HW) fails it on DS1O_S1/INET/
                    # OPENING/USBD, and pop'n disc-identical modules fail it too.
                    # It is exact for NBONLINE.EBN, which is what the verdict
                    # patch breaks (gate 9), so only that file is a verdict.
                    add(0, "info", tt, "signed SHA-1 model does not verify %d file(s) (model "
                        "incomplete, not by itself a defect): %s"
                        % (len(cs["sig_mismatch"]), ", ".join(cs["sig_mismatch"])))
                if tt == "nobunaga":
                    nb = g.get("containers", {}).get("/NBONLINE.EBN", {})
                    if nb.get("sig_ok") is False:
                        add(9, "FAIL", tt, "NBONLINE.EBN signed SHA-1 mismatch: verdict-patched "
                            "module, the console rejects it")
                    elif nb.get("sig_ok"):
                        add(9, "ok", tt, "NBONLINE.EBN signed SHA-1 verifies (stock module)")
                if served and "psbb" not in served and cs["sealed_files"]:
                    add(6, "risk", tt, "served ID is not the psbb ID (minted ID unproven on HW)")
        cs = g.get("containers_summary")
        if cs and cs["undecryptable"]:
            add(6, "FAIL", tt, "%d containers decrypt under NO candidate id: %s"
                % (len(cs["undecryptable"]), ", ".join(cs["undecryptable"][:5])))
        if tt == "mingol":
            d = g.get("dnas_bin")
            if d:
                add(11, "ok" if "PATCH 1" in d["what"] else "FAIL", tt,
                    "DNAS.BIN %s = %s" % (d["sha1"], d["what"]))
            fm = g.get("fmod_staged", {})
            if not g.get("pfs", {}).get("mounted"):
                add(11, "risk", tt, "partition not readable: DNAS.BIN / FMOD unchecked")
            elif not fm.get("FMOD") or not fm.get("FMOD2"):
                add(11, "FAIL", tt, "FMOD/FMOD2 not staged (%s)" % fm)
        if tt == "bomb":
            fe = m.get("sysconf", {}).get("feega", {})
            add(12, "info", tt, "feega.dat %s" % (", ".join(fe) if fe else "absent (__sysconf/etc/feega)"))
        if tt == "nobunaga" and g.get("nbconnsv"):
            add(12, "info", tt, "NBCONNSV.BIN = %r" % g["nbconnsv"])
    return v


# ---------------------------------------------------------------------------
# Human summary
# ---------------------------------------------------------------------------
def summary(m):
    L = []
    w = L.append
    w("hwaudit  %s  (%.1f GiB)  %s" % (m["target"], m["size"] / 2.0 ** 30, m["time"]))
    for n in m["notes"]:
        w("  note: %s" % n)
    w("")
    w("APA (main partitions; %d sub-partitions and %d free entries not listed)"
      % (sum(1 for e in m["apa"] if e.get("sub")),
         sum(1 for e in m["apa"] if e.get("type") == "0x0000" and not e.get("sub"))))
    for e in m["apa"]:
        if e.get("type") == "0x0000" and not e.get("sub"):
            continue
        if e.get("sub") or "error" in e:
            if "error" in e:
                w("  !! header LBA %d: %s" % (e["lba"], e["error"]))
            continue
        pw = e.get("passwords", {})
        flag = ""
        if pw.get("fpwd_ok") is not None:
            flag = " pwd fpwd:%s rpwd:%s" % ("ok" if pw["fpwd_ok"] else "BAD",
                                             "ok" if pw["rpwd_ok"] else "BAD")
        w("  %10d %6d MiB %-6s %-34s r=%s f=%s%s%s%s" % (
            e["start"], e["mib"], e["type"], e["name"] or "(free)", e["rpwd"], e["fpwd"], flag,
            "" if e["checksum_ok"] else " CHECKSUM-BAD", " BEYOND-IMAGE" if e.get("beyond_image_end") else ""))
    w("  sector 7: %s" % ("NONZERO %s" % m["sector7"]["words"] if m["sector7"]["nonzero"] else "clear"))
    net = m.get("net", {})
    if net.get("present"):
        rec = net["record_0x201800"]
        w("")
        w("__net (LBA %d)" % net["lba"])
        w("  +0x201800 %s; decodes with: %s" % (
            "EMPTY" if rec["empty"] else rec["head_36"][:40] + "...",
            "; ".join("%s -> four %s console %s" % (k, d["four"], d["console_ilink"])
                      for k, d in rec["decodes_with"].items()) or "none of the candidates"))
        af = net["access_flag25_0x202000"]
        w("  +0x202000 access_flag25 sha256 %s (%d nonzero): %s" % (af["sha256"], af["nonzero"], af["state"]))
        w("  /etc: %s" % ", ".join(net.get("etc_files", [])))
        w("  LBA 0x41000-0x4101f sha1 %s" % net["lba_0x41000_0x4101f_sha1"][:16])
    sc = m.get("sysconf", {})
    if sc.get("present"):
        nc = sc.get("netcnf000", {})
        w("  netcnf000.dat: %s" % ("absent" if not nc.get("present") else
                                   "decodes with %s" % nc.get("decodes_with")
                                   if nc.get("decodes_with") else
                                   "keyed to %s" % nc.get("keyed_to")))
        w("  netcnf files: %s" % sc.get("netcnf_files"))
        if sc.get("feega"):
            w("  feega: %s" % sc["feega"])
    for name, g in m.get("games", {}).items():
        w("")
        w("== %s  [%s]  LBA %d, %d MiB" % (name, g.get("title"), g["start"], g["sectors"] // 2048))
        if g.get("skipped"):
            w("  skipped: %s" % g["skipped"])
            continue
        at = g["attr"]
        if at.get("present"):
            w("  attr boot block:")
            for line in at["boot_text"].splitlines():
                w("    | %s" % line)
        else:
            w("  attr: ABSENT (no PS2ICON3D at +0x1000)")
        pf = g.get("pfs", {})
        if pf.get("mounted"):
            w("  pfs: %d files, root: %s%s" % (pf["files"], ", ".join(sorted(pf["root_files"]))[:300],
                                              "  dirs: " + ",".join(pf["dirs"]) if pf["dirs"] else ""))
            if pf["unreadable"]:
                w("  pfs: unreadable entries: %s" % pf["unreadable"])
        else:
            w("  pfs: NOT MOUNTABLE %s" % pf.get("error"))
        if g.get("trace_bin"):
            tb = g["trace_bin"]
            w("  /trace.bin LBA %s magic %r" % (tb["lba"], tb["magic"]))
        ld = g.get("loader")
        if ld:
            od = g.get("loader_on_drive")
            if od and od.get("missing"):
                w("  loader %s on the drive: MISSING" % g["loader_path"])
            elif od:
                w("  loader %s on the drive: %d B sha1 %s %s%s (not the one audited below)" % (
                    g["loader_path"], od["size"], od["sha1"][:8], od.get("form"),
                    (" = " + od["known"]) if od.get("known") else ""))
            if ld.get("missing"):
                w("  loader %s: MISSING" % g["loader_path"])
            else:
                w("  loader %s: %d B sha1 %s %s%s" % (ld.get("source") or g["loader_path"], ld["size"], ld["sha1"][:8],
                                                     ld.get("form"), (" = " + ld["known"]) if ld.get("known") else ""))
                k = ld.get("kelf")
                if k:
                    w("    kelf: hdr %d, header sig %s, all sigs %s%s" % (
                        k["header_size"], k.get("header_sig_ok"), k.get("signatures_ok"),
                                                    (", " + k["body"]) if k.get("body") else ""))
                if ld.get("install_header"):
                    ih = ld["install_header"]
                    w("    header: argv0 %s, elf %d/%d (sha1 %s), ioprp %d/%d, filled=%s" % (
                        ih["argv0"], ih["elf_len"], ih["elf_capacity"], ih["boot_elf_sha1"],
                        ih["ioprp_len"], ih["ioprp_capacity"], ih["filled"]))
                if ld.get("served_hddid"):
                    s = ld["served_hddid"]
                    w("    served HDD ID: %s (sha1 %s, serial %s)" % (s.get("label"), s.get("sha1"), s.get("serial")))
                if ld.get("ioprp"):
                    w("    IOPRP: %s %s" % (ld["ioprp"].get("version"), ld["ioprp"].get("conffile")))
                w("    drivers: %s; spoof: %s" % (ld.get("drivers"),
                                                  ", ".join(k for k, v in ld.get("spoof_ilink", {}).items() if v) or "none"))
                if ld.get("scefix"):
                    w("    scefix: %s" % ld["scefix"])
                tr = ld.get("trace", {})
                w("    trace: loader LBA %s, /trace.bin %s, armed %s%s" % (
                    tr.get("loader_trace_lba"), tr.get("trace_bin_lba"), tr.get("armed"),
                    "" if tr.get("inside_game_partition", True) else " (OUTSIDE the partition)"))
                if ld.get("verbose", {}).get("bomb_bb_trace"):
                    w("    verbose: [bb] SCREEN/trace build")
        if g.get("dnas_bin"):
            w("  DNAS.BIN %s: %s" % (g["dnas_bin"]["sha1"], g["dnas_bin"]["what"]))
        if g.get("fmod_staged"):
            w("  staged: %s" % g["fmod_staged"])
        if g.get("overlays_root"):
            w("  root overlays: %s" % ", ".join("%s=%s" % (k.strip("/"), v) for k, v in g["overlays_root"].items()))
        if g.get("nbconnsv"):
            w("  NBCONNSV.BIN: %r" % g["nbconnsv"])
        cs = g.get("containers_summary")
        if cs:
            w("  containers: %d sealed, %d plain" % (cs["sealed_files"], cs["plain_files"]))
            for k, n in cs["sealed_to"].items():
                w("    sealed-to: %s  (%d files)" % (k, n))
            if cs["tag_missing"]:
                w("    tail tag MISSING: %s" % ", ".join(cs["tag_missing"]))
            if cs["sig_mismatch"]:
                w("    signed SHA-1 MISMATCH: %s" % ", ".join(cs["sig_mismatch"]))
    w("")
    w("verdicts")
    for x in m["verdicts"]:
        w("  [%-4s] gate %-2s %-9s %s" % (x["level"], x["gate"] or "-", x["title"], x["text"]))
    return "\n".join(L)


def strip_private(o):
    if isinstance(o, dict):
        return {k: strip_private(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [strip_private(v) for v in o]
    if isinstance(o, tuple):
        return [strip_private(v) for v in o]
    if isinstance(o, bytes):
        return o.hex()
    return o


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target", nargs="?", help="/dev/sdX (after blockdev --flushbufs) or a raw .img")
    ap.add_argument("--hddid", action="append", metavar="PATH[=LABEL]",
                    help="extra candidate HDD ID block(s), e.g. the drive's games/POL/playonline.hddid")
    ap.add_argument("--four", action="append", metavar="HEX8", help="extra __net four(s) to try")
    ap.add_argument("--only", action="append", metavar="PARTITION", help="audit only these game partitions")
    ap.add_argument("--json", metavar="PATH", help="write the manifest here ('-' = stdout)")
    ap.add_argument("--helper", help="psbbn-playonline/scripts/helper (read-only import)")
    ap.add_argument("--keys", help="PS2KEYS.dat for KELF signature checks")
    ap.add_argument("--deep-limit", type=int, default=8 << 20,
                    help="largest container fully decrypted for the signed SHA-1 (default 8 MiB)")
    ap.add_argument("--max-container", type=int, default=64 << 20,
                    help="skip container candidates larger than this (default 64 MiB)")
    ap.add_argument("--no-containers", action="store_true", help="skip the container pass")
    ap.add_argument("--loader", dest="loader_file", metavar="[PART=]FILE", action="append",
                    help="with no target: audit this loader file alone. With a target: the loader that "
                         "serves PART (PCSX2 -elf boot); without PART= it applies to the audited title")
    args = ap.parse_args()
    env = load_env(args.helper, args.keys)

    if args.loader_file and not args.target:
        ids = base_ids(args.hddid)
        r = analyze_loader(open(args.loader_file[0].split("=")[-1], "rb").read(), env, ids)
        r.pop("_served_block", None)
        print(json.dumps(strip_private(r), indent=1))
        return 0
    if not args.target:
        ap.error("a target drive/image (or --loader FILE) is required")
    if args.json and args.json != "-":
        if os.path.exists(args.json) and os.path.exists(args.target) and \
                os.path.samefile(args.json, args.target):
            raise SystemExit("refusing: --json would overwrite the target")
    m = audit(args.target, env, args)
    out = strip_private(m)
    text = json.dumps(out, indent=1, sort_keys=False, default=str)
    sha = h256(text.encode())[:16]
    if args.json == "-":
        print(text)
        print(summary(m), file=sys.stderr)
        print("manifest sha256 %s" % sha, file=sys.stderr)
        return 0
    print(summary(m))
    if args.json:
        with open(args.json, "w") as f:
            f.write(text)
        print("manifest %s  sha256 %s" % (args.json, sha))
    else:
        print("manifest sha256 %s (pass --json PATH to save it)" % sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
