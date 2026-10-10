#!/usr/bin/env bash
#
# HDD Games menu for the PSBBN Definitive Project
# Copyright (C) 2024-2026 CosmicScale
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

[[ -t 0 && -t 1 ]] || exit 1

if [[ "$LAUNCHED_BY_MAIN" != "1" ]]; then
    echo "This script should not be run directly. Please run: PSBBN-Definitive-Patch.sh"
    exit 1
fi

term_width=110

# Set paths
TOOLKIT_PATH="$(pwd)"
SCRIPTS_DIR="${TOOLKIT_PATH}/scripts"
HELPER_DIR="${SCRIPTS_DIR}/helper"
ASSETS_DIR="${SCRIPTS_DIR}/assets"
LANG_DIR="${ASSETS_DIR}/lang"
STORAGE_DIR="${SCRIPTS_DIR}/storage"
LOG_FILE="${TOOLKIT_PATH}/logs/hddgames.log"

FIX_TOOL="${HELPER_DIR}/nobunaga/tools/netcnf_fix.py"

arch="$(uname -m)"

if [[ "$arch" = "x86_64" ]]; then
    HDL_DUMP="${HELPER_DIR}/HDL Dump.elf"
    PFS_SHELL="${HELPER_DIR}/PFS Shell.elf"
elif [[ "$arch" = "aarch64" ]]; then
    HDL_DUMP="${HELPER_DIR}/aarch64/HDL Dump.elf"
    PFS_SHELL="${HELPER_DIR}/aarch64/PFS Shell.elf"
fi

LANG_FILE="$1"
shift  # remove language
path_arg="$1"

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

text_width() {
    python3 -c '
from wcwidth import wcswidth
import sys
print(wcswidth(sys.argv[1]))
' "$1"
}

center_title() {
    local text=" $1 "

    local text_len
    text_len=$(text_width "$text")

    local total_padding=$(( term_width - text_len ))
    (( total_padding < 0 )) && total_padding=0

    local left_padding=$(( total_padding / 2 ))
    local right_padding=$(( total_padding - left_padding ))

    printf '%*s' "$left_padding" '' | tr ' ' '='
    printf '%s' "$text"
    printf '%*s\n' "$right_padding" '' | tr ' ' '='
}

center_text() {
    local text="$1"
    local text_len
    text_len=$(text_width "$text")
    local left_padding=$(( (term_width - text_len) / 2 ))
    (( left_padding < 0 )) && left_padding=0
    printf '%*s%s\n' "$left_padding" '' "$text"
}

center_menu() {
    local longest=0
    for key in "${MENU_KEYS[@]}"; do
        local text="${UI_TEXT[$key]}"
        local width=$(text_width "$text")
        (( width > longest )) && longest=$width
    done
    padding=$(( (term_width - longest + 3) / 2 ))
}

error_msg() {
  error_1="$1"
  error_2="$2"
  error_3="$3"
  error_4="$4"

  echo
  echo "[X]" "$error_1"
  [ -n "$error_2" ] && echo && echo "$error_2"
  [ -n "$error_3" ] && echo "$error_3"
  [ -n "$error_4" ] && echo "$error_4"
  echo
  echo "${UI_TEXT[ERROR_TROUBLE]}"
  echo "${UI_TEXT[TROUBLE_URL]}"
  echo
  read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
  echo
}

HDD_GAMES_SPLASH() {
    clear
    cat << "EOF"

                    _   _ ____  ____     ____
                   | | | |  _ \|  _ \   / ___| __ _ _ __ ___   ___  ___
                   | |_| | | | | | | | | |  _ / _` | '_ ` _ \ / _ \/ __|
                   |  _  | |_| | |_| | | |_| | (_| | | | | | |  __/\__ \
                   |_| |_|____/|____/   \____|\__,_|_| |_| |_|\___||___/



EOF
}

clean_up() {
    sudo rm -rf "${SCRIPTS_DIR}/tmp"
    if [ -d "${STORAGE_DIR}" ]; then
        sudo rm -rf "${STORAGE_DIR}" 2>>"${LOG_FILE}"
    fi
}

exit_script() {
    clean_up
    if [[ -n "$path_arg" ]]; then
        cp "${LOG_FILE}" "${path_arg}" > /dev/null 2>&1
    fi
}

detect_drive() {
    DEVICE=$(sudo blkid -t TYPE=exfat | grep OPL | awk -F: '{print $1}' | sed 's/[0-9]*$//')

    if [[ -z "$DEVICE" ]]; then
        echo "[X] Error: Unable to detect the PS2 drive" >> "${LOG_FILE}"
        echo "[X] ${UI_TEXT[ERROR_DETECT_DRIVE_1]}"
        echo
        echo "${UI_TEXT[ERROR_DETECT_DRIVE_4]}"
        echo
        read -n 1 -s -r -p "${UI_TEXT[MENU_RETURN]}" </dev/tty
        return 1
    fi

    echo "OPL partition found on $DEVICE" >> "${LOG_FILE}"

    mounted_volumes=$(lsblk -ln -o MOUNTPOINT "$DEVICE" | grep -v "^$")
    echo "Unmounting volumes associated with $DEVICE..." >> "${LOG_FILE}"
    for mount_point in $mounted_volumes; do
        echo "Unmounting $mount_point..." >> "${LOG_FILE}"
        if sudo umount "$mount_point"; then
            echo "[✓] Successfully unmounted $mount_point." >> "${LOG_FILE}"
        else
            echo
            echo "[X] Error: Failed to unmount: $mount_point" >> "${LOG_FILE}"
            error_msg "${UI_TEXT[ERROR_UNMOUNT_1]} $mount_point"
            return 1
        fi
    done

    if ! sudo "${HDL_DUMP}" toc $DEVICE >> "${LOG_FILE}" 2>&1; then
        echo "[X] Error: Failed to extract list of partitions. APA partition table could be broken on ${DEVICE}" >> "${LOG_FILE}"
        error_msg "${UI_TEXT[ERROR_HDL_TOC]}"
        return 1
    else
        echo "PS2 HDD detected as $DEVICE" >> "${LOG_FILE}"
    fi
}

HDL_TOC() {
    rm -f "$hdl_output"
    hdl_output=$(mktemp)
    if ! sudo "${HDL_DUMP}" toc "$DEVICE" 2>>"${LOG_FILE}" > "$hdl_output"; then
        rm -f "$hdl_output"
        echo "[X] Error: Failed to extract list of partitions. APA partition table could be broken on ${DEVICE}" >> "${LOG_FILE}"
        error_msg "${UI_TEXT[ERROR_HDL_TOC]}"
        return 1
    fi
}

CHECK_PARTITIONS() {
    mapfile -t names < <(grep -E '^0x0[01][0-9A-Fa-f]{2}' "${hdl_output}" | awk '{print $NF}')

    has_all() {
        local targets=("$@")
        for t in "${targets[@]}"; do
            local found=false
            for n in "${names[@]}"; do
                if [[ "$n" == "$t" ]]; then
                    found=true
                    break
                fi
            done
            $found || return 1
        done
        return 0
    }

    psbbn_parts=(__linux.1 __linux.4 __linux.5 __linux.6 __linux.7 __linux.8 __linux.9 __contents)
    hosd_parts=(__system __sysconf __common)

    if has_all "${psbbn_parts[@]}"; then
        echo "PSBBN Detected" >> "${LOG_FILE}"
        OS="PSBBN"
    elif has_all "${hosd_parts[@]}"; then
        echo "HOSDMenu Detected" >> "${LOG_FILE}"
        OS="HOSD"
    else
        echo "[X] Error: Failed to detect PSBBN or HOSDMenu on ${DEVICE}." >> "${LOG_FILE}"
        error_msg "${UI_TEXT[ERROR_OS_CHECK_1]}"
        return 1
    fi
}

# Function to display the menu
display_menu() {
    HDD_GAMES_SPLASH
    printf "\n\n\n"
    printf "%*s%s\n\n" "$padding" "1) " "${UI_TEXT[HDD_GAMES_MENU_OPTION_1]}"
    printf "%*s%s\n\n" "$padding" "2) " "${UI_TEXT[HDD_GAMES_MENU_OPTION_2]}"
    printf "%*s%s\n\n" "$padding" "3) " "${UI_TEXT[HDD_GAMES_MENU_OPTION_3]}"
    printf "%*s%s\n\n" "$padding" "4) " "${UI_TEXT[HDD_GAMES_MENU_OPTION_4]}"
    printf "%*s%s\n\n" "$padding" "5) " "${UI_TEXT[HDD_GAMES_MENU_OPTION_5]}"
    printf "%*s%s\n\n" "$padding" "b) " "${UI_TEXT[MENU_BACK]}"
    printf "%*s%s " "$((padding - 3))" "" "${UI_TEXT[MENU_PROMPT]}"
}

# Nobunaga's Ambition Online: handed the drive found at startup.
option_one() {
    bash "${SCRIPTS_DIR}/Nobunaga-Installer.sh" "$LANG_FILE" "${path_arg:-}" "$DEVICE"
}

# Net de Bomberman.
option_two() {
    bash "${SCRIPTS_DIR}/Bomb-Installer.sh" "$LANG_FILE" "${path_arg:-}" "$DEVICE"
}

# Minna no Golf Online.
option_three() {
    bash "${SCRIPTS_DIR}/Mingol-Installer.sh" "$LANG_FILE" "${path_arg:-}" "$DEVICE"
}

# pop'n Puzzle Dama Online.
option_four() {
    bash "${SCRIPTS_DIR}/Popn-Installer.sh" "$LANG_FILE" "${path_arg:-}" "$DEVICE"
}

# Fix network settings: write a DHCP netcnf000.dat keyed to the psbb spoof the
# loaders serve to NETCNF on every console, so the games stop reporting
# "connected to another PlayStation 2 / redo network settings". Console-agnostic
# (no per-console i.Link); needs the matching loader (scefix >= 1.4).
option_five() {
    local WORK="${SCRIPTS_DIR}/tmp/ncfix"

    HDD_GAMES_SPLASH
    center_title "${UI_TEXT[HDD_GAMES_FIXNET_TITLE]}"
    echo

    if [ ! -f "$FIX_TOOL" ]; then
        error_msg "${UI_TEXT[HDD_GAMES_FIXNET_FAIL]}"
        return 1
    fi

    center_text "${UI_TEXT[HDD_GAMES_FIXNET_INFO]}"
    echo
    center_text "${UI_TEXT[CONTINUE_PROMPT]}"
    echo
    read -n 1 -s -r -p "" key </dev/tty
    echo
    case "$key" in
        [yY]) ;;
        *) return 0 ;;
    esac

    sudo rm -rf "$WORK"   # prior runs leave root-owned files (pfsshell runs under sudo)
    mkdir -p "$WORK"

    if python3 "$FIX_TOOL" --device "$DEVICE" --pfsshell "$PFS_SHELL" --work "$WORK" --apply >>"${LOG_FILE}" 2>&1; then
        center_title "[✓] ${UI_TEXT[HDD_GAMES_FIXNET_DONE]}"
    else
        error_msg "${UI_TEXT[HDD_GAMES_FIXNET_FAIL]}"
        clean_up
        return 1
    fi

    clean_up
    echo
    center_text "${UI_TEXT[CONTINUE]}"
    read -n 1 -s -r -p "" </dev/tty
}

clear
trap 'echo; exit 130' INT
trap exit_script EXIT

cd "${TOOLKIT_PATH}"

echo "########################################################################################################" | tee -a "${LOG_FILE}" >/dev/null 2>&1
if [ $? -ne 0 ]; then
    sudo rm -f "${LOG_FILE}"
    echo "########################################################################################################" | tee -a "${LOG_FILE}" >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        error_msg "${UI_TEXT[ERROR_LOG]}"
        exit 1
    fi
fi

date >> "${LOG_FILE}"
echo >> "${LOG_FILE}"
echo "Toolkit path: $TOOLKIT_PATH" >> "${LOG_FILE}"
echo >> "${LOG_FILE}"
echo -n "PSBBN Definitive Project Version: " >> "${LOG_FILE}"
git rev-parse --short HEAD >> "${LOG_FILE}"
cat /etc/*-release >> "${LOG_FILE}" 2>&1

HDD_GAMES_SPLASH
detect_drive || exit 1
HDL_TOC || exit 1
CHECK_PARTITIONS || exit 1

if ! sudo rm -rf "${STORAGE_DIR}"; then
    echo "[X] Error: Failed to delete: $STORAGE_DIR" >> "${LOG_FILE}"
    error_msg "${UI_TEXT[ERROR_DELETE]} $STORAGE_DIR"
    exit 1
fi

# Main loop
while true; do
    MENU_KEYS=(
        HDD_GAMES_MENU_OPTION_1
        HDD_GAMES_MENU_OPTION_2
        HDD_GAMES_MENU_OPTION_3
        HDD_GAMES_MENU_OPTION_4
        HDD_GAMES_MENU_OPTION_5
    )
    center_menu
    display_menu
    read -rp "" choice

    case $choice in
        1) option_one ;;
        2) option_two ;;
        3) option_three ;;
        4) option_four ;;
        5) option_five ;;
        b|B) break ;;
        *)
            printf "%*s%s " "$((padding - 3))" "" "${UI_TEXT[MENU_INVALID]}"
            sleep 2
            ;;
    esac
done
