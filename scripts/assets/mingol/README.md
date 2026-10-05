# Minna no Golf Online loader

The one file the toolkit needs to install Minna no Golf Online (SCPS-15049)
that does not come from the player's discs. Everything else is made from the
discs at install time by `../../helper/mingol/stage` (see
`../../Mingol-Installer.sh`).

## Contents

| path | what | how it was made |
|---|---|---|
| `polbbnexec-mingol.kelf` | the signed, unfilled disc-less loader. Our polbbnexec built with DRIVERS=3: it reboots the IOP from its IOPRP slot, loads the shim that serves the drive's HDD ID and sends the game's `cdrom0:\FMOD\` / `cdrom0:\FMOD2\` module loads to `pfs2:/FMOD/` / `pfs2:/FMOD2/` (so it runs with no disc), leaves the four IOP drivers from its driver slots resident, then enters the boot ELF. Slots: boot ELF 1 MiB, IOPRP 512 KiB, HDD ID, argv0, and four driver slots (`POLDRIVERSLOTS1`). Only the first 32 content bytes are signed; every slot lies after them, so the installer fills it per drive without keys. | HippaulInstaller `playonline/games/mingol/loader-src/build.sh` (ps2dev/ps2dev, DRIVERS=3, SPOOF_ILINK=1 with the default console ID, FMOD redirect), output `assets/games/mingol-loader.elf` (sha1 d54be84e), then signed with `playonline.lib.polkelf --encrypt` using a Nobunaga `dnasload.elf` as header template (region mask 0x1, Japan). |

## How the installer fills it

`mingol.stage` (`helper/mingol/stage/loader.py`, via `playonline.loader.fill`):

- boot ELF: the disc's `SCPS_150.49` with the disc-less edits (`bootpatch.py`;
  guarded, checked against the proven SHA-1 bbf02fd5)
- IOPRP: the disc's `FMOD/DNAS270.IMG` with SYSMEM inserted from the Nobunaga
  no Yabou Online Hiryuu no Shou disc (SLPM-65783; `ioprp.py`, proven sha1
  356c7c48)
- driver slots: the disc's `FMOD/DEV9.IRX`, `ATAD.IRX`, `HDD.IRX`, `PFS.IRX`;
  ATAD with its genuine-drive check skipped and the drive's HDD ID in its
  identity block (`helper/mingol/stage/atadgp.py`, guarded), so a non-Sony drive works
- HDD ID: the drive's `games/POL/playonline.hddid`
- argv0: `cdrom0:\SCPS_150.49;1`

The filled file goes into the partition as `pfs:/dnasload.elf`. The disc's
`FMOD/*.IRX|ICO|SYS` and `FMOD2/*.IRX` go into the partition's `FMOD/` and
`FMOD2/` for the loader's redirect.

## Not shipped here (the player supplies)

- The SCPS-15049 disc image (or its extracted tree) under `games/MGO/`.
- The SLPM-65783 disc image (or its extracted tree) under `games/NOBU/`, for
  SYSMEM. Minna boots only with it.
- The drive ID at `games/POL/playonline.hddid`, minted by the PlayOnline step.

## Provenance

The KELF signature envelope is made with Sony's MagicGate keys from the
operator's PS2KEYS.dat; the content is our code and ps2sdk's only. No Sony
game code is in this folder.
