# Upstream PR: don't delete PP partitions a tool registered as protected

Target: `CosmicScale/PSBBN-Definitive-Project`, `scripts/Game-Installer.sh`.

## Problem

When the Game Installer adds games it rebuilds its launcher partitions by
deleting **every** `PP.*` partition and recreating the ones it manages:

```bash
delete_partition=$(grep -o 'PP\.[^ ]\+' "$hdl_output")
# ... rmpart each one ...
```

Tools that install a title into its own PFS partition on the same drive name
those partitions `PP.*` too (a second OS such as PlayOnline, Nobunaga no Yabou,
Minna no Golf, and others). PSBBN cannot regenerate them, so this sweep silently
destroys the user's installed game on the next game add. It is data loss with no
warning, and the user only finds out when the title is gone.

## Fix

Honor a keep-list: a newline-separated file of exact `PP.*` names,
`protect-parts.list`, on the exFAT (OPL) partition. Any installer - or the user
- can append the partitions it owns. The sweep skips those names. When the file
is absent the behavior is exactly as before, so this is purely additive.

Apply at both sweep passes (the initial delete and the "failed to delete"
re-check):

```diff
 delete_partition=$(grep -o 'PP\.[^ ]\+' "$hdl_output")
+# Keep partitions a tool or the user registered as "do not delete": exact PP.*
+# names, one per line, in protect-parts.list on the exFAT (OPL) partition. This
+# lets software that installs its own PFS title partitions (which the Game
+# Installer cannot regenerate) survive a game add. Absent list = unchanged.
+[ -f "${OPL}/protect-parts.list" ] && delete_partition=$(printf '%s\n' "$delete_partition" | grep -vxF -f "${OPL}/protect-parts.list")
```

`grep -vxF` matches whole lines literally, so a partition is kept only on an
exact full-name match; it cannot over-match a PSBBN launcher partition.

## Why a keep-list and not a name test

A name pattern cannot separate a foreign title partition from a PSBBN launcher:
a PS1 game's launcher partition can be `PP.SLPS-*` just like a title partition.
An explicit keep-list is the only reliable signal, and it puts the decision with
the tool that created the partition.

## Note for our fork

Our fork does not rely on the keep-list being populated by hand. It computes the
protected set from the title tables at sweep time and fails closed if it cannot
(`scripts/helper/protect-parts-keep.sh`), so a title partition is never deleted
even if no one registered it. The keep-list above is the generic, minimal piece
worth sending upstream so any third-party installer benefits.
