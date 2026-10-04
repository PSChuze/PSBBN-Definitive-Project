"""Options menus (OPTION screen family) + BGM title plates - IMAGE.DAT texture edits.

Every rect below comes from the block layout tables (sub-stream 0 of each block, LZSS,
u16 x/y/w/h per sprite, v / 512 = texture number). Sprite ids are (block index << 16) |
sprite number; block indices are the walker's order (0x1a = 0x433000 ... 0x4c =
0x15c6800), matching the 0x126230(sprite id) draw calls in the HDD ELF.

  0x433a50  block 0x1a tex0  Option main: background (0,0,512,448) has the Ball Cancel
            column heads ぜんだま / あくだま / くいだま baked in; sp14 (0,482,178,510) is
            the BGM value "ROSE~恋人よ、薔薇色に染まれ".
  0x4c5480  block 0x1b tex0  Key Config: background rows ○/×/□/△ボタン (1P x~100, 2P
            x~288); sp10/15/17 value plates ひだりまわり/つかわない/みぎまわり; sp12 / sp14
            warnings; sp0 / sp2 the selected-row ×/△ボタン sprites.
  0x4e9990  block 0x1b tex1  sp3/4/6/7/1/5 the other selected-row ボタン sprites, sp13 the
            1P warning (the Attention dialog itself, sp18, is already English).
  0x4f49c0  block 0x1c tex0  Ranking Data background: "○ボタンで Exit".
  0x514230  block 0x1d tex0  Sound: sp2 commentary plate "実況 パターンA" (twin of tex1 sp3).
  0x533b30  block 0x1d tex1  Sound: sp3/4/5 commentary plates A/B/B, sp6/sp7 "実況 Off".
  0x5631f0  block 0x1f tex0  Manual page: background "×目次" button hint.
  0x15c6a60 block 0x4c tex0  BGM title plates sp5/3/2 (ROSE, Home sick Pt2&3, Pink Rose).
  0x15e46a0 block 0x4c tex1  BGM title plates sp7/6/1/4/9/8.
Each texture's slot ends at the next sub-stream (block offsets); every tail is the 2-byte
END marker + zero padding. 0x5631f0 and 0x15c6a60 overflow their slots with
pnimage.compress even UNEDITED (by 352 / 1227 bytes); pntexnat.edit_texture now falls back
to an exact-cost parse (_compress_exact) only when the standard coder overflows, which
fits them (102430 / 103424 and 121222 / 121920).

Not covered here: block 0x1a tex1 (0x457660, owned by screens/lobby_room.py) also carries
Option-menu art: the help line strings (ランキング情報が見れるよ! ...), a second ROSE~ plate,
ジャージメン 愛のテーマ plates, ランダム, and あくだま / くいだま sprites that are probably the
highlighted twins of this module's Ball Cancel heads and ROSE plate.

Button swap (popn/re/RE-button-swap.md: X = confirm, O = cancel after the patch):
  * Key Config rows and the selected-row sprites name PHYSICAL buttons (the row-map word
    keeps them truthful), so the ○/×/□/△ glyph art is kept and only ボタン -> "Button".
  * Ranking Data "○ボタンで Exit": the viewer callback (HDD 0x1c4860, jump table 0x3242d0)
    exits only on mapped bit 1 = CONFIRM (case 2, cancel, does nothing). After the swap
    confirm is physical X, so the line reads "Press X to Exit" (letter X, the way the
    texture strings already write the buttons as letters).
  * Manual "×目次": the page viewer (HDD 0x209f98) returns to the contents on mapped bit 2
    = CANCEL. After the swap cancel is physical O, so the grey button's x is redrawn as a
    ring and the label is "Contents" (same treatment as the ranking strip's "O Back").

Ball Cancel column heads: 善玉 / 悪玉 / 食い玉, the three special balls the option turns
on or off (manual: "ぜんだま・あくだま・くいだまを使うか使わないかを設定" ). English:
"Good ball" / "Bad ball" / "Eater ball".

BGM genre tags: the small kana above each title are pop'n music GENRE names, not ruby
(the set includes a Latin "KC"), so they are translated, not removed: DIGI ROCK, SOFT ROCK,
HEART, VISUAL 2, J-TECHNO 2, FUTURE, PUZZLE DAMA, SYMPATHY.
"""

# ---- shared helpers -------------------------------------------------------------------

def _rm(clip, wht=200, drk=90, reach=2, dil=1, local=True):
    """Remove the Japanese only (white fill + dark outline, inpainted from the element)."""
    return dict(clip=clip, bg="outlined", wht=wht, drk=drk, reach=reach, dil=dil, local=local)


def _tx(clip, txt, ty0, fs, fill, out, sw=2, align="l", squeeze=False, margin=0, bold=0,
        lh=24):
    """Text only (empty removal mask: flat + hat 255 never flags a pixel)."""
    return dict(clip=clip, lines=[txt], ty0=ty0, lh=lh, fs=fs, align=align, fill=fill,
                outline=out, sw=sw, squeeze=squeeze, margin=margin, bold=bold,
                bg="flat", hat=255, kk=3, dil=0)


# ---- 0x433a50 Option main --------------------------------------------------------------
OPT_FILL, OPT_OUT = (243, 243, 234), (96, 83, 18)
BALLS = [((252, 131, 316, 164), 282, "Good ball"),
         ((318, 131, 382, 164), 349, "Bad ball"),
         ((384, 131, 448, 164), 414, "Eater ball")]
OPTION_MAIN = []
for _c, _cx, _t in BALLS:
    OPTION_MAIN += [_rm(_c, wht=150, drk=125, reach=4, dil=2),
                    _tx((_cx - 32, _c[1], _cx + 32, _c[3]), _t, 138, 16, OPT_FILL, OPT_OUT,
                        align="c", bold=1)]
ROSE_OPT = (0, 482, 178, 510)
OPTION_MAIN += [_rm(ROSE_OPT, wht=150, drk=100, reach=3, dil=1),
                _tx(ROSE_OPT, "ROSE ~Lover, Be Dyed in Rose~", 485, 17, (243, 243, 234),
                    (66, 52, 0), squeeze=True, margin=4, align="c", bold=1)]

# ---- 0x4c5480 Key Config (block 0x1b tex0) --------------------------------------------
# Background rows: "ボタン" right of each button glyph (rows y 182/211/241/271, columns
# x 112 / 300) is removed with the top/black-hat mask and inpainted from the background
# art (the rows sit inside the 512x448 background sprite), then "Button".
KC_FILL, KC_OUT = (246, 246, 242), (74, 86, 8)
KC_ROWS = [182, 211, 241, 271]          # top of each row's glyph block (outline incl.)
KC_COLS = [112, 300]                    # first column right of the button icon
KEY_CONFIG = []
for _x in KC_COLS:
    for _y in KC_ROWS:
        _c = (_x, _y - 1, _x + 41, _y + 25)
        KEY_CONFIG += [dict(clip=_c, bg="inpaint", hat=22, kk=13, dil=2),
                       _tx((_x + 1, _y - 1, _x + 41, _y + 25), "Button", _y - 2, 19,
                           KC_FILL, KC_OUT, squeeze=True, bold=1)]


# Value plates (dark checker-dithered olive, green glyphs with a WHITE outline). The glyphs
# fill the plate edge to edge, so a row copy has no source: key mode refills the glyph
# pixels with the plate's own most common index; the clip is inset 2 px so the plate's
# rounded rim is never touched.
VAL_FILL, VAL_OUT = (117, 167, 40), (253, 253, 253)
for _c, _t in [((132, 448, 208, 476), "Rotate left"), ((208, 448, 284, 476), "Not used"),
               ((284, 448, 360, 476), "Rotate right")]:
    _x0, _y0, _x1, _y1 = _c
    _in = (_x0 + 2, _y0 + 2, _x1 - 2, _y1 - 2)
    KEY_CONFIG += [dict(clip=_in, bg="key", wht=105, dil=2),
                   _tx(_in, _t, _y0 + 4, 17, VAL_FILL, VAL_OUT, align="c", squeeze=True,
                       margin=4)]

# "Can't rotate" warnings (light green plates, cream fill, heavy dark green outline).
WARN_FILL, WARN_OUT = (246, 246, 242), (42, 69, 0)


def _warn(c, t):
    x0, y0, x1, y1 = c
    return [_rm(c, wht=150, drk=100, reach=3, dil=2),
            _tx(c, t, y0 + 2, 18, WARN_FILL, WARN_OUT, align="c", squeeze=True, margin=6,
                bold=1)]


KEY_CONFIG += _warn((0, 482, 224, 508), "Neither player can rotate! OK!?")
KEY_CONFIG += _warn((224, 476, 422, 502), "2P can't rotate balls! OK!?")

# Selected-row sprites (bigger glyphs, orange-to-white fill): the button glyph keeps its
# art, "ボタン" (sprite x 15..) becomes "Button". All eight sprites share one placement
# relative to their own top-left (pair rule: they swap in over the rows).
SEL_FILL, SEL_OUT = (240, 234, 224), (34, 61, 0)
SEL_DX, SEL_DY, SEL_FS = 16, -1, 22


def _sel(x, y, w):
    return [_rm((x + 15, y, x + w, y + 26), wht=140, drk=95, reach=3, dil=2),
            _tx((x + SEL_DX, y, x + w, y + 26), "Button", y + SEL_DY, SEL_FS, SEL_FILL,
                SEL_OUT, squeeze=True, bold=1, margin=1)]


KEY_CONFIG += _sel(460, 448, 52) + _sel(422, 476, 52)          # x / triangle
ATTENTION = []
for _x, _y, _w in [(340, 0, 52), (392, 0, 52), (444, 0, 52), (340, 26, 52), (392, 26, 50),
                   (442, 26, 50)]:
    ATTENTION += _sel(_x, _y, _w)
ATTENTION += _warn((0, 136, 196, 162), "1P can't rotate balls! OK!?")

# ---- 0x4f49c0 Ranking Data (block 0x1c tex0) -------------------------------------------
# "○ボタンで Exit" -> "Press X to Exit" (the viewer exits on CONFIRM = physical X after
# the swap; see the module docstring).
RANK_CLIP = (96, 402, 214, 437)
RANKING = [_rm(RANK_CLIP, wht=120, drk=110, reach=4, dil=2),
           _tx(RANK_CLIP, "Press X to Exit", 408, 21, (242, 240, 238), (79, 4, 2),
               align="c", squeeze=True, margin=2, bold=1)]

# ---- 0x514230 / 0x533b30 Sound (block 0x1d) -------------------------------------------
# 実況 = the play-by-play voice. Plates (294x52): line 1 "実況 パターンA/B" (x 1..139),
# line 2 "1P:赤ポップ君 2P:青ポップちゃん" (x 47..293). tex0 sp2 is the dim (light green
# outline) twin of tex1 sp3; tex1 sp4 / sp5 are B twins. Every plate gets the same
# placement relative to its own top-left. "実況 Off" (72x28): 実況 -> "Voice", native
# "Off" art kept; sp6 dim / sp7 bright, same placement.
DIM_FILL, DIM_OUT = (249, 249, 249), (71, 121, 0)
BRT_FILL, BRT_OUT = (249, 249, 249), (37, 60, 0)
VOICE = {"A": ("Voice: Pattern A", "1P: Red Pop-kun   2P: Blue Pop-chan"),
         "B": ("Voice: Pattern B", "1P: Blue Pop-chan   2P: Red Pop-kun")}


def _plate(x, y, k, fill, out, drk, hat=28):
    l1, l2 = VOICE[k]
    c1, c2 = (x, y, x + 142, y + 26), (x + 44, y + 26, x + 294, y + 52)
    return [_rm(c1, wht=150, drk=drk, reach=4, dil=3),
            _rm(c2, wht=150, drk=drk, reach=4, dil=3),
            dict(clip=c1, bg="flat", hat=hat, kk=7, dil=1),    # leftover fill / halo
            dict(clip=c2, bg="flat", hat=hat, kk=7, dil=1),
            _tx((x + 2, y, x + 142, y + 26), l1, y, 21, fill, out, bold=1),
            _tx((x + 47, y + 26, x + 294, y + 52), l2, y + 26, 21, fill, out, bold=1,
                squeeze=True, margin=1)]


def _voff(x, y, fill, out, drk):
    c = (x + 1, y, x + 42, y + 28)
    return [_rm(c, wht=150, drk=drk, reach=4, dil=3),
            _tx((x + 2, y, x + 42, y + 28), "Voice", y + 1, 21, fill, out, bold=1,
                squeeze=True, margin=1)]


SOUND_0 = _plate(0, 448, "A", DIM_FILL, DIM_OUT, 140, hat=18)
SOUND_1 = (_plate(0, 0, "A", BRT_FILL, BRT_OUT, 100)
           + _plate(0, 52, "B", BRT_FILL, BRT_OUT, 100)
           + _plate(0, 104, "B", BRT_FILL, BRT_OUT, 100)
           + _voff(380, 0, DIM_FILL, DIM_OUT, 125) + _voff(294, 28, BRT_FILL, BRT_OUT, 100))

# ---- 0x5631f0 Manual page (block 0x1f tex0) -------------------------------------------
# "×目次": back to the contents is CANCEL (O after the swap). The grey button (black rim
# x 423..443, y 400..425) keeps its art; its light x strokes are inpainted from the ball
# and a ring is drawn in the strokes' own blue-grey. 目次 -> "Contents".
MAN_ICON = (427, 405, 441, 421)     # inside the rim on every row (strokes x 427..440)
MAN_TXT = (445, 398, 510, 428)
MANUAL = [dict(clip=MAN_ICON, bg="inpaint", hat=30, kk=7, dil=1),
          _tx(MAN_ICON, "O", 403, 20, (154, 184, 193), (154, 184, 193), sw=0, bold=1,
              align="c"),
          _rm(MAN_TXT, wht=200, drk=120, reach=3, dil=1),
          _tx(MAN_TXT, "Contents", 403, 17, (253, 253, 253), (113, 51, 180), bold=1)]

# ---- 0x15c6a60 / 0x15e46a0 BGM title plates (block 0x4c) ------------------------------
# Titles: teal/navy gradient fill inside a thick WHITE outline. Genre tags: navy kana in a
# white pill above the title's right end. Tags are replaced in place (centred on the
# Japanese tag, rows above the title only); the two Japanese titles are redrawn from the
# first Japanese glyph on, keeping the native "♪" (and "♪ROSE ~") art.
TAG_FILL, TAG_OUT = (65, 3, 135), (253, 253, 253)
TTL_FILL, TTL_OUT = (58, 130, 179), (253, 253, 253)


def _tag(x0, x1, y0, ys, y1, t, fs=10, drk=250):
    """Genre tag. Rows y0..ys (above the title): repaint as a white label (threshold mask
    over the whole rect, grey 253 -> the palette white). Rows ys..y1 (where the kana
    bottoms touch the title's own white outline): only the dark pixels (kana strokes and
    the plate between them) turn white, so the label joins the title's white outline the
    way the Japanese pill did. English in navy on top."""
    return [dict(clip=(x0, y0, x1, ys), bg=253, hat=0, wht=-1, drk=-1, dil=0),
            dict(clip=(x0, ys, x1, y1), bg=253, hat=0, wht=999, drk=drk, dil=0),
            _tx((x0, y0, x1, ys), t, y0 - 1, fs, TAG_FILL, TAG_FILL, sw=0, align="c",
                squeeze=True, margin=2)]


def _title(c, t, ty0, fs):
    """Remove everything inside/around the white title outline (non-white within 3 px of
    white, and the white itself), inpaint from the plate, then draw the English."""
    return [_rm(c, wht=200, drk=200, reach=3, dil=1),
            _tx(c, t, ty0, fs, TTL_FILL, TTL_OUT, sw=3, bold=1, squeeze=True, margin=1)]


BGM_0 = (_title((54, 455, 252, 486), "~Lover, Be Dyed in Rose~", 460, 20)
         + _tag(200, 243, 450, 460, 460, "DIGI ROCK")
         + _tag(348, 393, 450, 459, 462, "SOFT ROCK")
         + _tag(463, 490, 450, 459, 462, "HEART"))
BGM_1 = (_title((113, 86, 282, 118), "Jersey Men: Theme of Love", 93, 20)
         + _tag(227, 270, 83, 94, 94, "PUZZLE DAMA")
         + _tag(446, 491, 2, 12, 14, "VISUAL 2")
         + _tag(456, 497, 40, 50, 52, "J-TECHNO 2")
         + _tag(42, 85, 84, 93, 97, "FUTURE")
         + _tag(330, 371, 76, 84, 88, "SYMPATHY"))

SCREENS = [
    dict(name="option-main", file="IMAGE.DAT", fo=0x433a50, slot_end=0x457660,
         edits=OPTION_MAIN),
    dict(name="key-config", file="IMAGE.DAT", fo=0x4c5480, slot_end=0x4e9990,
         edits=KEY_CONFIG),
    dict(name="key-config-2", file="IMAGE.DAT", fo=0x4e9990, slot_end=0x4f42c0,
         edits=ATTENTION),
    dict(name="ranking-data", file="IMAGE.DAT", fo=0x4f49c0, slot_end=0x513f70,
         edits=RANKING),
    dict(name="sound", file="IMAGE.DAT", fo=0x514230, slot_end=0x533b30, edits=SOUND_0),
    dict(name="sound-2", file="IMAGE.DAT", fo=0x533b30, slot_end=0x542de0, edits=SOUND_1),
    dict(name="manual-page", file="IMAGE.DAT", fo=0x5631f0, slot_end=0x57c5f0, edits=MANUAL),
    dict(name="bgm-titles", file="IMAGE.DAT", fo=0x15c6a60, slot_end=0x15e46a0, edits=BGM_0),
    dict(name="bgm-titles-2", file="IMAGE.DAT", fo=0x15e46a0, slot_end=0x15f4570,
         edits=BGM_1),
]
