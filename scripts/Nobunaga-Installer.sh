#!/usr/bin/env bash
#
# Nobunaga's Ambition Online Installer for the PSBBN Definitive Project
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
# Prepares a PSBBN drive for Nobunaga no Yabou Online, Hiryuu no Shou
# (SLPM-65783), from the Extras menu.
#
# The game cannot be installed from the PC the way the PlayOnline titles are:
# its files are Sony DNAS2 containers, and only Koei's own installer, running
# on the console, turns the disc's form into the drive's. So this step checks
# the drive, keeps a copy of what the console install could disturb, and makes
# __net openable. See scripts/helper/nobunaga.
#
# It is written to sit beside the PlayOnline step without touching it: it only
# reads the playonline package, never mints or changes the PlayOnline drive
# ID, and on a drive that already has PlayOnline it writes nothing the
# PlayOnline step would not.

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
LOG_FILE="${LOGS_DIR}/nobunaga-installer.log"
GAMES_PATH="${TOOLKIT_PATH}/games"
WORK_DIR="${SCRIPTS_DIR}/tmp/nobunaga"

arch="$(uname -m)"
if [[ "$arch" = "x86_64" ]]; then
    HDL_DUMP="${HELPER_DIR}/HDL Dump.elf"
else
    HDL_DUMP="${HELPER_DIR}/aarch64/HDL Dump.elf"
fi

LANG_FILE="$1"
shift
path_arg=""
[[ -n "$1" && "$1" == /* ]] && path_arg="$1"
# Extras has already found the drive and passes it on.
DEVICE="${2:-}"

# The folder the user can reach, as the PlayOnline step uses games/POL. The
# __net record backups go here, because on a Windows install the toolkit's own
# folder is inside WSL, and these are the files someone may need to find.
NOBU_DIR="${GAMES_PATH}/NOBU"
[[ -n "${path_arg}" ]] && NOBU_DIR="${path_arg}/NOBU"
[[ -n "${NOBU_DIR_OVERRIDE}" ]] && NOBU_DIR="${NOBU_DIR_OVERRIDE}"
# The PlayOnline step's drive ID, when that step has run. Read, never written.
POL_HDDID_FILE="${POL_HDDID:-$(dirname "${NOBU_DIR}")/POL/playonline.hddid}"

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

    _   __      __                                     ____        ___
   / | / /___  / /_  __  ______  ____ _____ _____ _   / __ \____  / (_)___  ___
  /  |/ / __ \/ __ \/ / / / __ \/ __ `/ __ `/ __ `/  / / / / __ \/ / / __ \/ _ \
 / /|  / /_/ / /_/ / /_/ / / / / /_/ / /_/ / /_/ /  / /_/ / / / / / / / / /  __/
/_/ |_/\____/_.___/\__,_/_/ /_/\__,_/\__, /\__,_/   \____/_/ /_/_/_/_/ /_/\___/
                                    /____/

EOF
}

# The venv's python3, named outright because sudo resets PATH, as in the
# PlayOnline step.
NOBU_PY="${SCRIPTS_DIR}/venv/bin/python3"
[[ -x "${NOBU_PY}" ]] || NOBU_PY="python3"
nobusudo() { local m="$1"; shift; sudo -E env PYTHONPATH="${HELPER_DIR}" "${NOBU_PY}" -m "$m" "$@"; }

on_exit() {
    [[ -n "${SUDO_KEEPALIVE}" ]] && kill "${SUDO_KEEPALIVE}" 2>/dev/null
    return 0
}
trap on_exit EXIT

SPLASH
center_text "${UI_TEXT[NOBU_TITLE]}"
echo
echo "=== run $(date) ===" >> "${LOG_FILE}"

# Reading __net's passwords needs pycryptodome, which a venv made by an older
# Setup.sh lacks. The PlayOnline step installs it the same way.
"${NOBU_PY}" -c "import Crypto" 2>/dev/null || "${NOBU_PY}" -m pip install pycryptodome >> "${LOG_FILE}" 2>&1 || {
    echo "[X] Error: could not install pycryptodome into the venv." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[ERROR_ACTIVATE_PYTHON]}"
}
sudo -v || error_msg "${UI_TEXT[NOBU_ERROR_SUDO]}"
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
# Only this drive's own OPL partition, so that with two PSBBN drives
# connected the UUID is never another drive's.
line=$(awk -F: -v d="${DEVICE}" '$1 ~ ("^" d "p?[0-9]+$")' <<< "${opl_lines}" | head -1)
if [[ -z "${DEVICE}" ]]; then
    echo "[X] Error: no PSBBN drive found." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[NOBU_ERROR_NO_DEVICE]}"
fi
# The exFAT partition's UUID names this drive's backup folder, so the record
# saved from one drive is never compared with another's.
DRIVE_UUID=$(grep -o ' UUID="[^"]*"' <<< "$line" | head -1 | cut -d'"' -f2)
BACKUP_DIR="${NOBU_DIR}/backups/${DRIVE_UUID:-$(basename "${DEVICE}")}"
echo "Device: ${DEVICE} (UUID ${DRIVE_UUID:-none}), backups ${BACKUP_DIR}" >> "${LOG_FILE}"

if ! sudo "${HDL_DUMP}" toc "${DEVICE}" >> "${LOG_FILE}" 2>&1; then
    error_msg "${UI_TEXT[ERROR_HDL_TOC]}"
fi

echo "${UI_TEXT[NOBU_CHECKING]}"
echo
declare -A INFO
check_out=$(nobusudo nobunaga.check "${DEVICE}" --plain 2>>"${LOG_FILE}") \
    || error_msg "${UI_TEXT[NOBU_ERROR_READ]}"
check_out="${check_out//$'\r'/}"
while IFS='=' read -r key value; do
    [[ -n "$key" ]] && INFO["$key"]="$value"
done <<< "${check_out}"
nobusudo nobunaga.check "${DEVICE}" 2>>"${LOG_FILE}" | tee -a "${LOG_FILE}"
echo

[[ "${INFO[system]}" == "1" ]] || error_msg "${UI_TEXT[NOBU_ERROR_NOT_PS2]}"

# The console-side step will serve the drive the same ID the PlayOnline
# titles are keyed to, because a console is served one ID per drive. It is
# only reported here; minting it is the PlayOnline step's.
if [[ -f "${POL_HDDID_FILE}" ]]; then
    echo "  ${UI_TEXT[NOBU_HDDID_FOUND]} ${POL_HDDID_FILE}"
else
    echo "  ${UI_TEXT[NOBU_HDDID_NONE]}"
fi
echo "HDD ID: ${POL_HDDID_FILE} $([[ -f "${POL_HDDID_FILE}" ]] && echo found || echo absent)" >> "${LOG_FILE}"
echo

# ---- already installed: check the record --------------------------------
if [[ -n "${INFO[installed]}" ]]; then
    center_text "${UI_TEXT[NOBU_INSTALLED]}"
    echo
    if [[ ! -f "${BACKUP_DIR}/net-record-before-nobunaga.json" ]]; then
        echo "  ${UI_TEXT[NOBU_RECORD_NO_BACKUP]}"
    elif nobusudo nobunaga.record "${DEVICE}" --compare "${BACKUP_DIR}" >> "${LOG_FILE}" 2>&1; then
        echo "  ${UI_TEXT[NOBU_RECORD_SAME]}"
    else
        echo "  ${UI_TEXT[NOBU_RECORD_CHANGED]}"
        echo
        printf "%s " "${UI_TEXT[NOBU_RECORD_ASK]}"
        read -r answer </dev/tty
        case "$answer" in
            [Yy]*)
                nobusudo nobunaga.record "${DEVICE}" --restore "${BACKUP_DIR}" --write \
                    >> "${LOG_FILE}" 2>&1 || error_msg "${UI_TEXT[NOBU_ERROR_RECORD]}"
                echo "  ${UI_TEXT[NOBU_RECORD_RESTORED]}"
                ;;
        esac
    fi
    echo
    read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
    echo
    exit 0
fi

# ---- not installed: prepare ---------------------------------------------
[[ "${INFO[fits]}" == "1" ]] || error_msg "${UI_TEXT[NOBU_NO_ROOM]}"

echo "${UI_TEXT[NOBU_PLAN]}"
echo "  - ${UI_TEXT[NOBU_PLAN_RECORD]}"
[[ "${INFO[net]}" != "ok" ]] && echo "  - ${UI_TEXT[NOBU_PLAN_NET]}"
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

# The record first, before anything else can change it. The first copy on a
# drive is kept apart and never replaced (see record.py).
if [[ "${INFO[net]}" != "absent" ]]; then
    mkdir -p "${BACKUP_DIR}" || error_msg "${UI_TEXT[NOBU_ERROR_RECORD]}"
    nobusudo nobunaga.record "${DEVICE}" --save "${BACKUP_DIR}" 2>&1 \
        | tee -a "${LOG_FILE}" | sed 's/^/  /'
    [[ ${PIPESTATUS[0]} -eq 0 ]] || error_msg "${UI_TEXT[NOBU_ERROR_RECORD]}"
    # sudo wrote them; give them to the user, who may need to send them on.
    sudo chown -R "$(id -u):$(id -g)" "${NOBU_DIR}/backups" 2>/dev/null
fi

# The PlayOnline step's own __net preparation, which it runs on every pass:
# on a drive that step has prepared it changes nothing.
if [[ "${INFO[net]}" != "ok" ]]; then
    nobusudo playonline.netpart "${DEVICE}" --write \
        --backup "${WORK_DIR}/apa-before-net-$(date +%Y%m%d-%H%M%S).json" \
        >> "${LOG_FILE}" 2>&1 || error_msg "${UI_TEXT[NOBU_ERROR_NET]}"
fi

echo
center_text "${UI_TEXT[NOBU_READY]}"
[[ "${INFO[netcnf]}" == "present" ]] || center_text "${UI_TEXT[NOBU_NETCNF_MISSING]}"
center_text "${UI_TEXT[NOBU_CONSOLE_PENDING]}"
echo
center_text "${UI_TEXT[NOBU_BACKUPS]} ${BACKUP_DIR}"
echo
read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
echo
