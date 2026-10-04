#!/usr/bin/env bash
#
# Net de Bomberman Installer for the PSBBN Definitive Project
# Copyright (C) 2026 PrettyOpenLobby
#
# <https://github.com/CosmicScale/PSBBN-Definitive-Project>
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
# Installs Net de Bomberman (SLPS-20343) onto the drive from the Extras menu.
#
# One partition, exactly like a genuine install: the game partition is also
# the boot. The genuine Nobunaga partition boots via `BOOT2 = pfs:/dnasload.elf`;
# ours boots `BOOT2 = pfs:/bombload.kelf` - a multi-block MG-signed KELF that
# HDD-OSD accepts (see bomb/tools/bombkelf.py; block layout mirrors Sony's
# dnasload). bombload.elf and the original BOMBBOOT.ELF, DNAS280.IMG and the
# four Sony drive IRXs sit beside it in the partition root. The browser
# shows one entry; it boots with no disc.
#
# The user supplies, under games/BOMB/:
#   the disc    SLPS-20343 as a Redump .bin/.cue or an .iso (here or in disc/);
#               the installer unpacks and seals it itself (bomb/bombdisc.py).
#               A prebuilt drive-neutral tree at install/ is used instead if
#               present.
#   optional:   bomberman.ico (the browser icon; the game boots without it)
# boot/ comes with the toolkit. See scripts/helper/bomb for the engine.

[[ -t 0 && -t 1 ]] || exit 1

if [[ "$LAUNCHED_BY_MAIN" != "1" ]]; then
    echo "This script should not be run directly. Please run: PSBBN-Definitive-Patch.sh"
    exit 1
fi

term_width=110

TOOLKIT_PATH="$(pwd)"
SCRIPTS_DIR="${TOOLKIT_PATH}/scripts"
HELPER_DIR="${SCRIPTS_DIR}/helper"
ASSETS_DIR="${SCRIPTS_DIR}/assets"
LANG_DIR="${ASSETS_DIR}/lang"
LOGS_DIR="${TOOLKIT_PATH}/logs"
LOG_FILE="${LOGS_DIR}/bomb-installer.log"
GAMES_PATH="${TOOLKIT_PATH}/games"
BOMB_FILES="${SCRIPTS_DIR}/assets/bomb"
WORK_DIR="${SCRIPTS_DIR}/tmp/bomb"

arch="$(uname -m)"
if [[ "$arch" = "x86_64" ]]; then
    PFS_SHELL="${HELPER_DIR}/PFS Shell.elf"
else
    PFS_SHELL="${HELPER_DIR}/aarch64/PFS Shell.elf"
fi

LANG_FILE="$1"
shift
path_arg=""
[[ -n "$1" && "$1" == /* ]] && path_arg="$1"
DEVICE="${2:-}"

BOMB_DIR="${GAMES_PATH}/BOMB"
[[ -n "${path_arg}" ]] && BOMB_DIR="${path_arg}/BOMB"
[[ -n "${BOMB_DIR_OVERRIDE}" ]] && BOMB_DIR="${BOMB_DIR_OVERRIDE}"
# The PlayOnline step's drive ID, when that step has run. Read, never written.
POL_HDDID_FILE="${POL_HDDID:-$(dirname "${BOMB_DIR}")/POL/playonline.hddid}"

declare -A UI_TEXT

if [[ -f "${LANG_DIR}/$LANG_FILE.txt" ]]; then
    while IFS='=' read -r key value; do
        [[ -z "$key" ]] && continue
        UI_TEXT["$key"]="$value"
    done < "${LANG_DIR}/$LANG_FILE.txt"
else
    echo "[X] Error: Language file not found."
    sleep 3
    exit 1
fi

# English fallbacks for the disc-path strings so a lang file without them
# still shows English rather than a bare key.
: "${UI_TEXT[BOMB_DISC_HINT]:=Put the SLPS-20343 disc image (.bin/.cue or .iso) in this folder.}"
: "${UI_TEXT[BOMB_EXTRACT_FOUND]:=Found the disc image:}"
: "${UI_TEXT[BOMB_EXTRACT_RUNNING]:=Unpacking the game from the disc...}"
: "${UI_TEXT[BOMB_EXTRACT_FAIL]:=Could not unpack the game from the disc image. See logs/bomb-installer.log.}"

mkdir -p "${LOGS_DIR}" "${WORK_DIR}"

text_width() { echo -n "$1" | wc -L; }

center_text() {
    local w; w=$(text_width "$1")
    printf "%*s%s\n" $(( (term_width - w) / 2 )) "" "$1"
}

error_msg() {
    echo
    center_text "$1"
    echo
    read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
    echo
    exit 1
}

SPLASH() {
    clear
    cat << "EOF"

     ____  ___   ____  __  __ ___    ____  __  __  ___  ____
    | __ ) / _ \ | __ )|  \/  |_ _|  | __ )|  \/  |/ _ \|  _ \
    |  _ \| | | ||  _ \| |\/| || |   |  _ \| |\/| | | | | |_) |
    | |_) | |_| || |_) | |  | || |   | |_) | |  | | |_| |  _ <
    |____/ \___/ |____/|_|  |_|___|  |____/|_|  |_|\___/|_| \_\

EOF
}

# The venv's python3, named outright because sudo resets PATH, as in the
# PlayOnline step.
BOMB_PY="${SCRIPTS_DIR}/venv/bin/python3"
[[ -x "${BOMB_PY}" ]] || BOMB_PY="python3"
bombsudo() { local m="$1"; shift; sudo -E env PYTHONPATH="${HELPER_DIR}" "${BOMB_PY}" -m "$m" "$@"; }

# BOMBBOOT's DNAS step reads the access_flag25 boot record at __net+0x202000
# and fails (-101, a black screen after the loader) when it is not there. It
# is the same record Nobunaga needs, keyed to the console i.Link the loader's
# scefix reports to the DNAS side, so Nobunaga's tool writes it: only that
# record, after backing up what is there, leaving the shared PlayOnline record
# at +0x201800 untouched. Run on every pass, so a drive installed before this
# gets it too. See nobunaga/accessflag.py.
bomb_accessflag() {
    local backup="${BOMB_DIR}/backups/$(basename "${DEVICE}")"
    mkdir -p "${backup}"
    if bombsudo nobunaga.accessflag "${DEVICE}" --write --save "${backup}"         >> "${LOG_FILE}" 2>&1; then
        echo "  DNAS boot record in place (__net+0x202000); the PlayOnline record is untouched."
    else
        echo "  [!] could not write the DNAS boot record; see logs/bomb-installer.log"
    fi
}

on_exit() {
    [[ -n "${SUDO_KEEPALIVE}" ]] && kill "${SUDO_KEEPALIVE}" 2>/dev/null
    return 0
}
trap on_exit EXIT

SPLASH
center_text "${UI_TEXT[BOMB_TITLE]}"
echo
echo "=== run $(date) ===" >> "${LOG_FILE}"

"${BOMB_PY}" -c "import Crypto" 2>/dev/null || "${BOMB_PY}" -m pip install pycryptodome >> "${LOG_FILE}" 2>&1 || {
    echo "[X] Error: could not install pycryptodome into the venv." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[ERROR_ACTIVATE_PYTHON]}"
}
sudo -v || error_msg "${UI_TEXT[BOMB_ERROR_SUDO]}"
( while true; do
      sleep 50
      kill -0 "$$" 2>/dev/null || exit
      sudo -n true 2>/dev/null || exit
  done ) &
SUDO_KEEPALIVE=$!

# ---- the drive ----------------------------------------------------------
opl_lines=$(sudo blkid -t TYPE=exfat 2>/dev/null | grep OPL)
if [[ -z "${DEVICE}" ]]; then
    DEVICE=$(head -1 <<< "${opl_lines}" | awk -F: '{print $1}' | sed 's/[0-9]*$//')
fi
line=$(awk -F: -v d="${DEVICE}" '$1 ~ ("^" d "p?[0-9]+$")' <<< "${opl_lines}" | head -1)
if [[ -z "${DEVICE}" ]]; then
    echo "[X] Error: no PSBBN drive found." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[BOMB_ERROR_NO_DEVICE]}"
fi
DRIVE_UUID=$(grep -o ' UUID="[^"]*"' <<< "$line" | head -1 | cut -d'"' -f2)
echo "Device: ${DEVICE} (UUID ${DRIVE_UUID:-none})" >> "${LOG_FILE}"

if ! sudo "${HDL_DUMP}" toc "${DEVICE}" >> "${LOG_FILE}" 2>&1; then
    error_msg "${UI_TEXT[ERROR_HDL_TOC]}"
fi

# ---- the user's files ---------------------------------------------------
# Preferred: the disc itself. bombdisc unpacks DATA/FULL.BIN straight from
# the image (Redump .bin/.cue or .iso, in games/BOMB/ or games/BOMB/disc/; an
# extracted disc folder at games/BOMB/disc/ works too) and bombinstall --disc
# seals its containers offline. BOMB_DISC_IMAGE picks an image explicitly.
# A prebuilt neutral tree at games/BOMB/install/ is still taken when present.
BUNDLE_DIR="${BOMB_DIR}/install"
DISC_ARG=()
if [[ -z "$(find "${BUNDLE_DIR}" -type f -print -quit 2>/dev/null)" ]]; then
    BOMB_IMG="${BOMB_DISC_IMAGE:-}"
    if [[ -z "${BOMB_IMG}" ]]; then
        for cand in "${BOMB_DIR}"/*.bin "${BOMB_DIR}"/*.BIN "${BOMB_DIR}"/*.iso "${BOMB_DIR}"/*.ISO \
                    "${BOMB_DIR}"/disc/*.bin "${BOMB_DIR}"/disc/*.BIN "${BOMB_DIR}"/disc/*.iso "${BOMB_DIR}"/disc/*.ISO; do
            [[ -f "$cand" ]] && { BOMB_IMG="$cand"; break; }
        done
    fi
    [[ -z "${BOMB_IMG}" && -f "${BOMB_DIR}/disc/DATA/FULL.BIN" ]] && BOMB_IMG="${BOMB_DIR}/disc"
    if [[ -z "${BOMB_IMG}" ]]; then
        echo "[X] Error: no disc image or install tree in ${BOMB_DIR}." >> "${LOG_FILE}"
        error_msg "$(printf '%s %s\n%s' "${UI_TEXT[BOMB_NO_INSTALL]}" "${BOMB_DIR}" "${UI_TEXT[BOMB_DISC_HINT]}")"
    fi
    echo "  ${UI_TEXT[BOMB_EXTRACT_FOUND]} $(basename "${BOMB_IMG}")"
    echo "  ${UI_TEXT[BOMB_EXTRACT_RUNNING]}"
    BUNDLE_DIR="${WORK_DIR}/disctree"
    PYTHONPATH="${HELPER_DIR}" "${BOMB_PY}" -m bomb.bombdisc "${BOMB_IMG}" "${BUNDLE_DIR}" \
        --pem "${BOMB_FILES}/BOMBREG.PEM" \
        --tsv "${BOMB_FILES}/msg_FILES_install.en.tsv" >> "${LOG_FILE}" 2>&1 \
        || error_msg "${UI_TEXT[BOMB_EXTRACT_FAIL]}"
    DISC_ARG=(--disc)
    echo
fi

# ---- the served drive ID ------------------------------------------------
# With the PlayOnline shim the console serves playonline.hddid verbatim, and
# that file is everything the seal needs. Without it there is no automatic
# read (hdl_dump's hdd_id output is not the raw block): the user saves the
# drive's 512-byte ATA IDENTIFY page as bomberman.hddid themselves.
if [[ -f "${POL_HDDID_FILE}" ]]; then
    HDDID_FILE="${POL_HDDID_FILE}"
    echo "  ${UI_TEXT[BOMB_HDDID_FOUND]} ${HDDID_FILE}"
elif [[ -f "${BOMB_DIR}/bomberman.hddid" ]]; then
    HDDID_FILE="${BOMB_DIR}/bomberman.hddid"
    echo "  ${UI_TEXT[BOMB_HDDID_OWN]} ${HDDID_FILE}"
else
    echo "[X] Error: no served drive ID." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[BOMB_HDDID_FAIL]} ${BOMB_DIR}/bomberman.hddid"
fi
echo "HDD ID: ${HDDID_FILE}" >> "${LOG_FILE}"
echo

# ---- the icon (optional) ------------------------------------------------
ICON_ARG=()
if [[ -f "${BOMB_DIR}/bomberman.ico" ]]; then
    ICON_ARG=(--icon "${BOMB_DIR}/bomberman.ico")
elif [[ -f "${BOMB_FILES}/bomberman.ico" ]]; then
    ICON_ARG=(--icon "${BOMB_FILES}/bomberman.ico")
else
    echo "  ${UI_TEXT[BOMB_NO_ICON]}"
fi

# ---- installed check ----------------------------------------------------
if sudo "${HDL_DUMP}" toc "${DEVICE}" 2>>"${LOG_FILE}" | grep -q -- "PP.SLPS-20343.NET.BOMB"; then
    center_text "${UI_TEXT[BOMB_INSTALLED]}"
    echo
    bomb_accessflag
    echo
    read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
    echo
    exit 0
fi

# ---- the plan -----------------------------------------------------------
center_text "${UI_TEXT[BOMB_PLAN]}"
echo "  - ${UI_TEXT[BOMB_PLAN_SEAL]}"
echo "  - ${UI_TEXT[BOMB_PLAN_GAME]}"
echo
center_text "${UI_TEXT[NOBU_PLAN_UNTOUCHED]}"
echo
printf "%s " "${UI_TEXT[NOBU_CONFIRM]}"
read -r answer </dev/tty
case "$answer" in
    [Yy]*) ;;
    *) echo; echo "${UI_TEXT[NOBU_ABORTED]}"; sleep 2; exit 0 ;;
esac
echo

# ---- install ------------------------------------------------------------
echo "${UI_TEXT[BOMB_DOING]}"
echo
bombsudo bomb.bombinstall "${DEVICE}" \
    --bundle "${BUNDLE_DIR}" \
    "${DISC_ARG[@]}" \
    --boot "${BOMB_FILES}/bootfiles" \
    --hddid "${HDDID_FILE}" \
    --pfsshell "${PFS_SHELL}" \
    --helper "${HELPER_DIR}" \
    --work "${WORK_DIR}/stage" \
    "${ICON_ARG[@]}" \
    --write 2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
[[ ${PIPESTATUS[0]} -eq 0 ]] || error_msg "${UI_TEXT[BOMB_ERROR_INSTALL]}"
bomb_accessflag

echo
center_text "${UI_TEXT[BOMB_DONE]}"
echo
center_text "${UI_TEXT[BOMB_DONE_HINT]}"
echo
read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
echo
