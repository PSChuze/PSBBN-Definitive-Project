#!/usr/bin/env bash
#
# PlayOnline Installer for the PSBBN Definitive Project
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
# Installs PlayOnline onto a PS2 drive with neither PSBBN nor HOSDMenu on it:
# one formatted by HDD-OSD or the HDD Utility Disc, where the titles are
# started from Sony's own browser.
#
# It runs the same installer as the toolkit's main menu entry. The drive is
# named instead of being found by the OPL partition a PSBBN drive carries, and
# the only setup it needs is Python and one package, where the toolkit
# installs a long list.
#
#   ./PlayOnline-Standalone.sh              choose the drive from a list
#   ./PlayOnline-Standalone.sh /dev/sdX     name the drive
#
# Disc images go in games/POL next to this script. POL_DISC_DIR points
# somewhere else, and POL_LANG picks the language (eng, jpn, fre, ger, spa,
# ita, por, hun).

[[ -t 0 && -t 1 ]] || { echo "Run this from a terminal."; exit 1; }

TOOLKIT_PATH="$(cd "$(dirname "$0")" && pwd)"
cd "${TOOLKIT_PATH}" || exit 1
SCRIPTS_DIR="${TOOLKIT_PATH}/scripts"
LANG_DIR="${SCRIPTS_DIR}/assets/lang"
VENV_PY="${SCRIPTS_DIR}/venv/bin/python3"

# The language, chosen the way the toolkit's main script chooses it.
if [[ -z "${POL_LANG}" ]]; then
    SYS_LANG="${SYS_LANG:-${LANG:-$(locale 2>/dev/null | awk -F= '/^LANG=/{print $2}')}}"
    case "${SYS_LANG,,}" in
        ja*|jp*) POL_LANG=jpn ;;
        fr*)     POL_LANG=fre ;;
        es*|sp*) POL_LANG=spa ;;
        de*|ge*) POL_LANG=ger ;;
        it*)     POL_LANG=ita ;;
        pt*|po*) POL_LANG=por ;;
        hu*)     POL_LANG=hun ;;
        *)       POL_LANG=eng ;;
    esac
fi
[[ -f "${LANG_DIR}/${POL_LANG}.txt" ]] || POL_LANG=eng

declare -A UI_TEXT
while IFS='=' read -r key value; do
    [[ -z "$key" ]] && continue
    UI_TEXT["$key"]="$value"
done < "${LANG_DIR}/${POL_LANG}.txt"

# The installer's Python package needs pycryptodome and nothing else outside
# the standard library, and its two helper programs are 64-bit, so there is no
# 32-bit runtime to install either. A virtual environment the toolkit already
# built has the package, and is left as it is.
venv_ok() { "${VENV_PY}" -c "import Crypto" 2>/dev/null; }

if ! venv_ok; then
    echo "${UI_TEXT[POL_SA_SETUP]}"
    if [ -x "$(command -v apt-get)" ]; then
        sudo apt-get -q update && sudo apt-get install -y python3 python3-venv python3-pip
    elif [ -x "$(command -v dnf)" ]; then
        sudo dnf install -y python3 python3-pip
    elif [ -x "$(command -v pacman)" ]; then
        sudo pacman -S --needed --noconfirm python python-pip
    fi
    python3 -m venv --clear "${SCRIPTS_DIR}/venv" \
        && "${VENV_PY}" -m pip install -q pycryptodome
    if ! venv_ok; then
        echo "[X] ${UI_TEXT[POL_SA_SETUP_FAILED]}"
        exit 1
    fi
fi

# Reading the drives needs sudo. Ask here, where its prompt can be seen: the
# scan below sends sudo's stderr away, and a password prompt with it.
sudo -v || exit 1

# A drive formatted for the PS2 carries APA's magic, "APA\0", at byte 4 of its
# first sector. A PSBBN drive has it too, and the installer takes either.
list_ps2_drives() {
    local d
    while read -r d; do
        [[ "$(sudo dd if="$d" bs=1 skip=4 count=4 2>/dev/null \
              | od -An -tx1 | tr -d ' \n')" == "41504100" ]] && echo "$d"
    done < <(lsblk -dnpo NAME,TYPE | awk '$2 == "disk" {print $1}')
}

if [[ -n "$1" ]]; then
    POL_DRIVE="$1"
else
    mapfile -t DRIVES < <(list_ps2_drives)
    if [[ ${#DRIVES[@]} -eq 0 ]]; then
        echo "[X] ${UI_TEXT[POL_SA_NO_DRIVE]}"
        exit 1
    fi
    echo "${UI_TEXT[POL_SA_DRIVES]}"
    for i in "${!DRIVES[@]}"; do
        printf "  %d) %s  %s\n" $((i + 1)) "${DRIVES[$i]}" \
            "$(lsblk -dno SIZE,MODEL "${DRIVES[$i]}" 2>/dev/null)"
    done
    read -rp "${UI_TEXT[POL_SA_PICK]} " n </dev/tty
    if [[ ! "$n" =~ ^[0-9]+$ ]] || (( n < 1 || n > ${#DRIVES[@]} )); then
        echo "[X] ${UI_TEXT[POL_SA_BAD_PICK]}"
        exit 1
    fi
    POL_DRIVE="${DRIVES[$((n - 1))]}"
fi

export LAUNCHED_BY_MAIN=1 POL_DRIVE
exec "${SCRIPTS_DIR}/PlayOnline-Installer.sh" "${POL_LANG}" "${TOOLKIT_PATH}/games"
