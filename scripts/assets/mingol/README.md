# Minna no Golf Online loader

The two files the toolkit needs to install Minna no Golf Online (SCPS-15049)
that do not come from the player's discs. Everything else is made from the
discs at install time by `../../helper/mingol/stage` (see
`../../Mingol-Installer.sh`).

## Contents

| path | what | how it was made |
|---|---|---|
| `polbbnexec-mingol.kelf` | the signed, unfilled disc-less loader. Our polbbnexec built with DRIVERS=3: it reboots the IOP from its IOPRP slot, loads the shim that serves the drive's HDD ID and sends the game's `cdrom0:\FMOD\` / `cdrom0:\FMOD2\` module loads to `pfs2:/FMOD/` / `pfs2:/FMOD2/` (so it runs with no disc) and the game's open of `cdrom0:\FRES\ROOT_ED.PEM;1` to `pfs2:/ROOT_ED.PEM`, adds the console's own SYSMEM, read from its BIOS ROM, to the IOP reboot image before the reboot, leaves the four IOP drivers from its driver slots resident, then enters the boot ELF. Slots: boot ELF 1 MiB, IOPRP 512 KiB, HDD ID, argv0, and four driver slots (`POLDRIVERSLOTS1`). Only the first 32 content bytes are signed; every slot lies after them, so the installer fills it per drive without keys. | HippaulInstaller `playonline/games/mingol/loader-src/build.sh` (ps2dev/ps2dev, DRIVERS=3, SPOOF_ILINK=1 with the default console ID, FMOD and ROOT_ED.PEM redirects), output `assets/games/mingol-loader.elf` (sha1 a8713a0b), then signed with `playonline.lib.polkelf --encrypt` using a Nobunaga `dnasload.elf` as header template (region mask 0x1, Japan). |
| `ROOT_ED.PEM` | the revival's Feega CA, a public certificate (RSA-1024, SHA-1 fingerprint 91:92:25:B8:...:BE:14). The stage pads it with newlines to the disc file's 1652 bytes and puts it at the partition root, where the shim sends the Feega login's CA read; with `--stock-servers` (MINGOL_SERVERS=stock) the disc's own `FRES/ROOT_ED.PEM` goes there instead. | the revival's Feega server CA (file sha1 7622bb5f), as HippaulInstaller ships it (`assets/games/mingol-ROOT_ED.PEM`). |

## How the installer fills it

`mingol.stage` (`helper/mingol/stage/loader.py`, via `playonline.loader.fill`):

- boot ELF: the disc's `SCPS_150.49` with the disc-less edits (`bootpatch.py`;
  guarded, checked against the proven SHA-1 bbf02fd5)
- IOPRP: the disc's `FMOD/DNAS270.IMG` as it is (`ioprp.py`). It has no
  SYSMEM; the loader copies the console's own out of its BIOS ROM
  (0xBFC00000) and inserts it as the first module at boot, so no second
  disc is needed
- driver slots: the disc's `FMOD/DEV9.IRX`, `ATAD.IRX`, `HDD.IRX`, `PFS.IRX`;
  ATAD with its genuine-drive check skipped and the drive's HDD ID in its
  identity block (`helper/mingol/stage/atadgp.py`, guarded), so a non-Sony drive works
- HDD ID: the drive's `games/POL/playonline.hddid`
- argv0: `cdrom0:\SCPS_150.49;1`

The filled file goes into the partition as `pfs:/dnasload.elf`. The disc's
`FMOD/*.IRX|ICO|SYS` and `FMOD2/*.IRX` go into the partition's `FMOD/` and
`FMOD2/` for the loader's redirect, and `ROOT_ED.PEM` (above) into its root.

## Not shipped here (the player supplies)

- The SCPS-15049 disc image (or its extracted tree) under `games/MGO/`.
- The drive ID at `games/POL/playonline.hddid`, minted by the PlayOnline step.

## Provenance

The KELF signature envelope is made with Sony's MagicGate keys from the
operator's PS2KEYS.dat; the content is our code and ps2sdk's only. No Sony
game code is in this folder.
