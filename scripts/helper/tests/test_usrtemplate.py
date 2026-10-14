"""Offline checks for playonline.usrtemplate and build.make_extras.

    python -m pytest scripts/helper/tests/test_usrtemplate.py
"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from playonline import build, titles, usrtemplate  # noqa: E402

URL = ("usr", "all", "url")


class FakeDrive(object):
    def __init__(self, files, dirs):
        self.files = {k: None for k in files}
        self.dirs = set(dirs)
        self.data = files
        self.image = "/dev/sdx"
        self.title = types.SimpleNamespace(partition="PP.TEST.1000.POLVIEWER")

    def read(self, path):
        return self.data.get(tuple(path.split("/")))


def old_install():
    files = {
        ("default", "usr", "all", "url", "cert.db"): b"c" * 10,
        ("default", "usr", "all", "url", "rdthosts.bin"): b"r",
        ("default", "usr", "all", "url", "cache", "dcfat0.bin"): b"",
        ("usr", "all", "login_p.bin"): b"l",
    }
    dirs = {("default",), ("default", "usr"), ("default", "usr", "all"),
            ("default", "usr", "all", "url"), ("default", "usr", "all", "url", "cache"),
            ("usr",), ("usr", "all")}
    return FakeDrive(files, dirs)


def test_old_install_gets_the_three_files_and_their_directories():
    d = old_install()
    pairs = usrtemplate.missing(d)
    assert sorted(dest for _s, dest in pairs) == [
        URL + ("cache", "dcfat0.bin"), URL + ("cert.db",), URL + ("rdthosts.bin",)]
    work = tempfile.mkdtemp()
    usrtemplate.stage(d, pairs, work)
    assert open(os.path.join(work, *URL, "cert.db"), "rb").read() == b"c" * 10
    assert os.path.getsize(os.path.join(work, *URL, "cache", "dcfat0.bin")) == 0
    cmds = usrtemplate.commands(d, pairs, work)
    assert cmds.index("mkdir url") < cmds.index("mkdir cache") < cmds.index("put cert.db")
    assert "put dcfat0.bin" in cmds and cmds[-2:] == ["umount", "exit"]


def test_a_file_the_viewer_wrote_is_left_alone():
    d = old_install()
    d.files[URL + ("cert.db",)] = None
    d.data[URL + ("cert.db",)] = b"written by the Viewer"
    dests = [dest for _s, dest in usrtemplate.missing(d)]
    assert URL + ("cert.db",) not in dests and len(dests) == 2


def test_make_extras_copies_the_template():
    src, out = tempfile.mkdtemp(), tempfile.mkdtemp()
    d = os.path.join(src, "POL", "install", "PS2", "default")
    os.makedirs(os.path.join(d, "usr", "all", "url", "cache"))
    os.makedirs(os.path.join(d, "pub", "all"))
    open(os.path.join(d, "pub", "all", "install.inf"), "wb").write(b"x")
    open(os.path.join(d, "usr", "all", "url", "cert.db"), "wb").write(b"c")
    open(os.path.join(d, "usr", "all", "url", "cache", "dcfat0.bin"), "wb").close()
    viewer = [t for t in titles.TITLES.values()
              if t.tree == "POL/" and t.layout and t.boot != "NOBOOT"][0]
    made = build.make_extras(viewer, src, out)
    assert "usr/all/url/cert.db" in made and "usr/all/url/cache/dcfat0.bin" in made
    assert os.path.isfile(os.path.join(out, "usr", "all", "url", "cache", "dcfat0.bin"))
