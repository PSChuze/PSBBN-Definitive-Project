#!/usr/bin/env python3
#
# pop'n Puzzle Dama Online installer for the PSBBN Definitive Project
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
"""pop'n Puzzle Dama Online (SLPM-62464), on a PSBBN drive.

Unlike Nobunaga's Ambition Online, pop'n's disc-form DNAS2 containers can be
transcrypted to the drive form offline, using only bytes on the disc and the
public keystore. So the PC-side step here does the whole install: it seals
the disc's containers to the target drive's identity, creates the pop'n
partition, and writes the drive tree.

This package only reads from `playonline`. It never changes that package's
code, and on a drive that already carries PlayOnline or Nobunaga it writes
nothing that would disturb what those steps have written (see check.py).
"""

__version__ = "0.1"
