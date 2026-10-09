#!/usr/bin/env bash
#
# Boot debug text, shared by the title installers (Nobunaga, pop'n, Bomberman,
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
# Sourced by an installer after its lang file is read into UI_TEXT. Each title
# ships its boot loader twice, built from the same source and signed the same
# way: the silent one (the default, no text on the TV) and its FORK_VERBOSE
# twin, which prints every loader stage and stops with the reason when a stage
# fails (Bomberman: the SCREEN build, which prints its [boot]/[bb] lines and
# holds 5 s before the game). A player whose game does not boot answers Y,
# photographs the screen and sends the photo; running the step again with N
# puts the silent loader back.
#
# With Y the boot record (poltrace) is armed too where the loader has one: a
# tagged 512-byte trace.bin goes into the game partition and the loader's
# fill-time TRACELBA slot is pointed at its first sector (no re-signing; the
# slot lies in the KELF's unsigned content). The loader's atadpatch then writes
# what it saw while the game booted into that sector.
#
#   debugtext_ask                   once per run; sets DEBUG_TEXT=1 (Y) or 0 (N)
#   debugtext_pick SILENT VERBOSE   sets DEBUG_LOADER to the one to install,
#                                   in the variant for the console's region
#                                   (region.sh: region_pick; asks the console
#                                   region once per run when the drive does
#                                   not say it). Nobunaga passes the pair
#                                   for the install's language (English: the
#                                   input-patch loader, Japanese: the -ja
#                                   plain loader; nobu_debugtext)
#   debugtext_trace_arm DEVICE PARTITION MOUNT TAG [LOADER]
#                                   puts trace.bin, sets DEBUG_TRACE_LBA; with
#                                   LOADER (the staged dnasload.elf) also sets
#                                   its slot and puts it again as dnasload.elf
#
# DEBUG_TEXT=y or n in the environment answers the question without asking.
# Uses the caller's HELPER_DIR, LOG_FILE and PFS_SHELL (when set).

: "${UI_TEXT[DEBUG_TEXT_EXPLAIN1]:=Boot debug text: with Y, the console prints each step of the game start on the TV and stops with the reason if a step fails.}"
: "${UI_TEXT[DEBUG_TEXT_EXPLAIN2]:=It is for taking a photo of the screen when a game does not boot. With N (the default) the game starts with no text.}"
: "${UI_TEXT[DEBUG_TEXT_EXPLAIN3]:=You can run this step again at any time and answer N to turn the text off; your saves are kept.}"
: "${UI_TEXT[DEBUG_TEXT_ASK]:=Show boot debug text on the console? (y/N)}"
: "${UI_TEXT[DEBUG_TEXT_ON]:=Boot debug text is on. If the game does not boot, photograph the screen and send the photo.}"
: "${UI_TEXT[DEBUG_TEXT_NO_TWIN]:=The debug build of this loader is not in this toolkit, so the normal one (no text) is installed.}"
: "${UI_TEXT[DEBUG_TEXT_TRACE_ON]:=Boot record armed at drive sector}"
: "${UI_TEXT[DEBUG_TEXT_TRACE_FAIL]:=The boot record could not be armed on this drive (see the log); the text still shows.}"

source "${HELPER_DIR}/region.sh"

DEBUG_TEXT_ASKED=""
DEBUG_LOADER=""
DEBUG_TRACE_LBA=""

debugtext_ask() {
    [[ -n "${DEBUG_TEXT_ASKED}" ]] && return 0
    DEBUG_TEXT_ASKED=1
    local answer="${DEBUG_TEXT:-}"
    if [[ -z "${answer}" ]]; then
        echo
        echo "  ${UI_TEXT[DEBUG_TEXT_EXPLAIN1]}"
        echo "  ${UI_TEXT[DEBUG_TEXT_EXPLAIN2]}"
        echo "  ${UI_TEXT[DEBUG_TEXT_EXPLAIN3]}"
        printf "%s " "${UI_TEXT[DEBUG_TEXT_ASK]}"
        read -r answer </dev/tty
    fi
    case "${answer}" in
        [Yy1]*) DEBUG_TEXT=1 ;;
        *)      DEBUG_TEXT=0 ;;
    esac
    echo "debug text: ${DEBUG_TEXT}" >> "${LOG_FILE}"
    [[ "${DEBUG_TEXT}" == 1 ]] && echo "  ${UI_TEXT[DEBUG_TEXT_ON]}"
    echo
    return 0
}

debugtext_pick() {
    local silent="$1" verbose="$2"
    DEBUG_LOADER="${silent}"
    if [[ "${DEBUG_TEXT}" == 1 ]]; then
        if [[ -f "${verbose}" ]]; then
            DEBUG_LOADER="${verbose}"
        else
            echo "[!] debug text: no verbose twin at ${verbose}; installing ${silent}" >> "${LOG_FILE}"
            echo "  ${UI_TEXT[DEBUG_TEXT_NO_TWIN]}"
        fi
    fi
    region_pick "${DEBUG_LOADER}"
    DEBUG_LOADER="${REGION_LOADER}"
    echo "debug text: loader ${DEBUG_LOADER}" >> "${LOG_FILE}"
}

# The first sector of /trace.bin, read through the PFS reader (the zone map of
# the file itself, not a scan for the tag: a trace.bin removed earlier leaves
# its tagged sector behind as free space). -1 if it is not there or does not
# carry TAG.
debugtext_trace_lba() {
    local py="${SCRIPTS_DIR}/venv/bin/python3"
    [[ -x "${py}" ]] || py="python3"
    sudo env PYTHONPATH="${HELPER_DIR}" "${py}" - "$1" "$2" "$3" <<'PY'
import sys
from playonline.lib import pfsupdate
dev, part, tag = sys.argv[1], sys.argv[2], sys.argv[3].encode()
with pfsupdate.Installed(dev, part) as inst:
    ino = inst.files.get("trace.bin")
    if not ino or not ino["runs_full"]:
        print(-1)
        sys.exit(0)
    number, sub, _count = ino["runs_full"][0]
    lba = inst.part.zone_sector(number, sub)
    inst.f.seek(lba * 512)
    print(lba if inst.f.read(len(tag)) == tag else -1)
PY
}

debugtext_trace_arm() {
    local dev="$1" part="$2" mount="$3" tag="$4" loader="${5:-}"
    local pfs="${PFS_SHELL:-${HELPER_DIR}/PFS Shell.elf}"
    local slot_py="${HELPER_DIR}/nobunaga/tools/traceslot.py"
    local py="${SCRIPTS_DIR}/venv/bin/python3" tdir lba rc=0
    [[ -x "${py}" ]] || py="python3"
    DEBUG_TRACE_LBA=""
    # pfsshell's lcd takes the rest of the line as is: work in a folder with
    # no spaces in its path.
    tdir="$(mktemp -d)"
    "${py}" -c "import sys; t=sys.argv[2].encode(); open(sys.argv[1],'wb').write(t+bytes(512-len(t)))" \
        "${tdir}/trace.bin" "${tag}"
    printf 'device %s\nmount %s\nrm trace.bin\nlcd %s\nput trace.bin\numount\nexit\n' \
        "${dev}" "${mount}" "${tdir}" | sudo "${pfs}" >> "${LOG_FILE}" 2>&1
    sudo blockdev --flushbufs "${dev}" 2>/dev/null
    lba=$(debugtext_trace_lba "${dev}" "${part}" "${tag}" 2>>"${LOG_FILE}")
    if [[ -z "${lba}" || "${lba}" -le 0 ]]; then
        echo "[!] trace: /trace.bin not found in ${part} after the put; not armed." >> "${LOG_FILE}"
        rm -rf "${tdir}"
        return 1
    fi
    DEBUG_TRACE_LBA="${lba}"
    echo "trace: ${part}/trace.bin at LBA ${lba}" >> "${LOG_FILE}"

    if [[ -n "${loader}" ]]; then
        if [[ ! -f "${loader}" || ! -f "${slot_py}" ]]; then
            echo "[!] trace: loader ${loader} or traceslot.py missing; slot not set." >> "${LOG_FILE}"
            rc=1
        elif ! sudo "${py}" "${slot_py}" "${loader}" --set "${lba}" --check "${dev}" >> "${LOG_FILE}" 2>&1; then
            echo "[!] trace: traceslot --set ${lba} failed; slot not set." >> "${LOG_FILE}"
            rc=1
        else
            cp "${loader}" "${tdir}/dnasload.elf"
            printf 'device %s\nmount %s\nrm dnasload.elf\nlcd %s\nput dnasload.elf\numount\nexit\n' \
                "${dev}" "${mount}" "${tdir}" | sudo "${pfs}" >> "${LOG_FILE}" 2>&1
            sudo blockdev --flushbufs "${dev}" 2>/dev/null
            echo "trace: loader slot set to ${lba} and dnasload.elf put again" >> "${LOG_FILE}"
        fi
    fi
    rm -rf "${tdir}"
    return ${rc}
}
