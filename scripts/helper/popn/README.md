# pop'n Puzzle Dama Online helper

Used by `scripts/Popn-Installer.sh` (Extras menu). The game is installed straight
from the player's own disc: `tools/popninstall.py` seals the disc containers to the
target drive, fills the spoof loader, and writes `PP.BLJA-00010`.

## English translation

When the player says yes to the translation prompt (`popninstall.py --translate
elf.en.tsv`), the install is fully English:

- **Text**: the boot ELF gets the translated strings (`tools/pntext.py elf-b` with
  `translation/elf.en.tsv`) and the English-release patches
  (`tools/patch_boot_elf.py` `ENGLISH_PATCHES`: X confirms and O cancels, the keyboard
  opens on English, and the date/time, gender and birthdate fields are in English).
- **Images**: the menu, dialog, lobby and profile textures in `IMAGE.DAT` and
  `IMAGE1.DAT`, and the tutorial speech banners in `IMAGE3.DAT`, are rebuilt in English from the disc's own copies
  (`translation/apply_textures_nat.py` plus `translation/screens/*.py`, through
  `tools/textures_build.py`). This takes several minutes. Pass `--no-textures`
  (or set `POPN_NO_TEXTURES=1` for the installer) to keep the Japanese images.

Without `--translate`, or with `--no-textures`, the installer and the in-place
re-swap write the disc's stock `IMAGE.DAT` / `IMAGE1.DAT` / `IMAGE3.DAT`.

The image build needs Pillow and numpy. OpenCV (`opencv-python-headless`) is
optional but gives the reference result. `Popn-Installer.sh` installs all three
into the venv and the nix flake includes them. If Pillow or numpy is missing, the
install keeps the Japanese images and still applies the English text.

In the same Python environment, the images are byte-identical to the pop'n
project's own build (`apply_textures_nat.build()` over all screens).
`textures_build.py` pins Pillow's text layout to BASIC, because the Linux Pillow
wheels default to RAQM, which places glyphs differently. Across operating systems
the bytes still differ a little, because OpenCV's inpaint fills the erased
backgrounds slightly differently on Windows and on Linux. Each rebuilt file keeps
the disc file's size. Before anything is installed, every byte outside the
screens' texture slots is checked against the disc: the certificate area of
`IMAGE1.DAT` (the first 0x8f0 bytes), the block headers and layout tables of
`IMAGE3.DAT`, and every texture no screen edits.

## Source

`tools/` and `translation/` are copies of the pop'n project's `popn/tools` and
`popn/translation`, with the same layout: `apply_textures_nat.py` finds
`../tools` and `screens/` relative to its own folder. Keep that layout when you
re-sync. To refresh the copies (and `assets/popn/elf.en.tsv`) from a popn
checkout, run `python3 scripts/helper/popn/sync_from_popn.py <path to popn/>`
(`--check` only lists the differences).
