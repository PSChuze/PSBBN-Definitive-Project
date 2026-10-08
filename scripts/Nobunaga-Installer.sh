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
# The game's files are Sony DNAS2 containers that Koei's own installer, running
# on the console, turns from the disc's form into the drive's; the PC does not
# re-encrypt them for you. So this step prepares the drive - checks it, keeps a
# copy of what the console install could disturb, and makes __net openable - and
# the console installer then installs the game. Booting the installed game from
# HDD-OSD is proven on real hardware. See scripts/helper/nobunaga.
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

# English fallbacks for the optional install-kit prompts. These are new strings;
# the lang files carry no translation for them yet, so default them here and let
# a real translation in the lang files override (only set when unset/empty).
: "${UI_TEXT[NOBU_KIT_ASK]:=An install kit was found. Install Nobunaga to the drive now? (y/N)}"
: "${UI_TEXT[NOBU_KIT_ASK_TRANSLATE]:=Apply the English translation? It is downloaded from openlobby.fyi. (y/N)}"
: "${UI_TEXT[NOBU_KIT_INSTALLING]:=Installing Nobunaga to the drive. This can take a few minutes...}"
: "${UI_TEXT[NOBU_KIT_ERROR]:=Install failed. See logs/nobunaga-installer.log}"
: "${UI_TEXT[NOBU_KIT_DONE]:=Nobunaga installed. Boot HDD-OSD to launch it.}"
: "${UI_TEXT[NOBU_KIT_NEEDS_HDDID]:=An install kit is present, but the PlayOnline step must run first to mint the drive ID.}"
: "${UI_TEXT[NOBU_TR_ASK]:=English translation: apply (a), remove (r), or skip (Enter)?}"
: "${UI_TEXT[NOBU_TR_APPLYING]:=Applying the English translation...}"
: "${UI_TEXT[NOBU_TR_APPLIED]:=English translation applied.}"
: "${UI_TEXT[NOBU_TR_REMOVING]:=Restoring the original Japanese text...}"
: "${UI_TEXT[NOBU_TR_REMOVED]:=Original Japanese text restored.}"
: "${UI_TEXT[NOBU_TR_ERROR]:=Translation update failed. See logs/nobunaga-installer.log}"
: "${UI_TEXT[NOBU_EXTRACT_FOUND]:=Found a disc image:}"
: "${UI_TEXT[NOBU_EXTRACT_ASK]:=Extract it to games/NOBU/disc/ now? (Y/n)}"
: "${UI_TEXT[NOBU_EXTRACT_RUNNING]:=Extracting the disc image (this writes the full disc tree, a few minutes)...}"
: "${UI_TEXT[NOBU_EXTRACT_DONE]:=Extracted the disc tree to}"
: "${UI_TEXT[NOBU_EXTRACT_FAIL]:=Extraction failed. See logs/nobunaga-installer.log}"
: "${UI_TEXT[NOBU_UPDATE_ASK]:=Update the install in place? It is rebuilt from your disc; the saves and settings on the drive are kept. (y/N)}"
: "${UI_TEXT[NOBU_UPDATE_LANG]:=Language of the game after the update:}"
: "${UI_TEXT[NOBU_UPDATE_KEEP]:=Keep it as installed}"
: "${UI_TEXT[NOBU_UPDATE_EN]:=English (the translation is downloaded from openlobby.fyi)}"
: "${UI_TEXT[NOBU_UPDATE_JA]:=Japanese (as on the disc)}"
: "${UI_TEXT[NOBU_UPDATE_CHOICE]:=Choose:}"
: "${UI_TEXT[NOBU_UPDATE_NO_PACK]:=The translation pack could not be downloaded from openlobby.fyi, and none is kept on this machine. Check the connection and run this step again.}"
: "${UI_TEXT[NOBU_PACK_FETCHING]:=Getting the English translation pack...}"
: "${UI_TEXT[NOBU_UPDATE_NEED]:=To update in place, this machine also needs:}"
: "${UI_TEXT[NOBU_NEED_DISC]:=the game disc (an .iso in games/NOBU/, or the extracted tree in games/NOBU/disc/)}"
: "${UI_TEXT[NOBU_NEED_HDDID]:=the drive ID (playonline.hddid), which is read from the drive when PlayOnline is on it}"
: "${UI_TEXT[NOBU_UPDATE_DOING]:=Updating Nobunaga’s Ambition Online (this can take several minutes)...}"
: "${UI_TEXT[NOBU_UPDATE_DONE]:=Nobunaga’s Ambition Online was updated. Your saves were kept.}"

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

# The name in HDD-OSD and PSBBN's list follows the game's language, as the
# PlayOnline titles' do: English with the translation on, Koei's Japanese
# without it. Cosmetic (the game reads neither place), so a failure is only
# logged. See nobunaga/retitle.py.
nobu_retitle() {
    nobusudo nobunaga.retitle "${DEVICE}" "$1" --write >> "${LOG_FILE}" 2>&1 \
        || echo "[!] retitle ($1) failed; the name in the browser is unchanged." >> "${LOG_FILE}"
}

# Place Nobunaga's DNAS boot gate (access_flag25 at __net+0x202000), keyed to the
# psbb i.Link the dnasload spoof serves. This writes ONLY that record; the shared
# PlayOnline record at +0x201800 is never touched (accessflag.py refuses if it
# would change), so FFXI/the Viewer keep decrypting. The current record is backed
# up first. See nobunaga/accessflag.py.
nobu_accessflag() {
    if nobusudo nobunaga.accessflag "${DEVICE}" --write --save "${BACKUP_DIR}" \
        >> "${LOG_FILE}" 2>&1; then
        echo "  ${UI_TEXT[NOBU_AF_DONE]:-DNAS boot record placed, PlayOnline record left intact.}"
    else
        echo "[!] access_flag25 write failed; the game may not pass its boot check. See logs/nobunaga-installer.log" >> "${LOG_FILE}"
    fi
}

# Boot debug text, asked with the install (scripts/helper/debugtext.sh): Y
# installs the FORK_VERBOSE twin of the loader, which prints every stage on the
# TV and stops with the reason when one fails, and arms the boot record: the
# loader's atadpatch writes a gate record (kernel, atad, partition and __net
# opens, served HDD ID, ExecPS2) into one sector while the game boots, but only
# if that sector carries the POLTRACENOBUTRC1 tag and the loader's TRACELBA
# slot points at it. N installs the silent loader with the slot at 0 (off).
# NOBU_TRACE=1 still arms the record with the silent loader. Read the sector
# back after a boot with work/loader/trace-read.sh + trace-decode.py.
source "${HELPER_DIR}/debugtext.sh"
NOBU_LOADER_VERBOSE="${NOBU_LOADER_VERBOSE_OVERRIDE:-${SCRIPTS_DIR}/assets/nobunaga/polbbnexec-nobu-verbose.kelf}"

# Swaps NOBU_LOADER for its verbose twin on Y (not when NOBU_LOADER_OVERRIDE
# names a loader of its own).
nobu_debugtext() {
    debugtext_ask
    [[ -n "${NOBU_LOADER_OVERRIDE}" ]] && return 0
    debugtext_pick "${NOBU_LOADER}" "${NOBU_LOADER_VERBOSE}"
    NOBU_LOADER="${DEBUG_LOADER}"
}

nobu_trace_arm() {
    local part="PP.SLPM-65197.KOEI.NOBUON"
    if debugtext_trace_arm "${DEVICE}" "${part}" "${part}" POLTRACENOBUTRC1 \
            "${WORK_DIR}/stage/${part}/dnasload.elf"; then
        echo "  ${UI_TEXT[DEBUG_TEXT_TRACE_ON]} ${DEBUG_TRACE_LBA}."
    else
        echo "  ${UI_TEXT[DEBUG_TEXT_TRACE_FAIL]}"
    fi
}

# True when the kit carries a translation pack. A kit built without one still
# has translation/ holding a PUT-TRANSLATION-HERE.txt placeholder, which is not
# a pack (nobu-translate.sh skips PUT-* files the same way).
nobu_has_translation() {
    [[ -n "$(find "${NOBU_DIR}/kit/translation" -type f ! -name 'PUT-*' 2>/dev/null | head -n 1)" ]]
}

# A translation pack dropped into games/NOBU/translation/ (the README that
# nobuinstall leaves there does not count).
nobu_has_pack() {
    [[ -n "$(find "${NOBU_DIR}/translation" -type f ! -name 'README*' 2>/dev/null | head -n 1)" ]]
}

# Sets NOBU_EN_ARGS to what nobuinstall needs for English, or leaves it empty
# when there is none. First the published pack from openlobby.fyi (kept in
# games/NOBU/translation-pack/, so an offline run reuses the last one), then
# prebuilt files a tester dropped into games/NOBU/translation/.
NOBU_EN_ARGS=()
nobu_english_args() {
    local pack
    echo "  ${UI_TEXT[NOBU_PACK_FETCHING]}"
    pack=$(NOBU_TRANSLATION_CACHE="${NOBU_DIR}/translation-pack" PYTHONPATH="${HELPER_DIR}" \
        "${NOBU_PY}" -m nobunaga.download 2>>"${LOG_FILE}" | tee -a "${LOG_FILE}" | tail -n 1)
    if [[ -n "${pack}" && -f "${pack}" ]]; then
        NOBU_EN_ARGS=(--translation-pack "${pack}")
    elif nobu_has_pack; then
        NOBU_EN_ARGS=(--translation "${NOBU_DIR}/translation")
    else
        NOBU_EN_ARGS=()
    fi
}
NOBU_UPDATE=""

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
# only reported here; minting it is the PlayOnline step's. On a machine that
# never ran that step, it is read back from a loader already on the drive.
source "${HELPER_DIR}/recover-hddid.sh"
recover_drive_hddid "${POL_HDDID_FILE}" "${DEVICE}" "${NOBU_PY}" "${LOG_FILE}"
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

    # ---- update in place (also how the translation goes on or comes off) --
    # The game is staged again from the disc in the chosen language and
    # nobuinstall --update rewrites only the files that differ; the files only
    # the partition has (saves, settings) are kept.
    echo
    printf "%s " "${UI_TEXT[NOBU_UPDATE_ASK]}"
    read -r answer </dev/tty
    case "$answer" in
        [Yy]*) ;;
        *) exit 0 ;;
    esac
    nobu_state=$(nobusudo nobunaga.retitle "${DEVICE}" state 2>>"${LOG_FILE}")
    echo "Installed language: ${nobu_state:-unreadable}" >> "${LOG_FILE}"
    echo
    echo "${UI_TEXT[NOBU_UPDATE_LANG]}"
    echo "  1) ${UI_TEXT[NOBU_UPDATE_KEEP]} (${nobu_state})"
    echo "  2) ${UI_TEXT[NOBU_UPDATE_EN]}"
    echo "  3) ${UI_TEXT[NOBU_UPDATE_JA]}"
    echo
    printf "%s " "${UI_TEXT[NOBU_UPDATE_CHOICE]}"
    read -r answer </dev/tty
    case "$answer" in
        1|"") nobu_lang="${nobu_state}" ;;
        2) nobu_lang="english" ;;
        3) nobu_lang="japanese" ;;
        *) exit 0 ;;
    esac
    [[ "${nobu_lang}" == "english" ]] && nobu_english_args
    if [[ "${nobu_lang}" == "english" && ${#NOBU_EN_ARGS[@]} -eq 0 ]]; then
        center_text "${UI_TEXT[NOBU_UPDATE_NO_PACK]}"
        echo
        read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
        echo
        exit 0
    fi
    NOBU_UPDATE=1
    echo
fi

# ---- not installed: prepare ---------------------------------------------
if [[ -z "${NOBU_UPDATE}" ]]; then
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
fi

# ---- optional PC-side install (from the player's own disc) --------------
# Primary path (2026-09-29 onward): the player extracts their disc into
# ${NOBU_DIR}/disc/ (Hiryuu no Shou expansion, SLPM-65197). The installer
# builds every drive-form container from the disc bytes on the fly, keyed to
# the target drive's ID -- no precomputed neutral bundle needed.
# Legacy fallback: the older tester install kit at ${NOBU_DIR}/kit/ if the
# disc is not present; retained for the transition.
NOBU_DISC="${NOBU_DIR}/disc"
NOBU_KIT="${NOBU_DIR}/kit/nobu-install-kit.sh"
# nobunaga/tools/ ships as public code (no Koei/Sony bytes -- the disc supplies
# everything). Tester can override via $NOBU_TOOLS; falls back to a common
# layout under NOBU_DIR/tools, then a git-checkout sibling of the toolkit.
NOBU_TOOLS="${NOBU_TOOLS_OVERRIDE:-${NOBU_DIR}/tools}"
[[ -f "${NOBU_TOOLS}/nobuinstall.py" ]] || NOBU_TOOLS="${SCRIPTS_DIR}/../../nobunaga/nobunaga/tools"
[[ -f "${NOBU_TOOLS}/nobuinstall.py" ]] || NOBU_TOOLS="${SCRIPTS_DIR}/../../Nobunaga Online/nobunaga/tools"
[[ -f "${NOBU_TOOLS}/nobuinstall.py" ]] || NOBU_TOOLS="${HELPER_DIR}/nobunaga/tools"
NOBU_INSTALL_PY="${NOBU_TOOLS}/nobuinstall.py"
# The pre-signed spoof boot loader. nobuinstall fills it per drive from the
# disc's own boot ELF/IOP image + this drive's HDD ID (no re-signing, no PS2
# keys), then installs it as pfs:/dnasload.elf in place of the disc's stock
# dnasload, which cannot pass the dead DNAS console binding. It serves the
# drive's HDD ID and spoofs the psbb i.Link the access_flag25 record is keyed
# to. Built DRIVERS=4 (ps2sdk dev9/atad, no SCE-genuine drive gate; DRIVERS=2
# never passed that gate on hardware), silent, with the v4 trace slot left at 0
# (off; NOBU_TRACE=1 arms it, see nobu_trace_arm). Ships in the toolkit assets;
# override with $NOBU_LOADER_OVERRIDE.
# NO English text-input hook (2026-10-08): the file keeps its old name, but its
# content is the console-proven no-hook build (b6da0082, boots #54/#55). The
# EE VBlank hook build stopped the boot on the console right at ExecPS2 (boot
# #56); it is kept as polbbnexec-inputpatch.kelf.hook-unproven (edb519ed) and
# is NOT used. Until a hook build is hardware-proven, text input on a console
# install starts in Japanese (hiragana), as on the retail game. The PCSX2 path
# (HippaulInstaller) keeps the hook, which works there.
NOBU_LOADER="${NOBU_LOADER_OVERRIDE:-${SCRIPTS_DIR}/assets/nobunaga/polbbnexec-inputpatch.kelf}"
NOBU_INSTALLED_NOW=0

# ---- extract the disc tree from an .iso if needed -----------------------
# The disc path needs the extracted tree at games/NOBU/disc/. If it is not
# there but an .iso is (in games/NOBU/ or games/NOBU/disc/), extract it here
# with iso.py; 7-Zip drops part of this disc's tree, so it is not used. Point
# NOBU_DISC_IMAGE at the image to pick one explicitly.
if [[ ! -f "${NOBU_DISC}/SYSTEM.CNF" || ! -d "${NOBU_DISC}/AUTH" ]] \
   && [[ -f "${NOBU_TOOLS}/iso.py" ]]; then
    NOBU_IMG="${NOBU_DISC_IMAGE:-}"
    if [[ -z "${NOBU_IMG}" ]]; then
        for cand in "${NOBU_DIR}"/*.iso "${NOBU_DIR}"/*.ISO "${NOBU_DISC}"/*.iso "${NOBU_DISC}"/*.ISO; do
            [[ -f "$cand" ]] && { NOBU_IMG="$cand"; break; }
        done
    fi
    if [[ -n "${NOBU_IMG}" && -f "${NOBU_IMG}" ]]; then
        echo
        echo "  ${UI_TEXT[NOBU_EXTRACT_FOUND]} $(basename "${NOBU_IMG}")"
        printf "%s " "${UI_TEXT[NOBU_EXTRACT_ASK]}"
        read -r answer </dev/tty
        case "$answer" in
            [Nn]*) ;;
            *)
                echo "${UI_TEXT[NOBU_EXTRACT_RUNNING]}"
                mkdir -p "${NOBU_DISC}"
                echo "extracting ${NOBU_IMG} -> ${NOBU_DISC}" >> "${LOG_FILE}"
                "${NOBU_PY}" "${NOBU_TOOLS}/iso.py" x "${NOBU_IMG}" "${NOBU_DISC}" \
                    >> "${LOG_FILE}" 2>&1
                if [[ -f "${NOBU_DISC}/SYSTEM.CNF" && -d "${NOBU_DISC}/AUTH" ]]; then
                    echo "  ${UI_TEXT[NOBU_EXTRACT_DONE]} ${NOBU_DISC}"
                else
                    echo "  ${UI_TEXT[NOBU_EXTRACT_FAIL]}"
                fi
                ;;
        esac
    fi
fi

# Prefer the disc path when the extract is present and looks right (has
# SYSTEM.CNF at its root and the AUTH/ container tree).
NOBU_DISC_OK=""
[[ -f "${NOBU_DISC}/SYSTEM.CNF" ]] && [[ -d "${NOBU_DISC}/AUTH" ]] \
    && [[ -f "${NOBU_INSTALL_PY}" ]] && NOBU_DISC_OK=1
if [[ -n "${NOBU_UPDATE}" ]] && [[ -z "${NOBU_DISC_OK}" || ! -f "${POL_HDDID_FILE}" ]]; then
    center_text "${UI_TEXT[NOBU_UPDATE_NEED]}"
    [[ -n "${NOBU_DISC_OK}" ]]       || echo "    - ${UI_TEXT[NOBU_NEED_DISC]}"
    [[ -f "${POL_HDDID_FILE}" ]]     || echo "    - ${UI_TEXT[NOBU_NEED_HDDID]}"
    echo
    read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
    echo
    exit 0
fi
if [[ -n "${NOBU_DISC_OK}" ]]; then
    echo
    if [[ ! -f "${POL_HDDID_FILE}" ]]; then
        center_text "${UI_TEXT[NOBU_KIT_NEEDS_HDDID]}"
    else
        if [[ -n "${NOBU_UPDATE}" ]]; then
            answer=y
        else
            printf "%s " "${UI_TEXT[NOBU_KIT_ASK]}"
            read -r answer </dev/tty
        fi
        case "$answer" in
            [Yy]*)
                # Translation folder is auto-created next to the disc extract by
                # nobuinstall.py on first run. Users drop the translation zip's
                # contents into ${NOBU_DIR}/translation/ -- anything found there
                # (except README*) is overlaid onto the staged tree. The choice
                # is always passed explicitly: nobuinstall applies a pack it
                # finds there unless told --no-translation.
                TR_ARGS=(--no-translation)
                UPDATE_FLAG=""
                if [[ -n "${NOBU_UPDATE}" ]]; then
                    UPDATE_FLAG="--update"
                    [[ "${nobu_lang}" == "english" ]] && TR_ARGS=("${NOBU_EN_ARGS[@]}")
                    echo "${UI_TEXT[NOBU_UPDATE_DOING]}"
                else
                    printf "%s " "${UI_TEXT[NOBU_KIT_ASK_TRANSLATE]}"
                    read -r tr_answer </dev/tty
                    case "$tr_answer" in
                        [Yy]*)
                            nobu_english_args
                            if [[ ${#NOBU_EN_ARGS[@]} -eq 0 ]]; then
                                center_text "${UI_TEXT[NOBU_UPDATE_NO_PACK]}"
                                echo
                                read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
                                echo
                                exit 0
                            fi
                            TR_ARGS=("${NOBU_EN_ARGS[@]}")
                            ;;
                    esac
                fi
                nobu_debugtext
                LOADER_FLAG=""
                if [[ -f "${NOBU_LOADER}" ]]; then
                    LOADER_FLAG="--loader ${NOBU_LOADER}"
                else
                    echo "[!] spoof loader not found at ${NOBU_LOADER}; installing with the disc's stock dnasload (will NOT boot past the DNAS check)." >> "${LOG_FILE}"
                fi
                [[ -z "${NOBU_UPDATE}" ]] && echo "${UI_TEXT[NOBU_KIT_INSTALLING]}"
                sudo -E env PYTHONPATH="${HELPER_DIR}" "${NOBU_PY}" \
                    "${NOBU_INSTALL_PY}" "${DEVICE}" \
                    --disc "${NOBU_DISC}" \
                    --hddid "${POL_HDDID_FILE}" \
                    --helper "${HELPER_DIR}" \
                    --pfsshell "${HELPER_DIR}/PFS Shell.elf" \
                    --work "${WORK_DIR}/stage" \
                    ${LOADER_FLAG} ${UPDATE_FLAG} \
                    --write "${TR_ARGS[@]}" \
                    2>&1 | tee -a "${LOG_FILE}" | grep -v '^   kept ' | sed 's/^/  /'
                [[ ${PIPESTATUS[0]} -eq 0 ]] || error_msg "${UI_TEXT[NOBU_KIT_ERROR]}"
                NOBU_INSTALLED_NOW=1
                [[ "${DEBUG_TEXT}" == 1 || "${NOBU_TRACE:-0}" == 1 ]] && nobu_trace_arm
                nobu_accessflag
                if [[ "${TR_ARGS[0]}" != --no-translation ]]; then
                    nobu_retitle english
                else
                    nobu_retitle japanese
                fi
                ;;
        esac
    fi
elif [[ -f "${NOBU_KIT}" ]]; then
    # Legacy pre-built kit. Retained for the transition; the disc path above
    # is the supported one going forward.
    echo
    if [[ ! -f "${POL_HDDID_FILE}" ]]; then
        center_text "${UI_TEXT[NOBU_KIT_NEEDS_HDDID]}"
    else
        printf "%s " "${UI_TEXT[NOBU_KIT_ASK]}"
        read -r answer </dev/tty
        case "$answer" in
            [Yy]*)
                TR_FLAG=""
                if nobu_has_translation; then
                    printf "%s " "${UI_TEXT[NOBU_KIT_ASK_TRANSLATE]}"
                    read -r tr_answer </dev/tty
                    case "$tr_answer" in [Yy]*) TR_FLAG="--translate";; esac
                fi
                echo "${UI_TEXT[NOBU_KIT_INSTALLING]}"
                bash "${NOBU_KIT}" --device "${DEVICE}" --hddid "${POL_HDDID_FILE}" \
                    --helper "${HELPER_DIR}" --log "${LOG_FILE}" ${TR_FLAG} \
                    2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
                [[ ${PIPESTATUS[0]} -eq 0 ]] || error_msg "${UI_TEXT[NOBU_KIT_ERROR]}"
                NOBU_INSTALLED_NOW=1
                nobu_accessflag
                if [[ -n "${TR_FLAG}" ]]; then
                    nobu_retitle english
                else
                    nobu_retitle japanese
                fi
                ;;
        esac
    fi
fi

echo
if [[ ${NOBU_INSTALLED_NOW} -eq 1 && -n "${NOBU_UPDATE}" ]]; then
    center_text "${UI_TEXT[NOBU_UPDATE_DONE]}"
elif [[ ${NOBU_INSTALLED_NOW} -eq 1 ]]; then
    center_text "${UI_TEXT[NOBU_KIT_DONE]}"
else
    center_text "${UI_TEXT[NOBU_READY]}"
    [[ "${INFO[netcnf]}" == "present" ]] || center_text "${UI_TEXT[NOBU_NETCNF_MISSING]}"
    # The PC-side install did not run: say WHY, so a prepared-only drive is not a
    # mystery. It needs both the disc extract and the install tools.
    if [[ ! -f "${NOBU_DISC}/SYSTEM.CNF" || ! -d "${NOBU_DISC}/AUTH" ]]; then
        center_text "To install now: put your Hiryuu no Shou disc .iso in ${NOBU_DIR} and run this step again"
        echo "  install skipped: no disc extract at ${NOBU_DISC} (need SYSTEM.CNF + AUTH/)" >> "${LOG_FILE}"
    fi
    if [[ ! -f "${NOBU_INSTALL_PY}" ]]; then
        center_text "Install tools not found - update the toolkit (scripts/helper/nobunaga/tools)."
        echo "  install skipped: nobuinstall.py not found (looked in ${NOBU_TOOLS})" >> "${LOG_FILE}"
    fi
fi
echo
center_text "${UI_TEXT[NOBU_BACKUPS]} ${BACKUP_DIR}"
echo

# Register this title's partition in protect-parts.list (the standing pattern:
# an installer owns its keep-list entry), so PSBBN's Game-Installer keeps it on
# every game add. Idempotent; safe if the list already has it.
OPL_PROT_MNT="$(mktemp -d)"
if sudo mount "${DEVICE}3" "${OPL_PROT_MNT}" >> "${LOG_FILE}" 2>&1; then
    sudo touch "${OPL_PROT_MNT}/protect-parts.list"
    sudo grep -qxF "PP.SLPM-65197.KOEI.NOBUON" "${OPL_PROT_MNT}/protect-parts.list" 2>/dev/null \
        || echo "PP.SLPM-65197.KOEI.NOBUON" | sudo tee -a "${OPL_PROT_MNT}/protect-parts.list" >/dev/null
    sync
    sudo umount "${OPL_PROT_MNT}"
    echo "Nobunaga partition registered in protect-parts.list." >> "${LOG_FILE}"
else
    echo "[!] could not mount exFAT to update protect-parts.list; a future PSBBN game add may drop the Nobunaga partition." >> "${LOG_FILE}"
fi
rmdir "${OPL_PROT_MNT}" 2>/dev/null

read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
echo
