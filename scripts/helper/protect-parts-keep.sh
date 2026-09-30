#!/usr/bin/env bash
#
# PlayOnline installer for the PSBBN Definitive Project
# Copyright (C) 2026 PrettyOpenLobby
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Print every PP.* partition name the game-add sweep in Game-Installer.sh must
# NEVER delete.
#
# PSBBN rebuilds its own launcher partitions on each game add by deleting every
# PP.* partition and recreating the ones it manages. The titles this toolkit
# installs directly -- PlayOnline (Viewer / Tetra Master / Janhourou / FFXI /
# FMO / Dirge), Nobunaga, Minna no Golf, pop'n -- live in their own large PFS
# partitions that PSBBN cannot regenerate, so that sweep would silently destroy
# them. On 2026-09-29 an OPL install did exactly that to a user's drive.
#
# A name test cannot tell a title partition from a PSBBN launcher: a PS1 game's
# launcher can be PP.SLPS-* too. So the protected set is exact full partition
# names, taken from where each title is defined:
#   - the PlayOnline package's own table (authoritative, tracks titles.py)
#   - the three direct-install titles that are not in that package
#   - OPL/protect-parts.list, which any installer or the user may append to
#
# FAIL CLOSED: if the PlayOnline table cannot be read this exits non-zero
# WITHOUT printing a partial list, so the caller refuses to delete anything
# rather than fall through to deleting a title partition. That fall-through is
# the exact bug that wiped the drive.
set -u

HELPER_DIR="${HELPER_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SCRIPTS_DIR="${SCRIPTS_DIR:-$(cd "${HELPER_DIR}/.." && pwd)}"
OPL="${OPL:-}"

POL_PY="${SCRIPTS_DIR}/venv/bin/python3"
[ -x "$POL_PY" ] || POL_PY="python3"

# Field 2 of `titles --plain` is the partition name (key|partition|...).
if ! titles=$(PYTHONPATH="${HELPER_DIR}" "$POL_PY" -m playonline titles --plain 2>/dev/null); then
    exit 3
fi
pol_names=$(printf '%s\n' "$titles" | cut -d'|' -f2 | grep -E '^PP\.')
# An empty PlayOnline list means the table did not load; do not risk a wipe.
[ -n "$pol_names" ] || exit 3

{
    printf '%s\n' "$pol_names"

    # Direct-install titles that are not part of the PlayOnline package. Keep in
    # step with Nobunaga-Installer.sh, Mingol-Installer.sh, Popn-Installer.sh.
    printf '%s\n' \
        "PP.SLPM-65197.KOEI.NOBUON" \
        "PP.SCPS-15049..APPLICATION" \
        "PP.BLJA-00010"

    # Anything an installer or the user registered on the exFAT games partition.
    if [ -n "$OPL" ] && [ -f "${OPL}/protect-parts.list" ]; then
        cat "${OPL}/protect-parts.list"
    fi
} | sed 's/\r$//' | grep -E '^PP\.' | sort -u
