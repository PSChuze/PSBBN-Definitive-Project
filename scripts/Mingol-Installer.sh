#!/usr/bin/env bash
#
# Minna no Golf Online Installer for the PSBBN Definitive Project
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
# Installs Minna no Golf Online (SCPS-15049) onto the drive from the Extras
# menu. Fully PC-side, no console step, and everything comes from the player's
# own discs (ported from HippaulInstaller's playonline/games/mingol).
#
# One partition, PP.SCPS-15049..APPLICATION, that boots via the disc-less loader
# in `BOOT2 = pfs:/dnasload.elf`. scripts/helper/mingol/stage builds it:
#   - the nine ZZENC containers are decrypted off the disc and sealed to this
#     drive's HDD ID and the four of its __net record (read, never written:
#     PlayOnline shares that record);
#   - the disc's boot ELF and DNAS.BIN get the disc-less edits (guarded, the
#     result checked against the proven SHA-1s);
#   - the IOP reboot image is the disc's 2.70 kernel (FMOD/DNAS270.IMG) as
#     it is; UDNL takes SYSMEM from the console's rom0 at the reboot (the
#     loader's BIOS-ROM SYSMEM splice hung on real hardware on 2026-10-08
#     and is built out, ROM_SYSMEM=0);
#   - the disc's FMOD/ and FMOD2/ IOP modules go into the partition, where the
#     loader's shim sends the game's cdrom0 module loads (no disc needed);
#   - the attribute area is built from the disc's own icon;
#   - the signed loader scripts/assets/mingol/polbbnexec-mingol.kelf is filled
#     with the patched boot ELF, the reboot image, the disc's DEV9/ATAD/HDD/PFS
#     IRXs (ATAD with its genuine-drive check skipped) and the drive's HDD ID,
#     and goes in as pfs:/dnasload.elf;
#   - the game is pointed at the revival's servers: ADDRESS.XB rebuilt
#     from the disc's, and the revival's Feega CA staged as ROOT_ED.PEM,
#     which the loader's shim serves for cdrom0:\FRES\ROOT_ED.PEM;1.
#     MINGOL_SERVERS=stock keeps the disc's own (servers run under the
#     original names).
#
# The user supplies:
#   games/GOLF/        the SCPS-15049 .iso (here or in disc/), or the extracted
#                      tree at disc/ (SYSTEM.CNF, ZZBIN/, ZZENC/, FMOD/, ...).
#                      An existing games/MGO/ from older releases still works.
#   games/POL/playonline.hddid  minted by the PlayOnline step, or recovered
#                      from the drive when that step ran on another machine

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
LOG_FILE="${LOGS_DIR}/mingol-installer.log"
GAMES_PATH="${TOOLKIT_PATH}/games"
MINGOL_ASSETS="${ASSETS_DIR}/mingol"
WORK_DIR="${SCRIPTS_DIR}/tmp/mingol"
# The in-place update (playonline.lib.pfsupdate) refuses a stage path with a
# space in it; a toolkit checked out under such a path (e.g. "PlayOnline
# Project") stages in /tmp instead.
if [[ "${WORK_DIR}" =~ [[:space:]] ]]; then
    WORK_DIR="${TMPDIR:-/tmp}/psbbn-mingol-$(id -u)"
fi

arch="$(uname -m)"
if [[ "$arch" = "x86_64" ]]; then
    HDL_DUMP="${HELPER_DIR}/HDL Dump.elf"
    PFS_SHELL="${HELPER_DIR}/PFS Shell.elf"
else
    HDL_DUMP="${HELPER_DIR}/aarch64/HDL Dump.elf"
    PFS_SHELL="${HELPER_DIR}/aarch64/PFS Shell.elf"
fi

LANG_FILE="$1"
shift
path_arg=""
[[ -n "$1" && "$1" == /* ]] && path_arg="$1"
# Extras has already found the drive and passes it on.
DEVICE="${2:-}"

# The folder was games/MGO/ before it was renamed (MGO reads as Metal Gear
# Online). A setup that still has only the old folder, or sets the old
# variable names, keeps working.
: "${GOLF_DIR_OVERRIDE:=${MGO_DIR_OVERRIDE:-}}"
: "${GOLF_DISC_IMAGE:=${MGO_DISC_IMAGE:-}}"
GOLF_DIR="${GAMES_PATH}/GOLF"
[[ -n "${path_arg}" ]] && GOLF_DIR="${path_arg}/GOLF"
[[ ! -d "${GOLF_DIR}" && -d "$(dirname "${GOLF_DIR}")/MGO" ]] && GOLF_DIR="$(dirname "${GOLF_DIR}")/MGO"
[[ -n "${GOLF_DIR_OVERRIDE}" ]] && GOLF_DIR="${GOLF_DIR_OVERRIDE}"
# The PlayOnline step's drive ID. Never minted here; the sealed containers and
# the loader's atadpatch shim key to this exact 512-byte block.
POL_HDDID_FILE="${POL_HDDID:-$(dirname "${GOLF_DIR}")/POL/playonline.hddid}"

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

# English fallbacks for the Minna-specific strings so a lang file without them
# still shows English rather than a bare key.
: "${UI_TEXT[GOLF_TITLE]:=Minna no Golf Online Installer}"
: "${UI_TEXT[GOLF_ERROR_SUDO]:=This step needs administrator rights and the password was not accepted.}"
: "${UI_TEXT[GOLF_ERROR_NO_DEVICE]:=No PSBBN drive was found. Connect the drive and try again.}"
: "${UI_TEXT[GOLF_NO_DISC]:=The disc tree of the game was not found in}"
: "${UI_TEXT[GOLF_DISC_HINT]:=Put the SCPS-15049 disc image (.iso) in this folder, or the extracted disc tree in disc/ (SYSTEM.CNF, ZZBIN/, FMOD/, res/).}"
: "${UI_TEXT[GOLF_EXTRACT_FOUND]:=Found the disc image:}"
: "${UI_TEXT[GOLF_ERROR_LOADER]:=The Minna no Golf Online loader is missing from scripts/assets/mingol/. Update the toolkit and try again.}"
: "${UI_TEXT[GOLF_HDDID_FOUND]:=The PlayOnline drive ID was found. Minna no Golf Online will share it:}"
: "${UI_TEXT[GOLF_HDDID_FAIL]:=No PlayOnline drive ID was found. Run the PlayOnline step first: it mints the ID Minna needs.}"
: "${UI_TEXT[GOLF_NO_ICON]:=No browser icon found; the game will boot but the drive shows the art from the disc.}"
: "${UI_TEXT[GOLF_INSTALLED]:=Minna no Golf Online is already on this drive.}"
: "${UI_TEXT[GOLF_PLAN]:=This step will create one partition:}"
: "${UI_TEXT[GOLF_PLAN_PART]:=PP.SCPS-15049..APPLICATION - the game (about 1.5 GB)}"
: "${UI_TEXT[GOLF_PLAN_SEAL]:=seal the nine game containers to this drive (they are keyed to the drive ID)}"
: "${UI_TEXT[GOLF_PLAN_BOOT]:=install a disc-less loader so the title boots from HDD, no disc required}"
: "${UI_TEXT[GOLF_DOING]:=Installing Minna no Golf Online (this can take several minutes)...}"
: "${UI_TEXT[GOLF_ERROR_INSTALL]:=The install failed. See logs/mingol-installer.log.}"
: "${UI_TEXT[GOLF_ERROR_RECORD]:=The drive’s shared DNAS record could not be used, so nothing was written. Please send logs/mingol-installer.log: it holds a read-only dump of the record.}"
: "${UI_TEXT[GOLF_RECORD_REPAIR]:=Putting back the PlayOnline step’s DNAS record (only if the one on the drive cannot be read with any known drive ID)...}"
: "${UI_TEXT[GOLF_DONE]:=Minna no Golf Online was installed.}"
: "${UI_TEXT[GOLF_DONE_HINT]:=It appears in the browser; it boots with no disc.}"
: "${UI_TEXT[GOLF_ASK_TRANSLATE]:=Install the English translation? It is downloaded from openlobby.fyi. (y/N)}"

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

    __  ____                                     ______      ______   ____        ___
   /  |/  (_)___  ____  ____ _   ____  ____     / ____/___  / / __/  / __ \____  / (_)___  ___
  / /|_/ / / __ \/ __ \/ __ `/  / __ \/ __ \   / / __/ __ \/ / /_   / / / / __ \/ / / __ \/ _ \
 / /  / / / / / / / / / /_/ /  / / / / /_/ /  / /_/ / /_/ / / __/  / /_/ / / / / / / / / /  __/
/_/  /_/_/_/ /_/_/ /_/\__,_/  /_/ /_/\____/   \____/\____/_/_/     \____/_/ /_/_/_/_/ /_/\___/

EOF
}

# The venv's python3 (sudo resets PATH).
GOLF_PY="${SCRIPTS_DIR}/venv/bin/python3"
[[ -x "${GOLF_PY}" ]] || GOLF_PY="python3"

# The installer's Python is the package scripts/helper/mingol/stage
# (`python -m mingol.stage` stages, `python -m mingol.stage.write` writes); it
# uses playonline's attrarea, discs, loader and lib, also under scripts/helper.
mgopy() {
    PYTHONPATH="${HELPER_DIR}" "${GOLF_PY}" "$@"
}
mgosudo() {
    sudo -E env PYTHONPATH="${HELPER_DIR}" "${GOLF_PY}" "$@"
}

# The DNAS overlay reads the access_flag25 record at __net+0x202000 before it
# decrypts a container and fails with -101 when it is not there (proven under
# PCSX2, 2026-10-05). Which console the record names does not matter (the
# patched DNAS.BIN skips the console check), so Nobunaga's tool writes the
# same record Nobunaga and Bomberman use: only that record, after backing up
# what is there, leaving the shared PlayOnline record at +0x201800 untouched.
# Run on every pass, so a drive installed before this gets it too.
mgo_accessflag() {
    local backup="${GOLF_DIR}/backups/$(basename "${DEVICE}")"
    mkdir -p "${backup}"
    if mgosudo -m nobunaga.accessflag "${DEVICE}" --write --save "${backup}" >> "${LOG_FILE}" 2>&1; then
        echo "  DNAS boot record in place (__net+0x202000); the PlayOnline record is untouched."
    else
        echo "  [!] could not write the DNAS boot record; see logs/mingol-installer.log"
    fi
}

# Boot debug text, asked once before the stage (scripts/helper/debugtext.sh):
# Y stages the FORK_VERBOSE twin of the loader, which prints every stage on the
# TV and stops with the reason when one fails, and arms the boot record (a
# POLTRACEMGOETRC1-tagged trace.bin in the partition, the loader's TRACELBA
# slot pointed at it); N the silent loader with the slot at 0 (off).
source "${HELPER_DIR}/debugtext.sh"

mgo_trace_arm() {
    local part="PP.SCPS-15049..APPLICATION"
    if debugtext_trace_arm "${DEVICE}" "${part}" "${part}" POLTRACEMGOETRC1 \
            "${STAGE_DIR}/tree/dnasload.elf"; then
        echo "  ${UI_TEXT[DEBUG_TEXT_TRACE_ON]} ${DEBUG_TRACE_LBA}."
    else
        echo "  ${UI_TEXT[DEBUG_TEXT_TRACE_FAIL]}"
    fi
}

on_exit() {
    [[ -n "${SUDO_KEEPALIVE}" ]] && kill "${SUDO_KEEPALIVE}" 2>/dev/null
    return 0
}
trap on_exit EXIT

SPLASH
center_text "${UI_TEXT[GOLF_TITLE]}"
echo
echo "=== run $(date) ===" >> "${LOG_FILE}"

"${GOLF_PY}" -c "import Crypto" 2>/dev/null || "${GOLF_PY}" -m pip install pycryptodome >> "${LOG_FILE}" 2>&1 || {
    echo "[X] Error: could not install pycryptodome into the venv." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[ERROR_ACTIVATE_PYTHON]}"
}
sudo -v || error_msg "${UI_TEXT[GOLF_ERROR_SUDO]}"
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
    error_msg "${UI_TEXT[GOLF_ERROR_NO_DEVICE]}"
fi
DRIVE_UUID=$(grep -o ' UUID="[^"]*"' <<< "$line" | head -1 | cut -d'"' -f2)
echo "Device: ${DEVICE} (UUID ${DRIVE_UUID:-none})" >> "${LOG_FILE}"

if ! sudo "${HDL_DUMP}" toc "${DEVICE}" >> "${LOG_FILE}" 2>&1; then
    error_msg "${UI_TEXT[ERROR_HDL_TOC]}"
fi

# ---- user files ---------------------------------------------------------
# The disc: an extracted tree at games/GOLF/disc/ is used as is; otherwise the
# .iso in games/GOLF/ or games/GOLF/disc/ (GOLF_DISC_IMAGE picks one explicitly)
# is read directly, no extraction to disk needed.
GOLF_DISC="${GOLF_DIR}/disc"
GOLF_SRC=""
if [[ -f "${GOLF_DISC}/SYSTEM.CNF" && -d "${GOLF_DISC}/ZZBIN" && -d "${GOLF_DISC}/ZZENC" && -d "${GOLF_DISC}/FMOD" ]]; then
    GOLF_SRC="${GOLF_DISC}"
else
    GOLF_SRC="${GOLF_DISC_IMAGE:-}"
    if [[ -z "${GOLF_SRC}" ]]; then
        for cand in "${GOLF_DIR}"/*.iso "${GOLF_DIR}"/*.ISO "${GOLF_DISC}"/*.iso "${GOLF_DISC}"/*.ISO; do
            [[ -f "$cand" ]] && { GOLF_SRC="$cand"; break; }
        done
    fi
    if [[ -z "${GOLF_SRC}" || ! -f "${GOLF_SRC}" ]]; then
        echo "[X] Error: no SCPS-15049 image or extracted tree in ${GOLF_DIR}" >> "${LOG_FILE}"
        error_msg "$(printf '%s %s\n%s' "${UI_TEXT[GOLF_NO_DISC]}" "${GOLF_DIR}" "${UI_TEXT[GOLF_DISC_HINT]}")"
    fi
    echo "  ${UI_TEXT[GOLF_EXTRACT_FOUND]} $(basename "${GOLF_SRC}")"
fi
echo "Disc: ${GOLF_SRC}" >> "${LOG_FILE}"

# ---- the signed loader (ship-side) --------------------------------------
# The silent loader and its FORK_VERBOSE twin (boot debug text); both were
# booted on the console with the BIOS-ROM SYSMEM splice built out.
LOADER_KELF="${MINGOL_ASSETS}/polbbnexec-mingol.kelf"
LOADER_KELF_VERBOSE="${MINGOL_ASSETS}/polbbnexec-mingol-verbose.kelf"
if [[ ! -f "${LOADER_KELF}" ]]; then
    echo "[X] Missing loader: ${LOADER_KELF}" >> "${LOG_FILE}"
    error_msg "${UI_TEXT[GOLF_ERROR_LOADER]}"
fi

# ---- served drive ID ----------------------------------------------------
# On a machine that never ran the PlayOnline step, read it back from a loader
# already on the drive.
source "${HELPER_DIR}/recover-hddid.sh"
recover_drive_hddid "${POL_HDDID_FILE}" "${DEVICE}" "${GOLF_PY}" "${LOG_FILE}"
if [[ ! -f "${POL_HDDID_FILE}" ]]; then
    echo "[X] Error: no PlayOnline drive ID at ${POL_HDDID_FILE}" >> "${LOG_FILE}"
    error_msg "${UI_TEXT[GOLF_HDDID_FAIL]}"
fi
echo "  ${UI_TEXT[GOLF_HDDID_FOUND]} ${POL_HDDID_FILE}"
echo "HDD ID: ${POL_HDDID_FILE}" >> "${LOG_FILE}"
echo

# ---- installed check ----------------------------------------------------
# Already on the drive: offer an in-place update. The game is staged again
# exactly as a new install stages it (this toolkit's fixes, loader and
# translation) and mingol.stage.write --update rewrites only the files that
# changed or are new; every file the game made for itself (saves, settings)
# stays, as do the partition and its passwords.
: "${UI_TEXT[GOLF_UPDATE_ASK]:=Update it to the version this toolkit installs? Your saves and settings are kept.}"
: "${UI_TEXT[GOLF_UPDATE_OPT1]:=Update (keep saves)}"
: "${UI_TEXT[GOLF_UPDATE_OPT2]:=Exit}"
: "${UI_TEXT[GOLF_UPDATE_LANG]:=Language of the game after the update:}"
: "${UI_TEXT[GOLF_UPDATE_KEEP]:=Keep it as installed}"
: "${UI_TEXT[GOLF_UPDATE_EN]:=English (the translation is downloaded from openlobby.fyi)}"
: "${UI_TEXT[GOLF_UPDATE_JA]:=Japanese (as on the disc)}"
: "${UI_TEXT[GOLF_UPDATE_CHOICE]:=Choose:}"
: "${UI_TEXT[GOLF_UPDATE_OLD]:=This copy was installed by the older kit-based installer and cannot be updated in place.}"
: "${UI_TEXT[GOLF_REINSTALL_ASK]:=Uninstall it and install it again now? Your saves and settings are copied to the PC first and put back afterwards. (y/N)}"
: "${UI_TEXT[GOLF_REINSTALL_SAVES]:=If anything goes wrong after the old copy is removed, your saves are in:}"
: "${UI_TEXT[GOLF_REINSTALL_DONE]:=Minna no Golf Online was reinstalled. Your saves were kept.}"
: "${UI_TEXT[GOLF_UPDATE_DOING]:=Updating Minna no Golf Online (this can take several minutes)...}"
: "${UI_TEXT[GOLF_UPDATE_DONE]:=Minna no Golf Online was updated. Your saves were kept.}"
GOLF_UPDATE=""
GOLF_REINSTALL=""
GOLF_PRESENT=""
mgo_state=""
if sudo "${HDL_DUMP}" toc "${DEVICE}" 2>>"${LOG_FILE}" | grep -q -- "PP.SCPS-15049..APPLICATION"; then
    GOLF_PRESENT=1
    center_text "${UI_TEXT[GOLF_INSTALLED]}"
    echo
    mgo_accessflag
    echo
    mgo_state=$(mgosudo -m mingol.stage.write "${DEVICE}" --probe 2>>"${LOG_FILE}")
    echo "Installed: ${mgo_state:-unreadable}" >> "${LOG_FILE}"
fi
# The old kit-based layout cannot take an in-place update: offer to replace it,
# carrying the saves over (stage.write --reinstall), then go on as a fresh install.
if [[ "${mgo_state}" == "old" ]]; then
    center_text "${UI_TEXT[GOLF_UPDATE_OLD]}"
    echo
    printf "%s " "${UI_TEXT[GOLF_REINSTALL_ASK]}"
    read -r answer </dev/tty
    case "$answer" in
        [Yy]*) GOLF_REINSTALL=1; echo ;;
        *) exit 0 ;;
    esac
elif [[ -n "${GOLF_PRESENT}" ]]; then
    if [[ "${mgo_state}" != "english" && "${mgo_state}" != "japanese" ]]; then
        error_msg "${UI_TEXT[GOLF_ERROR_INSTALL]}"
    fi
    center_text "${UI_TEXT[GOLF_UPDATE_ASK]}"
    echo
    echo "  1) ${UI_TEXT[GOLF_UPDATE_OPT1]}"
    echo "  2) ${UI_TEXT[GOLF_UPDATE_OPT2]}"
    echo
    printf "%s " "${UI_TEXT[GOLF_UPDATE_CHOICE]}"
    read -r answer </dev/tty
    [[ "$answer" == "1" ]] || exit 0
    echo
    echo "${UI_TEXT[GOLF_UPDATE_LANG]}"
    echo "  1) ${UI_TEXT[GOLF_UPDATE_KEEP]} (${mgo_state})"
    echo "  2) ${UI_TEXT[GOLF_UPDATE_EN]}"
    echo "  3) ${UI_TEXT[GOLF_UPDATE_JA]}"
    echo
    printf "%s " "${UI_TEXT[GOLF_UPDATE_CHOICE]}"
    read -r answer </dev/tty
    case "$answer" in
        1|"") mgo_lang="${mgo_state}" ;;
        2) mgo_lang="english" ;;
        3) mgo_lang="japanese" ;;
        *) exit 0 ;;
    esac
    GOLF_UPDATE=1
    echo
fi

# ---- the plan -----------------------------------------------------------
if [[ -z "${GOLF_UPDATE}" ]]; then
    center_text "${UI_TEXT[GOLF_PLAN]}"
    echo "  - ${UI_TEXT[GOLF_PLAN_PART]}"
    echo "  - ${UI_TEXT[GOLF_PLAN_SEAL]}"
    echo "  - ${UI_TEXT[GOLF_PLAN_BOOT]}"
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
fi

# ---- stage, then write --------------------------------------------------
# 1. mingol.stage reads the four from this drive's __net record (the record
#    PlayOnline shares; read, never written), seals the nine containers to it
#    and the drive's HDD ID, patches the boot ELF and DNAS.BIN, takes the
#    disc's IOP reboot image, builds the attribute area and fills the signed
#    loader. Under sudo: it reads the drive.
# 2. mingol.stage.write checks the four again, has pfsshell make the 1536 MiB
#    partition and put the tree, sets the MM21 APA passwords, clears the APA
#    journal and writes the attribute area at +0x1000.
# English: the translation pack comes from openlobby.fyi, or from a pack the
# player put in games/GOLF/translation/ when the download cannot be had.
TR_ARGS=()
WRITE_ARGS=()
if [[ -n "${GOLF_UPDATE}" ]]; then
    # Update: the language picked above; write --update rewrites only what changed.
    [[ "${mgo_lang}" == "english" ]] && TR_ARGS=(--translate --translation-dir "${GOLF_DIR}/translation")
    WRITE_ARGS=(--update)
    echo "${UI_TEXT[GOLF_UPDATE_DOING]}"
else
    printf "%s " "${UI_TEXT[GOLF_ASK_TRANSLATE]}"
    read -r tr_answer </dev/tty
    case "$tr_answer" in
        [Yy]*) TR_ARGS=(--translate --translation-dir "${GOLF_DIR}/translation") ;;
    esac
    echo

    if [[ -n "${GOLF_REINSTALL}" ]]; then
        GOLF_SAVES="${GOLF_DIR}/backups/$(basename "${DEVICE}")/saves-$(date +%Y%m%d-%H%M%S)"
        WRITE_ARGS=(--reinstall --saves "${GOLF_SAVES}")
        echo "  ${UI_TEXT[GOLF_REINSTALL_SAVES]} ${GOLF_SAVES}"
        echo
    fi
    echo "${UI_TEXT[GOLF_DOING]}"
fi
echo

debugtext_ask
debugtext_pick "${LOADER_KELF}" "${LOADER_KELF_VERBOSE}"
LOADER_KELF="${DEBUG_LOADER}"

# Servers: by default the stage points the game at the revival's servers
# (ADDRESS.XB, and the Feega CA as ROOT_ED.PEM); MINGOL_SERVERS=stock in
# the environment keeps the disc's server table and Sony's root.
SERVER_ARGS=()
[[ "${MINGOL_SERVERS:-}" == "stock" ]] && SERVER_ARGS=(--stock-servers)

STAGE_DIR="${WORK_DIR}/stage"
# The four is read from the drive: drop any pages the kernel still holds from
# before another machine (or the PlayOnline step) wrote the record.
sudo blockdev --flushbufs "${DEVICE}" >/dev/null 2>&1
# mgo_record_info: a read-only dump of the shared __net record (what it decodes
# to under playonline.hddid, under every ID a loader on the drive serves and
# under the zero ID), for the log a tester sends.
mgo_record_info() {
    echo "---- __net record (read-only) ----" >> "${LOG_FILE}"
    mgosudo -m mingol.stage.write "${DEVICE}" --record-info \
        --hddid "${POL_HDDID_FILE}" >> "${LOG_FILE}" 2>&1
}
# A record no known drive ID decodes can be replaced by the one the PlayOnline
# step mints for this drive ID, on request only (the old sector is saved).
# write.py refuses when the record decodes under any known ID.
if [[ "${MINGOL_REPAIR_RECORD:-}" == 1 ]]; then
    echo "  ${UI_TEXT[GOLF_RECORD_REPAIR]}"
    mgo_record_info
    rec_backup="${GOLF_DIR}/backups/$(basename "${DEVICE}")/net-record-before-repair-$(date +%Y%m%d-%H%M%S).bin"
    mgosudo -m mingol.stage.write "${DEVICE}" --repair-record \
        --hddid "${POL_HDDID_FILE}" --backup "${rec_backup}" --write \
        2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
    # A refusal (the record already decodes, or the loaders disagree) is not
    # fatal: the stage below checks the record again either way.
    [[ ${PIPESTATUS[0]} -eq 0 ]] || echo "  [!] the record was left as it is (see logs/mingol-installer.log)"
    sudo chown -R "$(id -u):$(id -g)" "$(dirname "${rec_backup}")" 2>/dev/null
fi
# mgo_stage_run: stage the install; 0 on success, 2 when the stage refused the
# drive's shared __net record, 1 on any other failure.
mgo_stage_run() {
    mgosudo -m mingol.stage \
        --disc "${GOLF_SRC}" \
        --hddid "${POL_HDDID_FILE}" \
        --out "${STAGE_DIR}" \
        --kelf "${LOADER_KELF}" \
        --device "${DEVICE}" \
        "${TR_ARGS[@]}" \
        "${SERVER_ARGS[@]}" \
        2>&1 | tee -a "${LOG_FILE}" | grep -v '^progress: sealing' | sed 's/^/  /'
    [[ ${PIPESTATUS[0]} -eq 0 ]] && return 0
    tail -n 20 "${LOG_FILE}" | grep -q "__net" && return 2
    return 1
}
# mgo_record_repair: put back the record the PlayOnline step mints for this
# drive ID, after saving the old sector. write.py refuses when the record
# already decodes under any known ID or when the drive's loaders disagree.
mgo_record_repair() {
    local rec_backup
    rec_backup="${GOLF_DIR}/backups/$(basename "${DEVICE}")/net-record-before-repair-$(date +%Y%m%d-%H%M%S).bin"
    mgosudo -m mingol.stage.write "${DEVICE}" --repair-record \
        --hddid "${POL_HDDID_FILE}" --backup "${rec_backup}" --write \
        2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
    local rc=${PIPESTATUS[0]}
    sudo chown -R "$(id -u):$(id -g)" "$(dirname "${rec_backup}")" 2>/dev/null
    return "${rc}"
}
: "${UI_TEXT[GOLF_RECORD_ASK]:=The shared DNAS record on this drive was written for another drive ID, so neither this installer nor the console can read it. Replace it with the record the PlayOnline step makes for this drive? The old one is saved under games/GOLF/backups/. (y/N)}"
: "${UI_TEXT[GOLF_RECORD_REPAIRED]:=The DNAS record was replaced. Staging again...}"
: "${UI_TEXT[GOLF_RECORD_KEPT]:=The record was left as it is.}"
mgo_stage_run; mgo_rc=$?
if [[ ${mgo_rc} -eq 2 ]]; then
    mgo_record_info
    if [[ "${MINGOL_REPAIR_RECORD:-}" == 1 ]]; then
        mgo_ans=y
    else
        echo
        read -r -p "${UI_TEXT[GOLF_RECORD_ASK]} " mgo_ans
    fi
    if [[ "${mgo_ans,,}" == y* ]] && mgo_record_repair; then
        echo "  ${UI_TEXT[GOLF_RECORD_REPAIRED]}"
        sudo blockdev --flushbufs "${DEVICE}" >/dev/null 2>&1
        mgo_stage_run; mgo_rc=$?
    else
        echo "  ${UI_TEXT[GOLF_RECORD_KEPT]}"
    fi
    [[ ${mgo_rc} -eq 0 ]] || error_msg "${UI_TEXT[GOLF_ERROR_RECORD]}"
fi
[[ ${mgo_rc} -eq 0 ]] || error_msg "${UI_TEXT[GOLF_ERROR_INSTALL]}"

# --translate stays Japanese when no pack can be had or it does not fit the
# disc. On a new install that is a working Japanese game, but an update the
# player asked to make English would instead take an English drive back to
# Japanese: stop before anything is written.
: "${UI_TEXT[GOLF_UPDATE_NO_PACK]:=The English translation could not be used (see logs/mingol-installer.log); nothing was changed. Put the pack (.zip) in games/GOLF/translation/ and try again.}"
if [[ -n "${GOLF_UPDATE}" && "${mgo_lang}" == "english" ]] \
        && ! grep -q "overlays installed as plain files" "${STAGE_DIR}/game.json"; then
    echo "[X] Update to English: the stage stayed Japanese; nothing written." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[GOLF_UPDATE_NO_PACK]}"
fi

mgosudo -m mingol.stage.write "${DEVICE}" \
    --stage "${STAGE_DIR}" \
    --hddid "${POL_HDDID_FILE}" \
    --pfsshell "${PFS_SHELL}" \
    "${WRITE_ARGS[@]}" \
    --write 2>&1 | tee -a "${LOG_FILE}" | grep -v '^   kept ' | sed 's/^/  /'
[[ ${PIPESTATUS[0]} -eq 0 ]] || error_msg "${UI_TEXT[GOLF_ERROR_INSTALL]}"
mgo_accessflag
[[ "${DEBUG_TEXT}" == 1 ]] && mgo_trace_arm

# PSBBN's game list shows /res/info.sys, which a partition from the retail or
# the kit-based installer carries and an update keeps: give it the name of the
# language the game is now in (the browser entry already has it, from attr.bin).
mgo_now=$(mgosudo -m mingol.stage.write "${DEVICE}" --probe 2>>"${LOG_FILE}")
if [[ "${mgo_now}" == "english" || "${mgo_now}" == "japanese" ]]; then
    mgosudo -m mingol.stage.retitle "${DEVICE}" "${mgo_now}" --write >> "${LOG_FILE}" 2>&1 \
        || echo "  [!] could not set the PSBBN game-list name; see logs/mingol-installer.log"
fi

echo
if [[ -n "${GOLF_UPDATE}" ]]; then
    center_text "${UI_TEXT[GOLF_UPDATE_DONE]}"
elif [[ -n "${GOLF_REINSTALL}" ]]; then
    center_text "${UI_TEXT[GOLF_REINSTALL_DONE]}"
else
    center_text "${UI_TEXT[GOLF_DONE]}"
fi
echo
center_text "${UI_TEXT[GOLF_DONE_HINT]}"
echo

# Register this title's partition in protect-parts.list, the same way the
# Nobunaga / Bomberman installers do (idempotent).
OPL_PROT_MNT="$(mktemp -d)"
if sudo mount "${DEVICE}3" "${OPL_PROT_MNT}" >> "${LOG_FILE}" 2>&1; then
    sudo touch "${OPL_PROT_MNT}/protect-parts.list"
    sudo grep -qxF "PP.SCPS-15049..APPLICATION" "${OPL_PROT_MNT}/protect-parts.list" 2>/dev/null \
        || echo "PP.SCPS-15049..APPLICATION" | sudo tee -a "${OPL_PROT_MNT}/protect-parts.list" >/dev/null
    sync
    sudo umount "${OPL_PROT_MNT}"
    echo "Minna partition registered in protect-parts.list." >> "${LOG_FILE}"
else
    echo "[!] could not mount exFAT to update protect-parts.list; a future PSBBN game add may drop the Minna partition." >> "${LOG_FILE}"
fi
rmdir "${OPL_PROT_MNT}" 2>/dev/null

read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
echo
