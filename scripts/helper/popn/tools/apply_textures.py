#!/usr/bin/env python3
"""Apply all pop'n IMAGE.DAT texture translations to a stock IMAGE.DAT.

  PYTHONUTF8=1 python popn/translation/apply_textures.py \
      work/disc/IMAGE.DAT  work/translation/IMAGE.en.DAT

Each entry in SCREENS edits one 512x512 texture (identified by its sub-stream
file offset `fo` and the next sub-stream offset `slot_end`) via pntexedit, in
place (zero-padded to the original slot) so every other byte is unchanged.
Edits are applied sequentially; see popn/tools/pntexedit.py for the edit DSL and
popn/HANDOFF-translation.md for the codec/format.
"""
import sys, os
# pntexedit lives next to this file when bundled in the toolkit, else in ../tools.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
sys.path.insert(0, os.path.join(_here, '..', 'tools'))
from pntexedit import edit_texture

# --- disc-check dialog (3 state boxes + account footer) : tex @0x1ffa90 ---
DISC_CHECK = dict(fo=0x1ffa90, slot_end=0x213b50, edits=[
    {"erase": (100, 33, 320, 55), "cx": 300}, {"text": "Wrong disc!", "cx": 180, "ty": 38, "ink": 40},
    {"erase": (88, 59, 336, 79), "cx": 300},  {"text": "Please insert the correct disc!", "cx": 180, "ty": 60, "ink": 40},
    {"erase": (76, 79, 338, 103), "cx": 300}, {"text": "Press O to start the disc check!", "cx": 180, "ty": 82, "ink": 40},
    {"erase": (88, 183, 336, 203), "cx": 300},{"text": "The disc has not been ejected!", "cx": 180, "ty": 184, "ink": 40},
    {"erase": (70, 203, 340, 228), "cx": 300},{"text": "Eject the disc and press O!", "cx": 180, "ty": 205, "ink": 40},
    {"erase": (90, 301, 332, 321), "cx": 300},{"text": "No disc is inserted!", "cx": 180, "ty": 302, "ink": 40},
    {"erase": (88, 321, 336, 341), "cx": 300},{"text": "Please insert the correct disc!", "cx": 180, "ty": 322, "ink": 40},
    {"erase": (74, 341, 340, 379), "cx": 300},{"text": "Press O to start the disc check!", "cx": 180, "ty": 343, "ink": 40},
    {"erase": (0, 397, 292, 415), "flatg": 147}, {"text": "Create an account!", "cx": 6, "ty": 398, "maxw": 280, "align": "l", "ink": 40},
    {"erase": (0, 416, 292, 435), "flatg": 147}, {"text": "First-time players, register here!", "cx": 6, "ty": 417, "maxw": 285, "align": "l", "ink": 40},
])

# --- online login screen : tex @0x2b1100 ---
LOGIN = dict(fo=0x2b1100, slot_end=0x2c4e40, edits=[
    {"erase": (42, 96, 262, 122), "cx": 272},
    {"text": "Enter ID & Password", "cx": 150, "ty": 99, "maxw": 205, "align": "c", "ink": 245, "fs": 16},
    {"erase": (186, 224, 320, 244), "cx": 345},
    {"text": "Press the O button!", "cx": 250, "ty": 226, "maxw": 150, "align": "c", "ink": 245, "fs": 14},
    {"erase": (126, 150, 183, 166), "flatg": 183},
    {"text": "pop'n ID", "cx": 152, "ty": 151, "maxw": 56, "align": "c", "ink": 25, "fs": 12},
    {"erase": (126, 178, 185, 194), "flatg": 181},
    {"text": "Password", "cx": 152, "ty": 179, "maxw": 60, "align": "c", "ink": 25, "fs": 11},
    {"erase": (0, 448, 512, 510), "flat": 1},
    {"text": "Your ID & password have been issued. Don't forget them!", "cx": 4, "ty": 452, "maxw": 505, "align": "l", "ink": 235, "fs": 15},
    {"text": "Note: IDs/passwords never use o0 (oh), I1 (eye), or 1L (ell).", "cx": 4, "ty": 476, "maxw": 505, "align": "l", "ink": 235, "fs": 15},
])

# --- communication-error screen : tex @0x1b40a0 ---
COMM_ERROR = dict(fo=0x1b40a0, slot_end=0x1bd9c0, edits=[
    {"erase": (28, 53, 180, 86), "flatg": 253},
    {"text": "Communication error!", "cx": 32, "ty": 55, "maxw": 210, "align": "l", "ink": 20, "fs": 16},
    {"erase": (28, 449, 300, 467), "cx": 305},
    {"text": "Sending data... please wait!", "cx": 30, "ty": 450, "maxw": 270, "align": "l", "ink": 25, "fs": 14},
    {"erase": (316, 449, 484, 467), "cx": 489},
    {"text": "Press the O button!", "cx": 320, "ty": 450, "maxw": 165, "align": "l", "ink": 25, "fs": 14},
])

# --- user-data select : tex @0x3312a0 ---
USER_SELECT = dict(fo=0x3312a0, slot_end=0x344fc0, edits=[
    {"erase": (40, 97, 250, 119), "cx": 255},
    {"text": "Select User Data", "cx": 140, "ty": 99, "maxw": 205, "align": "c", "ink": 245, "fs": 16},
    {"erase": (158, 378, 228, 396), "flatg": 218}, {"text": "New", "cx": 193, "ty": 379, "maxw": 66, "align": "c", "ink": 25, "fs": 13},
    {"erase": (285, 378, 342, 396), "flatg": 218}, {"text": "Delete", "cx": 313, "ty": 379, "maxw": 56, "align": "c", "ink": 25, "fs": 12},
])

# --- data-update dialog : tex @0x372970 ---
DATA_UPDATE = dict(fo=0x372970, slot_end=0x386210, edits=[
    {"erase": (36, 97, 152, 118), "flatg": 72}, {"text": "Data Update", "cx": 90, "ty": 99, "maxw": 112, "align": "c", "ink": 245, "fs": 15},
    {"erase": (90, 149, 428, 168), "flatg": 184}, {"text": "The game has been updated!", "cx": 256, "ty": 150, "maxw": 330, "align": "c", "ink": 25, "fs": 15},
    {"erase": (55, 169, 458, 188), "flatg": 184}, {"text": "You can't play online without updating it.", "cx": 256, "ty": 170, "maxw": 400, "align": "c", "ink": 25, "fs": 13},
    {"erase": (208, 230, 298, 248), "flatg": 182}, {"text": "Update now?", "cx": 252, "ty": 231, "maxw": 120, "align": "c", "ink": 25, "fs": 13},
    {"erase": (172, 272, 228, 290), "flatg": 209}, {"text": "Update", "cx": 200, "ty": 273, "maxw": 54, "align": "c", "ink": 25, "fs": 12},
    {"erase": (278, 272, 347, 290), "flatg": 209}, {"text": "Cancel", "cx": 312, "ty": 273, "maxw": 66, "align": "c", "ink": 25, "fs": 12},
])

# --- manual contents menu : tex @0x5431f0 ---
_MANUAL_ITEMS = [(227, "Greeting"), (249, "Online Info"), (271, "Network Setup"), (293, "Controller"),
                 (315, "Getting Started"), (337, "How to Play"), (359, "User Support")]
MANUAL = dict(fo=0x5431f0, slot_end=0x562e40, edits=(
    [{"erase": (150, 226, 200, 244), "flatg": 200}, {"text": "Index", "cx": 170, "ty": 227, "maxw": 48, "align": "c", "ink": 25, "fs": 10}]
    + [e for (y, t) in _MANUAL_ITEMS for e in (
        {"erase": (210, y - 1, 416, y + 17), "flatg": 190},
        {"text": t, "cx": 286, "ty": y, "maxw": 150, "align": "c", "ink": 25, "fs": 13})]
))

# --- registration flow (shared field labels) : tex 010/012/014/015 ---
_REG_FIELDS = ["Postal Code", "Birthdate", "Occupation", "Gender", "Username"]
def _fields(ys, labels):
    out = []
    for y, t in zip(ys, labels):
        out.append({"erase": (124, y - 1, 202, y + 18), "flatg": 187})
        out.append({"text": t, "cx": 162, "ty": y, "maxw": 78, "align": "c", "ink": 25, "fs": 10})
    return out

# user-data registration (郵便番号/生年月日/職業/性別 + Next/Cancel)
USER_DATA_REG = dict(fo=0x2cac40, slot_end=0x2dfcb0, edits=(
    [{"erase": (36, 97, 232, 118), "flatg": 80},
     {"text": "Register User Data", "cx": 134, "ty": 99, "maxw": 194, "align": "c", "ink": 245, "fs": 15}]
    + _fields([152, 176, 200, 224], _REG_FIELDS[:4])
    + [{"erase": (174, 272, 228, 290), "flatg": 210}, {"text": "Next", "cx": 200, "ty": 273, "maxw": 50, "align": "c", "ink": 25, "fs": 12},
       {"erase": (278, 272, 347, 290), "flatg": 210}, {"text": "Cancel", "cx": 313, "ty": 273, "maxw": 66, "align": "c", "ink": 25, "fs": 12}]
))

# username registration (ユーザー名 + Next/Cancel)
USERNAME_REG = dict(fo=0x2ed1b0, slot_end=0x3006d0, edits=[
    {"erase": (36, 97, 168, 118), "flatg": 80}, {"text": "Enter Username", "cx": 93, "ty": 99, "maxw": 112, "align": "c", "ink": 245, "fs": 13},
    {"erase": (128, 150, 203, 168), "flatg": 185}, {"text": "Username", "cx": 165, "ty": 151, "maxw": 72, "align": "c", "ink": 25, "fs": 11},
    {"erase": (174, 272, 228, 290), "flatg": 210}, {"text": "Next", "cx": 200, "ty": 273, "maxw": 50, "align": "c", "ink": 25, "fs": 12},
    {"erase": (278, 272, 347, 290), "flatg": 210}, {"text": "Cancel", "cx": 312, "ty": 273, "maxw": 66, "align": "c", "ink": 25, "fs": 12},
])

# registration confirm (5 fields + Register with this? + Register/Cancel)
REG_CONFIRM = dict(fo=0x307970, slot_end=0x31c190, edits=(
    [{"erase": (36, 97, 138, 118), "flatg": 90}, {"text": "Confirm Signup", "cx": 84, "ty": 99, "maxw": 100, "align": "c", "ink": 245, "fs": 11}]
    + _fields([150, 176, 202, 228, 260], _REG_FIELDS)
    + [{"erase": (200, 310, 345, 328), "flatg": 176}, {"text": "Register with this?", "cx": 270, "ty": 311, "maxw": 150, "align": "c", "ink": 25, "fs": 12},
       {"erase": (172, 388, 228, 406), "flatg": 210}, {"text": "Register", "cx": 200, "ty": 389, "maxw": 54, "align": "c", "ink": 25, "fs": 10},
       {"erase": (278, 388, 347, 406), "flatg": 210}, {"text": "Cancel", "cx": 313, "ty": 389, "maxw": 66, "align": "c", "ink": 25, "fs": 12}]
))

# registration complete (5 fields + Press O)
REG_DONE = dict(fo=0x31c8e0, slot_end=0x3308a0, edits=(
    [{"erase": (36, 97, 138, 118), "flatg": 85}, {"text": "Signup Done", "cx": 84, "ty": 99, "maxw": 100, "align": "c", "ink": 245, "fs": 12}]
    + _fields([150, 176, 202, 228, 258], _REG_FIELDS)
    + [{"erase": (186, 308, 334, 326), "flatg": 177}, {"text": "Press the O button!", "cx": 256, "ty": 309, "maxw": 155, "align": "c", "ink": 25, "fs": 12}]
))

# --- delete / disconnect confirmation dialogs : tex 018/019/017 ---
DELETE_SELECT = dict(fo=0x351280, slot_end=0x366e70, edits=[
    {"erase": (36, 97, 196, 118), "flatg": 118}, {"text": "Delete User Data", "cx": 108, "ty": 99, "maxw": 150, "align": "c", "ink": 245, "fs": 13},
    {"erase": (155, 370, 355, 388), "flatg": 193}, {"text": "Select data to delete", "cx": 256, "ty": 371, "maxw": 210, "align": "c", "ink": 25, "fs": 12},
    {"erase": (222, 392, 292, 410), "flatg": 178}, {"text": "Cancel", "cx": 256, "ty": 393, "maxw": 66, "align": "c", "ink": 25, "fs": 12},
])
DELETE_CONFIRM = dict(fo=0x366e70, slot_end=0x372170, edits=[
    {"erase": (126, 40, 292, 58), "flatg": 184}, {"text": "Really delete?", "cx": 206, "ty": 41, "maxw": 160, "align": "c", "ink": 25, "fs": 14},
    {"erase": (88, 78, 152, 96), "flatg": 180}, {"text": "Delete", "cx": 120, "ty": 79, "maxw": 60, "align": "c", "ink": 25, "fs": 11},
    {"erase": (193, 78, 292, 96), "flatg": 180}, {"text": "Cancel", "cx": 242, "ty": 79, "maxw": 66, "align": "c", "ink": 25, "fs": 12},
])
DISCONNECT = dict(fo=0x344fc0, slot_end=0x350f40, edits=[
    {"erase": (120, 40, 300, 58), "flatg": 178}, {"text": "Disconnect?", "cx": 206, "ty": 41, "maxw": 175, "align": "c", "ink": 25, "fs": 13},
    {"erase": (72, 78, 162, 96), "flatg": 187}, {"text": "Disconnect", "cx": 117, "ty": 79, "maxw": 88, "align": "c", "ink": 25, "fs": 10},
    {"erase": (193, 78, 292, 96), "flatg": 193}, {"text": "Cancel", "cx": 242, "ty": 79, "maxw": 66, "align": "c", "ink": 25, "fs": 12},
])

# --- handicap / play-condition labels (white on black) : tex @0x168490 ---
HANDICAP = dict(fo=0x168490, slot_end=0x1729a0, edits=[
    {"erase": (286, 104, 418, 127), "flatg": 0}, {"text": "Big advantage!", "cx": 350, "ty": 106, "maxw": 128, "align": "c", "ink": 245, "fs": 13},
    {"erase": (286, 128, 422, 165), "flatg": 0}, {"text": "Huge advantage!", "cx": 352, "ty": 131, "maxw": 132, "align": "c", "ink": 245, "fs": 13},
    {"erase": (0, 183, 120, 208), "flatg": 0}, {"text": "Small edge!", "cx": 58, "ty": 185, "maxw": 118, "align": "c", "ink": 245, "fs": 13},
    {"erase": (118, 183, 292, 208), "flatg": 0}, {"text": "Big handicap!", "cx": 238, "ty": 185, "maxw": 122, "align": "c", "ink": 245, "fs": 12},
    {"erase": (290, 183, 418, 209), "flatg": 0}, {"text": "Small handicap!", "cx": 352, "ty": 185, "maxw": 126, "align": "c", "ink": 245, "fs": 11},
    {"erase": (400, 2, 486, 54), "flatg": 0},
    {"text": "Even!", "cx": 442, "ty": 16, "maxw": 80, "align": "c", "ink": 245, "fs": 13},
    {"text": "Even!", "cx": 442, "ty": 37, "maxw": 80, "align": "c", "ink": 245, "fs": 13},
])

# --- data-update result dialogs : tex @0x39ab00 ---
DATA_UPDATE_RESULT = dict(fo=0x39ab00, slot_end=0x3a73a0, edits=[
    {"erase": (95, 33, 325, 53), "flatg": 205}, {"text": "Update complete!", "cx": 210, "ty": 35, "maxw": 215, "align": "c", "ink": 25, "fs": 14},
    {"erase": (40, 60, 436, 81), "flatg": 188}, {"text": "Quit the game, then power on again!", "cx": 215, "ty": 62, "maxw": 380, "align": "c", "ink": 25, "fs": 13},
    {"erase": (95, 86, 365, 106), "flatg": 172}, {"text": "Press O to quit!", "cx": 215, "ty": 88, "maxw": 260, "align": "c", "ink": 25, "fs": 13},
    {"erase": (88, 178, 372, 198), "flatg": 152}, {"text": "Data update failed!", "cx": 205, "ty": 180, "maxw": 270, "align": "c", "ink": 25, "fs": 14},
    {"erase": (88, 203, 372, 223), "flatg": 140}, {"text": "Press the O button!", "cx": 205, "ty": 205, "maxw": 270, "align": "c", "ink": 25, "fs": 13},
])

# --- Auto-Load (BB Unit) dialogs : tex @0x28716c0 ---
AUTOLOAD = dict(fo=0x28716c0, slot_end=0x2884b00, edits=[
    {"erase": (110, 203, 378, 223), "flatg": 120}, {"text": "Loading...", "cx": 245, "ty": 205, "maxw": 180, "align": "c", "ink": 245, "fs": 14},
    {"erase": (78, 224, 482, 300), "flatg": 102},
    {"text": "Data may be corrupted. Don't power off or", "cx": 282, "ty": 233, "maxw": 400, "align": "c", "ink": 245, "fs": 13},
    {"text": "reset the PS2, or remove the BB Unit!", "cx": 282, "ty": 257, "maxw": 400, "align": "c", "ink": 245, "fs": 13},
    {"erase": (110, 342, 378, 372), "flatg": 132}, {"text": "Load complete!", "cx": 245, "ty": 347, "maxw": 180, "align": "c", "ink": 245, "fs": 14},
])

# --- BB Unit save/space dialogs : tex @0x4d110 ---
BBUNIT_SAVE = dict(fo=0x4d110, slot_end=0x60020, edits=[
    {"erase": (70, 56, 478, 80), "flatg": 108}, {"text": "Game data is saved on the BB Unit,", "cx": 274, "ty": 60, "maxw": 410, "align": "c", "ink": 245, "fs": 13},
    {"erase": (70, 82, 478, 105), "flatg": 100}, {"text": "so please check the BB Unit!", "cx": 274, "ty": 85, "maxw": 410, "align": "c", "ink": 245, "fs": 13},
    {"erase": (70, 192, 478, 216), "flatg": 104}, {"text": "Creating save data on the BB Unit!", "cx": 274, "ty": 196, "maxw": 410, "align": "c", "ink": 245, "fs": 13},
    {"erase": (70, 286, 478, 308), "flatg": 110}, {"text": "Not enough free space on the BB Unit!", "cx": 274, "ty": 289, "maxw": 410, "align": "c", "ink": 245, "fs": 13},
    {"erase": (70, 308, 478, 328), "flatg": 104}, {"text": "This game's data needs 7MB or more!", "cx": 274, "ty": 310, "maxw": 410, "align": "c", "ink": 245, "fs": 13},
    {"erase": (120, 328, 390, 348), "flatg": 98}, {"text": "Start anyway?", "cx": 255, "ty": 330, "maxw": 260, "align": "c", "ink": 245, "fs": 13},
])

# --- Auto-Load + install-space (PS2/BB Unit) dialogs : tex @0x28ac5e0 ---
INSTALL_SPACE = dict(fo=0x28ac5e0, slot_end=0x28c1ec0, edits=[
    {"erase": (90, 30, 380, 50), "flatg": 118}, {"text": "Loading...", "cx": 240, "ty": 32, "maxw": 180, "align": "c", "ink": 245, "fs": 14},
    {"erase": (28, 62, 484, 130), "flatg": 100},
    {"text": "Data may corrupt, so don't power off or reset", "cx": 256, "ty": 66, "maxw": 455, "align": "c", "ink": 245, "fs": 12},
    {"text": "the PS2, remove the card (8MB),", "cx": 256, "ty": 90, "maxw": 455, "align": "c", "ink": 245, "fs": 12},
    {"text": "or unplug the controllers!", "cx": 256, "ty": 112, "maxw": 455, "align": "c", "ink": 245, "fs": 12},
    {"erase": (28, 156, 484, 212), "flatg": 104},
    {"text": "Not enough BB Unit space!", "cx": 256, "ty": 158, "maxw": 455, "align": "c", "ink": 245, "fs": 13},
    {"text": "Installing this app needs 128MB or more!", "cx": 256, "ty": 178, "maxw": 455, "align": "c", "ink": 245, "fs": 12},
    {"text": "Start without installing?", "cx": 256, "ty": 194, "maxw": 455, "align": "c", "ink": 245, "fs": 13},
    {"erase": (28, 302, 484, 324), "flatg": 105}, {"text": "Make sure the BB Unit has 128MB+ free!", "cx": 256, "ty": 306, "maxw": 455, "align": "c", "ink": 245, "fs": 12},
])

SCREENS = [DISC_CHECK, LOGIN, COMM_ERROR, USER_SELECT, DATA_UPDATE, MANUAL,
           USER_DATA_REG, USERNAME_REG, REG_CONFIRM, REG_DONE,
           DELETE_SELECT, DELETE_CONFIRM, DISCONNECT, HANDICAP,
           DATA_UPDATE_RESULT, AUTOLOAD, BBUNIT_SAVE, INSTALL_SPACE]

if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    cur = src
    tmp = out + '.tmp'
    for i, s in enumerate(SCREENS):
        n, slot = edit_texture(cur, tmp, s['fo'], s['slot_end'], s['edits'])
        print(f"  screen {i} @ {s['fo']:#x}: {n} / {slot} bytes ({'ok' if n <= slot else 'OVERFLOW'})")
        cur = tmp
    os.replace(tmp, out)
    print("wrote", out)
