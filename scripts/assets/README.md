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
nobunaga/tools/traceslot.py). Tester notes: RELEASE-NOTES-hw-boot.md.

| title | silent (N) | debug (Y) |
|---|---|---|
| Nobunaga | `nobunaga/polbbnexec-inputpatch.kelf` (DRIVERS=4, **no input hook** since 2026-10-08 despite the name: b6da0082; the hook build is `polbbnexec-inputpatch.kelf.hook-unproven`, it stopped boot #56 on the console) | `nobunaga/polbbnexec-nobu-verbose.kelf` (FORK_VERBOSE, DRIVERS=4, no input hook) |
| pop'n | `popn/polbbnexec-popn.kelf` | `popn/polbbnexec-popn-verbose.kelf` (FORK_VERBOSE, same pre-v4 source; record LBA baked at 19264032) |
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
| `nobunaga/polbbnexec-inputpatch` | b6da0082 | db7ff679 | 26d46572 |
| `nobunaga/polbbnexec-nobu-verbose` | 0688ba91 | 3d407c3e | 8f01c6df |
| `popn/polbbnexec-popn` | 99bc9bbc | 9d41c19c | c625040f |
| `popn/polbbnexec-popn-verbose` | 04a340be | 3a76025c | 8d69532e |
| `mingol/polbbnexec-mingol` | ab62750a | def210fc | cbb0f654 |
| `mingol/polbbnexec-mingol-verbose` | 31ac2af8 | 72358602 | 6fd7d707 |
| `bomb/bootfiles/bombload` | af144da3 | 54b48e36 | bec01aa9 |
| `bomb/bootfiles-debug/bombload` | 9cd0dffc | 3b6dd18d | 86992bcb |

The Japanese copies are the console-proven files, unchanged. No title loader
has yet been started from its `-us` or `-all` copy on a console; the
PlayOnline loaders signed the same way have (US: `-us`; a console outside the
US and Japan: `-all`).

## UI text

`scripts/helper/check-ui-text.sh` refuses a straight apostrophe inside a `: "${UI_TEXT[KEY]:=...}"` default (older bash fails to parse it; use U+2019) and syntax-checks every script. Run it with `check-loader-assets.py` before publishing.
