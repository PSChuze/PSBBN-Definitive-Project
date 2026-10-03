#!/usr/bin/env bash
#
# pop'n Puzzle Dama Online Installer for the PSBBN Definitive Project
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
# Installs pop'n Puzzle Dama Online (SLPM-62464) to a PSBBN drive from the
# Extras menu.
#
# Unlike Nobunaga's Ambition Online, pop'n's disc-form DNAS2 containers can
# be transcrypted to the drive form offline (see popn/HANDOFF-disc-form-decrypt.md
# in the pop'n project). So this step does the whole install on the PC: it
# seals every container to the target drive's identity, creates PP.BLJA-00010
# (128 MiB, password POPNPUZZ, PFS), and writes the drive tree.
#
# It sits beside the PlayOnline and Nobunaga steps without touching them: it
# only reads the playonline package, never mints or changes the PlayOnline
# drive ID, and on a drive that already carries PlayOnline or Nobunaga it
# writes nothing those steps would not.

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
LOG_FILE="${LOGS_DIR}/popn-installer.log"
GAMES_PATH="${TOOLKIT_PATH}/games"
WORK_DIR="${SCRIPTS_DIR}/tmp/popn"

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
DEVICE="${2:-}"

POPN_DIR="${GAMES_PATH}/POPN"
[[ -n "${path_arg}" ]] && POPN_DIR="${path_arg}/POPN"
[[ -n "${POPN_DIR_OVERRIDE}" ]] && POPN_DIR="${POPN_DIR_OVERRIDE}"
POL_HDDID_FILE="${POL_HDDID:-$(dirname "${POPN_DIR}")/POL/playonline.hddid}"

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

# English fallbacks for the disc/install prompts. Lang files can override.
: "${UI_TEXT[POPN_KIT_ASK]:=A pop'n disc extract was found. Install pop'n to the drive now? (y/N)}"
: "${UI_TEXT[POPN_KIT_INSTALLING]:=Installing pop'n to the drive. This can take a few minutes...}"
: "${UI_TEXT[POPN_KIT_ERROR]:=Install failed. See logs/popn-installer.log}"
: "${UI_TEXT[POPN_KIT_DONE]:=pop'n installed. Boot HDD-OSD to launch it.}"
: "${UI_TEXT[POPN_KIT_NEEDS_HDDID]:=A pop'n disc extract is present, but the PlayOnline step must run first to mint the drive ID.}"
: "${UI_TEXT[POPN_KIT_NO_DISC]:=No pop'n disc extract found. Drop the SLPM-62464 disc tree into games/POPN/disc/ and run this step again.}"
: "${UI_TEXT[POPN_RESWAP_ASK]:=Re-swap the boot loader on this existing install (refresh the disc-less bypass) without reinstalling? (y/N)}"
: "${UI_TEXT[POPN_RESWAP_RUNNING]:=Swapping the boot loader in place...}"
: "${UI_TEXT[POPN_RESWAP_DONE]:=Loader swapped. Boot HDD-OSD to launch it.}"
: "${UI_TEXT[POPN_RESWAP_ERROR]:=Loader swap failed. See logs/popn-installer.log}"
: "${UI_TEXT[POPN_TR_ASK]:=Apply the English translation (UI text and the menu/logo textures)? (y/N)}"
: "${UI_TEXT[POPN_RECOVER_ASK]:=The game is installed on this drive, but this machine has no saved drive ID (playonline.hddid). Recover it from the installed loader on the drive? (Y/n)}"
: "${UI_TEXT[POPN_RECOVER_RUNNING]:=Recovering the drive ID from the installed loader...}"
: "${UI_TEXT[POPN_RECOVER_DONE]:=Recovered the drive ID:}"
: "${UI_TEXT[POPN_RECOVER_FAIL]:=Could not recover the drive ID. See logs/popn-installer.log}"

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

                       __     ______              __     ___
     ____  ____  ____  / /___/_ __/ _____ ___ ___/ /__  / _ \___ ___ _  ___ _
    / _ \/ _ \/ _ \/ /'_ /  / /   / __(_-</ // /_-</ // / _  / _ `/  ' \/ _ `/
   / .__/\___/ .__/_/\_,_/ /_/    \__/___/\_,_/___/\___/____/\_,_/_/_/_/\_,_/
  /_/       /_/

EOF
}

POPN_PY="${SCRIPTS_DIR}/venv/bin/python3"
[[ -x "${POPN_PY}" ]] || POPN_PY="python3"
popnsudo() { local m="$1"; shift; sudo -E env PYTHONPATH="${HELPER_DIR}" "${POPN_PY}" -m "$m" "$@"; }

# The name in HDD-OSD and PSBBN's list. English by default (the game has no
# English translation yet; the Latin title is a browser convenience);
# --language japanese restores the disc's own text.
popn_retitle() {
    popnsudo popn.retitle "${DEVICE}" "$1" --write >> "${LOG_FILE}" 2>&1 \
        || echo "[!] retitle ($1) failed; the name in the browser is unchanged." >> "${LOG_FILE}"
}

on_exit() {
    [[ -n "${SUDO_KEEPALIVE}" ]] && kill "${SUDO_KEEPALIVE}" 2>/dev/null
    return 0
}
trap on_exit EXIT

SPLASH
center_text "${UI_TEXT[POPN_TITLE]}"
echo
echo "=== run $(date) ===" >> "${LOG_FILE}"

# pycryptodome is used by playonline's polhdd (for the APA password derivation
# popninstall.py calls). Install if the venv doesn't have it. Same pattern as
# PlayOnline / Nobunaga steps.
"${POPN_PY}" -c "import Crypto" 2>/dev/null || "${POPN_PY}" -m pip install pycryptodome >> "${LOG_FILE}" 2>&1 || {
    echo "[X] Error: could not install pycryptodome into the venv." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[ERROR_ACTIVATE_PYTHON]}"
}
# Pillow is used to render the English menu/logo textures at install time
# (popninstall.py --translate -> apply_textures.py / pntexedit.py). Only needed
# when the user opts into the translation, but cheap to ensure up front.
"${POPN_PY}" -c "import PIL" 2>/dev/null || "${POPN_PY}" -m pip install Pillow >> "${LOG_FILE}" 2>&1 || {
    echo "[X] Error: could not install Pillow into the venv." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[ERROR_ACTIVATE_PYTHON]}"
}
sudo -v || error_msg "${UI_TEXT[POPN_ERROR_SUDO]}"
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
    error_msg "${UI_TEXT[POPN_ERROR_NO_DEVICE]}"
fi
DRIVE_UUID=$(grep -o ' UUID="[^"]*"' <<< "$line" | head -1 | cut -d'"' -f2)
echo "Device: ${DEVICE} (UUID ${DRIVE_UUID:-none})" >> "${LOG_FILE}"

if ! sudo "${HDL_DUMP}" toc "${DEVICE}" >> "${LOG_FILE}" 2>&1; then
    error_msg "${UI_TEXT[ERROR_HDL_TOC]}"
fi

echo "${UI_TEXT[POPN_CHECKING]}"
echo
declare -A INFO
check_out=$(popnsudo popn.check "${DEVICE}" --plain 2>>"${LOG_FILE}") \
    || error_msg "${UI_TEXT[POPN_ERROR_READ]}"
check_out="${check_out//$'\r'/}"
while IFS='=' read -r key value; do
    [[ -n "$key" ]] && INFO["$key"]="$value"
done <<< "${check_out}"
popnsudo popn.check "${DEVICE}" 2>>"${LOG_FILE}" | tee -a "${LOG_FILE}"
echo

[[ "${INFO[system]}" == "1" ]] || error_msg "${UI_TEXT[POPN_ERROR_NOT_PS2]}"

# The pop'n install keys to the same served HDD ID as the PlayOnline titles
# on this drive (the toolkit's polbbnexec loader serves one ID per drive).
if [[ -f "${POL_HDDID_FILE}" ]]; then
    echo "  ${UI_TEXT[POPN_HDDID_FOUND]} ${POL_HDDID_FILE}"
else
    echo "  ${UI_TEXT[POPN_HDDID_NONE]}"
fi
echo "HDD ID: ${POL_HDDID_FILE} $([[ -f "${POL_HDDID_FILE}" ]] && echo found || echo absent)" >> "${LOG_FILE}"
echo

# ---- recover the drive ID from the drive itself -------------------------
# New machine: the PlayOnline step never ran here, so playonline.hddid is
# absent. But if pop'n is already installed, the spoof loader on the drive
# carries the exact 512-byte HDD ID the sealed install was keyed to. Lift it
# back out of pfs:/dnasload.elf so a fresh machine does not have to re-run the
# PlayOnline step or reproduce a mint seed. (Nothing to recover if the game is
# not installed -- there is no loader on the drive yet.)
if [[ ! -f "${POL_HDDID_FILE}" && -n "${INFO[installed]}" ]]; then
    POPN_TOOLS="${POPN_TOOLS_OVERRIDE:-${POPN_DIR}/tools}"
    [[ -f "${POPN_TOOLS}/popninstall.py" ]] || POPN_TOOLS="${SCRIPTS_DIR}/../../popn/popn/tools"
    [[ -f "${POPN_TOOLS}/popninstall.py" ]] || POPN_TOOLS="${SCRIPTS_DIR}/../../Pop'N Puzzle Dama Online/popn/tools"
    [[ -f "${POPN_TOOLS}/popninstall.py" ]] || POPN_TOOLS="${HELPER_DIR}/popn/tools"
    if [[ -f "${POPN_TOOLS}/popninstall.py" ]]; then
        printf "%s " "${UI_TEXT[POPN_RECOVER_ASK]}"
        read -r answer </dev/tty
        case "$answer" in
            [Nn]*) ;;
            *)
                mkdir -p "$(dirname "${POL_HDDID_FILE}")"
                echo "${UI_TEXT[POPN_RECOVER_RUNNING]}"
                sudo -E env PYTHONPATH="${HELPER_DIR}" "${POPN_PY}" \
                    "${POPN_TOOLS}/popninstall.py" "${DEVICE}" \
                    --recover-hddid "${POL_HDDID_FILE}" \
                    --helper "${HELPER_DIR}" \
                    --pfsshell "${HELPER_DIR}/PFS Shell.elf" \
                    2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
                if [[ ${PIPESTATUS[0]} -eq 0 && -f "${POL_HDDID_FILE}" ]]; then
                    echo "  ${UI_TEXT[POPN_RECOVER_DONE]} ${POL_HDDID_FILE}"
                else
                    echo "  ${UI_TEXT[POPN_RECOVER_FAIL]}"
                fi
                echo
                ;;
        esac
    fi
fi

# ---- already installed --------------------------------------------------
if [[ -n "${INFO[installed]}" ]]; then
    center_text "${UI_TEXT[POPN_INSTALLED]}"
    echo
    # In-place loader re-swap: refresh pfs:/dnasload.elf with the spoof loader
    # (filled for this drive) WITHOUT reinstalling -- so a tester can iterate on
    # loader / boot-ELF-patch changes, or add the disc-less bypass to a drive that
    # was installed with the stock dnasload. Sealed containers, attr and passwords
    # are untouched. Needs the disc extract, the loader asset, and the drive's ID.
    POPN_DISC="${POPN_DIR}/disc"
    POPN_TOOLS="${POPN_TOOLS_OVERRIDE:-${POPN_DIR}/tools}"
    [[ -f "${POPN_TOOLS}/popninstall.py" ]] || POPN_TOOLS="${SCRIPTS_DIR}/../../popn/popn/tools"
    [[ -f "${POPN_TOOLS}/popninstall.py" ]] || POPN_TOOLS="${SCRIPTS_DIR}/../../Pop'N Puzzle Dama Online/popn/tools"
    [[ -f "${POPN_TOOLS}/popninstall.py" ]] || POPN_TOOLS="${HELPER_DIR}/popn/tools"
    POPN_INSTALL_PY="${POPN_TOOLS}/popninstall.py"
    POPN_LOADER="${POPN_LOADER_OVERRIDE:-${SCRIPTS_DIR}/assets/popn/polbbnexec-popn.kelf}"
    if [[ -f "${POPN_DISC}/MAIN.BIN" ]] && [[ -f "${POPN_INSTALL_PY}" ]] \
       && [[ -f "${POPN_LOADER}" ]] && [[ -f "${POL_HDDID_FILE}" ]]; then
        printf "%s " "${UI_TEXT[POPN_RESWAP_ASK]}"
        read -r answer </dev/tty
        case "$answer" in
            [Yy]*)
                POPN_TR_FLAG=""
                POPN_TRANSLATE="${POPN_TRANSLATE_OVERRIDE:-${SCRIPTS_DIR}/assets/popn/elf.en.tsv}"
                if [[ -f "${POPN_TRANSLATE}" ]]; then
                    printf "%s " "${UI_TEXT[POPN_TR_ASK]}"
                    read -r tr_answer </dev/tty
                    case "$tr_answer" in [Yy]*) POPN_TR_FLAG="--translate ${POPN_TRANSLATE}" ;; esac
                fi
                echo "${UI_TEXT[POPN_RESWAP_RUNNING]}"
                sudo -E env PYTHONPATH="${HELPER_DIR}" "${POPN_PY}" \
                    "${POPN_INSTALL_PY}" "${DEVICE}" \
                    --disc "${POPN_DISC}" \
                    --hddid "${POL_HDDID_FILE}" \
                    --helper "${HELPER_DIR}" \
                    --pfsshell "${HELPER_DIR}/PFS Shell.elf" \
                    --loader "${POPN_LOADER}" \
                    ${POPN_TR_FLAG} \
                    --loader-swap --write \
                    2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
                if [[ ${PIPESTATUS[0]} -eq 0 ]]; then
                    center_text "${UI_TEXT[POPN_RESWAP_DONE]}"
                else
                    error_msg "${UI_TEXT[POPN_RESWAP_ERROR]}"
                fi
                ;;
        esac
    fi
    echo
    read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
    echo
    exit 0
fi

# ---- not installed: fit + confirm ---------------------------------------
[[ "${INFO[fits]}" == "1" ]] || error_msg "${UI_TEXT[POPN_NO_ROOM]}"

echo "${UI_TEXT[POPN_PLAN]}"
echo "  - ${UI_TEXT[POPN_PLAN_PART]}"
echo
center_text "${UI_TEXT[POPN_PLAN_UNTOUCHED]}"
echo
printf "%s " "${UI_TEXT[POPN_CONFIRM]}"
read -r answer </dev/tty
case "$answer" in
    [Yy]*) ;;
    *) echo; echo "${UI_TEXT[POPN_ABORTED]}"; sleep 2; exit 0 ;;
esac
echo

# ---- PC-side install (from the player's own disc) -----------------------
POPN_DISC="${POPN_DIR}/disc"
# popn/tools/ ships as public code (no Konami/Sony bytes; the disc supplies
# everything). Tester can override via $POPN_TOOLS; falls back to a common
# layout under POPN_DIR/tools, then a git-checkout sibling of the toolkit.
POPN_TOOLS="${POPN_TOOLS_OVERRIDE:-${POPN_DIR}/tools}"
[[ -f "${POPN_TOOLS}/popninstall.py" ]] || POPN_TOOLS="${SCRIPTS_DIR}/../../popn/popn/tools"
[[ -f "${POPN_TOOLS}/popninstall.py" ]] || POPN_TOOLS="${SCRIPTS_DIR}/../../Pop'N Puzzle Dama Online/popn/tools"
# Bundled copy inside the toolkit -- makes a fresh clone self-contained (no
# external popn repo needed). Last fallback so a dev checkout's tools win.
[[ -f "${POPN_TOOLS}/popninstall.py" ]] || POPN_TOOLS="${HELPER_DIR}/popn/tools"
POPN_INSTALL_PY="${POPN_TOOLS}/popninstall.py"
# The pre-signed spoof boot loader. popninstall fills it per drive from this
# drive's HDD ID + the player's own patched boot ELF and DNAS280.IMG IOPRP,
# both carved from the disc's MAIN.BIN (no re-signing, no PS2 keys), then
# installs it as pfs:/dnasload.elf in place of the disc's stock dnasload, which
# cannot pass the dead DNAS console binding. Without it the game installs but
# stops at the DNAS check. Ships in the toolkit assets; override with
# $POPN_LOADER_OVERRIDE. Mirrors Nobunaga's polbbnexec-inputpatch.kelf.
POPN_LOADER="${POPN_LOADER_OVERRIDE:-${SCRIPTS_DIR}/assets/popn/polbbnexec-popn.kelf}"
POPN_INSTALLED_NOW=0

# Disc extract fingerprint: SYSTEM.CNF at root + MAIN.BIN + MODULES/ (see
# popn's HANDOFF-toolkit-integration.md for the identifying features).
if [[ -f "${POPN_DISC}/SYSTEM.CNF" ]] && [[ -f "${POPN_DISC}/MAIN.BIN" ]] \
   && [[ -d "${POPN_DISC}/MODULES" ]] && [[ -f "${POPN_INSTALL_PY}" ]]; then
    if [[ ! -f "${POL_HDDID_FILE}" ]]; then
        center_text "${UI_TEXT[POPN_KIT_NEEDS_HDDID]}"
    else
        printf "%s " "${UI_TEXT[POPN_KIT_ASK]}"
        read -r answer </dev/tty
        case "$answer" in
            [Yy]*)
                LOADER_FLAG=""
                if [[ -f "${POPN_LOADER}" ]]; then
                    LOADER_FLAG="--loader ${POPN_LOADER}"
                else
                    echo "[!] spoof loader not found at ${POPN_LOADER}; installing with the disc's stock dnasload (will NOT boot disc-less past the DNAS check)." >> "${LOG_FILE}"
                fi
                POPN_TR_FLAG=""
                POPN_TRANSLATE="${POPN_TRANSLATE_OVERRIDE:-${SCRIPTS_DIR}/assets/popn/elf.en.tsv}"
                if [[ -n "${LOADER_FLAG}" ]] && [[ -f "${POPN_TRANSLATE}" ]]; then
                    printf "%s " "${UI_TEXT[POPN_TR_ASK]}"
                    read -r tr_answer </dev/tty
                    case "$tr_answer" in [Yy]*) POPN_TR_FLAG="--translate ${POPN_TRANSLATE}" ;; esac
                fi
                echo "${UI_TEXT[POPN_KIT_INSTALLING]}"
                sudo -E env PYTHONPATH="${HELPER_DIR}" "${POPN_PY}" \
                    "${POPN_INSTALL_PY}" "${DEVICE}" \
                    --disc "${POPN_DISC}" \
                    --hddid "${POL_HDDID_FILE}" \
                    --helper "${HELPER_DIR}" \
                    --pfsshell "${HELPER_DIR}/PFS Shell.elf" \
                    ${LOADER_FLAG} \
                    ${POPN_TR_FLAG} \
                    --write \
                    2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
                [[ ${PIPESTATUS[0]} -eq 0 ]] || error_msg "${UI_TEXT[POPN_KIT_ERROR]}"
                POPN_INSTALLED_NOW=1
                popn_retitle english
                ;;
        esac
    fi
else
    center_text "${UI_TEXT[POPN_KIT_NO_DISC]}"
fi

echo
if [[ ${POPN_INSTALLED_NOW} -eq 1 ]]; then
    center_text "${UI_TEXT[POPN_KIT_DONE]}"
else
    center_text "${UI_TEXT[POPN_READY]}"
    [[ "${INFO[netcnf]}" == "present" ]] || center_text "${UI_TEXT[POPN_NETCNF_MISSING]}"
fi
echo

# Register this title's partition in protect-parts.list (the standing pattern:
# an installer owns its keep-list entry), so PSBBN's Game-Installer keeps it on
# every game add. Idempotent; safe if the list already has it.
OPL_PROT_MNT="$(mktemp -d)"
if sudo mount "${DEVICE}3" "${OPL_PROT_MNT}" >> "${LOG_FILE}" 2>&1; then
    sudo touch "${OPL_PROT_MNT}/protect-parts.list"
    sudo grep -qxF "PP.BLJA-00010" "${OPL_PROT_MNT}/protect-parts.list" 2>/dev/null \
        || echo "PP.BLJA-00010" | sudo tee -a "${OPL_PROT_MNT}/protect-parts.list" >/dev/null
    sync
    sudo umount "${OPL_PROT_MNT}"
    echo "pop'n partition registered in protect-parts.list." >> "${LOG_FILE}"
else
    echo "[!] could not mount exFAT to update protect-parts.list; a future PSBBN game add may drop the pop'n partition." >> "${LOG_FILE}"
fi
rmdir "${OPL_PROT_MNT}" 2>/dev/null

read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
echo
