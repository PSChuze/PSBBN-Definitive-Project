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
# menu. Fully PC-side, no console step (the disc contains a DNAS2 container set
# whose seal we can reproduce; see mingol/HANDOFF-install-and-dnas.md).
#
# One partition, PP.SCPS-15049..APPLICATION, that boots via the disc-less loader
# in `BOOT2 = pfs:/dnasload.elf`. The loader is a filled polbbnexec KELF: it
# reboots the IOP with an augmented IOPRP (base kernel + DEV9/ATAD/HDD/PFS.IRX
# from the disc's FMOD/), installs `atadpatch.irx` serving the drive's
# playonline.hddid so the sealed containers decrypt, then ExecPS2s the disc's
# boot ELF, SCPS_150.49. The 0x191600 DNAS-gate is short-circuited in a baked
# patch to SYSTEM.BIN before sealing (mingol/HANDOFF-boot-plan.md, s5 + s2).
#
# The user supplies, under games/MGO/:
#   disc/              the disc tree (SYSTEM.CNF, ZZBIN/, res/, CRS/, MENU/, ...);
#                      obtain via HDL Dump or by extracting the ISO
#   optional:          mingol.ico  (browser icon; the title works without it)
#
# Toolkit ships, under scripts/assets/mingol/:
#   kit/*.kit.json     the nine seal kits (44 KB) that rebuild the drive-form
#                      containers from the disc's plaintext ZZBIN overlays
#   patched/SYSTEM.BIN plaintext SYSTEM.BIN with the 0x1915d0 DNAS bypass baked
#   polbbnexec-mingol.kelf  the signed, unfilled loader (slots for boot ELF,
#                      IOPRP and hddid; filled per install)
#   attr-area.bin      the donor attr with SYSTEM.CNF rewritten to HDD boot
#
# See scripts/helper/mingol for the Python that implements each step.

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

MGO_DIR="${GAMES_PATH}/MGO"
[[ -n "${path_arg}" ]] && MGO_DIR="${path_arg}/MGO"
[[ -n "${MGO_DIR_OVERRIDE}" ]] && MGO_DIR="${MGO_DIR_OVERRIDE}"
# The PlayOnline step's drive ID. Read, never written; the sealed containers and
# the loader's atadpatch shim key to this exact 512-byte block.
POL_HDDID_FILE="${POL_HDDID:-$(dirname "${MGO_DIR}")/POL/playonline.hddid}"

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
: "${UI_TEXT[MGO_TITLE]:=Minna no Golf Online Installer}"
: "${UI_TEXT[MGO_ERROR_SUDO]:=This step needs administrator rights and the password was not accepted.}"
: "${UI_TEXT[MGO_ERROR_NO_DEVICE]:=No PSBBN drive was found. Connect the drive and try again.}"
: "${UI_TEXT[MGO_NO_DISC]:=The game's disc tree was not found in}"
: "${UI_TEXT[MGO_DISC_HINT]:=Extract the SCPS-15049 disc (or ISO) into this folder. It must contain SYSTEM.CNF, ZZBIN/, FMOD/ and res/.}"
: "${UI_TEXT[MGO_HDDID_FOUND]:=The PlayOnline drive ID was found. Minna no Golf Online will share it:}"
: "${UI_TEXT[MGO_HDDID_FAIL]:=No PlayOnline drive ID was found. Run the PlayOnline step first: it mints the ID Minna needs.}"
: "${UI_TEXT[MGO_NO_ICON]:=No browser icon found; the game will boot but the drive shows the disc's own art.}"
: "${UI_TEXT[MGO_INSTALLED]:=Minna no Golf Online is already on this drive.}"
: "${UI_TEXT[MGO_PLAN]:=This step will create one partition:}"
: "${UI_TEXT[MGO_PLAN_PART]:=PP.SCPS-15049..APPLICATION - the game (about 1.5 GB)}"
: "${UI_TEXT[MGO_PLAN_SEAL]:=seal the nine game containers to this drive (they are keyed to the drive's ID)}"
: "${UI_TEXT[MGO_PLAN_BOOT]:=install a disc-less loader so the title boots from HDD, no disc required}"
: "${UI_TEXT[MGO_DOING]:=Installing Minna no Golf Online (this can take several minutes)...}"
: "${UI_TEXT[MGO_ERROR_INSTALL]:=The install failed. See logs/mingol-installer.log.}"
: "${UI_TEXT[MGO_DONE]:=Minna no Golf Online was installed.}"
: "${UI_TEXT[MGO_DONE_HINT]:=It appears in the browser; it boots with no disc.}"
: "${UI_TEXT[MGO_ERROR_ASSETS]:=Kit assets are missing under scripts/assets/mingol/. This toolkit build cannot install Minna.}"

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

              __  ____                        __  _____ ____  __    ______
             /  |/  (_)___  ____  ____ _     / / / ___// __ \/ /   / ____/
            / /|_/ / / __ \/ __ \/ __ `/    / / / __ \/ / / / /   / /_
           / /  / / / / / / / / / /_/ /    / /_/ /_/ / /_/ / /___/ __/
          /_/  /_/_/_/ /_/_/ /_/\__,_/     \____\____/\____/_____/_/
                                          Online (SCPS-15049)

EOF
}

# The venv's python3 (sudo resets PATH). The mingolinstall imports its two
# sibling repos through NOBU_TOOLS / POL_PS2, whose sensible defaults live in
# mingolinstall itself; we set the ones this toolkit knows.
MGO_PY="${SCRIPTS_DIR}/venv/bin/python3"
[[ -x "${MGO_PY}" ]] || MGO_PY="python3"

# The installer's own package. Ships next to this script under scripts/helper/mingol.
MGO_TOOLS="${MGO_TOOLS_OVERRIDE:-${HELPER_DIR}/mingol/tools}"
[[ -f "${MGO_TOOLS}/mingolinstall.py" ]] || MGO_TOOLS="${SCRIPTS_DIR}/../../Minna no Golf Online/mingol/tools"

# mingolinstall's sealkit imports the Nobunaga DNAS2 crypto (dnas2, rc6,
# dnasbundle, dnasdec) via NOBU_TOOLS, and its partition walker + password /
# record helpers via POL_PS2. Both live under scripts/helper/ in this toolkit:
# the four DNAS modules were copied next to mingolinstall.py itself, and
# playonline's lib package (polnetdump/polhdd/polrecord) is at
# scripts/helper/playonline/lib.
mgosudo() {
    sudo -E env PYTHONPATH="${HELPER_DIR}" \
        NOBU_TOOLS="${NOBU_TOOLS:-${MGO_TOOLS}}" \
        POL_PS2="${POL_PS2:-${HELPER_DIR}/playonline/lib}" \
        "${MGO_PY}" "$@"
}

on_exit() {
    [[ -n "${SUDO_KEEPALIVE}" ]] && kill "${SUDO_KEEPALIVE}" 2>/dev/null
    return 0
}
trap on_exit EXIT

SPLASH
center_text "${UI_TEXT[MGO_TITLE]}"
echo
echo "=== run $(date) ===" >> "${LOG_FILE}"

"${MGO_PY}" -c "import Crypto" 2>/dev/null || "${MGO_PY}" -m pip install pycryptodome >> "${LOG_FILE}" 2>&1 || {
    echo "[X] Error: could not install pycryptodome into the venv." >> "${LOG_FILE}"
    error_msg "${UI_TEXT[ERROR_ACTIVATE_PYTHON]}"
}
sudo -v || error_msg "${UI_TEXT[MGO_ERROR_SUDO]}"
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
    error_msg "${UI_TEXT[MGO_ERROR_NO_DEVICE]}"
fi
DRIVE_UUID=$(grep -o ' UUID="[^"]*"' <<< "$line" | head -1 | cut -d'"' -f2)
echo "Device: ${DEVICE} (UUID ${DRIVE_UUID:-none})" >> "${LOG_FILE}"

if ! sudo "${HDL_DUMP}" toc "${DEVICE}" >> "${LOG_FILE}" 2>&1; then
    error_msg "${UI_TEXT[ERROR_HDL_TOC]}"
fi

# ---- user files ---------------------------------------------------------
MGO_DISC="${MGO_DIR}/disc"
if [[ ! -f "${MGO_DISC}/SYSTEM.CNF" ]] || [[ ! -d "${MGO_DISC}/ZZBIN" ]] || [[ ! -d "${MGO_DISC}/FMOD" ]]; then
    echo "[X] Error: ${MGO_DISC} missing SYSTEM.CNF / ZZBIN / FMOD" >> "${LOG_FILE}"
    error_msg "$(printf '%s %s\n%s' "${UI_TEXT[MGO_NO_DISC]}" "${MGO_DISC}" "${UI_TEXT[MGO_DISC_HINT]}")"
fi

# ---- kit assets (ship-side) ---------------------------------------------
KIT_DIR="${MINGOL_ASSETS}/kit"
PATCHED_DIR="${MINGOL_ASSETS}/patched"
LOADER_KELF="${MINGOL_ASSETS}/polbbnexec-mingol.kelf"
ATTR_TEMPLATE="${MINGOL_ASSETS}/attr-area.bin"
for f in "${KIT_DIR}" "${PATCHED_DIR}/SYSTEM.BIN" "${LOADER_KELF}" "${ATTR_TEMPLATE}"; do
    if [[ ! -e "$f" ]]; then
        echo "[X] Missing kit asset: $f" >> "${LOG_FILE}"
        error_msg "${UI_TEXT[MGO_ERROR_ASSETS]}"
    fi
done

# ---- served drive ID ----------------------------------------------------
if [[ ! -f "${POL_HDDID_FILE}" ]]; then
    echo "[X] Error: no PlayOnline drive ID at ${POL_HDDID_FILE}" >> "${LOG_FILE}"
    error_msg "${UI_TEXT[MGO_HDDID_FAIL]}"
fi
echo "  ${UI_TEXT[MGO_HDDID_FOUND]} ${POL_HDDID_FILE}"
echo "HDD ID: ${POL_HDDID_FILE}" >> "${LOG_FILE}"
echo

# ---- installed check ----------------------------------------------------
if sudo "${HDL_DUMP}" toc "${DEVICE}" 2>>"${LOG_FILE}" | grep -q -- "PP.SCPS-15049..APPLICATION"; then
    center_text "${UI_TEXT[MGO_INSTALLED]}"
    echo
    read -n 1 -s -r -p "${UI_TEXT[EXIT_KEY]}" </dev/tty
    echo
    exit 0
fi

# ---- the plan -----------------------------------------------------------
center_text "${UI_TEXT[MGO_PLAN]}"
echo "  - ${UI_TEXT[MGO_PLAN_PART]}"
echo "  - ${UI_TEXT[MGO_PLAN_SEAL]}"
echo "  - ${UI_TEXT[MGO_PLAN_BOOT]}"
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

# ---- build the per-install boot chain -----------------------------------
# 1. Augment the disc's IOPRP with DEV9/ATAD/HDD/PFS from the disc's FMOD.
# 2. Rewrite the donor attr so BOOT2 points at pfs:/dnasload.elf.
# 3. Fill the signed loader with the disc's boot ELF, the augmented IOPRP,
#    and the served drive ID.
# 4. Hand the whole thing to mingolinstall.py, which stages the disc tree,
#    rebuilds each container from the seal kit + the disc's plaintext (with
#    the patched SYSTEM overlay), writes the partition and the attr.
echo "${UI_TEXT[MGO_DOING]}"
echo

AUG_IOPRP="${WORK_DIR}/IOPRP270-augmented.IMG"
"${MGO_PY}" "${MGO_TOOLS}/ioprp_augment.py" "${MGO_DISC}/FMOD/IOPRP270.IMG" \
    --add DEV9="${MGO_DISC}/FMOD/DEV9.IRX" \
    --add ATAD="${MGO_DISC}/FMOD/ATAD.IRX" \
    --add HDD="${MGO_DISC}/FMOD/HDD.IRX" \
    --add PFS="${MGO_DISC}/FMOD/PFS.IRX" \
    -o "${AUG_IOPRP}" 2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
[[ ${PIPESTATUS[0]} -eq 0 ]] || error_msg "${UI_TEXT[MGO_ERROR_INSTALL]}"

ATTR_BOOT="${WORK_DIR}/attr-area-hddboot.bin"
"${MGO_PY}" "${MGO_TOOLS}/attr_rewrite_boot.py" "${ATTR_TEMPLATE}" "${ATTR_BOOT}" \
    >> "${LOG_FILE}" 2>&1 || error_msg "${UI_TEXT[MGO_ERROR_INSTALL]}"

DNASLOAD="${WORK_DIR}/dnasload.elf"
"${MGO_PY}" -m playonline.loader "${LOADER_KELF}" \
    --elf "${MGO_DISC}/SCPS_150.49" \
    --ioprp "${AUG_IOPRP}" \
    --hddid "${POL_HDDID_FILE}" \
    --argv0 "hdd0:PP.SCPS-15049..APPLICATION:pfs:/SCPS_150.49" \
    -o "${DNASLOAD}" 2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
[[ ${PIPESTATUS[0]} -eq 0 ]] || error_msg "${UI_TEXT[MGO_ERROR_INSTALL]}"

# The icon isn't a mingolinstall input yet; the disc's res/ carries a serviceable
# jacket image that BBNav shows. A future toolkit can override it.

mgosudo "${MGO_TOOLS}/mingolinstall.py" "${DEVICE}" \
    --disc "${MGO_DISC}" \
    --kit "${KIT_DIR}" \
    --hddid "${POL_HDDID_FILE}" \
    --four auto \
    --res "${MGO_DISC}/res" \
    --attr "${ATTR_BOOT}" \
    --zzbin-overlay "${PATCHED_DIR}" \
    --loader "${DNASLOAD}" \
    --pfsshell "${PFS_SHELL}" \
    --work "${WORK_DIR}/stage" \
    --write 2>&1 | tee -a "${LOG_FILE}" | sed 's/^/  /'
[[ ${PIPESTATUS[0]} -eq 0 ]] || error_msg "${UI_TEXT[MGO_ERROR_INSTALL]}"

echo
center_text "${UI_TEXT[MGO_DONE]}"
echo
center_text "${UI_TEXT[MGO_DONE_HINT]}"
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
