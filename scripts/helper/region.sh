#!/usr/bin/env bash
#
# Console region, shared by the title installers (Nobunaga, pop'n, Bomberman,
# Minna) for the PSBBN Definitive Project
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
#
# Sourced by debugtext.sh (so by every title installer) after the lang file is
# read into UI_TEXT. Each title loader is a signed KELF, and a KELF's header
# carries a MagicGate region mask: a console opens it only when its own
# region's bit is set there, and checks before any loader code runs, so a
# loader without that bit drops straight back to the browser with nothing
# drawn. Each loader ships the way the PlayOnline step ships its own
# (PlayOnline-Installer.sh, the console question), one per console region,
# signed by scripts/helper/sign-region-loaders.py from the same content:
#
#   <name>.kelf       Japanese console   AppType 0x0B, zones 0x01
#   <name>-us.kelf    US console         AppType 0x0B, zones 0x02
#   <name>-all.kelf   any other console  AppType 0x01, zones 0xFF
#
# The answer is the PlayOnline step's: POL_CONSOLE in the environment, else
# the region the drive already says (the zone mask of the PlayOnline Viewer's
# loader, read by playonline.driveinfo; failing that, a US or all-regions
# title loader this toolkit put on the drive), else the PlayOnline step's own
# question. The loader a run installs carries the answer for the next run, as
# the Viewer's does. A Japanese-zoned title loader does not answer it: every
# install made before this file existed is Japanese-zoned whatever the console.
#
#   region_ask                 once per run; sets CONSOLE_REGION (jp, us or all)
#   region_pick KELF           sets REGION_LOADER to KELF's variant for
#                              CONSOLE_REGION; stops the installer when that
#                              variant is missing or does not open on that console
#   region_zones KELF          prints KELF's MGZones byte (decimal)
#
# Uses the caller's DEVICE, HELPER_DIR, SCRIPTS_DIR and LOG_FILE.

: "${UI_TEXT[POL_SELECT_CONSOLE]:=Which region is the PS2 console this drive will be used in: US, Japanese, or European and other? [U/j/e]}"
: "${UI_TEXT[REGION_EXPLAIN]:=The game loader opens only on the console region it was made for; on any other console the game returns to the browser and shows nothing.}"
: "${UI_TEXT[REGION_FROM_DRIVE]:=Console region (read from the drive):}"
: "${UI_TEXT[REGION_CHOSEN]:=Console region:}"
: "${UI_TEXT[REGION_MISSING]:=This toolkit has no loader for that console region. Update the toolkit and try again. Missing:}"
: "${UI_TEXT[REGION_WRONG_ZONE]:=This loader would not open on that console (it is made for another region), so nothing was installed:}"

CONSOLE_REGION="${CONSOLE_REGION:-}"
REGION_ASKED=""
REGION_LOADER=""

# The title partitions and the loader file each boots.
REGION_TITLE_LOADERS=(
    "PP.SLPM-65197.KOEI.NOBUON|dnasload.elf"
    "PP.BLJA-00010|dnasload.elf"
    "PP.SCPS-15049..APPLICATION|dnasload.elf"
    "PP.SLPS-20343.NET.BOMB|bombload.kelf"
)

region_zones() {
    od -An -tu1 -j28 -N1 "$1" 2>/dev/null | tr -d ' \n'
}

# The region the drive already says: "viewer <r>" from the PlayOnline Viewer's
# loader, or "title <r>" from a US or all-regions title loader. Read only.
region_from_drive() {
    [[ -n "${DEVICE}" ]] || return 0
    local py="${SCRIPTS_DIR}/venv/bin/python3"
    [[ -x "${py}" ]] || py="python3"
    sudo env PYTHONPATH="${HELPER_DIR}" "${py}" - "${DEVICE}" "${REGION_TITLE_LOADERS[@]}" <<'PY'
import sys
from playonline import apa, driveinfo
from playonline.lib import polfill, polnetdump, polpfsread
dev = sys.argv[1]
try:
    found = driveinfo.viewers(dev)
    if len(found) == 1:
        (_v, part), = found.items()
        c = driveinfo.loader_console(dev, part)
        if c:
            print("viewer %s" % c)
            sys.exit(0)
except Exception as e:
    print("viewer loader unreadable: %s" % e, file=sys.stderr)
names = {p.ident for p in apa.partitions(dev)}
for spec in sys.argv[2:]:
    part, name = spec.split("|")
    if part not in names:
        continue
    try:
        lba, sectors = apa.find_partition(dev, part)
        with open(dev, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            p, root = polpfsread.mount(f, lba, sectors,
                                       polnetdump.sub_partitions(f, size).get(lba))
            if p is None:
                continue
            for n, inode, sub, _fl in polfill.read_dir_full(p, root):
                if n == name.encode():
                    ino = polfill.read_inode(p, inode, sub)
                    head = polfill.read_content(p, ino)[:0x20] if ino["ok"] else b""
                    c = {0x02: "us", 0xFF: "all"}.get(head[0x1C]) if len(head) > 0x1C else None
                    if c:
                        print("title %s" % c)
                        sys.exit(0)
    except Exception as e:
        print("%s loader unreadable: %s" % (part, e), file=sys.stderr)
PY
}

region_ask() {
    [[ -n "${REGION_ASKED}" ]] && return 0
    REGION_ASKED=1
    local answer src="" got
    if [[ -n "${POL_CONSOLE:-}" ]]; then
        CONSOLE_REGION="${POL_CONSOLE}"
        src="POL_CONSOLE"
    elif [[ -z "${CONSOLE_REGION}" ]]; then
        [[ -n "${DEVICE}" ]] && sudo blockdev --flushbufs "${DEVICE}" >/dev/null 2>&1
        got=$(region_from_drive 2>>"${LOG_FILE}" | tr -d '\r' | tail -n 1)
        if [[ -n "${got}" ]]; then
            CONSOLE_REGION="${got#* }"
            src="drive (${got% *} loader)"
            echo "  ${UI_TEXT[REGION_FROM_DRIVE]} ${CONSOLE_REGION}"
        fi
    fi
    if [[ -z "${CONSOLE_REGION}" ]]; then
        echo
        echo "  ${UI_TEXT[REGION_EXPLAIN]}"
        printf "%s " "${UI_TEXT[POL_SELECT_CONSOLE]}"
        read -r answer </dev/tty
        case "$answer" in
            [Jj]*) CONSOLE_REGION=jp ;;
            [Ee]*) CONSOLE_REGION=all ;;
            *)     CONSOLE_REGION=us ;;
        esac
        src="asked"
        echo "  ${UI_TEXT[REGION_CHOSEN]} ${CONSOLE_REGION}"
    fi
    # As the PlayOnline step: a European console gets the all-regions loader.
    case "${CONSOLE_REGION}" in
        [Jj]*) CONSOLE_REGION=jp ;;
        [Uu]*) CONSOLE_REGION=us ;;
        *)     CONSOLE_REGION=all ;;
    esac
    echo "console region: ${CONSOLE_REGION} (${src:-set by the caller})" >> "${LOG_FILE}"
    return 0
}

region_fail() {
    echo "[X] region: $*" >> "${LOG_FILE}"
    if declare -F error_msg >/dev/null; then
        error_msg "$*"
    fi
    echo "[X] $*"
    exit 1
}

region_pick() {
    local kelf="$1" base want zones
    REGION_LOADER="${kelf}"
    # No loader at all: the caller says so itself (and installs without one).
    [[ -f "${kelf}" ]] || return 0
    region_ask
    base="${kelf%.kelf}"
    REGION_LOADER="${base}-${CONSOLE_REGION}.kelf"
    # The Japanese one is the file without a suffix (as polbbnexec.kelf is).
    if [[ "${CONSOLE_REGION}" == jp && ! -f "${REGION_LOADER}" ]]; then
        REGION_LOADER="${kelf}"
    fi
    if [[ ! -f "${REGION_LOADER}" ]]; then
        region_fail "${UI_TEXT[REGION_MISSING]} ${REGION_LOADER}"
    fi
    # Never a Japan-only loader for another console, whatever the file is named.
    zones=$(region_zones "${REGION_LOADER}")
    case "${CONSOLE_REGION}" in
        jp)  want=1 ;;
        us)  want=2 ;;
        *)   want=255 ;;
    esac
    if [[ -z "${zones}" ]] || (( (zones & want) != want )); then
        region_fail "${UI_TEXT[REGION_WRONG_ZONE]} ${REGION_LOADER} (zones ${zones:-?}, ${CONSOLE_REGION})"
    fi
    echo "region: loader ${REGION_LOADER} (zones ${zones})" >> "${LOG_FILE}"
}
