"""Online menu (hub) + ranking category screens - IMAGE1.DAT block 0x101800.

Block 0x101800 header = [0x10, 0x3c0, 0x1a7c0, 0x30170] -> sub-streams:
  0x101810  layout table (20 sprite rects, u16 u,v,w,h; v>=512 = second texture)
  0x101bc0  hub background (texture 1): "Menu Select" plate, "(Coming soon!)" note,
            lobby help strips, the High score / Prefecture highlight labels
  0x11bfc0  overlay sprites (texture 2): ranking category list panel, lobby list panel,
            two grey HELP strips, the highlighted (selected) category / lobby labels
  0x131970  empty sub-stream (u32 0) -> texture 2 must end before it, so its slot_end
            is 0x131970 (not the next header at 0x132460, which belongs to block 0x132000).
Clips are the layout-table rects where the table lists them; the rest were measured.
The ranking table itself (rows, names, numbers) is drawn by the ELF text renderer, not
from textures. "???" and "Ranking"/"Lobby"/"Online" art are already English.

Highlight labels (and the Menu Select plate) need `local=True`: inpaint only from pixels
inside the clip. Those sprites sit on black atlas gaps, and a whole-image inpaint pulls
black blotches into the plate. If the editor does not support `local` yet, those edits
are skipped (the Japanese stays) instead of producing blotches.
"""
import os, sys, inspect

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
    import pntexnat as _pn
    _LOCAL = '"local"' in inspect.getsource(_pn.apply_edits)
except Exception:
    _LOCAL = False


# Selected-label colours sampled from the Japanese glyphs: cream fill (the JP fill runs
# peach (254,216,141) at the top to near-white at the bottom) and a heavy outline that is
# mostly dark green (2,64,27)/(3,78,39)/(13,89,46) mixed with dark brown (61,28,3); it
# reads as dark green / near-black, so the outline uses the dark green.
HL_FILL = (255, 247, 222)
HL_OUT = (2, 64, 27)
LS_FILL, LS_OUT = 252, 175          # unselected list labels: soft white, light outline

# SELECTED / NORMAL PAIRS. Each highlighted sprite is drawn in place of its normal label;
# matching the Japanese fill masks gives where it lands on the normal art: the 12
# category sprites land at x=13 of the list panel (y below), the two lobby sprites at
# x=168 of the lobby panel. The English is drawn at the SAME offset from each sprite's
# own top-left, in the SAME font size, so it does not move when the selection blinks.
# Size = as tall as the Japanese glyphs (the whole plate height), heavy sw=3 outline,
# and squeeze=True compresses long words horizontally instead of shrinking them.
#   name, english, highlight (texture, rect), normal-label origin on texture 2, (unused)
PAIRS = [
    ("rank",     "Rank",             (2, (396, 138, 432, 160)), (13, 15), 17),
    ("win",      "Win%",             (2, (432, 138, 468, 160)), (13, 39), 17),
    ("wins",     "Wins",             (2, (450, 92, 500, 114)),  (13, 63), 17),
    ("loss",     "Losses",           (2, (346, 140, 396, 162)), (13, 88), 17),
    ("games",    "Games",            (2, (432, 70, 484, 92)),   (13, 112), 17),
    ("chain",    "Max chain",        (2, (264, 140, 346, 162)), (13, 136), 17),
    ("balls",    "Balls cleared",    (2, (156, 140, 264, 162)), (13, 160), 17),
    ("pref",     "Prefecture",       (1, (436, 470, 502, 492)), (13, 185), 17),
    ("chara",    "Top characters",   (2, (392, 116, 506, 139)), (13, 209), 17),
    ("attack",   "Top attack balls", (2, (310, 70, 432, 92)),   (13, 233), 17),
    ("hs",       "High score",       (1, (436, 448, 508, 470)), (13, 258), 17),
    ("pts",      "Points",           (2, (436, 44, 494, 66)),   (13, 282), 17),
    ("normal",   "Normal Lobby",     (2, (156, 116, 278, 140)), (168, 18), 19),
    ("beginner", "Beginner Lobby",   (2, (278, 116, 392, 140)), (168, 49), 19),
]
DX = 1          # text starts 1 px in from the sprite's left edge (where the JP glyph starts)
SW = 3          # heavy outline like the original selected glyphs
MARGIN = 2      # squeeze width = sprite width - DX - MARGIN

# The 12 ranking categories all use ONE font size and ONE baseline (live test: per-word
# sizing made "Wins"/"Points" big and the squeezed "Prefecture"/"High score" small).
# 17 px is the biggest size whose glyph box over ALL twelve words (ascenders, the
# descenders of "Top"/"High score", the sw=3 outline) fits the 22 px sprites; long
# words in narrow sprites are then only condensed horizontally (squeeze >= ~0.76).
CAT_FS = 17
CAT_N = 12


def _measure(t, fs):
    from PIL import Image, ImageDraw, ImageFont
    dr = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    return dr.textbbox((0, 0), t, font=ImageFont.truetype(_pn.FONT, fs), stroke_width=SW)


def _pair_layout(t, w, h, cap=None):
    """(fs, dy): the biggest size whose full glyph box (ascenders, descenders, outline)
    fits the sprite height minus 1, and the y offset (from the sprite top) that centres
    it. Width is handled by squeeze in the editor."""
    fs = 30
    while fs > 8:
        bb = _measure(t, fs)
        if bb[3] - bb[1] <= h - 1:
            break
        fs -= 1
    bb = _measure(t, fs)
    return fs, int(round((h - (bb[3] - bb[1])) / 2.0)) - bb[1]


def _cat_layout(words, h):
    """(fs, dy) shared by all category labels: fixed CAT_FS, vertically centred on the
    union glyph box of every word so all baselines line up."""
    bbs = [_measure(t, CAT_FS) for t in words]
    top, bot = min(b[1] for b in bbs), max(b[3] for b in bbs)
    assert bot - top <= h - 1, "CAT_FS too big for %d px sprites" % h
    return CAT_FS, int(round((h - (bot - top)) / 2.0)) - top


def _text(sx, sy, w, h, t, fs, dy, fill, out):
    # text-only edit (hat=255 -> empty removal mask). The clip is the same rect relative
    # to the sprite origin in both members of a pair, so squeeze/placement is identical.
    return dict(clip=(sx + DX, sy, sx + w, sy + h), lines=[t], ty0=sy + dy, lh=20, fs=fs,
                align="l", fill=fill, outline=out, sw=SW, squeeze=True, margin=MARGIN,
                bg="flat", hat=255, kk=3, dil=0)


def _rm_hl(clip):
    # remove the JP from a highlighted sprite (outlined glyphs, rebuilt from the plate)
    return dict(clip=clip, bg="outlined", wht=130, drk=120, reach=3, dil=1, local=True)


def _rm_panel(clip):
    # Remove the soft white JP from the bubbly list / lobby panels WITHOUT smoothing
    # the panel (live test: inpaint left pale smears where the labels were). The panel
    # is rows of a 2-px dither plus dotted lines and large dotted-rim bubbles. Glyph =
    # cream fill (min channel > 215; ~2 % of the panel is that light, and those
    # pixels just get their own row's neighbour) grown 3 px over its tan outline; each glyph pixel takes the ORIGINAL palette index of
    # the nearest clean pixel in the same row an even number of px away (dir (2, 0)),
    # so the dither phase and the original indices are kept. The highlighted twins do
    # not help here: their bold glyphs cover ~96 % of the normal glyph pixels and their
    # plates are not index-identical to the panel.
    return dict(clip=clip, bg="rows", dir=(2, 0), wht=215, dil=3, drk=-1)


def _rm_soft(clip):
    # remove soft white JP from the list / lobby panels (pastel bands + bokeh)
    return dict(clip=clip, bg="inpaint", hat=14, kk=9, dil=1)


def _grey(clip, t):
    # grey HELP strip (flat key colour)
    return dict(clip=clip, lines=[t], ty0=clip[1] + 3, lh=20, fs=13, bg="key",
                fill=250, outline=28, sw=2, wht=190, dil=3)


def _green(clip, lines):
    # two-line lobby HELP strip on the flat green HELP colour
    return dict(clip=clip, lines=lines, ty0=clip[1] + 1, lh=21, fs=14, bg="key", align="l",
                fill=250, outline=28, sw=2, wht=190, dil=3)


def _copy_plate(clip, src):
    # Rebuild a whole highlight plate from a same-sized, already cleaned region.
    # local=True: dropped together with the (local) cleanups on an older editor, so it
    # never copies an uncleaned Japanese plate.
    return dict(clip=clip, bg="copy", src=src, local=True)


# HIGHLIGHT PLATES. Removing the bold JP glyphs from a highlight sprite and inpainting the
# few plate pixels left leaves dark outline remnants: live tests showed "Win%" on a dark
# rectangle, Prefecture tan and "Wins" with a dark brown slanted wedge (the inpainted
# outline of 数). The original highlight plate is exactly the list-panel art behind the
# label (same bands and bokeh at the same offset; only the glyphs differ), so every
# category highlight on texture 2 is rebuilt as a copy of the CLEANED panel region at its
# normal-label origin (after LIST_RM/GHOST, before any English is drawn). The two hub
# (texture 1) sprites cannot copy across textures, and an outlined cleanup of ハイスコア
# still left a dark brown plate on screen (live test), so both are repainted whole with
# bg="pattern": one colour per row, the panel's own row colour sampled from texture 2
# (median of the glyph-free panel x 95..149 at the normal-label rows; those rows are
# flat there). The High score layout rect is 72 wide (436..508): the old 70-px clip left
# the tail of ア at x 506-507 as a stray "'" speck.
PLATE_FROM_PANEL = True
PLATE_FROM = {}                            # tex 1 twin copies (none now)
_HS_ROWS = [(227, 251, 156)] * 7 + [(229, 251, 157)] * 2 + [(227, 251, 156)]     + [(231, 251, 159)] * 3 + [(232, 251, 159), (231, 251, 159), (232, 251, 159)]     + [(234, 252, 160)] * 6
_PREF_ROWS = [(208, 228, 149)] * 2 + [(197, 245, 139)] * 9 + [(202, 246, 140)] * 9     + [(254, 226, 158)] * 2
PLATE_ROWS = {"hs": _HS_ROWS, "pref": _PREF_ROWS}

HUB_RM, HUB_TX, OV_HL_RM, OV_HL_TX, OV_LS_TX = [], [], [], [], []
HUB_CP, OV_CP = [], []
LAYOUT = {}
_CAT = _cat_layout([p[1] for p in PAIRS[:CAT_N]], 22)
_HL = {p[0]: p[2] for p in PAIRS}
for _k, (_n, _t, (_tex, _r), (_lx, _ly), _cap) in enumerate(PAIRS):
    _w, _h = _r[2] - _r[0], _r[3] - _r[1]
    _fs, _dy = _CAT if _k < CAT_N else _pair_layout(_t, _w, _h)
    LAYOUT[_n] = dict(fs=_fs, dx=DX, dy=_dy, hl=_r, tex=_tex, list=(_lx, _ly))
    if _k < CAT_N and _tex == 2 and PLATE_FROM_PANEL:
        # the list panel spans x 12..149 here; the source must stay on it
        assert 12 <= _lx and _lx + _w <= 149, _n
        OV_CP.append(_copy_plate(_r, (_lx - _r[0], _ly - _r[1])))
    elif _n in PLATE_ROWS:
        assert len(PLATE_ROWS[_n]) == _h, _n
        (HUB_CP if _tex == 1 else OV_CP).append(
            dict(clip=_r, bg="pattern", rows=[[c] for c in PLATE_ROWS[_n]], local=True))
    elif _n in PLATE_FROM:
        _tw, (_ddx, _ddy) = PLATE_FROM[_n]
        _ttex, _tr = _HL[_tw]
        # the source region must lie inside the twin's own (cleaned) sprite
        assert _ttex == _tex and _tr[0] <= _r[0] + _ddx and _r[2] + _ddx <= _tr[2]             and _tr[1] <= _r[1] + _ddy and _r[3] + _ddy <= _tr[3], _n
        (HUB_CP if _tex == 1 else OV_CP).append(_copy_plate(_r, (_ddx, _ddy)))
    else:
        (HUB_RM if _tex == 1 else OV_HL_RM).append(_rm_hl(_r))
    (HUB_TX if _tex == 1 else OV_HL_TX).append(
        _text(_r[0], _r[1], _w, _h, _t, _fs, _dy, HL_FILL, HL_OUT))
    OV_LS_TX.append(_text(_lx, _ly, _w, _h, _t, _fs, _dy, LS_FILL, LS_OUT))

LIST_RM = [_rm_panel((12, 17 + round(24.3 * i) - 3, 149, 17 + round(24.3 * i) + 21))
           for i in range(12)]
LOBBY_RM = [_rm_panel((164, 18, 304, 46)), _rm_panel((164, 48, 304, 78))]

# Menu Select plate interior x 38..156, rows 87..116: per row the colours of the
# 2-px dither at x (38, 39), sampled from the disc texture (each is a unique palette
# entry of tex 0x101bc0, so the repaint maps back to the original indices).
MS_X0, MS_X1 = 38, 157
MS_ROWS = [
    [(173, 250, 145), (173, 250, 145)],
    [(173, 250, 145), (173, 250, 145)],
    [(190, 233, 114), (190, 233, 114)],
    [(190, 233, 114), (187, 228, 114)],
    [(187, 228, 114), (187, 228, 114)],
    [(159, 212, 186), (187, 228, 114)],
    [(187, 217, 97), (187, 217, 97)],
    [(198, 198, 197), (198, 198, 197)],
    [(198, 198, 197), (177, 223, 104)],
    [(159, 221, 101), (159, 221, 101)],
    [(159, 221, 101), (159, 221, 101)],
    [(134, 232, 89), (154, 221, 97)],
    [(134, 232, 89), (134, 232, 89)],
    [(134, 232, 89), (130, 229, 88)],
    [(130, 229, 88), (137, 204, 117)],
    [(137, 204, 117), (132, 215, 90)],
    [(137, 204, 117), (137, 204, 117)],
    [(132, 198, 139), (110, 218, 88)],
    [(110, 218, 88), (110, 218, 88)],
    [(117, 202, 94), (117, 202, 94)],
    [(112, 199, 94), (112, 199, 94)],
    [(155, 154, 156), (155, 154, 156)],
    [(155, 154, 156), (155, 154, 156)],
    [(157, 159, 155), (157, 159, 155)],
    [(157, 159, 155), (157, 159, 155)],
    [(89, 190, 86), (89, 190, 86)],
    [(89, 190, 86), (84, 186, 88)],
    [(84, 186, 88), (84, 186, 88)],
    [(75, 184, 87), (84, 186, 88)],
    [(75, 184, 87), (75, 184, 87)],
]
HUB = [
    # "Menu Select" plate: rows of a 2-px dither that only changes top to bottom. The
    # outlined inpaint left dark-green blotches where 選択's outline rose above the
    # text line (live test: splotches around "Select"), so the plate interior is
    # repainted whole from its own clean left columns (x 38/39, left of メ), then the
    # English is drawn on top with an empty removal mask.
    dict(clip=(MS_X0, 87, MS_X1, 117), bg="pattern", rows=MS_ROWS, local=True),
    dict(clip=(38, 87, 157, 117), lines=["Menu Select"], ty0=91, lh=20, fs=18,
         bg="flat", hat=255, wht=256, drk=-1, dil=0, fill=250, outline=28, sw=2),
    # JP style: pale fill inside a soft GREEN halo (108,196,96), not a grey outline
    # (the grey read as splotches on the leafy green)
    # clip from x 230: the JP "(" and its halo start at ~x 236 (left a white smear)
    dict(clip=(230, 190, 388, 228), lines=["(Coming soon!)"], ty0=196, lh=22, fs=18,
         bg="inpaint", hat=14, kk=9, dil=2, fill=(240, 240, 236), outline=(108, 196, 96),
         sw=3),
    _green((0, 448, 260, 492), ["It's the Beginner Lobby!", "Only for 6 Kyu and below!"]),
    _green((260, 448, 436, 492), ["It's the Normal Lobby!", "Anyone can join!"]),
] + HUB_RM + HUB_CP + HUB_TX

# Faint bokeh-circle arcs right of the short "Wins" (the JP 勝ち数 used to cover them)
# read as a leftover "~" mark; smooth them out (no text). NOT USED since the row
# copy (_rm_panel): its inpaint itself left a pale smear right of "Wins".
GHOST = dict(clip=(50, 63, 100, 88), bg="inpaint", hat=6, kk=7, dil=1)

OVERLAY = LIST_RM + LOBBY_RM + OV_HL_RM + OV_CP + [
    _grey((157, 93, 323, 115), "View the rankings!"),
    _grey((325, 93, 449, 115), "Go to the lobby!"),
] + OV_LS_TX + OV_HL_TX


def _ok(edits):
    return [e for e in edits if _LOCAL or not e.get("local")]


SCREENS = [
    dict(name="online-hub", file="IMAGE1.DAT", fo=0x101bc0, slot_end=0x11bfc0,
         edits=_ok(HUB)),
    dict(name="ranking-overlay", file="IMAGE1.DAT", fo=0x11bfc0, slot_end=0x131970,
         edits=_ok(OVERLAY)),
]
