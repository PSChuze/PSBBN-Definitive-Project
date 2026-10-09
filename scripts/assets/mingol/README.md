# Minna no Golf Online loader

The two files the toolkit needs to install Minna no Golf Online (SCPS-15049)
that do not come from the player's discs. Everything else is made from the
discs at install time by `../../helper/mingol/stage` (see
`../../Mingol-Installer.sh`).

## Contents

| path | what | how it was made |
|---|---|---|
| `polbbnexec-mingol.kelf` | the signed, unfilled disc-less loader. Our polbbnexec built with DRIVERS=3: it reboots the IOP from its IOPRP slot, loads the shim that serves the drive's HDD ID and sends the game's `cdrom0:\FMOD\` / `cdrom0:\FMOD2\` module loads to `pfs2:/FMOD/` / `pfs2:/FMOD2/` (so it runs with no disc) and the game's open of `cdrom0:\FRES\ROOT_ED.PEM;1` to `pfs2:/ROOT_ED.PEM`, reboots the IOP with the slot's image as it is (UDNL takes SYSMEM from the console's rom0; the BIOS-ROM SYSMEM splice is compiled out, ROM_SYSMEM=0, see below), leaves the four IOP drivers from its driver slots resident, then enters the boot ELF. It also carries the game's way to its Feega account client with no disc (2026-10-09): before it starts the game it puts a small program of its own (`relaunch.c`) at 0x00090000 and points the game's LoadExecPS2 system call at it, so `cdrom0:\FEEGAGUI.ELF;1` (and the client's way back, `cdrom0:\SCPS_150.49;1`) keeps the IOP and starts `pfs2:/RELAUNCH.ELF`, the installer's plain copy of this loader; called with that `argv[0]` it boots the IOP the same way, mounts the partition through the shim and starts the staged, patched `pfs2:/FEEGAGUI.ELF` (or the game, with the client's result and `Register`). Its `plain_head` slot (`POLPLAINHEAD1`) holds the ELF's first 32 bytes, the ones the KELF keeps encrypted, so the installer can write that plain copy without keys (`helper/mingol/stage/feega.py`). Slots: boot ELF 1 MiB, IOPRP 512 KiB, HDD ID, argv0, and four driver slots (`POLDRIVERSLOTS1`). Only the first 32 content bytes are signed; every slot lies after them, so the installer fills it per drive without keys. | HippaulInstaller `playonline/games/mingol/loader-src/build.sh` (ps2dev/ps2dev, DRIVERS=3, SPOOF_ILINK=1 with the default console ID, FMOD, ROOT_ED.PEM and FRES redirects, the Feega relauncher, v4 trace slot `TRACELBA` = 0, ROM_SYSMEM=0), output `assets/games/mingol-loader.elf` (sha1 631a358b; `VERBOSE=1` builds the narrating twin, `assets/games/mingol-loader-verbose.elf`, sha1 c5056b22), then signed with `playonline.lib.polkelf --encrypt` using the previous kelf (ab62750a, itself templated on a Nobunaga `dnasload.elf`; region mask 0x1, Japan) as header template, keys PS2KEYS.dat: kelf sha1 5895fb0d, verbose 23858b0f (2026-10-09, after the Feega build: the trace check before the IOP reboot is compiled out, `PREREBOOT_TRACE_CHECK`, since it ran through the launcher's IOP and halted the verbose loader on a stock HDD-OSD console; region twins by `helper/sign-region-loaders.py`). The Feega build it replaces was kelf 742e0e05, verbose c959a70e (content d9b694a5 / b368079a). The build before the Feega client was kelf ab62750a (content ee2854cf). The splice build it replaces is kept as `polbbnexec-mingol.kelf.bak-splice-20261007` (2d2b0a6b, content a8713a0b). |
| `ROOT_ED.PEM` | the revival's Feega CA, a public certificate (RSA-1024, SHA-1 fingerprint 91:92:25:B8:...:BE:14). The stage pads it with newlines to the disc file's 1652 bytes and puts it at the partition root, where the shim sends the Feega login's CA read; with `--stock-servers` (MINGOL_SERVERS=stock) the disc's own `FRES/ROOT_ED.PEM` goes there instead. | the revival's Feega server CA (file sha1 7622bb5f), as HippaulInstaller ships it (`assets/games/mingol-ROOT_ED.PEM`). |

## How the installer fills it

`mingol.stage` (`helper/mingol/stage/loader.py`, via `playonline.loader.fill`):

- boot ELF: the disc's `SCPS_150.49` with the disc-less edits (`bootpatch.py`;
  guarded, checked against the proven SHA-1 1d2f2908), including the answer
  to the online DNAS step's disc read, so going online needs no disc either
- IOPRP: the disc's `FMOD/DNAS270.IMG` as it is (`ioprp.py`). It has no
  SYSMEM; at the IOP reboot UDNL takes the console's own from rom0, so no
  second disc is needed. (Until 2026-10-07 the loader spliced the SYSMEM
  out of the BIOS ROMDIR at 0xBFC00000 into the image itself; that walk is
  BIOS-dependent and hung on real hardware on 2026-10-08 at "driver slot 3",
  while the same loader built with ROM_SYSMEM=0 booted the game to its
  title. The splice code stays in the source behind `ROM_SYSMEM=1`.)
- driver slots: the disc's `FMOD/DEV9.IRX`, `ATAD.IRX`, `HDD.IRX`, `PFS.IRX`;
  ATAD with its genuine-drive check skipped and the drive's HDD ID in its
  identity block (`helper/mingol/stage/atadgp.py`, guarded), so a non-Sony drive works
- HDD ID: the drive's `games/POL/playonline.hddid`
- argv0: `cdrom0:\SCPS_150.49;1`

The filled file goes into the partition as `pfs:/dnasload.elf`. The disc's
`FMOD/*.IRX|ICO|SYS` and `FMOD2/*.IRX` go into the partition's `FMOD/` and
`FMOD2/` for the loader's redirect, and `ROOT_ED.PEM` (above) into its root.
For the Feega account client the partition also gets the same loader as a
plain ELF (`RELAUNCH.ELF`), the disc's `FEEGAGUI.ELF` with its disc-less
patches (English when the translation pack carries the client's text) and
the disc's `FRES/` but `ROOT_ED.PEM`.

## Not shipped here (the player supplies)

- The SCPS-15049 disc image (or its extracted tree) under `games/GOLF/`.
- The drive ID at `games/POL/playonline.hddid`, minted by the PlayOnline step.

## Provenance

The KELF signature envelope is made with Sony's MagicGate keys from the
operator's PS2KEYS.dat; the content is our code and ps2sdk's only. No Sony
game code is in this folder.
