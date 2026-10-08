#!/usr/bin/env bash
# Refuse a straight apostrophe inside a UI text default. The installers set
# their English defaults as : "${UI_TEXT[KEY]:=text}", and some bash releases
# read a ' inside that text as the start of a string and refuse the whole
# script with a syntax error (a tester hit it on 2026-10-08). Use U+2019 in
# the text instead. Run from the toolkit root before publishing:
#   bash scripts/helper/check-ui-text.sh
cd "$(dirname "$0")/../.." || exit 2
bad=$(grep -n -E '^\s*: "\$\{UI_TEXT\[[A-Z0-9_]+\]:=[^}]*'"'" scripts/*.sh scripts/helper/*.sh 2>/dev/null)
if [[ -n "${bad}" ]]; then
    echo "straight apostrophe inside a UI_TEXT default (use U+2019):"
    echo "${bad}"
    exit 1
fi
for f in scripts/*.sh scripts/helper/*.sh; do bash -n "$f" || exit 1; done
echo "UI text defaults ok, every script parses"
