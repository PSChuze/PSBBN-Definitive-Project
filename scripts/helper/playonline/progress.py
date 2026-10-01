#!/usr/bin/env python3
#
# PlayOnline installer for the PSBBN Definitive Project
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
"""One redrawn progress line, written to the terminal itself.

The installer pipes and redirects most of what its steps print into its
log, and a pipe holds Python's output back until it fills, so a long step
looks hung. This line goes to /dev/tty instead, the way pfsprogress does,
and so reaches the screen whatever happens to stdout:

    [##########..............................]  26%  10,240/39,102 files  570/2,188 MB  2.8 MB/s  ~10 min left

The percentage follows `weight` (bytes, when the caller knows them) and
falls back to the item count. Redrawing is limited to a few times a second.
"""
import sys
import time

WIDTH = 40


def _terminal():
    try:
        return open("/dev/tty", "w")
    except OSError:
        return sys.stderr


def duration(secs):
    """A rough, readable time: "40 s", "12 min", "1 h 05 min"."""
    secs = int(secs)
    if secs < 60:
        return "%d s" % max(secs, 1)
    if secs < 3600:
        return "%d min" % ((secs + 30) // 60)
    return "%d h %02d min" % (secs // 3600, (secs % 3600) // 60)


class Bar(object):
    """Progress over `total` items, optionally weighted by `weight` bytes."""

    def __init__(self, total, unit="files", weight=0, out=None, every=0.25):
        self.total, self.unit, self.weight = total, unit, weight
        self.done = self.bytes = 0
        self.out = out or _terminal()
        self.every = every
        self.start = self.last = time.monotonic()
        self.closed = False

    def add(self, items=1, nbytes=0):
        self.done += items
        self.bytes += nbytes
        now = time.monotonic()
        if now - self.last >= self.every or self.done >= self.total:
            self.last = now
            self.draw(now)

    def fraction(self):
        if self.weight:
            return min(self.bytes / float(self.weight), 1.0)
        return min(self.done / float(self.total), 1.0) if self.total else 1.0

    def line(self, now=None):
        now = now or time.monotonic()
        frac = self.fraction()
        fill = int(frac * WIDTH)
        parts = ["  [%s%s] %3d%%" % ("#" * fill, "." * (WIDTH - fill), int(frac * 100)),
                 "%s/%s %s" % (format(min(self.done, self.total), ","),
                               format(self.total, ","), self.unit)]
        elapsed = now - self.start
        if self.weight:
            parts.append("%s/%s MB" % (format(int(self.bytes / 1e6), ","),
                                       format(int(self.weight / 1e6), ",")))
            if elapsed > 1:
                parts.append("%.1f MB/s" % (self.bytes / 1e6 / elapsed))
        if 0.01 < frac < 1.0 and elapsed > 3:
            parts.append("~%s left" % duration(elapsed * (1 - frac) / frac))
        elif frac >= 1.0:
            parts.append("done in %s" % duration(elapsed))
        return "  ".join(parts)

    def draw(self, now=None):
        self.out.write("\r" + self.line(now) + "\033[K")
        self.out.flush()

    def close(self):
        if not self.closed:
            self.closed = True
            self.draw()
            self.out.write("\n")
            self.out.flush()


class Counter(object):
    """A count with no known total: "  reading the partition: 12,340 entries"."""

    def __init__(self, label, unit="entries", out=None, every=0.25):
        self.label, self.unit = label, unit
        self.count = 0
        self.out = out or _terminal()
        self.every = every
        self.last = 0.0

    def add(self, n=1):
        self.count += n
        now = time.monotonic()
        if now - self.last >= self.every:
            self.last = now
            self.draw()

    def draw(self):
        self.out.write("\r  %s: %s %s\033[K" % (self.label, format(self.count, ","), self.unit))
        self.out.flush()

    def close(self):
        self.draw()
        self.out.write("\n")
        self.out.flush()
