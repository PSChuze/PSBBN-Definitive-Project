#!/usr/bin/env python3
#
# Nobunaga's Ambition Online installer for the PSBBN Definitive Project
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
"""Nobunaga no Yabou Online, Hiryuu no Shou (SLPM-65783), on a PSBBN drive.

Unlike the PlayOnline titles, this one cannot be installed from the PC. Its
files are Sony DNAS2 containers, and the disc-to-drive re-encryption only
happens inside Koei's own installer, on the console. So the PC side of this
step prepares the drive and protects what is already on it, and the install
itself runs on the console.

This package only reads from `playonline`. It never changes that package's
code, and on a drive that already carries PlayOnline it writes nothing that
the PlayOnline step would not write itself (see check.py and record.py).
"""

__version__ = "0.1"
