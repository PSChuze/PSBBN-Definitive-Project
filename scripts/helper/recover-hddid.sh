#!/usr/bin/env bash
#
# PlayOnline installer for the PSBBN Definitive Project
# Copyright (C) 2026 PrettyOpenLobby
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Sourced by the title installers. Defines recover_drive_hddid.
#
# Every title on a drive is keyed to the one HDD ID the PlayOnline step mints,
# and the minted games/POL/playonline.hddid stays on the PC that ran that
# step. A drive moved to a new machine (or a games folder that was not copied
# along) therefore looked like "PlayOnline was never installed", even with the
# Viewer sitting on the drive. The ID is not lost: every filled loader on the
# drive carries it for its shim to serve, so it is read back out of
# pfs:/dnasload.elf (playonline.hddid --recover). Read-only on the drive.

: "${UI_TEXT[HDDID_RECOVER_RUNNING]:=No saved drive ID on this machine. Looking for one on the drive (PlayOnline or another title installed earlier)...}"
: "${UI_TEXT[HDDID_RECOVER_DONE]:=Recovered the drive ID from the drive and saved it to:}"
: "${UI_TEXT[HDDID_RECOVER_NONE]:=No installed title on this drive carries a drive ID.}"

# recover_drive_hddid OUT DEVICE PYTHON LOG
# Returns 0 when OUT exists afterwards, 1 when nothing could be recovered.
recover_drive_hddid() {
    local out="$1" dev="$2" py="$3" log="$4"
    [[ -f "$out" ]] && return 0
    [[ -n "$dev" ]] || return 1
    echo "  ${UI_TEXT[HDDID_RECOVER_RUNNING]}"
    # The kernel can hold stale pages for a drive that was written elsewhere.
    sudo blockdev --flushbufs "$dev" >/dev/null 2>&1
    mkdir -p "$(dirname "$out")"
    if sudo -E env PYTHONPATH="${HELPER_DIR}" "$py" -m playonline.hddid \
            --recover "$out" --device "$dev" >> "$log" 2>&1 && [[ -f "$out" ]]; then
        sudo chown "$(id -u):$(id -g)" "$out" 2>/dev/null
        echo "  ${UI_TEXT[HDDID_RECOVER_DONE]} ${out}"
        echo "HDD ID: recovered from ${dev} -> ${out}" >> "$log"
        return 0
    fi
    echo "  ${UI_TEXT[HDDID_RECOVER_NONE]}"
    echo "HDD ID: nothing to recover on ${dev}" >> "$log"
    return 1
}
