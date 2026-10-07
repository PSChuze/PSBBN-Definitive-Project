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
"""Point Minna no Golf Online at the revival's servers.

Two files, both on by default for English and Japanese installs alike:

  ADDRESS/ADDRESS.XB
      The game's server table. Each of its four entries
      DATA\\address\\online<n>.txt (the client reads online2.txt) is
      rebuilt from the player's own disc file: the stock comment block (its
      '//<n>' marker) is kept and VALUES follows, one `NAME = value` per
      line, CRLF, with a CRLF after the last line (the client's line
      splitter drops a last line without one). The entries are stored raw,
      as the disc stores them. A disc file that is not the known one
      (ADDRESS_SHA1) is left as it is, with a note.

  ROOT_ED.PEM (partition root)
      The certificate the Feega login (EDAUTH.BIN) checks its server
      against. The game asks for cdrom0:\\FRES\\ROOT_ED.PEM;1; the loader's
      shim sends that open to pfs2:/ROOT_ED.PEM. By default it is the
      revival's Feega CA (scripts/assets/mingol/ROOT_ED.PEM, a public
      certificate), padded with newlines to the size of the disc's file;
      with the opt-out it is the disc's own FRES/ROOT_ED.PEM.

The opt-out (--stock-servers, or MINGOL_SERVERS=stock in the environment)
keeps the disc's ADDRESS.XB and Sony's root, for whoever runs their own
servers under the original names.

Ported from HippaulInstaller (playonline/games/mingol/servers.py).
"""
import hashlib
import os
import struct

from . import xbcodec

# The revival's servers, as online<n>.txt lines (NAME, value).
VALUES = (
    ("APP_VERSION", "101"),
    ("REGIST_SERVER", "regi.mgo.mingol.net"),
    ("REGIST_SERVERPORT", "12102"),
    ("WEB_SERVER", "http://www.mgo.mingol.net/tour/"),
    ("WEB_PAGE", "mgo.fcgi"),
    ("BBS_SERVER", "http://bbs.mgo.mingol.net/ps2/"),
    ("BBS_PAGE", "dbbbs.fcgi"),
    ("JAPANTOUR_POSTPROTO", "http"),
    ("JAPANTOUR_GETPROTO", "http"),
    ("JAPANTOUR_SERVER", "://www.mgo.mingol.net:12105/tour/"),
    ("JAPANTOUR_PAGE", "mgzantei.fcgi"),
)

ADDRESS_FILE = "ADDRESS/ADDRESS.XB"
ADDRESS_SHA1 = "b0e89d364651e4c9d0efe6b40be8e94d232fda12"    # the disc's
ENTRY = b"DATA\\address\\online%d.txt"

ROOT_ED_FILE = "ROOT_ED.PEM"                 # at the partition root (the shim's target)
ROOT_ED_DISC = "FRES/ROOT_ED.PEM"
ROOT_ED_ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                             os.pardir, os.pardir, "assets", "mingol", "ROOT_ED.PEM")
ROOT_ED_SHA1 = "7622bb5f7b9ee03ad53526c941c00666fd1cafe7"    # the asset as shipped
ROOT_ED_SIZE = 1652                                          # the disc's file

ENV = "MINGOL_SERVERS"


def stock_wanted(flag=False):
    """Whether the opt-out is on: the flag, or MINGOL_SERVERS=stock."""
    return bool(flag) or os.environ.get(ENV, "").strip().lower() == "stock"


def body():
    """The online<n>.txt lines after the comment block."""
    return b"".join(("%s = %s\r\n" % kv).encode("ascii") for kv in VALUES)


def _raw_entry(data):
    payload = struct.pack("<II", len(data), 0) + data
    return struct.pack("<II", len(payload), 0) + payload


def build_address(orig):
    """ADDRESS.XB with VALUES in all four entries, from the disc's file."""
    info = xbcodec.parse_all(orig)
    ents = info["entries"]
    stock = dict(xbcodec.decode_all(orig))
    names = [ENTRY % i for i in range(4)]
    if sorted(e["path"] for e in ents) != sorted(names):
        raise ValueError("ADDRESS.XB does not hold online0..3.txt")
    repl = {}
    for name in names:
        head = b""
        for line in stock[name].split(b"\r\n"):
            if not line.startswith(b"//"):
                break
            head += line + b"\r\n"
        repl[name] = head + body()
    # xbcodec.build_all with every replaced entry stored raw
    out = bytearray(orig[:ents[0]["off"]])
    for i, e in enumerate(ents):
        new = repl[e["path"]]
        struct.pack_into("<I", out, 8 + 8 * i, len(new))
        if i:
            out += b"\0" * ((-len(out)) & 3)
        struct.pack_into("<I", out, 8 + 8 * i + 4, len(out) // 4)
        out += _raw_entry(new)
    out = bytes(out)
    if dict(xbcodec.decode_all(out)) != repl:
        raise ValueError("the rebuilt ADDRESS.XB does not decode back")
    return out


def root_ed():
    """The revival's Feega CA, padded with newlines to the disc file's size."""
    with open(ROOT_ED_ASSET, "rb") as f:
        pem = f.read()
    if hashlib.sha1(pem).hexdigest() != ROOT_ED_SHA1:
        raise SystemExit("%s is not the certificate this step was made for"
                         % os.path.normpath(ROOT_ED_ASSET))
    if len(pem) > ROOT_ED_SIZE:
        raise SystemExit("%s is longer than the disc's ROOT_ED.PEM"
                         % os.path.normpath(ROOT_ED_ASSET))
    return pem + b"\n" * (ROOT_ED_SIZE - len(pem))


def apply(root, tree, m, stock=False):
    """Write ADDRESS.XB and ROOT_ED.PEM into the staged tree. `root` holds the
    disc's files (FRES/), `tree` the partition with the disc's ADDRESS/
    already copied in, `m` the manifest (the choice goes into its notes)."""
    path = os.path.join(tree, *ADDRESS_FILE.split("/"))
    disc_pem = os.path.join(root, *ROOT_ED_DISC.split("/"))
    if not os.path.isfile(disc_pem):
        raise SystemExit("the disc is missing %s; is it a complete dump?" % ROOT_ED_DISC)
    with open(disc_pem, "rb") as f:
        sony = f.read()
    if stock:
        pem = sony
        m.note("servers: the disc's own (ADDRESS.XB as on the disc, Sony's Feega root)")
    else:
        pem = root_ed()
        with open(path, "rb") as f:
            orig = f.read()
        if hashlib.sha1(orig).hexdigest() != ADDRESS_SHA1:
            m.note("servers: this disc's ADDRESS.XB (sha1 %s) is not the known one; "
                   "left as it is" % hashlib.sha1(orig).hexdigest())
        else:
            with open(path, "wb") as f:
                f.write(build_address(orig))
            m.note("servers: ADDRESS.XB points at %s; the Feega login trusts the "
                   "revival's CA" % dict(VALUES)["REGIST_SERVER"])
    with open(os.path.join(tree, ROOT_ED_FILE), "wb") as f:
        f.write(pem)
