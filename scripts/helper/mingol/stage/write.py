#
# Minna no Golf Online installer for the PSBBN Definitive Project
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
"""Write a staged Minna no Golf Online partition onto a PS2 drive (or image).

    python -m mingol.stage.write DEVICE --stage DIR --hddid FILE
        [--pfsshell CMD] [--keeplist <OPL>/protect-parts.list] [--write]

DIR is what `python -m mingol.stage` wrote. The steps, as the kit-based
mingolinstall.py did them:

  1. check     the partition is not there yet, and the drive's own __net record
               decodes with this HDD ID to the four the stage sealed with (the
               record is read, never written here: it is the one PlayOnline
               shares; only --repair-record below writes it, on request).
  2. mkpart    PP.SCPS-15049..APPLICATION, 1536 MiB PFS (pfsshell shapes it as a
               1 GiB main + one 512 MiB sub, the retail layout), then put tree/.
  3. password  rpwd = fpwd = apa_password(id, "MM21") on the main header (the
               boot ELF mounts hdd0:PP.SCPS-15049..APPLICATION,MM21). Then clear
               the APA journal pfsshell leaves behind (it holds the pre-password
               header).
  4. attr      the attribute area (browser icon + boot block) at main + 0x1000.
  5. protect   add the partition to the PSBBN keep-list (protect-parts.list) so a
               PSBBN game add never deletes it, when --keeplist is given.

Dry run unless --write.

    python -m mingol.stage.write DEVICE --stage DIR --hddid FILE --update [--write]

--update brings a partition this installer made up to a new stage, in place:
the partition, its passwords and its size stay. The stage is compared file by
file with what the partition holds (read with playonline's PFS reader), and
pfsshell rewrites only the files that changed (rm, then put) and puts the new
ones (mkdir as needed); it never runs mkpart or rmpart. Every file only the
partition has, the game's saves and settings, is left as it is, except the
plain overlays an English install puts at the root, which a Japanese stage
drops (they are this installer's, not the game's). Afterwards the MM21
passwords are set again, the APA journal cleared, the attribute area rewritten
if it changed, and the partition read back: every staged file must match and
every kept file must be byte for byte what it was. A partition from the old
kit-based installer (no FMOD/) is refused with exit status 3: reinstall it.

    python -m mingol.stage.write DEVICE --probe

prints what the drive has: absent, old (the kit-based install), english or
japanese (from the browser title).

    python -m mingol.stage.write DEVICE --record-info --hddid FILE

prints, read-only, what the shared __net record decodes to under the given HDD
ID, under every ID a loader on the drive serves and under the zero ID: the
four, and whether the PlayOnline step minted it or a console wrote it. It also
reports, per PlayOnline title partition on the drive (the Viewer, FFXI, Tetra
Master, ...), which HDD ID and four that title's keyed containers decrypt
under, so a title sealed to a different id than the record is easy to spot.

    python -m mingol.stage.write DEVICE --repair-record --hddid FILE --backup OUT [--write]

replaces a record that decodes under none of those IDs with the record the
PlayOnline step mints for FILE (the only write this module makes to __net, and
only on request: the installer runs it when MINGOL_REPAIR_RECORD=1). A record
that decodes under any known ID is refused.

The __net record is shared by every PlayOnline title on the drive, so before it
is replaced the keyed containers of every PlayOnline title present (FFXI and the
Viewer among them) are checked, read-only, against the id and four the new
record will carry. If any is sealed to a different id or four, replacing the
record would stop that title decrypting, so the repair is refused: the record,
the loaders and every record-keyed title must agree on one id. --force replaces
it anyway (this strands the titles sealed to another id).

    python -m mingol.stage.write DEVICE --stage DIR --hddid FILE \
        --reinstall --saves BACKUP_DIR [--write]

--reinstall replaces a partition --update refuses (the old kit-based install)
without losing the game's saves. The files only the partition has, the same
set --update keeps, are copied to BACKUP_DIR and read back there first; then
the partition's passwords are cleared and pfsshell removes it (with its sub),
and the fresh install puts the stage and the saved files together. Last, the
saved files are read back from the new partition. If anything fails after the
removal, BACKUP_DIR still holds them.
"""
import argparse
import json
import os
import shlex
import struct
import subprocess
import sys

from playonline.lib import polhdd, polrecord

SECTOR = 512
PARTITION = "PP.SCPS-15049..APPLICATION"
PASSWORD = b"MM21"
PART_MIB = 1536
ATTR_OFF = 0x1000
NET_RECORD_OFF = 0x201800
RECORD_LEN = 512


def partitions(device):
    from playonline.lib.polnetdump import partitions as walk
    with open(device, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        return list(walk(f, size))


def find_partition(device, name):
    for start, length, _ptype, pname in partitions(device):
        if pname == name:
            return start, length
    return None


def read_record(device):
    """(lba of __net, the 512-byte sector at +0x201800)."""
    net = find_partition(device, "__net")
    if not net:
        raise SystemExit("no __net partition on %s" % device)
    with open(device, "rb") as f:
        f.seek(net[0] * SECTOR + NET_RECORD_OFF)
        return net[0], f.read(RECORD_LEN)


def decode_record(rec, hddid):
    """The record's 20-byte plaintext under this HDD ID, or None when it does not
    decode. The key is polrecord.derive_key(HDD ID bytes 0x50..0x60) and nothing
    else: the console i.Link is not part of it, it is only stored inside the
    plaintext at [4:12]. A good decode has zeros at [12:20]."""
    dec = bytes(polrecord.decode(rec[:32], polrecord.derive_key(hddid[0x50:0x60])))
    return None if any(dec[12:20]) else dec[:20]


def record_writer(dec, hddid=None):
    """Who wrote a decoded record, from its identity field [4:12]."""
    ident = dec[4:12]
    if hddid is not None:
        from playonline.lib import ci_transcrypt
        if ident == ci_transcrypt.default_identity(hddid):
            return "minted by the PlayOnline step"
    if not any(ident):
        return "identity zero"
    console = struct.pack(">II", *struct.unpack("<II", ident))
    return "written for console i.Link %s" % console.hex()


def record_candidates(device, hddid):
    """[(label, 512-byte block)]: the given ID, every ID a filled loader on the
    drive serves, and the all-zero ID (PCSX2, or a console that was served
    none). Entries with the same key material are merged into one label."""
    out = [("playonline.hddid", hddid)]
    for name, blk in served_loaders(device):
        out.append(("the loader in %s" % name, blk))
    out.append(("a zero HDD ID (PCSX2, or a console served no ID)", bytes(512)))
    uniq = []
    for label, blk in out:
        same = [i for i, (_l, b) in enumerate(uniq) if b[0x50:0x60] == blk[0x50:0x60]]
        if same:
            i = same[0]
            uniq[i] = ("%s = %s" % (uniq[i][0], label), uniq[i][1])
        else:
            uniq.append((label, blk))
    return uniq


def served_loaders(device):
    """[(partition, block)] for every filled loader on the drive (read-only)."""
    try:
        from playonline.hddid import served_on_drive
        return served_on_drive(device)
    except Exception as e:                      # noqa: BLE001 - diagnostics only
        print("[!] could not read the loaders on %s: %s" % (device, e), file=sys.stderr)
        return []


def record_info(device, hddid):
    """Read-only report of the __net record for a bug report: [lines]."""
    import hashlib
    lba, rec = read_record(device)
    lines = ["__net LBA %d, record at +0x%x" % (lba, NET_RECORD_OFF),
             "record head %s" % rec[:36].hex(),
             "record sha256 %s, %s" % (hashlib.sha256(rec).hexdigest()[:16],
                                       "EMPTY" if not any(rec) else "present"),
             "playonline.hddid sha1 %s, key material %s"
             % (hashlib.sha1(hddid).hexdigest()[:8], (hddid[0x40:0x48] + hddid[0x50:0x60]).hex())]
    if any(rec):
        for label, blk in record_candidates(device, hddid):
            dec = decode_record(rec, blk)
            lines.append("  %-52s %s" % (
                "%s (key %s)" % (label, blk[0x50:0x58].hex()),
                "decodes: four %s, %s" % (dec[:4].hex(), record_writer(dec, hddid))
                if dec else "does not decode"))
    try:
        lines += keyed_info_lines(device, hddid)
    except BaseException as exc:                    # noqa: BLE001 - diagnostics only
        lines.append("keyed PlayOnline containers: could not check (%s)" % exc)
    return lines


REPORT_HINT = ("Nothing was written. Please send logs/mingol-installer.log: the "
               "installer adds a read-only dump of the record to it (the same as "
               "`python3 -m mingol.stage.write DRIVE --record-info --hddid "
               "games/POL/playonline.hddid`).")

# A keyed PlayOnline container (a *.pex.enc / *.enc in installed form) is at
# most a few hundred KiB; FFXI's multi-GiB DATA/ROM*.DAT files are not keyed
# through this record, so a cap keeps the read-only scan cheap and skips them.
KEYED_CONTAINER_CAP = 16 * 1024 * 1024


def playonline_titles_present(device):
    """[(key, partition)] for every PlayOnline title whose partition is on the
    drive. Their modules are all keyed through the one shared __net record, so
    changing the record touches all of them at once."""
    try:
        from playonline.titles import TITLES as POL_TITLES
    except Exception:                               # noqa: BLE001 - diagnostics only
        return []
    names = {pname for _s, _l, _t, pname in partitions(device)}
    return [(t.key, t.partition) for t in POL_TITLES.values() if t.partition in names]


def keyed_containers(device):
    """([(partition, rel, blob)], [(partition, error)]): every keyed PlayOnline
    container on the drive (the installed-form *.pex.enc / *.enc up to the size
    cap), and any title partition that could not be read. Strictly read-only."""
    from playonline.lib import pfsupdate
    out, errs = [], []
    for _key, partition in playonline_titles_present(device):
        try:
            with pfsupdate.Installed(device, partition) as inst:
                for rel in sorted(inst.files):
                    low = rel.lower()
                    if not (low.endswith(".pex.enc") or low.endswith(".enc")):
                        continue
                    if inst.files[rel]["size"] > KEYED_CONTAINER_CAP:
                        continue
                    blob = inst.read(rel)
                    if blob is not None:
                        out.append((partition, rel, blob))
        except BaseException as exc:                # noqa: BLE001 - SystemExit from mount etc.
            errs.append((partition, str(exc) or exc.__class__.__name__))
    return out, errs


def _bulk_tags(check_result):
    """The bulk-tag booleans in a ci_transcrypt.check() result. A non-empty list
    means the blob IS an installed container (its section table verified under
    SE's public keys, which does not depend on the HDD ID); each bool is whether
    that section's bulk decrypts under the id and four checked."""
    return [ok for lab, ok, _d in check_result if lab.endswith("bulk tag")]


def _se_keys():
    """Square Enix's public keys for reading containers, or None when they are
    not available. They are derived from a PlayOnline/FFXI disc boot ELF, which
    the Minna rig does not carry; set $PLAYONLINE_DISC_ELF (to SLPS_202.00,
    SLUS_217.04, ...) to supply one. Without them a container cannot be read, so
    the caller cannot verify a keyed title and must err on the safe side."""
    try:
        from playonline.lib import ci_universal
        return ci_universal._keys()
    except Exception:                               # noqa: BLE001 - no disc ELF, etc.
        return None


def keyed_stranding(device, hddid, four):
    """(stranded, unreadable) or None when the SE keys are not available.

    stranded   = [(partition, rel)] keyed containers that do NOT decrypt under
                 (hddid, four): sealed to another id/four, so stranded if the
                 shared record is set to `four` under `hddid`.
    unreadable = [(partition, error)] title partitions that could not be read.
    None       = the SE keys to read containers with are not available here, so
                 nothing could be checked. Read-only throughout."""
    from playonline.lib import ci_transcrypt
    keys = _se_keys()
    if keys is None:
        return None
    conts, errs = keyed_containers(device)
    stranded = []
    for partition, rel, blob in conts:
        tags = _bulk_tags(ci_transcrypt.check(blob, hddid, four, keys))
        if tags and not all(tags):
            stranded.append((partition, rel))
    return stranded, errs


def keyed_info_lines(device, hddid):
    """Read-only report lines: for each keyed PlayOnline container on the drive,
    which candidate HDD ID and four decrypt it. Shows when FFXI or the Viewer is
    sealed to a different id or four than the shared record carries."""
    from playonline.lib import ci_transcrypt
    present = playonline_titles_present(device)
    if not present:
        return ["keyed PlayOnline titles: none on this drive"]
    keys = _se_keys()
    if keys is None:
        lines = ["keyed PlayOnline titles present (cannot decode-probe without the "
                 "PlayOnline disc keys; set PLAYONLINE_DISC_ELF to SLPS_202.00 / "
                 "SLUS_217.04 to see what each is keyed to):"]
        return lines + ["  %s (%s)" % (partition, key) for key, partition in present]
    cands = record_candidates(device, hddid)
    _lba, rec = read_record(device)
    fours = [("record-mint four %s" % ci_transcrypt.DEFAULT_FOUR.hex(), ci_transcrypt.DEFAULT_FOUR)]
    seen = {ci_transcrypt.DEFAULT_FOUR}
    if any(rec[:32]):
        for label, blk in cands:
            dec = decode_record(rec, blk)
            if dec and dec[:4] not in seen:
                seen.add(dec[:4])
                fours.append(("four %s (record under %s)" % (dec[:4].hex(), label), dec[:4]))
    conts, errs = keyed_containers(device)
    errmap = dict(errs)
    bypart = {}
    for partition, rel, blob in conts:
        bypart.setdefault(partition, []).append((rel, blob))
    lines = ["keyed PlayOnline containers (read-only):"]
    for key, partition in present:
        lines.append("  %s (%s)" % (partition, key))
        if partition in errmap:
            lines.append("    could not read: %s" % errmap[partition])
            continue
        items = bypart.get(partition, [])
        reported = False
        for rel, blob in items:
            hit, is_container = None, False
            for idlabel, blk in cands:
                pcsx2 = not any(blk[0x40:0x48]) and not any(blk[0x50:0x60])
                for flabel, four in fours:
                    tags = _bulk_tags(ci_transcrypt.check(blob, blk, four, keys, pcsx2))
                    if not tags:
                        continue
                    is_container = True
                    if all(tags):
                        hit = (idlabel, flabel)
                        break
                if hit:
                    break
            if not is_container:
                continue
            reported = True
            if hit:
                lines.append("    %-32s decrypts under %s, %s" % (rel, hit[0], hit[1]))
            else:
                lines.append("    %-32s KEYED but no candidate id/four on this drive "
                             "decrypts it (sealed elsewhere)" % rel)
        if not reported:
            lines.append("    no keyed container found (not record-dependent for boot)")
    return lines


def net_four(device, hddid):
    """The four the stage seals with: the drive's own __net DNAS record
    (partition +0x201800) decoded with the HDD ID the loader will serve.

    At boot Minna's DNAS decodes the same record with the ID the loader serves
    (this `hddid`), so the four has to come from that decode: a record keyed to
    any other ID gives the console a different four than any we could seal with,
    and there is no safe default. When the record does not decode, every other
    ID the drive is known to answer with is tried, to say why."""
    _lba, rec = read_record(device)
    if not any(rec[:32]):
        raise SystemExit("the __net DNAS record is empty: this drive has never been "
                         "provisioned (run the PlayOnline step first)")
    dec = decode_record(rec, hddid)
    if dec:
        print("__net record: four %s, %s" % (dec[:4].hex(), record_writer(dec, hddid)),
              file=sys.stderr)
        return dec[:4]
    cands = record_candidates(device, hddid)
    for label, blk in cands[1:]:
        other = decode_record(rec, blk)
        if not other:
            continue
        if any(blk):
            raise SystemExit(
                "the __net record is keyed to the HDD ID %s serves (key %s), not to "
                "this PC's playonline.hddid (key %s): the playonline.hddid here is not "
                "the one this drive was installed with. Move games/POL/playonline.hddid "
                "aside and run again: it is then read back from the drive.\n%s"
                % (label, blk[0x40:0x48].hex(), hddid[0x40:0x48].hex(), REPORT_HINT))
        raise SystemExit(
            "the __net record is keyed to a zero HDD ID (four %s, %s): it was written "
            "under PCSX2 or by a console that was served no drive ID, so it does not "
            "decode with playonline.hddid on the console either.\n%s"
            % (other[:4].hex(), record_writer(other), REPORT_HINT))
    if "the loader in" in cands[0][0]:
        why = ("%s serves this same ID, so the console cannot read this record "
               "either: it was written for another HDD ID (a record left from an "
               "earlier install of the drive, or one a console wrote under another "
               "ID). Anything else keyed through it (FFXI) cannot decrypt on this "
               "drive either." % cands[0][0].split(" = ", 1)[1])
    else:
        why = ("no loader on the drive serves this ID, so either playonline.hddid "
               "or the record is not this drive's.")
    raise SystemExit(
        "the __net record does not decode with playonline.hddid (key %s) nor with "
        "any ID a loader on the drive serves: %s Minna's DNAS reads its four from "
        "this record, so the game cannot be sealed to it.\n%s"
        % (hddid[0x40:0x48].hex(), why, REPORT_HINT))


def repair_record(device, hddid, backup, write=False, force=False):
    """Put back the record the PlayOnline step mints (route.mint_record: four
    ci_transcrypt.DEFAULT_FOUR, identity from the HDD ID), keyed to `hddid`.

    Only when every filled loader on the drive serves exactly `hddid` and the record
    decodes under none of record_candidates: such a record cannot be read on
    the console through the served ID, so nothing the
    drive's loaders serve can be using it, and the PlayOnline step itself writes
    this same record whenever it routes the Viewer (FFXI's containers are keyed
    to its four). The old sector is saved to `backup` first and read back.

    The record is shared by every PlayOnline title on the drive, so it is only
    replaced when doing so strands none of them: every record-keyed title present
    (FFXI, the Viewer) must already decrypt under (hddid, DEFAULT_FOUR), which is
    the state the PlayOnline step leaves. That is verified read-only when the SE
    disc keys are available; otherwise, or if a title is sealed elsewhere or a
    title partition cannot be read, the repair is refused unless `force`."""
    from playonline.lib import ci_transcrypt
    lba, rec = read_record(device)
    # The console decodes the record with the ID its loader serves. Only when the
    # loaders on this drive all serve exactly `hddid` is a record that `hddid`
    # cannot decode known to be useless; otherwise `hddid` may be the wrong file
    # and the record the right one.
    loaders = served_loaders(device)
    if not loaders or any(blk != hddid for _name, blk in loaders):
        raise SystemExit("not every loader on %s serves this HDD ID (%s), so it cannot "
                         "be told whether the record or playonline.hddid is wrong: not "
                         "replacing the record"
                         % (device, ", ".join("%s %s" % (n, "same" if b == hddid else "OTHER")
                                              for n, b in loaders) or "no filled loader"))
    # The record is PlayOnline's: its own loader has to be one of them.
    from playonline.titles import TITLES
    viewers = {t.partition for t in TITLES.values() if t.boot == "pfs:/dnasload.elf"}
    if not any(name in viewers for name, _blk in loaders):
        raise SystemExit("the PlayOnline Viewer's loader is not on %s: not replacing "
                         "the record PlayOnline shares" % device)
    if any(rec[:32]):
        for label, blk in record_candidates(device, hddid):
            dec = decode_record(rec, blk)
            if dec:
                raise SystemExit("the __net record decodes with %s (four %s): not "
                                 "replacing it" % (label, dec[:4].hex()))
    _ata24, key = ci_transcrypt.ata_material(hddid, False)
    new = polrecord.encode(polrecord.mint(ci_transcrypt.DEFAULT_FOUR,
                                          ci_transcrypt.default_identity(hddid)), key)
    if len(new) != RECORD_LEN or decode_record(new, hddid) is None:
        raise SystemExit("the minted record does not decode back")
    # The record keys every PlayOnline title on the drive, not just Minna. Before
    # it is overwritten, confirm that no other record-keyed title (FFXI, the
    # Viewer) would be stranded. The safe state, the one the PlayOnline step
    # leaves, is that every such title already decrypts under the id and four
    # the new record carries. The repair fires only when the current record
    # decodes under no known id, so those titles are NOT currently consistent
    # with the drive's served id, and minting a record for `hddid` is correct
    # only if they happen to be sealed to (hddid, DEFAULT_FOUR). That is checked
    # here when the SE keys are available; when they are not, or a title cannot
    # be read, or one is sealed elsewhere, the repair cannot be proven safe and
    # is refused unless --force. --force WILL strand a title sealed to another id.
    present = playonline_titles_present(device)
    if present and not force:
        try:
            result = keyed_stranding(device, hddid, ci_transcrypt.DEFAULT_FOUR)
        except BaseException as exc:                # noqa: BLE001 - diagnostics only
            result = None
            _probe_err = str(exc) or exc.__class__.__name__
        else:
            _probe_err = None
        title_list = "\n    ".join("%s (%s)" % (p, k) for k, p in present)
        guidance = ("The record, the loaders and every record-keyed title must share one "
                    "id; overwriting the record cannot make a title sealed to another id "
                    "start. Reinstall the odd title through the PlayOnline step so it is "
                    "re-keyed to this id, or keep the current record. Pass --force to "
                    "replace it anyway (this WILL strand any title sealed to another id).")
        if result is None:
            raise SystemExit(
                "not replacing the shared __net record: %d other PlayOnline title(s) are "
                "on this drive and their keyed containers cannot be read here to confirm "
                "they stay readable (no PlayOnline disc keys%s). FFXI is likely among "
                "them.\n    %s\nTo check precisely, rerun --record-info with "
                "PLAYONLINE_DISC_ELF set to the Viewer/FFXI boot ELF. %s"
                % (len(present), "" if _probe_err is None else ": %s" % _probe_err,
                   title_list, guidance))
        stranded, unreadable = result
        if stranded or unreadable:
            detail = []
            if stranded:
                detail.append("keyed container(s) sealed to a different HDD ID or four:\n    "
                              + "\n    ".join("%s  %s" % (p, r) for p, r in stranded))
            if unreadable:
                detail.append("title partition(s) that could not be read to check them:\n    "
                              + "\n    ".join("%s (%s)" % (p, why) for p, why in unreadable))
            raise SystemExit(
                "not replacing the shared __net record: changing it to four %s under this "
                "id would strand record-keyed PlayOnline titles.\n  %s\nFFXI is likely "
                "affected. %s"
                % (ci_transcrypt.DEFAULT_FOUR.hex(), "\n  ".join(detail), guidance))
    if not write:
        return "would replace the __net record (LBA %d + 0x%x) with four %s  (plan only)" % (
            lba, NET_RECORD_OFF, ci_transcrypt.DEFAULT_FOUR.hex())
    if os.path.exists(backup):
        raise SystemExit("%s already exists; not overwriting a backup" % backup)
    os.makedirs(os.path.dirname(os.path.abspath(backup)), exist_ok=True)
    with open(backup, "wb") as f:
        f.write(rec)
    with open(backup, "rb") as f:
        if f.read() != rec:
            raise SystemExit("the backup %s did not read back" % backup)
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR + NET_RECORD_OFF)
        f.write(new)
        f.flush()
        os.fsync(f.fileno())
    if read_record(device)[1] != new:
        raise SystemExit("the __net record did not read back as written")
    return "replaced the __net record with the PlayOnline step's (four %s); the old one is in %s" % (
        ci_transcrypt.DEFAULT_FOUR.hex(), backup)


def _quote(name):
    return '"%s"' % name if " " in name else name


def emit_dir(out, host_dir):
    entries = sorted(os.scandir(host_dir), key=lambda e: e.name)
    files = [e for e in entries if e.is_file()]
    if files:
        out.append("lcd %s" % _quote(host_dir.replace("\\", "/")))
        out += ["put %s" % _quote(e.name) for e in files]
    for e in entries:
        if e.is_dir():
            out += ["mkdir %s" % _quote(e.name), "cd %s" % _quote(e.name)]
            emit_dir(out, e.path)
            out.append("cd ..")


def pfsshell_script(device, staged):
    out = ["device %s" % device,
           "mkpart %s %dM PFS" % (PARTITION, PART_MIB), "mount %s" % PARTITION]
    emit_dir(out, staged)
    return "\n".join(out + ["umount", "exit", ""])


def set_password(device, lba):
    """rpwd = fpwd = apa_password(id, MM21) on the main header, checksum refreshed."""
    pw = polhdd.apa_password(PARTITION, PASSWORD)
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR)
        h = bytearray(f.read(1024))
        if h[0x10:0x30].split(b"\0")[0].decode("latin-1") != PARTITION:
            raise SystemExit("header at LBA %d is not %s" % (lba, PARTITION))
        h[0x30:0x38] = pw
        h[0x38:0x40] = pw
        struct.pack_into("<I", h, 0, polhdd.checksum(bytes(h)))
        f.seek(lba * SECTOR)
        f.write(h)
    return pw


def clear_journal(device, backup):
    """pfsshell leaves its APA journal behind (MBR-area sectors 6-7, 10-15), holding our
    header as it was BEFORE set_password. A stale journal stops HDD-OSD booting, and a
    replay would drop the password. Same sectors as PlayOnline poljournal.py --clear;
    8-9 are left alone."""
    with open(device, "r+b") as f:
        with open(backup, "wb") as b:
            b.write(f.read(SECTOR * 16))
        for s in (6, 7, 10, 11, 12, 13, 14, 15):
            f.seek(s * SECTOR)
            f.write(bytes(SECTOR))


def write_attr(device, lba, attr):
    with open(attr, "rb") as f:
        area = f.read()
    if area[:9] != b"PS2ICON3D":
        raise SystemExit("attr file has no PS2ICON3D magic")
    with open(device, "r+b") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        f.write(area)


def protect(keeplist):
    """The installer owns its keep-list entry: append once, never rewrite other lines."""
    lines = []
    if os.path.exists(keeplist):
        with open(keeplist, encoding="utf-8") as f:
            lines = f.read().splitlines()
    if PARTITION in lines:
        return False
    ends_nl = True
    if lines:
        with open(keeplist, "rb") as f:
            ends_nl = f.read().endswith(b"\n")
    with open(keeplist, "a", encoding="utf-8", newline="\n") as f:
        if not ends_nl:
            f.write("\n")
        f.write(PARTITION + "\n")
    return True


# ---- the in-place update ---------------------------------------------------

OLD_KIT = 3            # exit status: the partition is the old kit-based install


def plain_overlay_names(tree, inst):
    """The root-level plain overlays an English install puts in (one per
    overlay in the disc's ZZBIN/ but DNAS.BIN): this installer's files, not
    the game's, so a Japanese update removes them. Taken as every *.BIN at
    the root of the stage or the drive whose name is also a sealed container
    under ZZENC/ZZBIN/, or any *.BIN at the root of an English stage."""
    sealed = {p.split("/")[-1].upper() for p in inst.files
              if p.upper().startswith("ZZENC/ZZBIN/") and p.count("/") == 2}
    zz = os.path.join(tree, "ZZENC", "ZZBIN")
    if os.path.isdir(zz):
        sealed |= {n.upper() for n in os.listdir(zz)}
    names = {n for n in sealed if n.endswith(".BIN")}
    names |= {n.upper() for n in os.listdir(tree)
              if n.upper().endswith(".BIN") and os.path.isfile(os.path.join(tree, n))}
    names.discard("DNAS.BIN")
    return names


def save_files(device, tree):
    """{rel: bytes} for the files only the partition has: what --update keeps."""
    from playonline.lib import pfsupdate
    with pfsupdate.Installed(device, PARTITION) as inst:
        ours = plain_overlay_names(tree, inst)
        p = pfsupdate.plan(inst, tree, lambda rel: "/" not in rel and rel.upper() in ours)
        return {rel: inst.read(rel) for rel in p.kept}


def backup_saves(saves, backup):
    """Write the saves under `backup` and read each one back."""
    for rel, data in saves.items():
        dst = os.path.join(backup, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        with open(dst, "rb") as f:
            if f.read() != data:
                raise SystemExit("the copy of %s in %s does not read back" % (rel, backup))


def remove_partition(device, pfsshell):
    """Clear the MM21 passwords (the APA driver refuses to remove a partition
    whose fpwd does not match), then rmpart, which takes the sub with it."""
    part = find_partition(device, PARTITION)
    with open(device, "r+b") as f:
        f.seek(part[0] * SECTOR)
        h = bytearray(f.read(1024))
        h[0x30:0x40] = bytes(16)
        struct.pack_into("<I", h, 0, polhdd.checksum(bytes(h)))
        f.seek(part[0] * SECTOR)
        f.write(h)
    cmd = [pfsshell] if os.path.isfile(pfsshell) else shlex.split(pfsshell)
    subprocess.run(cmd, input="device %s\nrmpart %s\nexit\n" % (device, PARTITION),
                   text=True, check=True)
    if find_partition(device, PARTITION):
        raise SystemExit("pfsshell did not remove %s" % PARTITION)


def read_attr(device, lba, n):
    with open(device, "rb") as f:
        f.seek(lba * SECTOR + ATTR_OFF)
        return f.read(n)


def probe(device):
    """absent, old (the kit-based install, no FMOD/), english or japanese."""
    from playonline import attrarea
    from playonline.lib import pfsupdate
    if not find_partition(device, PARTITION):
        return "absent"
    with pfsupdate.Installed(device, PARTITION) as inst:
        if not any(p.startswith("FMOD/") for p in inst.files):
            return "old"
        lba = inst.lba
    area = attrarea.read_area(device, lba)
    title = ((attrarea.title0_of(area) if area else None) or "").strip()
    try:
        title.encode("ascii")
    except UnicodeEncodeError:
        return "japanese"
    return "english" if title else "japanese"


def update(a, stage, tree, attr):
    from playonline.lib import pfsupdate
    with pfsupdate.Installed(a.device, PARTITION) as inst:
        if not any(p.startswith("FMOD/") for p in inst.files):
            print("%s on %s is the old kit-based install (no FMOD/): it cannot be "
                  "updated in place; remove it and install again" % (PARTITION, a.device))
            return OLD_KIT
        lba = inst.lba
        ours = plain_overlay_names(tree, inst)
        plan = pfsupdate.plan(inst, tree, lambda rel: "/" not in rel and rel.upper() in ours)
    with open(attr, "rb") as f:
        want_attr = f.read()
    attr_stale = read_attr(a.device, lba, len(want_attr)) != want_attr
    print("== update %s at LBA %d: %s%s" % (PARTITION, lba, plan.summary(),
                                            ", browser entry changed" if attr_stale else ""))
    for line in plan.lines():
        print(line)
    if plan.empty and not attr_stale:
        print("== the partition is current: nothing to write")
        return 0
    script = pfsupdate.script(a.device, PARTITION, tree, plan)
    with open(stage.rstrip("/\\") + ".update.pfsshell.txt", "w", newline="\n") as f:
        f.write(script)
    if not a.write:
        print(script[:800] + ("..." if len(script) > 800 else ""))
        print("== dry run: nothing written (pass --write)")
        return 0

    if not plan.empty:
        pfsupdate.run(a.pfsshell, script)
    part = find_partition(a.device, PARTITION)
    if not part or part[0] != lba:
        raise SystemExit("%s moved or vanished during the update" % PARTITION)
    pw = set_password(a.device, lba)
    print("== password kept on LBA %d (%s)" % (lba, pw.hex()))
    jb = stage.rstrip("/\\") + ".journal-backup.bin"
    clear_journal(a.device, jb)
    print("== APA journal cleared (sectors 0-15 backed up to %s)" % jb)
    if attr_stale:
        write_attr(a.device, lba, attr)
        print("== attr rewritten at LBA %d + 0x1000" % lba)
    bad = pfsupdate.verify(a.device, PARTITION, tree, plan)
    if read_attr(a.device, lba, len(want_attr)) != want_attr:
        bad.append("attribute area")
    if bad:
        raise SystemExit("the update did not read back as written:\n  " + "\n  ".join(bad))
    print("== read back: every staged file matches, %d kept file(s) unchanged"
          % len(plan.kept))
    if a.keeplist:
        print("== keep-list: %s" % ("added" if protect(a.keeplist) else "already listed"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("device")
    ap.add_argument("--probe", action="store_true",
                    help="print absent, old, english or japanese and stop")
    ap.add_argument("--stage", help="the folder `python -m mingol.stage` wrote")
    ap.add_argument("--hddid", help="the drive's 512-byte identity")
    ap.add_argument("--update", action="store_true",
                    help="update the partition already on the drive in place")
    ap.add_argument("--pfsshell", default="pfsshell",
                    help="pfsshell command line (a path with spaces is quoted as one word)")
    ap.add_argument("--keeplist", help="<OPL>/protect-parts.list on the exFAT partition")
    ap.add_argument("--reinstall", action="store_true",
                    help="remove the partition on the drive and install afresh, "
                         "carrying the game's saves over (needs --saves)")
    ap.add_argument("--saves", help="with --reinstall: where the saves are copied first")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--record-info", action="store_true",
                    help="with --hddid: print what the __net record decodes to under "
                         "every ID the drive is known to answer with, and stop (read-only)")
    ap.add_argument("--repair-record", action="store_true",
                    help="with --hddid and --backup: when the __net record decodes under "
                         "no known ID, replace it with the one the PlayOnline step mints "
                         "for this HDD ID (dry run unless --write)")
    ap.add_argument("--backup", help="with --repair-record: where the old record sector is saved")
    ap.add_argument("--force", action="store_true",
                    help="with --repair-record: replace the record even when another "
                         "PlayOnline title (FFXI, the Viewer) on the drive is keyed to a "
                         "different id; this strands that title")
    a = ap.parse_args(argv)
    if a.probe:
        print(probe(a.device))
        return 0
    if a.record_info or a.repair_record:
        if not a.hddid:
            ap.error("--record-info and --repair-record need --hddid")
        with open(a.hddid, "rb") as f:
            hddid = f.read()
        if a.repair_record:
            if not a.backup:
                ap.error("--repair-record needs --backup")
            print(repair_record(a.device, hddid, a.backup, a.write, a.force))
        print("\n".join(record_info(a.device, hddid)))
        return 0
    if not (a.stage and a.hddid):
        ap.error("--stage and --hddid are required")

    stage = os.path.abspath(a.stage)
    with open(os.path.join(stage, "game.json")) as f:
        game = json.load(f)
    tree = os.path.join(stage, "tree")
    attr = os.path.join(stage, "attr.bin")
    for p in (tree, attr, os.path.join(tree, "dnasload.elf")):
        if not os.path.exists(p):
            raise SystemExit("the stage is incomplete: no %s" % p)
    if game.get("partition") != PARTITION:
        raise SystemExit("the stage is for %s, not %s" % (game.get("partition"), PARTITION))

    with open(a.hddid, "rb") as f:
        hddid = f.read()
    if len(hddid) != 512 or hddid[:32] != b"Sony Computer Entertainment Inc.":
        raise SystemExit("%s does not look like a PS2 HDD ID" % a.hddid)
    there = find_partition(a.device, PARTITION)
    if a.update and a.reinstall:
        ap.error("--update and --reinstall are alternatives")
    if a.reinstall and not a.saves:
        ap.error("--reinstall needs --saves")
    if there and not (a.update or a.reinstall):
        raise SystemExit("%s already exists on %s: update it with --update, or "
                         "--reinstall it" % (PARTITION, a.device))
    if (a.update or a.reinstall) and not there:
        raise SystemExit("%s is not on %s: nothing to replace" % (PARTITION, a.device))
    four = net_four(a.device, hddid)
    if four.hex() != game.get("four"):
        raise SystemExit("the stage was sealed with four %s but %s's __net record holds %s"
                         % (game.get("four"), a.device, four.hex()))
    print("== target %s, four %s" % (a.device, four.hex()))
    if a.update:
        return update(a, stage, tree, attr)
    if a.reinstall:
        return reinstall(a, stage, tree, attr)
    return fresh(a, stage, tree, attr)


def reinstall(a, stage, tree, attr):
    from playonline.lib import pfsupdate
    saves = save_files(a.device, tree)
    print("== reinstall %s: %d file(s) only the partition has are carried over"
          % (PARTITION, len(saves)))
    for rel in sorted(saves):
        print("   save %s (%d B)" % (rel, len(saves[rel])))
    if not a.write:
        print("== dry run: nothing written (pass --write)")
        return 0
    backup = os.path.abspath(a.saves)
    backup_saves(saves, backup)
    print("== saves copied to %s and read back" % backup)
    remove_partition(a.device, a.pfsshell)
    print("== removed the old %s" % PARTITION)

    # The saves go in with the stage, then leave the stage again.
    placed, made = [], []
    try:
        for rel, data in saves.items():
            dst = os.path.join(tree, *rel.split("/"))
            d = os.path.dirname(dst)
            while not os.path.isdir(d):
                made.append(d)
                d = os.path.dirname(d)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            placed.append(dst)
        rc = fresh(a, stage, tree, attr)
    finally:
        for p in placed:
            os.remove(p)
        for d in sorted(made, key=len, reverse=True):
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
    with pfsupdate.Installed(a.device, PARTITION) as inst:
        bad = [rel for rel, data in saves.items()
               if rel not in inst.files or inst.read(rel) != data]
    if bad:
        raise SystemExit("saves did not read back from the new partition (copies are "
                         "in %s):\n  %s" % (backup, "\n  ".join(sorted(bad))))
    print("== read back: all %d save file(s) are on the new partition" % len(saves))
    return rc


def fresh(a, stage, tree, attr):
    script = pfsshell_script(a.device, tree)
    with open(stage.rstrip("/\\") + ".pfsshell.txt", "w", newline="\n") as f:
        f.write(script)
    print("== pfsshell script: %d commands (saved next to the stage dir)" % script.count("\n"))
    if not a.write:
        print(script[:600] + ("..." if len(script) > 600 else ""))
        print("== dry run: nothing written (pass --write)")
        return 0

    cmd = [a.pfsshell] if os.path.isfile(a.pfsshell) else shlex.split(a.pfsshell)
    subprocess.run(cmd, input=script, text=True, check=True)
    part = find_partition(a.device, PARTITION)
    if not part:
        raise SystemExit("pfsshell finished but %s is not in the APA table" % PARTITION)
    pw = set_password(a.device, part[0])
    print("== password set on LBA %d (%s)" % (part[0], pw.hex()))
    jb = stage.rstrip("/\\") + ".journal-backup.bin"
    clear_journal(a.device, jb)
    print("== APA journal cleared (sectors 0-15 backed up to %s)" % jb)
    write_attr(a.device, part[0], attr)
    print("== attr written at LBA %d + 0x1000" % part[0])
    if a.keeplist:
        print("== keep-list: %s" % ("added" if protect(a.keeplist) else "already listed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
