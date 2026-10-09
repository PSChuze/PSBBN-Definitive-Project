#!/usr/bin/env bash
# Make sure PSBBN's own Feega client is set up for the revival, from a game installer.
#
#   ensure-psbbn-feega.sh <device> <hdl dump> <helper dir> <assets dir> <log file>
#
# The Feega games (Net de Bomberman, Minna no Golf Online) sign in through Feega, and PSBBN's own
# "Join feega" needs psbbn-feega.sh's certificate (and, on an English PSBBN, its English screens).
# PSBBN-Installer and Extras' language change already run it; this runs it from a game install
# when the drive does not have it yet, so a drive set up before that fix gets it too.
#
# Nothing happens on a drive without PSBBN (__linux.4), or when ROOT_ED.cer is already our CA and,
# on an English PSBBN, every English Feega screen is in place. The PSBBN language comes from the
# OPL partition's version.txt (LANG=), as PSBBN-Installer reads it; English when it cannot be read.
# Only __linux.4 is mapped and mounted, and both are undone before it returns. Never fatal: the
# game install has already succeeded, so a failure here is logged and the script exits 0.
set -u
DEVICE="$1"; HDL_DUMP="$2"; HELPER="$3"; ASSETS="$4"; LOG="$5"

log() { echo "$*" >> "$LOG"; }

dev_cut=$(basename "$DEVICE")
dm_line=$(sudo "$HDL_DUMP" toc "$DEVICE" --dm 2>/dev/null | tr ';' '\n' | grep "^${dev_cut}-__linux.4," | head -1)
if [[ -z "$dm_line" ]]; then
    log "Feega (PSBBN): no __linux.4 on ${DEVICE}, not a PSBBN drive; nothing to do"
    exit 0
fi

# The PSBBN language, from OPL/version.txt
lang="eng"
opl_part=$(sudo blkid -t TYPE=exfat -o device 2>/dev/null | grep -E "^${DEVICE}p?[0-9]+$" | head -1)
if [[ -n "$opl_part" ]]; then
    opl_mnt=$(mktemp -d)
    if sudo mount -o ro "$opl_part" "$opl_mnt" 2>>"$LOG"; then
        v=$(awk -F' *= *' '$1=="LANG"{print $2}' "$opl_mnt/version.txt" 2>/dev/null | tr -d '\r')
        [[ -n "$v" ]] && lang="$v"
        sudo umount "$opl_mnt" 2>>"$LOG"
    fi
    rmdir "$opl_mnt" 2>/dev/null
fi

# Map and mount __linux.4 (reuse a map someone else left, remove only our own)
map="${dev_cut}-__linux.4"
made_map=0
if ! sudo dmsetup info "$map" >/dev/null 2>&1; then
    echo "$dm_line" | sudo dmsetup create --concise 2>>"$LOG" || { log "[!] Feega (PSBBN): could not map __linux.4"; exit 0; }
    made_map=1
fi
mnt=$(mktemp -d)
cleanup() {
    sudo umount "$mnt" 2>/dev/null
    rmdir "$mnt" 2>/dev/null
    [[ $made_map -eq 1 ]] && sudo dmsetup remove "$map" 2>/dev/null
}
trap cleanup EXIT
if ! sudo mount "/dev/mapper/${map}" "$mnt" 2>>"$LOG"; then
    log "[!] Feega (PSBBN): could not mount __linux.4"
    exit 0
fi

# Already in place?
missing=""
cmp -s "${ASSETS}/bomb/BOMBREG.PEM" "${mnt}/bn/certs/ROOT_ED.cer" || missing="certificate"
if [[ "$lang" == "eng" ]]; then
    for f in "${ASSETS}/feega/edclient-eng/"*.xml; do
        t="${mnt}/bn/script/edclient/$(basename "$f")"
        [[ -f "$t" ]] || continue
        cmp -s "$f" "$t" || { missing="${missing:+$missing, }English screens"; break; }
    done
fi
if [[ -z "$missing" ]]; then
    log "Feega (PSBBN): already set up (PSBBN language ${lang})"
    exit 0
fi

log "Feega (PSBBN): adding ${missing} (PSBBN language ${lang})"
sudo bash "${HELPER}/feega/psbbn-feega.sh" "$mnt" "$lang" "$ASSETS" "$LOG"
sync
echo "  PSBBN Feega: ${missing} added"
exit 0
