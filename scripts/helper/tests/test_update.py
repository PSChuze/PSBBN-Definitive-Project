#!/usr/bin/env python3
"""Offline checks for playonline.polp and playonline.update.

    python3 scripts/helper/tests/test_update.py

No drive and no server: a patch server is stood up on loopback from a list
built here, and the drive is a stand-in with the attributes `commands` reads.
"""
import hashlib
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from playonline import polp, update  # noqa: E402


def row_for(ver, raw, blob):
    s = polp.signed_bytesum(raw)
    m = struct.unpack("<i", hashlib.md5(raw).digest()[:4])[0]
    return "%s %d %d %d %s %d" % (ver, len(raw), s, m, blob, 0)


class FakeServer(object):
    """Answers 7, 1 and 3 from memory. `marked` says whether it knows "PS2+"."""

    def __init__(self, listing, blobs, latest, marked=True):
        self.listing, self.blobs, self.latest, self.marked = listing, blobs, latest, marked
        self.tags, self.versions = [], []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def region_ok(self, tag):
        self.tags.append(tag)
        return tag == b"PS2" or (self.marked and tag == b"PS2+")

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        buf = b""
        with conn:
            while True:
                while len(buf) < 16 or len(buf) < struct.unpack_from("<I", buf)[0]:
                    c = conn.recv(65536)
                    if not c:
                        return
                    buf += c
                n = struct.unpack_from("<I", buf)[0]
                pkt, buf = buf[:n], buf[n:]
                cmd = struct.unpack_from("<I", pkt, 12)[0]
                conn.sendall(self.reply(cmd, pkt))

    def reply(self, cmd, pkt):
        if cmd == 7:
            self.versions.append(pkt[24:0x58].split(b"\0")[0])
        if cmd == 7 and self.region_ok(pkt[16:20].rstrip(b"\0")):
            b = bytearray(0x58)
            b[8:12] = b"POLP"
            struct.pack_into("<I", b, 12, 8)
            s = b"registered\x00127.0.0.1\x00"
            b[0x18:0x18 + len(s)] = s
            body = self.latest.encode() + b"\0"
            return polp.frame(8, bytes(b[16:]) + struct.pack("<I", len(body)) + body)
        if cmd == 1 and self.region_ok(pkt[16:20].rstrip(b"\0")):
            return polp.frame(2, b"\x03" + zlib.compress(self.listing))
        if cmd == 3 and self.region_ok(pkt[24:28].rstrip(b"\0")):
            off, length = struct.unpack_from("<II", pkt, 16)
            plen = struct.unpack_from("<I", pkt, 32)[0]
            name = pkt[36:36 + plen - 1].decode()
            data = self.blobs[name][off:off + length]
            return polp.frame(4, struct.pack("<III", off, length, plen) + pkt[36:36 + plen] + data)
        return polp.frame(5, b"")


FILES = {
    "a.dat": [("20070911_0", b"old a"), ("20160203_0", b"new a, longer")],
    "dir/b.tm2": [("20100101_0", b"b at 2010")],
    "dir/c.dat": [("20000101_0", b"c too old")],
    "pinned.dat": [("20160203_0", b"p ok"), ("20200101_0", b"p past latest")],
}


def build_listing():
    lines, blobs = [], {}
    for path, rows in FILES.items():
        lines.append("file %s {" % path)
        for k, (ver, raw) in enumerate(rows):
            name = "%s/%s.slc" % (ver, path.replace("/", "_"))
            blob = b"\x03" + zlib.compress(raw)
            blobs[name] = blob
            r = row_for(ver, raw, name).rsplit(" ", 1)[0] + " %d" % len(blob)
            lines.append(r)
        lines.append("}")
        lines.append("")
    return ("\n".join(lines) + "\nend\n\n\n").encode(), blobs


class FakeDrive(object):
    image = "/dev/sdz"

    class title:
        partition = "PP.SCUS-97266.0001.FFXI"

    files = {("a.dat",): {"size": 5}, ("patch.ver",): {"size": 10}}
    dirs = set()


class Tests(unittest.TestCase):
    def test_decompress_methods(self):
        raw = b"abcabcabcabc" * 50
        self.assertEqual(polp.slc_decompress(b"\x03" + zlib.compress(raw)), raw)
        self.assertEqual(polp.slc_decompress(b"\x01" + raw), raw)
        # method 2: literal 'a','b','c' then a match of 9 at distance 3
        bits = []
        for ch in b"abc":
            bits += [0] + [(ch >> i) & 1 for i in range(8)]
        bits += [1] + [(3 >> i) & 1 for i in range(16)] + [(9 >> i) & 1 for i in range(8)]
        stream = bytearray((len(bits) + 7) // 8)
        for i, bit in enumerate(bits):
            stream[i >> 3] |= bit << (i & 7)
        blob = b"\x02" + struct.pack("<I", len(bits)) + bytes(stream)
        self.assertEqual(polp.slc_decompress(blob), b"abc" * 4)

    def test_row_check_catches_each_column(self):
        raw = b"\xff\x01hello"
        row = polp.Row(row_for("20160203_0", raw, "x/0.slc") + "9")
        self.assertIsNone(row.check(raw))
        self.assertIn("bytes", row.check(raw + b"!"))
        self.assertIn("byte-sum", row.check(b"\xff\x02hello"))
        # the same bytes in another order keep the sum; only MD5 sees it
        self.assertIn("MD5", row.check(b"\x01\xffhello"))

    def test_keyed_names_follow_the_viewer(self):
        yes = ["image/ffxi/prog/ps2/ffxi_pol.pex.enc", "dancer.enc", "V/pml.pex",
               "x.prg", "JanHouRou.dat.enc", "SCUS-97269", "SLPS-20200"]
        no = ["JanHouRou.dat", "config.sys", "data/a.tm2", "MIDAS.PEX", "Sound",
              "image/ffxi/ROM/0/0.DAT", "file.txt"]
        for n in yes:
            self.assertTrue(update.keyed_on_console(n), n)
        for n in no:
            self.assertFalse(update.keyed_on_console(n), n)

    def test_title_key_is_read_from_config_sys(self):
        class D(object):
            def __init__(self, cfg):
                self.cfg = cfg

            def read(self, path):
                return self.cfg if path == "config.sys" else None
        ffxi = b"TITLE=FINAL FANTASY XI\r\nBOOT=/image/ffxi/prog/ps2/ffxi_pol.pex\r\nKEY=/polkey.dat\r\n"
        self.assertTrue(update.title_keyed(D(ffxi)))
        self.assertFalse(update.title_keyed(D(b"TITLE=x\nBOOT=/bin/kel_rel.dat\n")))
        self.assertFalse(update.title_keyed(D(None)))
        self.assertEqual(update.module_name("a/ffxi_pol.pex.enc"), "a/ffxi_pol.pex")
        self.assertEqual(update.module_name("a/dancer.enc"), "a/dancer.bin")
        self.assertIsNone(update.module_name("a/b.dat"))

    def test_restore_served_puts_back_only_what_differs(self):
        p = "image/ffxi/prog/ps2/"

        class D(object):
            files = {}
            data = {
                p + "ffxi_pol.pex.enc": b"keyed by an earlier run",
                p + "ffxi_pol.pex.enc.tmp2": b"served",
                p + "ffxi_pol.pex": b"module",
                p + "dancer.enc": b"served d",
                p + "dancer.enc.tmp2": b"served d",
                p + "dancer.bin": b"module d",
                p + "other.enc": b"no tmp2 beside it",
            }

            def read(self, path):
                return self.data.get(path)
        D.files = {tuple(k.split("/")): {} for k in D.data}
        calls = []
        saved = update.served_form
        update.served_form = lambda served, path, stage: (
            calls.append((served, path)) or [tuple(update.module_name(path).split("/"))])
        try:
            out = update.restore_served(D(), "stage")
        finally:
            update.served_form = saved
        self.assertEqual(calls, [(b"served", p + "ffxi_pol.pex.enc")])
        self.assertEqual(["/".join(x) for x in out],
                         [p + "ffxi_pol.pex.enc", p + "ffxi_pol.pex"])

    def test_work_list_matches_the_viewers_shape(self):
        blocks = polp.parse_list("file a {\n20260913_M 1 2 3 v/a.slc 4\n}\n\nend\n")
        self.assertEqual(polp.work_list(blocks),
                         b"file a {\n20260913_m 1 2 3 v/a.slc 4\n}\n\n\nend\n\n")

    def plan_against(self, marked):
        listing, blobs = build_listing()
        srv = FakeServer(listing, blobs, "20160203_0", marked=marked)

        class D(object):
            class title:
                partition = "PP.SCUS-97266.0001.FFXI"

            def version(self):
                return "20070911_0"
        p = update.plan(D(), "127.0.0.1", srv.port, "PS2")
        return p, srv

    def test_plan_takes_newer_rows_up_to_latest(self):
        p, srv = self.plan_against(marked=True)
        got = {b.path: r.version for b, r in p.chosen}
        self.assertEqual(got, {"a.dat": "20160203_0", "dir/b.tm2": "20100101_0",
                               "pinned.dat": "20160203_0"})
        self.assertTrue(p.tool)
        self.assertTrue(all(t == b"PS2+" for t in srv.tags))

    def plan_unpatched(self, files):
        listing, blobs = build_listing()
        srv = FakeServer(listing, blobs, "20160203_0")

        class D(object):
            class title:
                partition = "PP.SLPM-65981.0004.FMO"

            def version(self):
                return None
        d = D()
        d.files = files
        return update.plan(d, "127.0.0.1", srv.port, "PS2"), srv

    def test_plan_without_patch_ver_starts_at_the_base_version(self):
        # FMO as installed has no patch.ver: ask as the Viewer does, with an
        # empty version, and take the list's oldest version as the drive's.
        files = {("a.dat",): {"size": 5}, ("dir", "c.dat"): {"size": 9}}
        p, srv = self.plan_unpatched(files)
        self.assertEqual(srv.versions, [b""])
        self.assertTrue(p.unpatched)
        self.assertEqual(p.have, "20000101_0")
        self.assertFalse(p.current)
        got = {b.path: r.version for b, r in p.chosen}
        self.assertEqual(got, {"a.dat": "20160203_0", "dir/b.tm2": "20100101_0",
                               "pinned.dat": "20160203_0"})

    def test_plan_without_patch_ver_fetches_a_base_file_that_differs(self):
        files = {("a.dat",): {"size": 5}, ("dir", "c.dat"): {"size": 4}}
        p, _srv = self.plan_unpatched(files)
        self.assertEqual({b.path: r.version for b, r in p.chosen}["dir/c.dat"],
                         "20000101_0")
        p, _srv = self.plan_unpatched({("a.dat",): {"size": 5}})
        self.assertIn("dir/c.dat", {b.path for b, _r in p.chosen})

    def test_plan_with_patch_ver_leaves_base_files_alone(self):
        p, srv = self.plan_against(marked=True)
        self.assertFalse(p.unpatched)
        self.assertEqual(srv.versions[0], b"20070911_0")
        self.assertNotIn("dir/c.dat", {b.path for b, _r in p.chosen})

    def test_plan_falls_back_to_the_plain_tag(self):
        p, srv = self.plan_against(marked=False)
        self.assertFalse(p.tool)
        self.assertEqual(srv.tags[:2], [b"PS2+", b"PS2"])

    def test_fetch_stage_and_commands(self):
        p, srv = self.plan_against(marked=True)
        with tempfile.TemporaryDirectory() as work:
            stage, meta = os.path.join(work, "tree"), os.path.join(work, "meta")
            update.fetch_all(p, "127.0.0.1", srv.port, "0001", stage, 2, log=lambda *_: None)
            with open(os.path.join(stage, "a.dat"), "rb") as f:
                self.assertEqual(f.read(), b"new a, longer")
            update.write_own_files(p, meta)
            with open(os.path.join(meta, "patch.ver"), "rb") as f:
                self.assertEqual(f.read(), b"20160203_0")
            with open(os.path.join(meta, "patch.cfg"), "rb") as f:
                self.assertEqual(f.read(), p.listing)
            cmds = update.commands(FakeDrive(), p, stage, meta)
            self.assertEqual(cmds[:2], ["device /dev/sdz", "mount PP.SCUS-97266.0001.FFXI"])
            self.assertIn("mkdir dir", cmds)
            # a file on the drive is removed first; a new one is not
            i = cmds.index("put a.dat")
            self.assertEqual(cmds[i - 1], "rm a.dat")
            self.assertNotIn("rm pinned.dat", cmds)
            # the version goes on last, after the lists, and replaces the old one
            self.assertEqual(cmds[-4:], ["rm patch.ver", "put patch.ver", "umount", "exit"])
            self.assertLess(cmds.index("put patch2.cfg"), cmds.index("put patch.ver"))
            # re-keyed files ride along; on their own, the version files stay
            cmds = update.commands(FakeDrive(), p, stage, meta, extra=[("a.dat",)])
            self.assertEqual(cmds.count("put a.dat"), 2)
            only = update.commands(FakeDrive(), None, stage, meta, extra=[("a.dat",)])
            self.assertIn("put a.dat", only)
            self.assertNotIn("put patch.ver", only)
            self.assertEqual(only[-2:], ["umount", "exit"])
            # a second run keeps what it already has
            kept = update.fetch_all(p, "127.0.0.1", srv.port, "0001", stage, 2,
                                    log=lambda *_: None)
            self.assertEqual(kept["kept"], len(p.chosen))


if __name__ == "__main__":
    unittest.main()
