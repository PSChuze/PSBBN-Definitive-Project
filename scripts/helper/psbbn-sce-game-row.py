#!/usr/bin/env python3
#
# PSBBN game-list row builder for the PSBBN Definitive Project
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
"""Emit the SQL that registers one direct-to-drive game in PSBBN's game list.

PSBBN's games menu is the `sce_game` table of
`__linux.7/database/sqlite/game.db`. The BB Navigator fills that table from
each `PP.*` partition's `/res/info.sys` plus the partition's APA metadata, but
only when the table is (re)built from scratch; it does not add a partition that
appears after the table already exists. A toolkit that writes partitions
directly (PlayOnline, Nobunaga, pop'n, Bomberman, Minna no Golf) therefore has
to add its own row, or the game is on the drive yet absent from the menu.

This prints a `DELETE` for the partition's `uri` followed by an `INSERT` that
reproduces, byte for byte, the row the Navigator itself would write (verified
against a drive the Navigator built). The columns come from `/res/info.sys`
(the same file the Navigator reads), the partition name, its size in MB and its
APA install date; the rest are the constants every row carries.

    python3 psbbn-sce-game-row.py INFO_SYS PARTITION SIZE_MB INSTALL_DATE
"""
import io
import sys

# sce_game columns, in table order.
COLS = ["type", "key_flag", "inst_size", "title", "title_id", "title_sub_id",
        "release_date", "developer_id", "publisher_id", "note", "content_web",
        "install_date", "table_version", "version", "uri", "resource_path",
        "image_topviewflag", "image_type", "image_count", "image_viewsec",
        "copyright_viewflag", "copyright_imgcount", "genre", "parental_lock",
        "effective_date", "expire_date", "area", "violence_flag",
        "content_type", "content_subtype", "content_attr"]

# Columns stored as integers.
INT_COLS = frozenset((
    "type", "key_flag", "inst_size", "title_sub_id", "release_date",
    "install_date", "table_version", "version", "image_topviewflag",
    "image_type", "image_count", "image_viewsec", "copyright_viewflag",
    "copyright_imgcount", "parental_lock", "effective_date", "expire_date",
    "violence_flag", "content_type", "content_subtype", "content_attr"))

# The fields taken verbatim from /res/info.sys (the Navigator reads the same).
FROM_INFO = ["title", "title_id", "title_sub_id", "release_date",
             "developer_id", "publisher_id", "note", "content_web",
             "image_topviewflag", "image_type", "image_count", "image_viewsec",
             "copyright_viewflag", "copyright_imgcount", "genre",
             "parental_lock", "effective_date", "expire_date",
             "violence_flag", "content_type", "content_subtype"]


def parse_info(path):
    fields = {}
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    return fields


def sql_text(value):
    return "'" + value.replace("'", "''") + "'"


def build_insert(info_path, partition, size_mb, install_date):
    info = parse_info(info_path)
    row = {
        "type": 0,
        "key_flag": 0,
        "inst_size": int(size_mb),
        "install_date": int(install_date),
        "table_version": 4096,
        "version": 1,
        "uri": "pfs:/" + partition,
        "resource_path": "pfs:/" + partition + "/res",
        "area": "J",
        "content_attr": 0,
    }
    for key in FROM_INFO:
        row[key] = info.get(key, "0" if key in INT_COLS else "")
    values = []
    for col in COLS:
        if col in INT_COLS:
            values.append(str(int(row[col])))
        else:
            values.append(sql_text(str(row[col])))
    return "INSERT INTO sce_game VALUES(" + ",".join(values) + ");"


def main(argv):
    if len(argv) != 5:
        sys.stderr.write(
            "usage: psbbn-sce-game-row.py INFO_SYS PARTITION SIZE_MB "
            "INSTALL_DATE\n")
        return 2
    info_path, partition, size_mb, install_date = argv[1:5]
    uri = "pfs:/" + partition
    # The upsert: drop any stale row for this partition, then add the fresh one.
    # Wrapped in a transaction so a reader never sees the table without the row.
    print("BEGIN;")
    print("DELETE FROM sce_game WHERE uri=%s;" % sql_text(uri))
    print(build_insert(info_path, partition, size_mb, install_date))
    print("COMMIT;")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
