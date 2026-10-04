"""Character (user data) select / create / delete screens - texture edits.

Loaded by ../apply_textures_nat.py (see README.md). Every clip is tight inside its own
element; rank tiles and record labels are shared sprites the game draws onto the
user-data panels.
"""


def _btn(clip, txt, fs=13, ty=None, **kw):
    # white letters + dark outline on a busy plate/button: remove only the letters
    d = dict(clip=clip, lines=[txt], ty0=clip[1] + 2 if ty is None else ty, lh=20, fs=fs,
             bg="outlined", fill=250, outline=28, sw=2, wht=200, drk=90, reach=2, dil=1)
    d.update(kw)
    return d


# --- box + rows: the robust way to clear text off a patterned plate --------------
# Step 1 paints the text's bounding box pure white (bg=255 over the whole box; the
# threshold mask with wht=-1 marks every pixel). Step 2 (bg="rows") masks exactly that
# white box (wht=254: no palette entry is that bright, so nothing else on the plate is
# caught; drk=-1 disables the dark-outline term) and refills each pixel with the
# ORIGINAL palette index of the nearest pixel outside the box along `d`:
#   d=(2,0)  title plates (horizontal gradient bands with dotted rows; the 2-px step
#            keeps the dot phase), d=(3,-1) buttons/panels (shallow diagonal stripes).
# The plate pattern continues through the box, the indices are ones the plate already
# uses (palette-cycling hover animations stay intact), then the English is drawn.
def _box(box, clip, txt, fs, ty, d=(3, -1), lh=20, **kw):
    e = dict(clip=clip, lines=[txt] if isinstance(txt, str) else list(txt), ty0=ty, lh=lh,
             fs=fs, bg="rows", dir=d, wht=254, drk=-1, dil=0, fill=250, outline=28, sw=2)
    e.update(kw)
    return [dict(clip=box, bg=255, hat=0, wht=-1, drk=-1, dil=0), e]


def _float(box, clip, txt, fs, ty, lh=20, **kw):
    # text floating on background art (no plate): same white-box trick, but the box
    # is rebuilt by inpainting from the surrounding art instead of row copying
    e = dict(clip=clip, lines=[txt] if isinstance(txt, str) else list(txt), ty0=ty, lh=lh,
             fs=fs, bg="inpaint", hat=0, wht=254, drk=-1, dil=1, fill=250, outline=28, sw=2,
             local="ring")      # v4: inpainted pixels use only the surrounding art's indices
    e.update(kw)
    return [dict(clip=box, bg=255, hat=0, wht=-1, drk=-1, dil=0), e]


def _paint(box):
    # step 1 of the box trick on its own (several boxes, one shared rows/inpaint pass)
    return dict(clip=box, bg=255, hat=0, wht=-1, drk=-1, dil=0)


def _fillrows(clip, d=(2, 0)):
    # step 2 on its own: refill every painted box inside `clip`, no text
    return dict(clip=clip, bg="rows", dir=d, wht=254, drk=-1, dil=0)


def _draw(clip, txt, fs, ty, lh=20, **kw):
    # text only (empty erase mask); auto-fit keeps it 4 px inside the clip
    e = dict(clip=clip, lines=[txt] if isinstance(txt, str) else list(txt), ty0=ty, lh=lh,
             fs=fs, bg="flat", hat=0, wht=999, drk=-1, dil=0, fill=250, outline=28, sw=2)
    e.update(kw)
    return e


def _title(box, clip, txt, fs, ty):
    return _box(box, clip, txt, fs, ty, d=(2, 0))


# --- normal / highlighted button pairs ------------------------------------------
# The game blinks a button between its normal sprite and its highlighted (red/magenta)
# sprite; in the original the Japanese sits at the identical offset inside both, so
# the text must not move. Every button label is therefore anchored to its JAPANESE
# GLYPH box: English centred on the glyph's centre column, top at the glyph's top row,
# with ONE font size and ONE fit width per word (the auto-fit shrinks identically).
# Highlighted glyph boxes are the normal glyph box + the offset measured by template
# matching the two Japanese glyphs (TM_CCOEFF_NORMED >= 0.86 for every pair).
WORD = {  # word: (font px, fit width) - shared by every sprite that shows the word
    "New": (13, 70), "Delete": (13, 70), "Disconnect": (13, 70), "Cancel": (13, 70),
    "Postal Code": (13, 70), "Birthdate": (13, 70), "Occupation": (13, 70),
    "Gender": (13, 70), "Next": (13, 70), "Username": (13, 70), "Register": (13, 70),
    "1st Choice": (13, 70), "2nd Choice": (13, 70), "3rd Choice": (13, 70),
}


def _lab(glyph, clip, txt, shift=(0, 0), d=(3, -1), bands=None, twin=None, **kw):
    """Erase the JP glyph (white-box + rows refill inside the plate `clip`), then draw
    `txt` anchored to the glyph box (+ `shift` for a highlighted copy). `bands` =
    (first, end) row of the plate interior (absolute) selects the v4 refill below;
    `twin` = [(rect, (dx, dy)), ...] copies an identical plate's clean pixels first."""
    gx0, gy0 = glyph[0] + shift[0], glyph[1] + shift[1]
    gx1, gy1 = glyph[2] + shift[0], glyph[3] + shift[1]
    cx0, cy0, cx1, cy1 = clip
    box = (max(gx0 - 3, cx0 + 1), max(gy0 - 2, cy0), min(gx1 + 3, cx1 - 1), min(gy1 + 2, cy1))
    fs, w = WORD[txt]
    cx = (gx0 + gx1) // 2
    # v3 (live test: lime speckles under the labels): the diagonal refill continued the
    # plate's lime stripes from the box's upper-right corner down under the text. Below
    # the baseline (glyph top + 11) the box is refilled along rows instead: a blend from
    # the plain plate left of it to the plate right of it (bg="lerp", no mid seam);
    # above it the diagonal keeps the stripe pattern.
    if bands is not None:
        # v4 (live test: splotches around the text on the selected/orange button; the
        # splotch probe, popn/tools/splotch_probe.py, found them): the lerp below the
        # baseline mapped its blend to the nearest of ALL the clip's indices, which
        # include the JP glyph's own entries. Those do not take part in the button's
        # palette-cycling glow, so they stayed put while the plate around them
        # changed colour. Now every refilled pixel is a COPY of a plate pixel:
        #  * optional twin: an identical plate elsewhere on the sheet whose own label
        #    does not cover these columns is copied in first (exact plate),
        #  * the plate interior rows (bands = (first, end) row) are refilled along the
        #    stripe direction with a distance-weighted ordered dither between the two
        #    ends (no seam, no foreign index),
        #  * the top highlight / bottom border rows outside the interior are refilled
        #    along their own row (bg="lerp" mapped to the band's own unmasked indices,
        #    local="ring"), so the stripe walk never drags stripe colours into the
        #    border and the border keeps its smooth left-to-right gradient.
        iy0, iy1 = bands
        fills = [_paint(box)]
        for rect, src in (twin or []):
            fills.append(dict(clip=rect, bg="copy", src=src))
        fills.append(dict(clip=(cx0, iy0, cx1, iy1), bg="rows", dir=d, wht=254, drk=-1, dil=0,
                          src="cur", blend="dither"))
        if cy0 < iy0:
            fills.append(dict(clip=(cx0, cy0, cx1, iy0), bg="lerp", local="ring", wht=254, drk=-1, dil=0))
        if iy1 < cy1:
            fills.append(dict(clip=(cx0, iy1, cx1, cy1), bg="lerp", local="ring", wht=254, drk=-1, dil=0))
        return fills + [_draw((cx - w // 2 - 4, gy0 - 2, cx + w // 2 + 4, gy1 + 3), txt, fs, gy0, **kw)]
    sy = gy0 + 11
    if box[1] < sy < box[3]:
        return [_paint(box), _fillrows((cx0, cy0, cx1, sy), d),
                dict(clip=(cx0, sy, cx1, cy1), bg="lerp", wht=254, drk=-1, dil=0),
                _draw((cx - w // 2 - 4, gy0 - 2, cx + w // 2 + 4, gy1 + 3), txt, fs, gy0, **kw)]
    return [_paint(box), _fillrows(clip, d),
            _draw((cx - w // 2 - 4, gy0 - 2, cx + w // 2 + 4, gy1 + 3), txt, fs, gy0, **kw)]


def _fills_first(*labs):
    """Several _lab() groups with every refill before any text: a later twin copy or
    stripe walk must never pick up an earlier button's English (each group's text
    draw is its last edit)."""
    return [e for g in labs for e in g[:-1]] + [g[-1] for g in labs]


# normal glyph boxes (tight, lum<100), per sheet
G_NEW, G_DEL_US = (174, 380, 222, 396), (302, 380, 327, 396)                  # 0x3312a0
G_DISC, G_CAN_DC = (84, 77, 140, 94), (202, 78, 253, 93)                     # 0x344fc0
G_DEL_PK, G_CAN_PK = (100, 78, 125, 94), (202, 78, 253, 93)                  # 0x366e70
G_CAN_DS = (230, 390, 281, 405)                                              # 0x351280
G_POSTAL, G_BIRTH = (134, 150, 181, 166), (134, 178, 180, 194)               # 0x2cac40
G_OCC, G_GENDER = (145, 206, 170, 222), (145, 234, 170, 250)
G_NEXT, G_CANCEL = (186, 277, 210, 293), (288, 277, 339, 292)                # 0x2cac40/0x2ed1b0
G_UNAME = (130, 150, 184, 166)                                               # 0x2ed1b0
G_REG, G_CAN_C = (185, 380, 211, 397), (288, 381, 339, 396)                  # 0x307970
G_PICK = [(22, 4, 69, 20), (112, 4, 159, 20), (202, 4, 249, 20)]             # 0x3006d0 (only
#   highlighted copies of the 1st/2nd/3rd choice buttons exist on the disc)


# --- rank tiles (18 ranks, 2-kanji sprites 26x18 on a transparent backdrop) ------
# Every tile is wiped (every non-black pixel -> the transparent backdrop index), then
# its English rank is drawn inside it. v4 (splotch probe, CROSS/OUTSIDE rows): the
# old draw clips were tile +-4 px and the wipes spanned whole blocks, so labels
# spilled into the NEIGHBOURING tile (cut-in text when one rank is shown) and the
# 0x344fc0 wipe cleared the red New plate's right border (x 428-429). Now every clip
# is exactly the tile's sprite rect from the block layout table; a word wider than
# the tile keeps its height and is compressed horizontally (squeeze).
def _wipe(clip):
    return dict(clip=clip, bg="flat", hat=0, wht=3, drk=-1, dil=1)


# fix5 (same live report as the lobby rank tiles: tiny squeezed labels): no space in
# the word ("1Kyu", like lobby_room.py), fs 13 with a dark outline for every tile (was
# fs 10 / 1 px), drawn aliased (solid fill, no speckle), centred on one "Hg" box.
# fix6: 1 px outline (the 2 px aliased outline closed the counters at 1x, same live
# report as the lobby rank tiles).
RANK_FS, RANK_SW = 13, 1


def _rank(rect, txt, fs=RANK_FS):
    from PIL import ImageFont, ImageDraw, Image
    import pntexnat
    x0, y0, x1, y1 = rect
    f = ImageFont.truetype(pntexnat.FONT, fs)
    r = ImageDraw.Draw(Image.new("RGB", (4, 4))).textbbox((0, 0), "Hg", font=f, stroke_width=RANK_SW)
    return dict(clip=rect, lines=[txt], ty0=y0 + (y1 - y0 - (r[3] - r[1])) // 2 - r[1], lh=12,
                fs=fs, bg="flat", hat=0, wht=999, drk=-1, dil=0, fill=245, outline=20,
                sw=RANK_SW, margin=1, squeeze=True, aa=False)


def _tiles(pairs):
    return [_wipe(r) for r, _ in pairs] + [_rank(r, t) for r, t in pairs]


# block on the select/delete-select sheets (0x3312a0, 0x351280); rects = layout table
RANKS_A = _tiles([
    ((344, 474, 370, 492), "1Kyu"), ((370, 474, 396, 492), "2Dan"), ((396, 474, 422, 492), "2Kyu"),
    ((422, 474, 448, 492), "3Dan"), ((448, 474, 474, 492), "3Kyu"),
    ((344, 492, 370, 510), "5Dan"), ((370, 492, 396, 510), "5Kyu"), ((396, 492, 422, 510), "6Dan"),
    ((422, 492, 448, 510), "6Kyu"), ((448, 492, 474, 510), "7Dan"),
    ((470, 448, 496, 466), "1Dan"), ((496, 448, 510, 466), "God"),
    ((474, 466, 500, 484), "4Dan"), ((474, 484, 500, 502), "4Kyu"),
])

# block on the disconnect/delete-confirm sheets (0x344fc0, 0x366e70)
RANKS_B = _tiles([
    ((430, 0, 456, 18), "7Kyu"), ((456, 0, 482, 18), "8Dan"), ((482, 0, 508, 18), "8Kyu"),
    ((430, 18, 456, 36), "Master"),
])


# --- record labels on the user-data panel (shared by 0x344fc0 / 0x366e70) -------
# "12戦 8勝 4敗 ハイスコア 123456" -> "12Gm 8W 4L Hi-Score 123456". The counts are drawn
# just LEFT of each label, so the English starts at the kanji's left edge and grows
# right (into empty panel); the panel has shallow diagonal stripes -> d=(3,-1).
def _lbl(box, txt, fs=12, x1=None):
    x0, y0, bx1, y1 = box
    return _box(box, (x0, 154, x1 or bx1 + 10, 175), txt, fs, 159, align="l")


PANEL = (_lbl((55, 157, 71, 174), "Gm", x1=86) + _lbl((124, 157, 140, 174), "W", x1=150)
         + _lbl((193, 157, 208, 174), "L", x1=212) + _lbl((211, 157, 269, 174), "Hi-Score", x1=274))


USER_SELECT = dict(name="user-select", file="IMAGE.DAT", fo=0x3312a0, slot_end=0x344fc0, edits=(
    _title((44, 90, 206, 115), (36, 88, 210, 117), "Select User Data", 17, 92)
    # New/Delete plates are identical (x +116): New's label columns that Delete's
    # does not cover are copied from the Delete plate first
    + _fills_first(
        _lab(G_NEW, (161, 377, 237, 398), "New", bands=(379, 397),
             twin=[((171, 378, 183, 398), (116, 0)), ((215, 378, 225, 398), (116, 0))]),
        _lab(G_DEL_US, (284, 377, 354, 398), "Delete", bands=(379, 397)))
    + RANKS_A))

# Disconnect dialog + highlighted (red) New/Delete/Disconnect/Cancel buttons + panel
DISCONNECT = dict(name="disconnect", file="IMAGE.DAT", fo=0x344fc0, slot_end=0x350f40, edits=(
    _box((118, 35, 222, 61), (104, 33, 240, 63), "OK to disconnect?", 15, 38, d=(2, 0))
    + _fills_first(
        _lab(G_DISC, (70, 74, 158, 97), "Disconnect", bands=(77, 94)),
        _lab(G_CAN_DC, (186, 74, 274, 97), "Cancel", bands=(77, 94)),
        # highlighted (sprites 340..430 x 24 rows): New/Delete of 0x3312a0,
        # Disconnect/Cancel of this dialog. The New and Delete red plates are twins
        # (y +24): New's outer label columns come from the Delete plate.
        _lab(G_NEW, (341, 2, 426, 23), "New", shift=(187, -376), bands=(3, 21),
             twin=[((358, 2, 370, 23), (0, 24)), ((401, 2, 412, 23), (0, 24))]),
        _lab(G_DEL_US, (341, 26, 426, 47), "Delete", shift=(71, -352), bands=(27, 45)),
        _lab(G_DISC, (341, 50, 426, 71), "Disconnect", shift=(273, -26), bands=(51, 69)),
        _lab(G_CAN_DC, (341, 74, 426, 95), "Cancel", shift=(157, -2), bands=(75, 93)))
    + PANEL + RANKS_B))

# "Really delete?" dialog (pink) + highlighted Cancel/Cancel/Delete buttons + panel
DELETE_CONFIRM = dict(name="delete-confirm", file="IMAGE.DAT", fo=0x366e70, slot_end=0x372170, edits=(
    _box((125, 34, 215, 62), (104, 33, 240, 63), "Really delete?", 15, 38, d=(2, 0))
    + _fills_first(
        _lab(G_DEL_PK, (70, 74, 158, 97), "Delete", bands=(78, 94)),
        _lab(G_CAN_PK, (186, 74, 274, 97), "Cancel", bands=(78, 94)),
        # highlighted: Cancel of 0x351280 (top), Cancel/Delete of this dialog
        _lab(G_CAN_DS, (341, 2, 426, 23), "Cancel", shift=(129, -386), bands=(3, 20)),
        _lab(G_CAN_PK, (341, 26, 426, 47), "Cancel", shift=(157, -50), bands=(27, 44)),
        _lab(G_DEL_PK, (341, 50, 426, 71), "Delete", shift=(273, -26), bands=(51, 68)))
    + PANEL + RANKS_B))


DELETE_SELECT = dict(name="delete-select", file="IMAGE.DAT", fo=0x351280, slot_end=0x366e70, edits=(
    _title((44, 89, 206, 116), (36, 87, 210, 118), "Delete User Data", 17, 92)
    # v4 (splotch probe): inpainting this line left a pink smear over the cup pattern.
    # The backdrop repeats every 70 px along x (~70 % exact), so the text box is
    # rebuilt from clean backdrop one or two periods away (left part from the left,
    # right part from the right; no source column lies inside the box), then drawn.
    + [dict(clip=(163, 362, 233, 384), bg="copy", src=(-70, 0)),
       dict(clip=(233, 362, 276, 384), bg="copy", src=(-140, 0)),
       dict(clip=(276, 362, 346, 384), bg="copy", src=(70, 0)),
       _draw((150, 359, 358, 385), "Choose the data to delete!", 15, 365)]
    + _lab(G_CAN_DS, (213, 387, 299, 408), "Cancel", bands=(389, 406))
    + RANKS_A))


# Occupation picker (faded items, 0x2cac40 y455-500) and its bright value tiles (the
# strip at y494-511, plus "Part-timer" on 0x2dfcb0). Each item/tile pair is anchored
# like the buttons: the tile anchor is the faded item's anchor + the template-matched
# offset of the two Japanese glyphs (TM_CCOEFF_NORMED 0.86-0.97), and both use the
# same font size, stroke and fit width (the tile's), so a tile shown over its item
# lines up exactly. Tile boxes stop 1 px short of the clean column between tiles,
# which is the row-copy source.
#
# v2 (live test: labels thin, washed out, sizes all over the place): every word now
# uses ONE font size (OCC_FS) and keeps its full height; a word wider than its tile
# is compressed horizontally ("squeeze") instead of shrinking the font. Words are
# short so the squeeze stays mild. The text box of a pair is the TILE's own x-range
# (centred on the tile, never past its edges) and the faded item uses that box minus
# the tile shift, so the two render pixel-identically. Colours are sampled from the
# Japanese: faded items = cream fill + grey-brown outline, tiles = white + dark brown.
OCC_FS = 13
_OCC = [  # faded-item JP glyph box, tile shift, text, tile x-range
    ((12, 459, 36, 474), (411, 35), "Pupil", (422, 446)),      # 学生
    ((56, 459, 92, 474), (218, 35), "Office", (274, 308)),     # 会社員
    ((116, 459, 152, 474), (232, 35), "Owner", (349, 384)),    # 自営業 (same word as the ELF value)
    ((170, 459, 206, 474), (142, 35), "Civil", (311, 346)),    # 公務員
    ((12, 483, 36, 498), (438, 12), "Wife", (449, 474)),       # 主婦
    ((44, 483, 104, 498), (170, 12), "Home", (215, 271)),      # 家事手伝い
    ((170, 483, 206, 498), (215, 12), "Other", (386, 419)),    # その他
]
_PT = ((112, 483, 160, 498), (138, -457), "Part-time", (250, 299))   # フリーター, tile on 0x2dfcb0
_OCC_PAINT = [((11, 455, 42, 476)), ((54, 455, 98, 476)), ((114, 455, 158, 476)),
              ((166, 455, 208, 476)), ((11, 478, 42, 499)), ((42, 478, 106, 499)),
              ((108, 478, 166, 499)), ((166, 478, 208, 499))]

_FADED = dict(fill=(236, 228, 212), outline=(158, 142, 126))   # JP item: ~(235,226,209) / (165,148,135)
_BRIGHT = dict(fill=253, outline=(42, 18, 3))                  # JP tile: 253 / (42,18,3)


def _tile_text(xr, gy, txt, fs, shift=(0, 0), h=16, dy=0, bold=1, **kw):
    """`txt` in the tile box xr (tile coords, glyph top gy), moved by -shift for the
    item copy. Clip = the tile's own columns (margin 1), so text never leaves it."""
    x0, x1, y = xr[0] - shift[0], xr[1] - shift[0], gy - shift[1]
    return _draw((x0, y, x1, y + h), txt, fs, y - 2 + dy, margin=1, squeeze=True, sw=1, bold=bold, **kw)


def _occ(anchor, shift, txt, xr, item, **kw):
    gy = anchor[1] + shift[1]                    # tile glyph top
    return _tile_text(xr, gy, txt, OCC_FS, shift if item else (0, 0), dy=2, **kw)


_TILE_X = [(215, 271), (274, 308), (311, 346), (349, 385), (386, 419), (422, 446),
           (449, 475), (476, 488), (491, 504)]          # every tile on the strip (paint)

# Gender: faded 男/女 on the picker (0x2dfcb0) and the value tiles 女/男 at the end of
# the strip (0x2cac40), which the game also draws over the picker as the highlight.
# Shift = template match of the JP glyphs (男 tile 491 -> picker 201, 女 476 -> 224,
# y 495 -> 13). Same box, same size, so the highlight no longer shrinks the letter.
GEN_FS, GEN_BOLD = 15, 2         # tile is only 13 px wide: heavier, not wider
_GEN = [((491, 504), (290, 482), "M"), ((476, 488), (252, 482), "F")]

# v3 (live test: highlighted "Other" showed a green box, others a speckled halo): a
# value tile is a crop of the picker panel with bright glyphs, and the game pastes it
# over the faded item. So the tile's background must BE the cleaned panel at the
# item's place. Same-sheet tiles copy it (bg="copy", after the items are cleaned and
# before any text is drawn); M/F (panel on 0x2dfcb0) and Part-time (tile on 0x2dfcb0,
# panel here) are repainted with the panel's 2-px dither rows (bg="pattern"), sampled
# from clean panel columns with the right x phase.
TILE_Y = (494, 512)


# fix5 (live test: thin green bars left/right of the highlighted Home / Other): the
# tile backgrounds were copied over the TEXT x-range only, but each value tile's sprite
# (block layout table) is 1-3 px wider on each side. Those edge columns kept the strip's
# gap fill (a clean column of the strip's own green), so pasted over the item they
# showed as vertical green bars. Owner's / Wife's text range also ran 1 px into the
# next sprite (Other / F). Now the background copy covers the WHOLE sprite and every
# text range stays inside its sprite.
_TILE_SPR = {"Home": (214, 272), "Office": (272, 310), "Civil": (310, 348),
             "Owner": (348, 384), "Other": (384, 420), "Pupil": (420, 448),
             "Wife": (448, 474), "F": (474, 490), "M": (490, 504)}


def _tile_bg(t, shift):
    x0, x1 = _TILE_SPR[t]
    return dict(clip=(x0, TILE_Y[0], x1, TILE_Y[1]), bg="copy", src=(-shift[0], -shift[1]))


_PICK_ROWS = [  # 0x2dfcb0 picker rows 12..29 (even col, odd col)
    ((165, 164, 165), (112, 218, 87)), ((133, 207, 101), (133, 207, 101)),
    ((133, 207, 101), (133, 207, 101)), ((139, 207, 104), (139, 207, 104)),
    ((139, 207, 104), (139, 207, 104)), ((143, 209, 113), (146, 211, 112)),
    ((146, 211, 112), (146, 211, 112)), ((146, 211, 112), (162, 214, 125)),
    ((189, 189, 189), (189, 189, 189)), ((189, 189, 189), (189, 189, 189)),
    ((189, 189, 189), (153, 211, 117)), ((153, 211, 117), (153, 211, 117)),
    ((168, 217, 131), (168, 217, 131)), ((168, 217, 131), (168, 217, 131)),
    ((175, 218, 138), (175, 218, 138)), ((178, 220, 142), (178, 220, 142)),
    ((182, 223, 146), (178, 220, 142)), ((182, 223, 146), (182, 223, 146))]
_PT_ROWS = [  # 0x2cac40 picker rows 483..498 (even col, odd col)
    ((162, 214, 125), (162, 214, 125)), ((162, 214, 125), (162, 214, 125)),
    ((168, 218, 131), (168, 218, 131)), ((168, 218, 131), (168, 218, 131)),
    ((168, 218, 131), (168, 218, 131)), ((211, 201, 178), (211, 201, 178)),
    ((211, 201, 178), (211, 201, 178)), ((172, 216, 160), (211, 201, 178)),
    ((172, 216, 160), (172, 216, 160)), ((172, 216, 160), (172, 216, 160)),
    ((172, 216, 160), (172, 216, 160)), ((182, 214, 179), (172, 216, 160)),
    ((182, 214, 179), (182, 214, 179)), ((193, 226, 159), (182, 214, 179)),
    ((182, 214, 179), (182, 214, 179)), ((193, 226, 159), (182, 214, 179))]


def _gen_bg(t, shift):
    # tile x0 maps to picker x0 - shift: start the dither on that column's parity
    x0, x1 = _TILE_SPR[t]
    odd = (x0 - shift[0]) % 2
    return dict(clip=(x0, TILE_Y[0], x1, TILE_Y[1]), bg="pattern",
                rows=[(o, e) if odd else (e, o) for e, o in _PICK_ROWS])

# 0x2cac40: Register User Data. Field buttons, Next/Cancel, the occupation picker
# (faded = unselected), the birthday Y/M/D plate and the selected-value tiles.
USER_DATA_REG = dict(name="user-data-reg", file="IMAGE.DAT", fo=0x2cac40, slot_end=0x2dfcb0, edits=(
    _title((44, 89, 206, 116), (36, 87, 210, 118), "Register User Data", 17, 92)
    + _lab(G_POSTAL, (118, 146, 198, 169), "Postal Code", bands=(149, 166))
    + _lab(G_BIRTH, (118, 172, 198, 197), "Birthdate", bands=(177, 194))
    + _lab(G_OCC, (118, 199, 198, 224), "Occupation", bands=(205, 222))
    + _lab(G_GENDER, (118, 227, 198, 251), "Gender", bands=(233, 250))
    + _lab(G_NEXT, (164, 273, 238, 295), "Next", bands=(276, 293))
    + _lab(G_CANCEL, (268, 273, 352, 295), "Cancel", bands=(276, 293))
    + [_paint(b) for b in _OCC_PAINT] + [_fillrows((4, 452, 210, 504))]
    # value strip: clear it (gap columns keep this fill), then give every tile the
    # cleaned panel behind its item (no text drawn anywhere on the picker yet)
    + [_paint((x0, 494, x1, 512)) for x0, x1 in _TILE_X] + [_fillrows((214, 494, 504, 512), d=(1, 0))]
    + [_tile_bg(t, sh) for _, sh, t, _ in _OCC]
    + [_gen_bg(t, sh) for _, sh, t in _GEN]
    + [_occ(an, sh, t, xr, True, **_FADED) for an, sh, t, xr in _OCC + [_PT]]
    + [_paint(b) for b in [(315, 455, 341, 486), (392, 455, 415, 486), (464, 456, 486, 486)]]
    + [_fillrows((222, 452, 486, 490))]
    + [_draw((cx - 16, 452, cx + 16, 490), t, 24, 456, fill=(30, 30, 30), outline=(30, 30, 30), sw=1)
       for cx, t in ((328, "Y"), (403, "M"), (475, "D"))]
    + [_occ(an, sh, t, xr, False, **_BRIGHT) for an, sh, t, xr in _OCC]
    + [_tile_text(xr, 494, t, GEN_FS, bold=GEN_BOLD, **_BRIGHT) for xr, _, t in _GEN]))



# 0x2dfcb0: registration parts - HELP-line messages on a flat green strip (key index
# 132, refilled exactly like HELP_MSGS), highlighted (red) field buttons, the M/F
# picker and the "Part-timer" value tile.
def _msg(clip, txt, fs=13, tx=None):
    """Erase the JP message in `clip` (key refill), then draw `txt` left-aligned from
    x = tx, the JP text's own first column. v3 (live test): the HELP box frame hides
    the first few px of every strip, so English starting at the strip edge lost its
    first letter, and a clip starting left of the strip drew into the neighbouring
    sprite (the "N" seen on the highlighted Cancel was the M of "Moving on!")."""
    if tx is None:
        return dict(clip=clip, lines=[txt], ty0=clip[1] + 2, lh=20, fs=fs, bg="key",
                    align="l", fill=250, outline=28, sw=2, wht=190, dil=4)
    return [dict(clip=clip, bg="key", wht=190, dil=4),
            _draw((tx, clip[1], clip[2], clip[3]), txt, fs, clip[1] + 2, align="l", margin=2)]


# v4 (splotch probe OUTSIDE rows): every clip on 0x2dfcb0 / 0x2ed1b0 is now inside its
# own sprite rect from the block layout table; several strips ran 2 px into the strip
# below or beside them, and the highlighted Postal / Birthdate / Next / Cancel plate
# clips overlapped the neighbouring red plate.
REG_PARTS = dict(name="reg-parts", file="IMAGE.DAT", fo=0x2dfcb0, slot_end=0x2ed000, edits=(
    # tx = first column of the JP text (strips start ~8 px earlier, under the frame)
    _msg((376, 1, 506, 24), "Choose your job!", 14, tx=384)
    + _msg((6, 49, 196, 70), "Some fields are still empty!", 14, tx=12)
    + _msg((200, 49, 356, 70), "Enter your postal code!", 14, tx=206)
    + _msg((364, 49, 488, 70), "Choose your gender!", 14, tx=368)
    + _msg((6, 73, 160, 94), "Enter your birthdate!", 14, tx=12)
    + _msg((166, 73, 292, 94), "Back to the last screen!", 13, tx=170)  # plate starts at x 292
    + _msg((362, 97, 448, 118), "Moving on!", 14, tx=370)     # strip starts at 362; 352-361 = Cancel's edge
    # highlighted field/Next/Cancel buttons of 0x2cac40
    + _lab(G_POSTAL, (302, 74, 382, 94), "Postal Code", shift=(180, -76), bands=(74, 90))
    + _lab(G_BIRTH, (390, 74, 472, 94), "Birthdate", shift=(270, -104), bands=(74, 90))
    + _lab(G_OCC, (2, 98, 85, 118), "Occupation", shift=(-112, -108), bands=(98, 114))
    + _lab(G_GENDER, (90, 98, 173, 118), "Gender", shift=(-22, -136), bands=(98, 114))
    + _lab(G_NEXT, (181, 98, 261, 118), "Next", shift=(27, -179), bands=(98, 114))
    + _lab(G_CANCEL, (271, 98, 349, 118), "Cancel", shift=(1, -179), bands=(98, 114))
    + [_paint((196, 12, 216, 32)), _paint((220, 12, 242, 32)), _fillrows((190, 4, 246, 40)),
       ] + [_tile_text(xr, 494, t, GEN_FS, sh, bold=GEN_BOLD, **_FADED) for xr, sh, t in _GEN]
    # "Part-time" value tile (x248-299, y26-41): the glyph covers the whole tile, and
    # its item sits on 0x2cac40, so the tile is repainted with that panel's dither rows
    # (x 248 <-> panel x 110, even phase; y 26 <-> 483)
    + [dict(clip=(248, 26, 300, 42), bg="pattern", rows=_PT_ROWS),
       _occ(*_PT, False, **_BRIGHT)]))



# 0x2ed1b0: Enter Username (+ its HELP messages and highlighted buttons at the bottom)
USERNAME_REG = dict(name="username-reg", file="IMAGE.DAT", fo=0x2ed1b0, slot_end=0x3006d0, edits=(
    _title((44, 89, 183, 116), (36, 87, 184, 118), "Enter Username", 17, 92)
    + _lab(G_UNAME, (118, 146, 198, 169), "Username", bands=(149, 166))
    + _lab(G_NEXT, (164, 273, 238, 295), "Next", bands=(276, 293))
    + _lab(G_CANCEL, (268, 273, 352, 295), "Cancel", bands=(276, 293))
    + _msg((128, 449, 358, 472), "Enter a username!", 14, tx=137)
    + _msg((368, 449, 496, 472), "Back to the last screen!", 13, tx=377)
    + _msg((272, 473, 360, 496), "Moving on!", 14, tx=280)
    # highlighted Username/Next/Cancel
    + _lab(G_UNAME, (2, 474, 87, 495), "Username", shift=(-112, 328), bands=(477, 494))
    + _lab(G_NEXT, (92, 474, 177, 495), "Next", shift=(-63, 201), bands=(477, 494))
    + _lab(G_CANCEL, (182, 474, 267, 495), "Cancel", shift=(-89, 199), bands=(475, 492))))   # sprite (180,472,...): 2 px higher



# 0x3006d0: username suggestion buttons (highlighted state) + "Moving on!" strip
USERNAME_PICK = dict(name="username-pick", file="IMAGE.DAT", fo=0x3006d0, slot_end=0x307800, edits=(
    _lab(G_PICK[0], (2, 2, 87, 23), "1st Choice", bands=(3, 20))
    + _lab(G_PICK[1], (92, 2, 177, 23), "2nd Choice", bands=(3, 20))
    + _lab(G_PICK[2], (182, 2, 267, 23), "3rd Choice", bands=(3, 20))
    # highlighted Next/Cancel of 0x2ed1b0 (same buttons on the suggestion screen)
    + _lab(G_NEXT, (272, 2, 357, 23), "Next", shift=(117, -273), bands=(3, 20))
    + _lab(G_CANCEL, (362, 2, 447, 23), "Cancel", shift=(91, -273), bands=(3, 20))
    + _msg((2, 25, 89, 48), "Moving on!", 14, tx=12)))



# 0x307970 / 0x31c8e0: Confirm / Signup Done. The field labels float on the panel
# (values are drawn to their right), so they are inpainted and redrawn centred.
def _fields():
    out = []
    for box, txt in (((131, 147, 185, 168), "Postal Code"), ((131, 175, 184, 196), "Birthdate"),
                     ((142, 203, 174, 224), "Occupation"), ((142, 231, 174, 252), "Gender"),
                     ((127, 259, 188, 278), "Username")):
        out += _float(box, (118, box[1] - 2, 200, box[3] + 1), txt, 13, box[1] + 2)
    return out


REG_CONFIRM = dict(name="reg-confirm", file="IMAGE.DAT", fo=0x307970, slot_end=0x31c190, edits=(
    _title((42, 89, 131, 117), (36, 87, 133, 118), "Confirm", 17, 92)
    + _fields()
    + _float((205, 308, 307, 329), (186, 305, 330, 331), "Register with this?", 14, 311)
    + _lab(G_REG, (164, 377, 238, 399), "Register", bands=(380, 397))
    + _lab(G_CAN_C, (276, 377, 352, 399), "Cancel", bands=(380, 397))
    # highlighted Register/Cancel
    + _lab(G_REG, (132, 449, 212, 470), "Register", shift=(-27, 72), bands=(452, 469))
    + _lab(G_CAN_C, (220, 449, 298, 470), "Cancel", shift=(-53, 72), bands=(452, 469))))

REG_DONE = dict(name="reg-done", file="IMAGE.DAT", fo=0x31c8e0, slot_end=0x3308a0, edits=(
    _title((42, 89, 131, 117), (36, 87, 133, 118), "All Done!", 17, 92)
    + _fields()
    + _float((203, 308, 310, 329), (186, 305, 330, 331), "Press the X button!", 14, 311)))


SCREENS = [USER_DATA_REG, REG_PARTS, USERNAME_REG, USERNAME_PICK, REG_CONFIRM, REG_DONE, USER_SELECT, DELETE_SELECT, DISCONNECT, DELETE_CONFIRM]
