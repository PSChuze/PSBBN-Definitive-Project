# Real hardware boot: tester release notes

This release is about getting the four online titles to start on a real PS2
from the hard drive, with no disc:

- Nobunaga's Ambition Online (Hiryu no Sho)
- Pop'n Puzzle-dama Online
- Net de Bomberman
- Minna no Golf Online (Everybody's Golf Online)

All four have now started on a real console. This build packages what made
that work, and adds a way for you to show us what your console does when a
game does not start.

## What changed for real hardware

- **New drive driver for Nobunaga.** Nobunaga's loader now uses the same open
  ATA driver as pop'n (the "DRIVERS=4" build). The old one checked for a
  genuine Sony hard drive and never got past that check on a console; the new
  one works on any drive PSBBN works on, including SSDs and non-Sony drives.
- **Bomberman: console ID split.** The Bomberman loader (scefix 1.2) now gives
  the game's DNAS check the console ID its boot record was made for, and gives
  your network settings your console's real ID, so both work. The browser
  entry also carries the DNAS boot line the console expects. Before this,
  Bomberman went straight back to the PSBBN menu.
- **Minna: no more BIOS patching at start-up.** The Minna loader used to copy a
  part of the console's BIOS into the game's start-up image. That hung on a
  real console, so it is now built out. Minna starts, logs in to Feega and goes
  online on a real PS2 with this loader.
- **Pop'n: drive ID guard.** The game files on the drive are locked to one
  drive ID, and the loader must serve that same ID or the screen stays black.
  Refreshing the pop'n loader now checks this first. If they do not match, it
  stops and offers three choices: re-lock the game files to this machine's ID
  (R), keep the drive as it is and use the ID its files are locked to (K), or
  write nothing (N, the default).
- **Boot debug text (new).** Every title installer now asks:

      Show boot debug text on the console? (y/N)

  - **N** (the default): the game starts as normal, with no text on the screen.
  - **Y**: the console prints each step of the game's start-up on the TV, and
    if a step fails it stops there and shows the reason. Where the loader
    supports it, a small boot record (`trace.bin`, one sector) is also set up
    in the game's partition, so the loader can write down what it saw.
    Bomberman shows its `[boot]` lines and waits 5 seconds before the game
    starts.

  You can run the title's step again at any time and answer N to turn the text
  off. Your saves are kept.

## If a game does not boot

1. In the PSBBN toolkit, open Extras and run the step for that game again.
   When it asks whether to update the game already on the drive (for pop'n:
   whether to re-swap the boot loader), answer yes; your saves are kept. Then
   answer **Y** to "Show boot debug text on the console?". Note the line
   "Boot record armed at drive sector N" if it shows one.
2. Put the drive back in the PS2 and start the game from the browser.
3. **Take a photo of the TV** when the text stops changing (or when the game
   goes back to the menu, photograph the last screen you saw). Make sure the
   text can be read.
4. Put the drive back in the PC and make a drive report with `hwaudit`. It only
   reads the drive; it never writes to it.

   **Linux** (from the toolkit folder, with the PS2 drive connected; find it
   with `lsblk -o NAME,SIZE,MODEL`, below it is `/dev/sdX`):

       sudo blockdev --flushbufs /dev/sdX
       sudo scripts/venv/bin/python3 scripts/helper/nobunaga/tools/hwaudit.py /dev/sdX --helper scripts/helper --json hwaudit.json > hwaudit.txt

   **Windows**: start the PSBBN Launcher and pick the PS2 drive as usual, so
   that it is attached. Then, in a second PowerShell window:

       wsl -d PSBBN --cd ~/PSBBN-Definitive-Project
       lsblk -o NAME,SIZE,MODEL
       sudo blockdev --flushbufs /dev/sdX
       sudo scripts/venv/bin/python3 scripts/helper/nobunaga/tools/hwaudit.py /dev/sdX --helper scripts/helper --json hwaudit.json > hwaudit.txt
       cp hwaudit.txt hwaudit.json /mnt/c/Users/Public/

   (`/dev/sdX` is the PS2 drive from the `lsblk` list. The two files then
   appear in `C:\Users\Public`.)

   If step 1 showed "Boot record armed at drive sector N", save that sector
   too (replace N and the game name):

       sudo dd if=/dev/sdX of=trace-GAME.bin bs=512 skip=N count=1

5. Send us the photo, `hwaudit.txt`, `hwaudit.json`, any `trace-GAME.bin`, the
   installer log from `logs/` (for example `logs/bomb-installer.log`), and
   your console model (the SCPH number on the label at the back or bottom).

When the game works again, run the step once more with **N** to remove the
text.

## Known limits

- **Nobunaga text input stays Japanese by default.** The game's text is in
  English with the translation, but typing still starts in Japanese input
  mode. The fix for this changes the game while it runs, and it stopped the
  game from starting on a real console, so it is held back until it is
  reworked.
- **Bomberman web pages are Japanese.** The game's messages are in English with
  the translation, but the pages it shows from its web server, and the menus
  that are drawn as pictures, stay Japanese.
- **Pop'n boot record.** The pop'n loader writes its boot record to one fixed
  sector, so the record only works on a drive where `trace.bin` lands on that
  sector. Elsewhere the debug text still shows; the installer tells you when
  no record can be kept.

## Updates keep your saves

Running a title's step again on a drive that already has the game updates it
in place. Only the files that changed are rewritten; your saves and settings
stay on the drive. Choosing the language or the debug text again works the
same way.
