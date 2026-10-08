# Shipped assets

Per-title folders (`nobunaga/`, `popn/`, `mingol/`, `bomb/`) hold the files the
title installers need that do not come from the player's discs. The signed
loaders among them are checked with one command before a release:

    python3 scripts/helper/check-loader-assets.py [--keys PS2KEYS.dat] [--report-only TITLE]

It runs `nobunaga/tools/hwaudit.py --loader` (Nobunaga project, read-only;
`--hwaudit PATH` or `$HWAUDIT` if it is not found) on every shipped loader:
`nobunaga/*.kelf`, `popn/*.kelf`, `mingol/*.kelf`,
`bomb/bootfiles/bombload.{elf,kelf}` (`.bak-*` copies are skipped). Per file it
prints the DRIVERS mode, the IOPRP version (an unfilled polbbnexec slot is
filled per drive with the title's own image), the sceCdRI spoof id, the
scefix version, the fill-time trace slot and, for Minna, the ROM SYSMEM
splice state. It exits 1 when a rule of the hardware contract
(nobunaga/PLAN-hw-boot-all-titles.md, section 2) fails:

| title | rule |
|---|---|
| Nobunaga, pop'n | DRIVERS=4 (ps2sdk atad, no genuine-drive gate) |
| Bomberman | scefix 1.2 or newer, sceCdRI spoof present |
| Minna | the BIOS-ROM SYSMEM splice off: the loader carries the "splice DISABLED" string of a ROM_SYSMEM=0 build (the splice hung on real hardware on 2026-10-08) |
| every polbbnexec | exactly one `TRACELBA` fill-time trace slot (bombload has none: reported only) |

`--report-only TITLE` keeps a title's failures as notes, for an asset that is
being rebuilt elsewhere.
