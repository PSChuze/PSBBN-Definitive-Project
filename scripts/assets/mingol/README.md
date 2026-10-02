# Minna no Golf Online install kit

Everything the toolkit needs to install Minna no Golf Online (SCPS-15049) that
does not come from the player's disc. See `../../Mingol-Installer.sh` for how
these are used and `../../helper/mingol/tools/` for the Python.

## Contents

| path | what | how it was made |
|---|---|---|
| `kit/*.kit.json` | nine 2-7 KB "seal kits" that, together with the disc's plaintext `ZZBIN/<name>` overlay, rebuild each drive-neutral DNAS2 container. No game code (Sony copyright) lives in them - only signed records + framing + the decrypted K1 block. Total ~44 KB. | `mingol/tools/sealkit.py make` from a decrypted install (Minna project, HANDOFF-install-and-dnas s7). |
| `patched/SYSTEM.BIN` | the plaintext SYSTEM overlay with the 0x1915d0 DNAS state-machine short-circuited (`lui at,0x29 / sw zero,0x2e88(at) / b 0x191ac4 / nop`), so the game reports DNAS pass without a live Sony gateway. | Minna project, `work/patched/SYSTEM.BIN`; see HANDOFF-boot-plan.md s5. Substitutes for the disc's own `ZZBIN/SYSTEM.BIN` when the installer seals. |
| `attr-area.bin` | 112,128-byte PS2ICON3D attr from a retail install. The installer rewrites the SYSTEM.CNF at +0x200 in place before writing (`BOOT2 = pfs:/dnasload.elf` + `DNASBOOT2 = pfs:/SCPS_150.49`) so BBNav launches HDD-side. | Extracted from the archive.org donor drive (Minna project HANDOFF-install-and-dnas s6). |
| `polbbnexec-mingol.kelf` | signed polbbnexec loader with an unfilled 2 MB boot-ELF slot, a 512 KB IOPRP slot, an HDD ID slot and an argv0 slot. The installer fills the four slots per drive with the disc's boot ELF, an IOPRP augmented with DEV9/ATAD/HDD/PFS from the disc's FMOD, the drive's `playonline.hddid`, and `hdd0:PP.SCPS-15049..APPLICATION:pfs:/SCPS_150.49`. | Docker build of `mingol/work/loader/build-mingol.sh` (ps2dev/ps2dev:latest, DRIVERS=2, IOPRP_SLOT=524288), then signed via `playonline.lib.polkelf --encrypt` using a Nobunaga dnasload.elf as header template. |

## Not shipped here (the player supplies)

- The disc tree at `games/MGO/disc/` (SYSTEM.CNF, ZZBIN/, FMOD/, res/, and the
  asset dirs). The installer refuses to run without it.
- The served drive ID at `games/POL/playonline.hddid`. The PlayOnline step mints
  it; Minna reads it, never writes it.

## Provenance

The Sony bytes here (signed records inside the kit, the retail attr, the KELF
signature envelope from Sony's Kbit/Kc under the operator's PS2KEYS.dat) are
metadata shared with other PlayStation 2 Sony-title tools. No decrypted game
code from Sony's Minna no Golf Online is present.
