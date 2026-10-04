"""Online ranking viewer + "load/save failed" labels - IMAGE.DAT textures that the old
block walker missed (they sit in blocks with 0x20 / 0x30 headers).

Ranking viewer, block 0x2741800 (header 0x20, 5 textures). Its first sub-stream
(0x2741820) is an LZSS layout table: u16 x, y, w, h per sprite, v / 512 = texture
number (tex0 0x2741c80, tex1 0x274c380, tex2 0x27556b0, tex3 0x275d310, tex4 0x276de60).
Every clip below is that table's sprite rect or a cell inside it.
  tex0 0x2741c80  bottom help strip (0,438,512,500): blue x icon + "戻る" (Back)
  tex1 0x274c380  段位 / 勝率 tabs (438,306,508,332) / (438,332,508,358) and the
                  こうげきだま column header (142,468,478,494)
  tex2 0x27556b0  no Japanese
  tex3 0x275d310  three table header rows (0,412|438|464, 438x26), cells split by
                  black divider columns at x 140-141, 274-275 (middle row only), 336-337
  tex4 0x276de60  キャラクター / 使用率 header (0,0,438,26), seven 132x26 column labels
                  (rows y 156/182/208) and ten bold teal category plates (rows 130-260)
Each texture's slot ends at the next sub-stream (the block offsets), checked to be
only the stream tail + zero padding.

Load / save failed labels (62x26 or 66x28 plates, gradient plate, heavy outline):
  0x105d0   title sheet (block 0x6800 tex1) "ロード失敗!" (364,484,426,510)
  0x2849200 byte-identical copy of 0x105d0 (block 0x283f800 tex2), same rect
  0x603c0   ending sheet (block 0x60000 tex0) "セーブ失敗!" (380,448,442,474)
  0x28ccd10 Save&Load sheet (block 0x28cc800 tex0) "セーブ失敗!" (0,476,66,504) and
            (422,476,484,502)

Button swap: the English client swaps Circle/Cross (US: X = confirm, O = back). The
ranking help strip said "x 戻る" (x = back). After the swap x CONFIRMS, so keeping the x
icon with any "Back" word would send players to the wrong button. The back action is
now Circle, so the icon is redrawn as a ring (an "O" glyph in the x's own blue, the same
way the texture strings already write the button as the letter O) and the word is
"Back": "O Back".
"""

# ---- shared styles -------------------------------------------------------------------

def _rows(clip, txt, fs=15, ty0=None):
    """White text with a thin dark outline on the horizontally striped table rows.
    Each removed pixel copies the original index two px away in the same row (the
    stripes alternate with period 2 on some rows), so the stripes continue exactly."""
    x0, y0, x1, y1 = clip
    return dict(clip=clip, lines=[txt], ty0=y0 + 6 if ty0 is None else ty0, lh=20, fs=fs,
                align="c", fill=(253, 253, 253), outline=(0, 0, 0), sw=1,
                bg="rows", dir=(2, 0), wht=90, drk=90, dil=2)


# Bold category plates: grey/cyan fill with a teal glow on a flat dark-teal plate.
# The glyph (fill + glow) is everything brighter than the plate (luminance threshold,
# hat=0); refilled with the plate's own most common index (bg="flat"). No key mode:
# nothing outside the glyphs is recoloured.
CAT_FS = 21          # shared size for all 12 plates (fits the 24 px ハイスコア plate)
CAT_DX = 2           # JP glyph glow starts ~2 px in from the plate's left edge
CAT_DY = 1           # top of the union glyph box, from the plate top


def _plate(clip, txt, fill, out, wht):
    x0, y0, x1, y1 = clip
    return dict(clip=clip, lines=[txt], ty0=y0 + CAT_DY + _CAT_OFF, lh=24, fs=CAT_FS,
                align="l", fill=fill, outline=out, sw=2, bold=1, squeeze=True, margin=2,
                bg="flat", hat=0, wht=wht, drk=0, dil=1)


def _cat_off():
    """-top of the union glyph box over all 12 words at CAT_FS (so every plate has the
    same baseline), asserting it fits the shortest (24 px) plate."""
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
    import pntexnat
    from PIL import Image, ImageDraw, ImageFont
    dr = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    f = ImageFont.truetype(pntexnat.FONT, CAT_FS)
    bbs = [dr.textbbox((0, 0), t, font=f, stroke_width=2) for t in CAT_WORDS]
    top, bot = min(b[1] for b in bbs), max(b[3] for b in bbs)
    assert CAT_DY + bot - top <= 24, "CAT_FS too big"
    return -top


# Failed-save/load plates: the glyph covers the plate almost edge to edge. Remove it
# with the outlined mask (dark outline + the bright fill it encloses, reach 4) and a
# LOCAL inpaint (only from plate pixels inside the clip: the plates touch black atlas
# gaps). drk=140 also takes the green/blue/ochre noise pixels in the JP glyph art (left
# as inpaint sources they smeared brown into the ending plate). dil per plate, picked
# by preview: 2 leaves a dark outline remnant on two plates at dil 1, but bleeds a
# diagonal/pink patch on the other two. English: pale pink fill, dark plum outline.
FAIL_FILL = (253, 220, 251)
FAIL_OUT = (51, 0, 39)


def _fail(clip, txt, dil):
    x0, y0, x1, y1 = clip
    h = y1 - y0
    return dict(clip=clip, lines=[txt], ty0=y0 + (h - 16) // 2 - 3, lh=20, fs=15,
                align="c", fill=FAIL_FILL, outline=FAIL_OUT, sw=2, squeeze=True, margin=4,
                bg="outlined", wht=50, drk=140, reach=4, dil=dil, local=True)


# ---- tex0 0x2741c80: help strip ----------------------------------------------------
# Cream strip; row 458 is a teal dither edge, so clips start at y 459. Threshold mask
# (hat=0): everything darker than the cream (icon blues, outline, teal fill) or brighter
# (white fill) is refilled with the cream index.
BACK = [
    # x icon (x 42-53, y 461-476) -> blue ring
    # (fs 20 "O" glyph box is 13x14 from y+4: lands on y 462-475 like the x; faux bold
    # 1 px thickens the ring to the x's stroke weight)
    dict(clip=(40, 459, 56, 478), lines=["O"], ty0=458, lh=20, fs=20, align="c",
         fill=(100, 110, 210), outline=(100, 110, 210), sw=0, bold=1, margin=0,
         bg="flat", hat=0, wht=245, drk=228, dil=1),
    # 戻る (x 56-77, y 462-474) -> Back
    dict(clip=(56, 459, 96, 478), lines=["Back"], ty0=461, lh=20, fs=13, align="l",
         fill=(253, 253, 253), outline=(40, 41, 35), sw=1,
         bg="flat", hat=0, wht=245, drk=228, dil=1),
]

# ---- category words (same English as screens/menu_ranking.py) ------------------------
# name: (texture, plate rect, English)
CAT_PLATES = [
    ("rank",   1, (438, 306, 508, 332), "Rank"),
    ("win",    1, (438, 332, 508, 358), "Win%"),
    ("attack", 4, (0, 130, 176, 156),   "Top attack balls"),
    ("chara",  4, (176, 130, 344, 156), "Top characters"),
    ("balls",  4, (344, 130, 504, 156), "Balls cleared"),
    ("pref",   4, (396, 156, 506, 182), "Prefecture"),
    ("pts",    4, (396, 182, 494, 208), "Points"),
    ("chain",  4, (132, 208, 260, 234), "Max chain"),
    ("games",  4, (260, 208, 350, 234), "Games"),
    ("wins",   4, (350, 208, 438, 234), "Wins"),
    ("loss",   4, (0, 234, 88, 260),    "Losses"),
    ("hs",     4, (88, 234, 204, 258),  "High score"),
]
CAT_WORDS = [c[3] for c in CAT_PLATES]
_CAT_OFF = _cat_off()


def _cat_edit(tex, r, t):
    if tex == 1:   # tex1 palette: cyan fill (158,224,227), glow (9,115,134), plate lum ~63
        e = _plate(r, t, (158, 224, 227), (9, 115, 134), 68)
    else:          # tex4 palette: grey fill (180,180,180), glow (7,116,135), plate lum ~64
        e = _plate(r, t, (180, 180, 180), (7, 116, 135), 70)
    return e


# The editor left-aligns text at the clip's x0. Remove the JP over the whole plate, then
# draw the English from a second, text-only clip that starts CAT_DX px in (where the JP
# glyphs start), so every plate has the same left inset.
def _cat_pair(tex, r, t):
    x0, y0, x1, y1 = r
    rm = {k: v for k, v in _cat_edit(tex, r, t).items() if k != "lines"}
    tx = _cat_edit(tex, (x0 + CAT_DX, y0, x1, y1), t)
    tx.update(bg="flat", hat=255, kk=3, dil=0)      # text only (empty removal mask)
    return [rm, tx]


TEX1_CAT, TEX4_CAT = [], []
for _n, _tex, _r, _t in CAT_PLATES:
    (TEX1_CAT if _tex == 1 else TEX4_CAT).extend(_cat_pair(_tex, _r, _t))

# ---- tex1 0x274c380 ------------------------------------------------------------------
TEX1 = TEX1_CAT + [
    _rows((142, 468, 478, 494), "Attack ball", ty0=473),
]

# ---- tex3 0x275d310: table header rows -----------------------------------------------
C1, C2, C2A, C2B, C3 = (0, 140), (142, 336), (142, 274), (276, 336), (338, 438)


def _hdr(y, cells):
    return [_rows((c[0], y, c[1], y + 26), t, ty0=y + 6) for c, t in cells]


TEX3 = (_hdr(412, [(C1, "User name"), (C2, "Rank"), (C3, "Prefecture")])
        + _hdr(438, [(C1, "User name"), (C2A, "Win%"), (C2B, "Rank"), (C3, "Prefecture")])
        + _hdr(464, [(C1, "Prefecture"), (C2, "Total wins"), (C3, "Players")]))

# ---- tex4 0x276de60 ------------------------------------------------------------------
TEX4 = TEX4_CAT + [
    _rows((0, 0, 336, 26), "Character", ty0=5),
    _rows((338, 0, 438, 26), "Pick rate", ty0=5),
    _rows((0, 156, 132, 182), "Wins", ty0=161),
    _rows((132, 156, 264, 182), "Losses", ty0=161),
    _rows((264, 156, 396, 182), "Games", ty0=161),
    _rows((0, 182, 132, 208), "Max chain", ty0=187),
    _rows((132, 182, 264, 208), "Balls cleared", ty0=187),
    _rows((264, 182, 396, 208), "High score", ty0=187),
    _rows((0, 208, 132, 234), "Points", ty0=213),
]

# ---- failed labels -------------------------------------------------------------------
LOAD_FAIL = [_fail((364, 484, 426, 510), "Load failed!", 1)]
SAVE_FAIL_END = [_fail((380, 448, 442, 474), "Save failed!", 2)]
SAVE_FAIL_SL = [_fail((0, 476, 66, 504), "Save failed!", 1),
                _fail((422, 476, 484, 502), "Save failed!", 2)]

SCREENS = [
    dict(name="load-failed-title", file="IMAGE.DAT", fo=0x105d0, slot_end=0x1b3d0,
         edits=LOAD_FAIL),
    dict(name="save-failed-end", file="IMAGE.DAT", fo=0x603c0, slot_end=0x77f60,
         edits=SAVE_FAIL_END),
    dict(name="ranking-strip", file="IMAGE.DAT", fo=0x2741c80, slot_end=0x274c380,
         edits=BACK),
    dict(name="ranking-tabs", file="IMAGE.DAT", fo=0x274c380, slot_end=0x27556b0,
         edits=TEX1),
    dict(name="ranking-headers", file="IMAGE.DAT", fo=0x275d310, slot_end=0x276de60,
         edits=TEX3),
    dict(name="ranking-labels", file="IMAGE.DAT", fo=0x276de60, slot_end=0x277a690,
         edits=TEX4),
    dict(name="load-failed-dup", file="IMAGE.DAT", fo=0x2849200, slot_end=0x2854000,
         edits=LOAD_FAIL),
    dict(name="save-failed-sl", file="IMAGE.DAT", fo=0x28ccd10, slot_end=0x28ecc40,
         edits=SAVE_FAIL_SL),
]
