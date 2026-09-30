#!/usr/bin/env bash
#
# PlayOnline installer for the PSBBN Definitive Project
# Copyright (C) 2026 PrettyOpenLobby
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Test that the game-add PP.* sweep never deletes a title partition this
# toolkit installs directly. Reproduces the 2026-09-29 wipe as a negative
# control, then proves the keep-list stops it.
#
#   bash scripts/helper/tests/test_protect_parts_keep.sh
set -u

HELPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEEP_SH="${HELPER_DIR}/protect-parts-keep.sh"

fail=0
ok()   { printf '  ok   %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; fail=1; }

# The PP.* names a real drive shows after an OPL install: PSBBN's own launcher
# and app partitions, plus a PS1 game launcher (which is a PP.SLPS-* name too --
# why a name test cannot be trusted), plus every title we install directly.
PSBBN_OWNED=$(cat <<'EOF'
PP.DST_HDDCHECKER
PP.SYS_R3CONFIGURATOR
PP.APP_WLE-R3Z
PP.HOSDMENU.HIDDEN
PP.SCPN-60160.PSBBN
PP.POPSLOADER
PP.LAUNCHER
PP.SLPS-01234
EOF
)
OUR_TITLES=$(cat <<'EOF'
PP.SLPS-20200.1000.POLVIEWER
PP.SCUS-97269.1000.POLVIEWER
PP.SLPS-20200.0002.TETRAMASTER
PP.SCUS-97269.0002.TETRAMASTER
PP.SLPS-20200.0003.JANHOUROU
PP.SLPS-25200.0001.FFXI
PP.SCUS-97266.0001.FFXI
PP.SLPM-65981.0004.FMO
PP.SLPM-66271.0010.CERBERUS
PP.SLPM-65197.KOEI.NOBUON
PP.SCPS-15049..APPLICATION
PP.BLJA-00010
EOF
)
ALL_ON_DRIVE=$(printf '%s\n%s\n' "$PSBBN_OWNED" "$OUR_TITLES")

# --- The helper produces a keep-list, and it covers every title -------------
if ! KEEP=$(OPL="" bash "$KEEP_SH"); then
    bad "helper exited non-zero (cannot enumerate the PlayOnline title table)"
    echo "RESULT: FAIL"; exit 1
fi
while IFS= read -r t; do
    [ -n "$t" ] || continue
    if printf '%s\n' "$KEEP" | grep -qxF "$t"; then ok "protected: $t"
    else bad "NOT protected: $t"; fi
done <<< "$OUR_TITLES"

# --- The sweep (with the fix) deletes PSBBN's set and nothing of ours -------
delete=$(printf '%s\n' "$ALL_ON_DRIVE" | grep -vxF -f <(printf '%s\n' "$KEEP"))
while IFS= read -r t; do
    [ -n "$t" ] || continue
    if printf '%s\n' "$delete" | grep -qxF "$t"; then
        bad "sweep would DELETE our title: $t"
    fi
done <<< "$OUR_TITLES"
# PSBBN's own partitions must still be swept (so its GC keeps working).
for p in PP.DST_HDDCHECKER PP.LAUNCHER PP.POPSLOADER PP.SLPS-01234; do
    if printf '%s\n' "$delete" | grep -qxF "$p"; then ok "sweep still deletes PSBBN's $p"
    else bad "sweep no longer deletes PSBBN's $p (GC broken)"; fi
done

# --- Negative control: without the keep-list the bug reproduces -------------
delete_unguarded=$(printf '%s\n' "$ALL_ON_DRIVE")
if printf '%s\n' "$delete_unguarded" | grep -qxF "PP.SLPS-20200.1000.POLVIEWER"; then
    ok "negative control: unguarded sweep deletes POLVIEWER (bug reproduced)"
else
    bad "negative control did not reproduce the bug -- the test is not exercising it"
fi

# --- A user/installer entry on the exFAT is honored, even with a CR ----------
TMP_OPL=$(mktemp -d)
printf 'PP.CUSTOM-THING\r\n' > "${TMP_OPL}/protect-parts.list"
KEEP2=$(OPL="${TMP_OPL}" bash "$KEEP_SH") || bad "helper failed with an exFAT list present"
if printf '%s\n' "$KEEP2" | grep -qxF "PP.CUSTOM-THING"; then ok "exFAT keep-list entry honored (CRLF stripped)"
else bad "exFAT keep-list entry ignored"; fi
rm -rf "$TMP_OPL"

if [ "$fail" -eq 0 ]; then echo "RESULT: PASS"; else echo "RESULT: FAIL"; fi
exit "$fail"
