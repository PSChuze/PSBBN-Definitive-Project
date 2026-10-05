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
"""The DNAS2 constant tables, as read off the player's own disc.

The container code needs four fixed tables from Sony's DNAS library: the
100-entry RSA keystore (100 x 200 bytes) and three DES constant windows.
Nothing ships them: `common.provide_dnas_consts` finds them by fingerprint in
the disc's ZZBIN/DNAS.BIN (the plaintext overlay that links the DNAS 2.70
library) and this module loads what it wrote. It must therefore be imported
only after that call (see `stage`).
"""
from . import common

_PIECES = common.load_dnas_consts()

KEYSTORE = _PIECES["KEYSTORE"]
STAT_2ACDD8 = _PIECES["STAT_2ACDD8"]
STAT_2ACDF8 = _PIECES["STAT_2ACDF8"]
STAT_2ACE20 = _PIECES["STAT_2ACE20"]
