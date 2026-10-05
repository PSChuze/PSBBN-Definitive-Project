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
"""Fetch the latest Minna no Golf Online translation pack from openlobby.fyi.

HippaulInstaller's playonline/games/mingol/download.py, made standalone (the
toolkit has no selfupdate module to borrow from). A small JSON document names
the pack:

    {"format": 1, "version": "2026.10.05", "date": "2026-10-05",
     "file": "mingol-translation-2026.10.05.zip",
     "size": 24890, "sha256": "70f5..."}

`file` is taken relative to the document's address and must stay on the same
host; the download is checked against `size` and `sha256` before it is kept.
Packs are kept in the cache folder (MINGOL_TRANSLATION_CACHE; the installer
script points it at games/MGO/translation), so with the server out of reach
the newest pack kept there, or one the user dropped in, is used.

MINGOL_TRANSLATION_URL names a different document; MINGOL_TRANSLATION_URL=none
turns the download off.

    python -m mingol.stage.download          fetch, print the path
"""
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request

MANIFEST_URL = "https://openlobby.fyi/downloads/mingol-translation/latest"
URL_ENV = "MINGOL_TRANSLATION_URL"
CACHE_ENV = "MINGOL_TRANSLATION_CACHE"
MAX_SIZE = 64 * 1024 * 1024
USER_AGENT = "psbbn-mingol-installer"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.zip$")


def manifest_url(environ=None):
    """The document to ask, or None when the download is turned off."""
    value = (environ if environ is not None else os.environ).get(URL_ENV)
    if not value:
        return MANIFEST_URL
    if value.strip().lower() == "none":
        return None
    return value.strip()


def cache_dir(environ=None):
    """Where fetched packs are kept."""
    env = environ if environ is not None else os.environ
    if env.get(CACHE_ENV):
        return env[CACHE_ENV]
    base = env.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "hippaulinstaller", "mingol-translation")


def read_manifest(raw, base):
    """The pack a published document describes, or ValueError saying what is wrong."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("the answer is not JSON")
    if not isinstance(doc, dict):
        raise ValueError("the answer is not a JSON object")
    name = doc.get("file")
    if not isinstance(name, str) or not _FILE.match(name):
        raise ValueError("no usable file name in %r" % (name,))
    sha = str(doc.get("sha256") or "").lower()
    if not _SHA256.match(sha):
        raise ValueError("no usable sha256")
    size = doc.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_SIZE:
        raise ValueError("no usable size in %r" % (size,))
    url = urllib.parse.urljoin(base, name)
    here, there = urllib.parse.urlsplit(base), urllib.parse.urlsplit(url)
    if (here.scheme, here.netloc) != (there.scheme, there.netloc):
        raise ValueError("the pack is not on the manifest's own host")
    return {"version": str(doc.get("version", "?")), "file": name, "url": url,
            "sha256": sha, "size": size}


def _get(url, limit, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("%s is longer than expected" % url)
    return data


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def newest(folder):
    """The newest pack (*.zip) in `folder`, or None."""
    try:
        found = [os.path.join(folder, n) for n in os.listdir(folder) if _FILE.match(n)]
    except OSError:
        return None
    return max(found, key=os.path.getmtime) if found else None


def fetch(url, folder, timeout=15):
    """The published pack, in `folder`. Raises when it cannot be had."""
    offer = read_manifest(_get(url, 64 * 1024, timeout), url)
    dest = os.path.join(folder, offer["file"])
    if os.path.isfile(dest) and os.path.getsize(dest) == offer["size"] \
            and _sha256(dest) == offer["sha256"]:
        return dest
    data = _get(offer["url"], offer["size"], timeout)
    if len(data) != offer["size"] or hashlib.sha256(data).hexdigest() != offer["sha256"]:
        raise ValueError("the download does not match its size and sha256")
    os.makedirs(folder, exist_ok=True)
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return dest


def latest(environ=None, local=None):
    """(path of a pack, None) or (None, why there is none). Never raises.

    The published pack when it can be fetched; otherwise the newest one kept
    from an earlier fetch, then the newest pack in the folder `local` (if
    given), so an offline install still gets English.
    """
    url = manifest_url(environ)
    folder = cache_dir(environ)
    if url is None:
        why = "%s=none turns the download off" % URL_ENV
    else:
        try:
            path = fetch(url, folder)
            print("translation pack: %s" % path)
            return path, None
        except Exception as e:                  # network, HTTP, disk, bad answer
            why = "could not fetch %s: %s" % (url, e)
        kept = newest(folder)
        if kept:
            print("translation pack: %s; using the one kept at %s" % (why, kept))
            return kept, None
    if local:
        kept = newest(local)
        if kept:
            print("translation pack: %s; using %s" % (why, kept))
            return kept, None
    return None, why


def main():
    path, why = latest()
    if path is None:
        print(why)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
