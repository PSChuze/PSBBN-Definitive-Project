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
- **Nobunaga in English: US buttons and English typing.** An English install
  now gets a loader that adjusts the game's controls as it starts (proven on
  a real console): Cross confirms and Circle cancels, as on US games, every
  on-screen keyboard opens in half-width (English) mode, and the name fields
  take letters, up to 8 per part (family and given name). A Japanese install
  gets the plain loader and plays exactly like the retail game.
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

- **Consoles from every region (new).** Until now every title's loader opened
  only on a Japanese PS2. On a US, European or other console the game went
  straight back to the PSBBN browser with nothing on the screen, and no error
  anywhere. Each title now ships one loader per console region, as the
  PlayOnline step does, and the installer asks the PlayOnline step's question:

      Which region is the PS2 console this drive will be used in: US, Japanese, or European and other? [U/j/e]

  Answer for the console the drive will be used in (not the region of the
  game or of your discs). If the PlayOnline Viewer is already on the drive,
  or a title was installed with this release, the answer is read from the
  drive and not asked again. To change it (the drive moved to another
  console), set `POL_CONSOLE=us`, `jp` or `eu` for the step and run it again.

  **Wrong region looks like this:** you pick the game in the browser, the
  screen goes dark for a moment and you are back in the browser, with no text
  even with boot debug text on (the console refuses the loader before any of
  it runs). If that happens, run the step again and check the region answer.

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
   installer log from `logs/` (for example `logs/bomb-installer.log`), your
   console model (the SCPH number on the label at the back or bottom) and the
   console region you answered.

When the game works again, run the step once more with **N** to remove the
text.

## Known limits

- **US and European loaders are new.** The title loaders for US and for
  European and other consoles are signed the same way as the PlayOnline
  loaders that start on those consoles, but no title has been started from
  them on a console yet. Reports from US and European testers are the test.
- **Bomberman web pages are Japanese.** The game's messages are in English with
  the translation, but the pages it shows from its web server, and the menus
  that are drawn as pictures, stay Japanese.
- **Pop'n loader is new on consoles.** The pop'n loader now records a boot
  trace on any drive (it used to work only where `trace.bin` landed on one
  fixed sector), and its debug build no longer stops early on a console that
  only has the stock HDD-OSD browser. This build has run on our test setup but
  not yet on a console: the first console boots (a Japanese console and a
  non-Japanese one) are pending.

## Updates keep your saves

Running a title's step again on a drive that already has the game updates it
in place. Only the files that changed are rewritten; your saves and settings
stay on the drive. Choosing the language or the debug text again works the
same way.
