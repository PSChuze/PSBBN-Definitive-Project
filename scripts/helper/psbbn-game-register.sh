#!/usr/bin/env bash
#
# PSBBN game-list registration for the PSBBN Definitive Project
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
# Add one direct-to-drive game to PSBBN's games menu.
#
# PSBBN lists games from the `sce_game` table of
# __linux.7/database/sqlite/game.db. The BB Navigator fills that table from
# each PP.* partition's /res/info.sys when it (re)builds the table, but it does
# not notice a partition that a PC-side installer wrote after the table already
# existed. So a game installed directly to the drive is present yet missing from
# the menu until its row is added. This reads the partition's /res/info.sys and
# APA metadata, then writes the exact row the Navigator would (an upsert keyed on
# the partition's uri, so re-running an install or update is safe), leaving every
# other row and the Navigator's own sort order untouched.
#
# It never touches the HOSDMenu attribute area (that is the installer's own
# build_attr / retitle), the exFAT keep-list, or any partition's contents.
#
# Usage: psbbn-game-register.sh DEVICE PARTITION HELPER_DIR [LOG_FILE]
#
# Best-effort: any failure is reported on stderr and returns non-zero so the
# caller can warn, but it is not fatal to an install.

set -u

DEVICE="${1:-}"
PART="${2:-}"
HELPER_DIR="${3:-}"
LOG_FILE="${4:-/dev/null}"

if [[ -z "$DEVICE" || -z "$PART" || -z "$HELPER_DIR" ]]; then
    echo "usage: psbbn-game-register.sh DEVICE PARTITION HELPER_DIR [LOG_FILE]" >&2
    exit 2
fi

if [[ "$(uname -m)" == "x86_64" ]]; then
    HDL_DUMP="${HELPER_DIR}/HDL Dump.elf"
    PFS_SHELL="${HELPER_DIR}/PFS Shell.elf"
    SQLITE="${HELPER_DIR}/sqlite"
else
    HDL_DUMP="${HELPER_DIR}/aarch64/HDL Dump.elf"
    PFS_SHELL="${HELPER_DIR}/aarch64/PFS Shell.elf"
    SQLITE="${HELPER_DIR}/aarch64/sqlite"
fi
ROW_PY="${HELPER_DIR}/psbbn-sce-game-row.py"

log() { echo "$*" >> "$LOG_FILE" 2>/dev/null; }
fail() { log "[!] PSBBN game list: $*"; echo "[!] PSBBN game list: $*" >&2; exit 1; }

TMP="$(mktemp -d)"
LOOP=""
MNT=""
cleanup() {
    [[ -n "$MNT" ]] && sudo umount "$MNT" 2>/dev/null
    [[ -n "$LOOP" ]] && sudo losetup -d "$LOOP" 2>/dev/null
    rm -rf "$TMP"
}
trap cleanup EXIT

# Drop any stale page cache the kernel still holds for the drive, so the APA
# line, header and /res/info.sys we read are what the install just wrote.
sudo blockdev --flushbufs "$DEVICE" >/dev/null 2>&1 || true

# --- the partition's APA line: start LBA (hex) and total size in MB ----------
TOC="$(sudo "$HDL_DUMP" toc "$DEVICE" 2>>"$LOG_FILE")" || fail "could not read the partition table"
LINE="$(printf '%s\n' "$TOC" | awk -v p="$PART" '$NF==p {print; exit}')"
[[ -n "$LINE" ]] || fail "partition $PART not found on $DEVICE"
START_HEX="$(printf '%s\n' "$LINE" | awk '{print $2}')"; START_HEX="${START_HEX%%.*}"
SIZE_MB="$(printf '%s\n' "$LINE" | awk '{print $4}')"; SIZE_MB="${SIZE_MB%MB}"
[[ "$START_HEX" =~ ^[0-9a-fA-F]+$ && "$SIZE_MB" =~ ^[0-9]+$ ]] || fail "could not parse the APA line for $PART"
START_DEC=$((16#$START_HEX))

# --- the APA install timestamp (8-byte ps2 time at the header's +0x50) -------
HDR="$(sudo dd if="$DEVICE" bs=512 skip="$START_DEC" count=1 2>/dev/null | xxd -p -c 512)"
D="${HDR:160:16}"   # 0x50 * 2 hex chars per byte
[[ ${#D} -eq 16 ]] || fail "could not read the APA header for $PART"
SEC=$((16#${D:2:2})); MIN=$((16#${D:4:2})); HOUR=$((16#${D:6:2}))
DAY=$((16#${D:8:2})); MON=$((16#${D:10:2})); YEAR=$((16#${D:14:2}${D:12:2}))
INSTALL_DATE="$(printf '%04d%02d%02d%02d%02d%02d' "$YEAR" "$MON" "$DAY" "$HOUR" "$MIN" "$SEC")"

# --- the partition's /res/info.sys (the same file the Navigator reads) -------
printf 'device %s\nmount %s\ncd res\nlcd %s\nget info.sys\nexit\n' \
    "$DEVICE" "$PART" "$TMP" | sudo "$PFS_SHELL" >> "$LOG_FILE" 2>&1
[[ -f "$TMP/info.sys" ]] || fail "$PART has no res/info.sys"
sudo chown "$(id -u)" "$TMP/info.sys" 2>/dev/null

python3 "$ROW_PY" "$TMP/info.sys" "$PART" "$SIZE_MB" "$INSTALL_DATE" > "$TMP/row.sql" \
    || fail "could not build the game-list row"

# --- __linux.7 as ext2 (the dm table hdl_dump prints gives the exact slice) --
BASE="$(basename "$DEVICE")"
DM="$(sudo "$HDL_DUMP" toc "$DEVICE" --dm 2>>"$LOG_FILE" | tr ';' '\n' | grep -E "^${BASE}-__linux\.7," | head -n1)"
[[ -n "$DM" ]] || fail "no __linux.7 partition (is this a PSBBN drive?)"
TBL="${DM##*rw,}"
L7_SIZE="$(printf '%s\n' "$TBL" | awk '{print $2}')"
L7_OFF="$(printf '%s\n' "$TBL" | awk '{print $5}')"
[[ "$L7_SIZE" =~ ^[0-9]+$ && "$L7_OFF" =~ ^[0-9]+$ ]] || fail "could not parse the __linux.7 slice"

LOOP="$(sudo losetup -f --show -o $((L7_OFF * 512)) --sizelimit $((L7_SIZE * 512)) "$DEVICE" 2>>"$LOG_FILE")" \
    || fail "could not attach __linux.7"
MNT="$TMP/l7"; mkdir -p "$MNT"
sudo mount -t ext2 -o rw "$LOOP" "$MNT" 2>>"$LOG_FILE" || fail "could not mount __linux.7"

GAMEDB="$MNT/database/sqlite/game.db"
if [[ ! -f "$GAMEDB" ]]; then
    # No database yet: the Navigator builds it from all PP.* partitions on its
    # next boot, which will include this one. Nothing to do.
    log "PSBBN game list: game.db not present yet; the Navigator will build it on next boot."
    exit 0
fi

# The bundled sqlite CLI reports a bad statement on its output but still exits 0,
# so treat any output as a failure (a clean upsert prints nothing).
SQL_OUT="$(sudo "$SQLITE" "$GAMEDB" < "$TMP/row.sql" 2>&1)"
if [[ $? -ne 0 || -n "$SQL_OUT" ]]; then
    log "sqlite: $SQL_OUT"
    fail "sqlite upsert failed"
fi
sync
log "PSBBN game list: registered $PART (size ${SIZE_MB}MB, installed ${INSTALL_DATE})."
exit 0
