"""Offline menus: Player Select / Level Select / Play Condition help strips, the level
speech bubbles and the unlock dialogs (new character / attack ball / BGM).

Every clip is a sprite rect (or a cell inside one) from the block's layout table
(sub-stream 0, LZSS: 16-byte header, then u16 x, y, w, h per sprite until the first
empty record; v / 512 = texture number in the block):

  block 0xc9000   tex0 0xc9520  (66,482,274,510) / (274,482,482,508) 2-player strip
                                (pale / highlighted pair)
                  tex1 0xec880  (180,260,372,286) / (180,286,370,312) vs-COM strip pair
  block 0x104000  tex0 0x104a70 (0,478,150,504) pale / (246,448,396,474) hi   normal
                                (288,474,426,500) pale / (150,478,288,504) hi beginner
                                (396,448,490,474) hi                          expert
                  tex1 0x11d030 (0,414,94,440) pale expert (pair of the one above)
                                (0|154|308, 280, +154, 414) three speech bubbles
  block 0x14d000  tex0 0x14d860 (364,448,498,474) pale "とっても有利だよ!"
  block 0x173000  tex1 0x1926e0 (0, 0|134|268, 340, +134) three unlock dialogs (blue)
                  tex2 0x1a9af0 (0,0,340,134) new-BGM dialog (blue)
  block 0x1cc800  tex3 0x213b50 (0, 0|134|268, 340, +134) three unlock dialogs (green)
                  (the survey's 0x213b60 was 0x10 off: the stream starts at 0x213b50,
                  right where login_account's disc-check slot ends; its own slot is
                  0x213b50-0x2234b0 and no other module touches that texture)
Each slot_end is the next sub-stream (or the block end for the last texture),
checked to hold only the stream's own tail + zero padding.

Strips: the text floats on the TRANSPARENT palette entry 0 (index 1 is an opaque
black used in the glyph outlines, so a luminance mask cannot tell them apart). Each
strip is wiped to index 0 (bg="key" with an explicit key=0) and the English is drawn
in three layers like the JP: a 1 px rim, a thick outline, the fill, aliased (aa=False)
so no edge pixel blends into the transparent black and maps to a dark halo. Pairs
(pale/highlighted) use one font size and the same sprite-relative origin.

Bubbles: white text over a striped ellipse it almost covers; the ellipse is rebuilt
row by row from its fitted geometry (see BUBBLES). Dialogs: pale text with a dark
outline on horizontal bands -> bg="rows" (each removed pixel copies its own row's
index) + a per-row dark-pixel cleanup.

Needs two opt-in keys added to pntexnat (default behaviour unchanged): "key" (an
explicit key index for bg="key") and "aa" (False = aliased glyphs).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import pntexnat
from PIL import Image, ImageDraw, ImageFont

_DR = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def _bbox(txt, fs, sw):
    return _DR.textbbox((0, 0), txt, font=ImageFont.truetype(pntexnat.FONT, fs), stroke_width=sw)


# ---- floating help strips --------------------------------------------------------
# one font size per family: Player Select (2P + vs-COM) 17, Level Select 16 (bounded
# by the 94 px expert strip), Play Condition 17
PLAYER_FS, LEVEL_FS, COND_FS = 17, 16, 17
SW_OUT, SW_MAIN = 3, 2  # rim pass / outline pass stroke widths

# (rim, outline, fill) per strip look, all taken from the strips' own palettes
PALE = ((228, 240, 218), (253, 253, 253), (217, 193, 100))     # white outline, gold fill
HI_PURPLE = ((124, 147, 58), (134, 50, 124), (246, 246, 245))  # olive rim, purple outline
HI_LEVEL = ((161, 203, 116), (143, 46, 130), (253, 253, 253))
HI_OLIVE = ((95, 191, 25), (84, 86, 3), (236, 229, 208))       # green rim, olive outline


def _wipe(clip):
    """Every non-transparent pixel of the clip -> index 0 (the sprite holds only text)."""
    return dict(clip=clip, bg="key", key=0, wht=-1, dil=0)


def _draw_only(clip, txt, ty0, fs, fill, outline, sw):
    """Text-only pass: empty removal mask, aliased glyphs, left-aligned at clip x0."""
    return dict(clip=clip, lines=[txt], ty0=ty0, lh=20, fs=fs, align="l", margin=0,
                fill=fill, outline=outline, sw=sw, bg="flat", hat=255, kk=3,
                wht=255, drk=0, dil=0, aa=False)


def _strip(rect, txt, look, ref_w, ref_h, fs):
    """Wipe the strip sprite and draw `txt` centred in a (ref_w x ref_h) box at the
    sprite's top-left, so both members of a pair get the same relative origin."""
    x0, y0, x1, y1 = rect
    bb = _bbox(txt, fs, SW_OUT)
    w, top, bot = bb[2] - bb[0], bb[1], bb[3]
    assert w <= x1 - x0 and w <= ref_w, "%r does not fit %r" % (txt, rect)
    ox = x0 + (ref_w - w) // 2                 # left edge of the rim's bbox
    ty0 = y0 + (ref_h - (bot - top)) // 2 - top
    assert ty0 + top >= y0 and ty0 + bot <= y1, "%r too tall for %r" % (txt, rect)
    rim, out, fill = look
    return [_wipe(rect),
            _draw_only((ox, y0, x1, y1), txt, ty0, fs, rim, rim, SW_OUT),
            _draw_only((ox + SW_OUT - SW_MAIN, y0, x1, y1), txt, ty0, fs,
                       fill, out, SW_MAIN)]


def _pair(a, b, txt, look_a, look_b, fs):
    w = min(a[2] - a[0], b[2] - b[0]); h = min(a[3] - a[1], b[3] - b[1])
    return _strip(a, txt, look_a, w, h, fs), _strip(b, txt, look_b, w, h, fs)


FRIEND = "Battle a friend!"
VS_COM = "Battle the computer!"    # "Play against the computer!" only fits at 15 px
NORMAL = "Normal difficulty!"
BEGIN = "For beginners!"
EXPERT = "For experts!"           # "Experts only!" only fits the 94 px strip at 15 px
HUGE_ADV = "Huge advantage!"      # same wording as lobby_room's handicap labels

P2_PALE, P2_HI = _pair((66, 482, 274, 510), (274, 482, 482, 508), FRIEND, PALE, HI_PURPLE,
                       PLAYER_FS)
COM_PALE, COM_HI = _pair((180, 260, 372, 286), (180, 286, 370, 312), VS_COM, PALE, HI_OLIVE,
                         PLAYER_FS)
NOR_PALE, NOR_HI = _pair((0, 478, 150, 504), (246, 448, 396, 474), NORMAL, PALE, HI_LEVEL,
                         LEVEL_FS)
BEG_PALE, BEG_HI = _pair((288, 474, 426, 500), (150, 478, 288, 504), BEGIN, PALE, HI_LEVEL,
                         LEVEL_FS)
EXP_PALE, EXP_HI = _pair((0, 414, 94, 440), (396, 448, 490, 474), EXPERT, PALE, HI_LEVEL,
                         LEVEL_FS)
ADV = _strip((364, 448, 498, 474), HUGE_ADV, PALE, 134, 26, COND_FS)


# ---- level speech bubbles (tex1 0x11d030) ------------------------------------------
BUB_FS = 13
BUB_LH = 15
# JP lines sit at rows 317-328 / 332-343 / 347-358 (pitch 15) in every bubble.
# The JP sits on a striped inner ellipse (rows alternate teal 80 / red 82: odd rows 80,
# even rows 82) inside the dark green bubble (34). The text covers most of the ellipse,
# so nothing nearby is clean enough to copy or inpaint from (row copies pulled dark
# green into the ellipse, vertical copies broke its outline). The ellipse is rebuilt
# instead, row by row over the text band (rows 315-361), from its fitted geometry
# (least squares on the clean boundary rows of all three bubbles, which agree:
# centre x 76.1 / y 336.4, semi-axes 67.0 x 28.35, bubble-relative):
#   inside the ellipse  -> the row's stripe index (bg="key", explicit key, whole span)
#   outside, to the rim -> pixels brighter than lum 85 (text + the ellipse's soft edge)
#                          refilled with the bubble's dark green 34 (bg="key", key=34)
# Clips stay in x 13..143 (bubble-relative): the pale rim is at x <= 12 / >= 145 on
# these rows. The English is then drawn in one text-only pass.
ELL_CX, ELL_CY, ELL_A, ELL_B = 76.1, 336.4, 67.0, 28.35
BUB_ROWS = range(315, 362)
BUB_X0, BUB_X1 = 13, 143

BUBBLES = [
    # (bubble x0, English)  EASY / HARD / NORMAL descriptions, in sprite order
    (0, ["Your rival's attack", "balls are all one color,", "so chains are easy!"]),
    (154, ["When your rival", "sends attack balls,", "chains get tough!"]),
    (308, ["Even under attack,", "you can still chain", "and strike back!"]),
]


def _ell_span(y):
    import math
    h = ELL_A * math.sqrt(max(0.0, 1 - ((y - ELL_CY) / ELL_B) ** 2))
    return int(round(ELL_CX - h + 0.5)), int(round(ELL_CX + h - 0.5)) + 1


def _bubble(bx, lines):
    out = []
    for y in BUB_ROWS:
        l, r = _ell_span(y)
        il, ir = max(l, BUB_X0 - 1), min(r, BUB_X1 + 1)
        out.append(dict(clip=(bx + il, y, bx + ir, y + 1), bg="key",
                        key=80 if y % 2 else 82, wht=-1, dil=0))
        for a, b in ((BUB_X0, il), (ir, BUB_X1)):
            if b > a:
                out.append(dict(clip=(bx + a, y, bx + b, y + 1), bg="key", key=34,
                                wht=85, dil=0))
    top = min(_bbox(t, BUB_FS, 1)[1] for t in lines)
    out.append(dict(clip=(bx + 8, 314, bx + 146, 362), lines=lines, ty0=317 - top,
                    lh=BUB_LH, fs=BUB_FS, align="c", margin=2, fill=(253, 253, 253),
                    outline=(40, 89, 17), sw=1, bg="flat", hat=255, kk=3, wht=255,
                    drk=0, dil=0))
    for t in lines:
        assert _bbox(t, BUB_FS, 1)[2] + 1 <= 136, t   # never shrinks
    return out


BUBBLE_EDITS = [e for bx, ls in BUBBLES for e in _bubble(bx, ls)]


# ---- unlock dialogs ----------------------------------------------------------------
DLG_FS = 15
CHAR = "New character unlocked!"
BALL = "New attack ball unlocked!"
APPEAR = "A new character appears!"
SONG = "A new song was added!"

# (fill, outline, wht, drk): text fill min channel >= ~178 (blue) / ~156 (green) while
# the band behind it stays <= 151 / <= 148; the outline lum < 80 vs band lum >= 113 / 204
BLUE = ((225, 240, 200), (16, 40, 48), 170, 108)   # pale green fill, dark teal outline
GREEN = ((250, 240, 205), (72, 40, 16), 152, 198)  # cream fill, brown outline


def _dlg(py, txt, look):
    """Body line of the dialog sprite at plate y `py`: JP at rows py+63 .. py+85,
    centred on x 170 (the JP's own centre; the bubbles on the left end at x ~85).
    1. bg="rows": the pale fill seeds the mask (+ the dark outline near it); each
       masked pixel copies the nearest clean index in its own row.
    2. per-row cleanup: outline pixels the fill seed did not reach (the fill's top is
       a darker gradient) are refilled with that row's most common index (bg="flat",
       hat=0, dark threshold only; one 1 px row per edit, so each band keeps its own
       colour).
    3. the English, text only."""
    fill, out, wht, drk = look
    x0, x1, y0, y1 = 80, 300, py + 60, py + 89
    eds = [dict(clip=(x0, y0, x1, y1), bg="rows", dir=(1, 0), wht=wht, drk=drk, dil=4)]
    eds += [dict(clip=(x0, y, x1, y + 1), bg="flat", hat=0, wht=255, drk=drk, dil=0)
            for y in range(y0, y1)]
    bb = _bbox(txt, DLG_FS, 2)
    ty0 = py + 74 - (bb[1] + bb[3]) // 2
    eds.append(dict(clip=(x0, y0, x1, y1), lines=[txt], ty0=ty0, lh=20, fs=DLG_FS,
                    align="c", margin=0, fill=fill, outline=out, sw=2, bg="flat",
                    hat=255, kk=3, wht=255, drk=0, dil=0))
    return eds


SCREENS = [
    dict(name="player-select-strip", file="IMAGE.DAT", fo=0xc9520, slot_end=0xec880,
         edits=P2_PALE + P2_HI),
    dict(name="player-select-com", file="IMAGE.DAT", fo=0xec880, slot_end=0x103fb0,
         edits=COM_PALE + COM_HI),
    dict(name="level-select-strips", file="IMAGE.DAT", fo=0x104a70, slot_end=0x11d030,
         edits=NOR_PALE + NOR_HI + BEG_PALE + BEG_HI + EXP_HI),
    dict(name="level-bubbles", file="IMAGE.DAT", fo=0x11d030, slot_end=0x130f00,
         edits=BUBBLE_EDITS + EXP_PALE),
    dict(name="play-condition-strip", file="IMAGE.DAT", fo=0x14d860, slot_end=0x168490,
         edits=ADV),
    dict(name="unlock-dialogs-blue", file="IMAGE.DAT", fo=0x1926e0, slot_end=0x1a9af0,
         edits=_dlg(0, CHAR, BLUE) + _dlg(134, BALL, BLUE) + _dlg(268, APPEAR, BLUE)),
    dict(name="unlock-bgm-blue", file="IMAGE.DAT", fo=0x1a9af0, slot_end=0x1b3be0,
         edits=_dlg(0, SONG, BLUE)),
    dict(name="unlock-dialogs-green", file="IMAGE.DAT", fo=0x213b50, slot_end=0x2234b0,
         edits=_dlg(0, APPEAR, GREEN) + _dlg(134, SONG, GREEN) + _dlg(268, BALL, GREEN)),
]
