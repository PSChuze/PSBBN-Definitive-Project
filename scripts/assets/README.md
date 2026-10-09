# Shipped assets

Per-title folders (`nobunaga/`, `popn/`, `mingol/`, `bomb/`) hold the files the
title installers need that do not come from the player's discs. The signed
loaders among them are checked with one command before a release:

    python3 scripts/helper/check-loader-assets.py [--keys PS2KEYS.dat] [--report-only TITLE]

It runs `nobunaga/tools/hwaudit.py --loader` (Nobunaga project, read-only;
`--hwaudit PATH` or `$HWAUDIT` if it is not found) on every shipped loader:
`nobunaga/*.kelf`, `popn/*.kelf`, `mingol/*.kelf`,
`bomb/bootfiles*/bombload.elf` and `bombload*.kelf` (`.bak-*` copies are
skipped). Per file it prints the console region it is signed for (MGZones and
AppType from the KELF header, and whether its signatures verify), the DRIVERS
mode, the IOPRP version (an unfilled polbbnexec slot is
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
| every KELF | signatures verify (with PS2KEYS); `<name>.kelf` opens on a Japanese console, `<name>-us.kelf` and `<name>-all.kelf` exist, open on their console (a Japan-only file under a US or all-regions name is refused) and carry the same body as `<name>.kelf` |

`--report-only TITLE` keeps a title's failures as notes, for an asset that is
being rebuilt elsewhere.

## Silent and debug twins

Each title ships its loader twice, built from one source and signed the same
way, so the only difference is the on-screen text. The installers ask "Show
boot debug text on the console?" (scripts/helper/debugtext.sh): N installs the
silent loader, Y the debug twin and, where the loader has a boot record, arms
it (trace.bin in the game partition, the TRACELBA slot set with
nobunaga/tools/traceslot.py). Every title loader decides whether the record is
armed after its own IOP reboot, on its own drivers, never through the
launcher's IOP: that older check halted verbose boots on stock HDD-OSD
consoles. Tester notes: RELEASE-NOTES-hw-boot.md.

| title | silent (N) | debug (Y) |
|---|---|---|
| Nobunaga | `nobunaga/polbbnexec-inputpatch.kelf` (DRIVERS=4, **no input hook** since 2026-10-08 despite the name: 6d29f4fe; the hook build is `polbbnexec-inputpatch.kelf.hook-unproven`, it stopped boot #56 on the console) | `nobunaga/polbbnexec-nobu-verbose.kelf` (FORK_VERBOSE, DRIVERS=4, no input hook) |
| pop'n | `popn/polbbnexec-popn.kelf` (poltrace v4) | `popn/polbbnexec-popn-verbose.kelf` (FORK_VERBOSE, poltrace v4: the record goes wherever trace.bin lands) |
| Minna | `mingol/polbbnexec-mingol.kelf` | `mingol/polbbnexec-mingol-verbose.kelf` (FORK_VERBOSE, ROM SYSMEM splice off) |
| Bomberman | `bomb/bootfiles/bombload.{elf,kelf}` | `bomb/bootfiles-debug/bombload.{elf,kelf}` (SCREEN build, 5 s hold; no record slot) |

Bomberman's debug pair keeps the on-partition name `bombload.kelf` (the name
the browser entry boots): the installer stages `bootfiles/` with the
`bootfiles-debug/` loader in its place.

## One loader per console region

A KELF's header carries a MagicGate region mask (MGZones), and a console opens
a KELF only when its own region's bit is set there. It checks before any
loader code runs, so a loader zoned for another region drops straight back to
the browser with nothing drawn. Every title loader ships the way the
PlayOnline step ships `playonline/polbbnexec*.kelf`, once per console region,
signed from the same content (only the 32-byte header and what is derived
from it differ):

| file | console | AppType | MGZones | header from |
|---|---|---|---|---|
| `<name>.kelf` | Japanese | 0x0B | 0x01 | Nobunaga's own `dnasload.elf` (as before) |
| `<name>-us.kelf` | US | 0x0B | 0x02 | `playonline/polbbnexec-us.kelf` (Square Enix's US `dnasload.elf`; proven on a US console) |
| `<name>-all.kelf` | European and any other | 0x01 | 0xFF | `playonline/polbbnexec-all.kelf` (all eight bits; proven on a console from outside the US and Japan) |

`scripts/helper/sign-region-loaders.py --keys PS2KEYS.dat` signs the `-us` and
`-all` copies of every title loader from its `<name>.kelf` (re-run it after a
loader is rebuilt; `--check` writes nothing and fails on a missing or stale
copy). The installers pick the copy through `scripts/helper/region.sh`, called
from `debugtext.sh`: the console region is `POL_CONSOLE` when set, else what
the drive already says (the zone mask of the PlayOnline Viewer's loader, as
the PlayOnline step reads it, or of a US or all-regions title loader), else the
PlayOnline step's own question (`POL_SELECT_CONSOLE`, `[U/j/e]`). Bomberman
stages its boot files in its work folder with only the chosen copy, named
`bombload.kelf`.

| loader | jp | us | all |
|---|---|---|---|
| `nobunaga/polbbnexec-inputpatch` | 6d29f4fe | bff197a5 | 0c95656a |
| `nobunaga/polbbnexec-nobu-verbose` | f1e4ff1e | 1d68a7c5 | f247c8b1 |
| `popn/polbbnexec-popn` | 49fa2d6e | cf89d70e | b4a073b7 |
| `popn/polbbnexec-popn-verbose` | f83fd58e | 497a8e05 | 1a157f01 |
| `mingol/polbbnexec-mingol` | 5895fb0d | 535f42d9 | 15cd2733 |
| `mingol/polbbnexec-mingol-verbose` | 23858b0f | 71d070d9 | 8062b6a1 |
| `bomb/bootfiles/bombload` | b65ba7f2 | 247ef42f | 0777e32f |
| `bomb/bootfiles-debug/bombload` | c9f75fd9 | 811c9606 | c487b77e |

The loaders were rebuilt on 2026-10-09 without the launcher-IOP trace check
(pop'n also moves to poltrace v4) and rig-tested from the stock HDD-OSD
browser to each title screen; these exact files are new on consoles. No title
loader has yet been started from its `-us` or `-all` copy on a console; the
PlayOnline loaders signed the same way have (US: `-us`; a console outside the
US and Japan: `-all`).

## UI text

`scripts/helper/check-ui-text.sh` refuses a straight apostrophe inside a `: "${UI_TEXT[KEY]:=...}"` default (older bash fails to parse it; use U+2019) and syntax-checks every script. Run it with `check-loader-assets.py` before publishing.
