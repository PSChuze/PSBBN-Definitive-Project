#!/usr/bin/env bash
# PSBBN's own Feega client (__linux.4:/bn/modules/edclient.so) against the revival Feega server.
#
#   psbbn-feega.sh <mounted __linux.4> <language code> <assets dir> <log file>
#
# 1. Certificate (every language): PSBBN trusts the certs in /bn/certs and only accepts a Feega
#    server signed by Sony Finance's root, ROOT_ED.cer. It becomes our CA (assets/bomb/BOMBREG.PEM,
#    the CA the revival's lib.feega.sonyfinance.co.jp certificate is issued under); Sony's copy is
#    kept beside it as ROOT_ED.cer.sony.
# 2. English Feega screens (eng only): the text is inline in each bn/script/edclient/*.xml, which
#    the language pack leaves mostly Japanese. assets/feega/edclient-eng holds the translated files
#    (helper/feega/apply.py writes helper/feega/en.tsv into Sony's originals).
# Run as root after the language pack has been extracted.
set -u
L4="$1"; LANG_CODE="$2"; ASSETS="$3"; LOG="$4"

CERTS="${L4}/bn/certs"
CA="${ASSETS}/bomb/BOMBREG.PEM"
if [ -d "$CERTS" ] && [ -f "$CA" ]; then
    if [ -f "${CERTS}/ROOT_ED.cer" ] && [ ! -f "${CERTS}/ROOT_ED.cer.sony" ] \
        && grep -q "BEGIN CERTIFICATE" "${CERTS}/ROOT_ED.cer" \
        && ! cmp -s "$CA" "${CERTS}/ROOT_ED.cer"; then
        cp -p "${CERTS}/ROOT_ED.cer" "${CERTS}/ROOT_ED.cer.sony"
    fi
    if cp -f "$CA" "${CERTS}/ROOT_ED.cer" && chmod 644 "${CERTS}/ROOT_ED.cer"; then
        echo "Feega: ROOT_ED.cer set to the revival CA" >> "$LOG"
    else
        echo "[X] Error: Feega: could not write ${CERTS}/ROOT_ED.cer" >> "$LOG"
    fi
else
    echo "[!] Feega: ${CERTS} or ${CA} missing, certificate left as is" >> "$LOG"
fi

if [ "$LANG_CODE" = "eng" ]; then
    n=0
    for f in "${ASSETS}/feega/edclient-eng/"*.xml; do
        t="${L4}/bn/script/edclient/$(basename "$f")"
        [ -f "$t" ] || continue
        cp -f "$f" "$t" && chmod 644 "$t" && n=$((n + 1))
    done
    echo "Feega: ${n} English edclient screens installed" >> "$LOG"
fi
exit 0
