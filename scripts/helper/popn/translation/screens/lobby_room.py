"""Lobby / room / match-result / BB Unit texture screens (pop'n Taisen Puzzle-dama Online).

Loaded by ../apply_textures_nat.py; a screen here with the same (file, fo) replaces
the built-in one. Clips are tight to each sprite (rendered at 2-4x with a grid).

Edit helpers
  _clear(clip)    erase EVERY non-black pixel in clip (text on a transparent/black
                  sprite background): threshold mask lum > 6, refill with the
                  clip's most common remaining index (the transparent/black bg).
  _txt(clip,...)  draw English only (mask nothing); used after a _clear so that
                  neighbouring labels whose outlines touch can be erased as one
                  region and then each redrawn inside its own sprite.
  _key(clip,...)  white text with a purple outline on a flat green strip.
  _btn(clip,...)  white text with a dark outline on a busy plate (bg="outlined").
"""

# ---------------------------------------------------------------- helpers

def _clear(clip):
    return dict(clip=clip, bg="flat", hat=0, wht=6, drk=-1, dil=0)


# normal handicap label: white letters, dark (olive/brown) outline
NORM = dict(fill=250, outline=70, sw=2)
# highlighted (selected, blinking) label: yellow letters inside a thick white glow,
# like the JP
HIGH = dict(fill=(215, 187, 82), outline=(253, 253, 253), sw=3)
# per-sheet normal style: white letters with the JP normal labels' own outline colour
NORM_RC = dict(fill=253, outline=(87, 63, 54), sw=2)     # room-create: dark brown
NORM_HC = dict(fill=253, outline=(77, 77, 0), sw=2)      # handicap sheet: dark olive


def _txt(clip, txt, ty0, fs, st=NORM, **kw):
    e = dict(clip=clip, lines=[txt], ty0=ty0, lh=20, fs=fs, bg="flat",
             hat=0, wht=255, drk=-1, dil=0)
    e.update(st); e.update(kw)
    return e


def _lab(cx, cy, txt, fs, st=NORM):
    """Gauge label centred on (cx, cy) at a FIXED font size: the clip is symmetric
    around cx and just wide enough that pntexnat never shrinks the text, so a
    normal/highlighted pair drawn with the same fs and offset overlays exactly
    (the game blinks between the two sprites)."""
    from PIL import ImageFont, ImageDraw, Image
    import pntexnat
    f = ImageFont.truetype(pntexnat.FONT, fs)
    d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    b = d.textbbox((0, 0), txt, font=f, stroke_width=st["sw"])
    g = d.textbbox((0, 0), txt, font=f)
    half = (b[2] - b[0] + 9) // 2          # smallest clip with no auto-shrink
    ty0 = cy - (g[1] + g[3]) // 2
    assert cx - half >= 0 and cx + half <= 512, (txt, cx, half)
    return _txt((cx - half, cy - 13, cx + half, cy + 13), txt, ty0, fs, st)


def _spr(rect, txt, fs, st=NORM):
    """One handicap label SPRITE (rect = its exact entry in the block's layout table).
    The label floats on the transparent entry (index 0) and the game draws it over
    the room's purple-striped plate, so:
      * the whole sprite is wiped to index 0 (bg="key", key=0): no Japanese residue
        anywhere in the rect, nothing written outside it;
      * the English is drawn ALIASED (aa=False): an antialiased edge blends with
        index 0's black RGB and maps to dark palette entries, which shows as a grimy
        dark fringe around the glow on the stripes;
      * the text is centred in the sprite at a fixed size (margin=0, asserted to
        fit), on a fixed "Hg" baseline box. The game centres a normal/highlighted
        pair on the same point (the JP art of a 76x26 / 74x24 pair is offset by
        exactly half the size difference), so centring in each sprite overlays them."""
    from PIL import ImageFont, ImageDraw, Image
    import pntexnat
    x0, y0, x1, y1 = rect
    f = ImageFont.truetype(pntexnat.FONT, fs)
    d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    b = d.textbbox((0, 0), txt, font=f, stroke_width=st["sw"])
    assert b[2] - b[0] <= x1 - x0, (txt, rect, b)
    r = d.textbbox((0, 0), "Hg", font=f, stroke_width=st["sw"])
    ty0 = y0 + (y1 - y0 - (r[3] - r[1])) // 2 - r[1]
    e = dict(clip=rect, bg="key", key=0, wht=-1, dil=0, lines=[txt], ty0=ty0, lh=20,
             fs=fs, margin=0, aa=False)
    e.update(st)
    return e


def _key(clip, txt, fs=13, outline=95, **kw):
    e = dict(clip=clip, lines=[txt], ty0=clip[1] + 1, lh=20, fs=fs, bg="key",
             fill=250, outline=outline, sw=2, wht=190, dil=4)
    e.update(kw)
    return e


def _btn(clip, txt, fs, **kw):
    e = dict(clip=clip, lines=[txt], ty0=clip[1] + 2, lh=20, fs=fs, bg="outlined",
             fill=250, outline=28, sw=2, wht=200, drk=90, reach=2, dil=1)
    e.update(kw)
    return e


# Handicap wording (gauge, 5 steps), shared by the room-create and handicap sheets:
#   とっても有利だよ! Huge advantage! / ちょっと有利だよ! Slight advantage! /
#   同じだよ! Even! / すこし不利だよ! Slight handicap! / すごく不利だよ! Huge handicap!
HUGE_ADV, SLIGHT_ADV, EVEN = "Huge advantage!", "Slight advantage!", "Even!"
SLIGHT_HC, HUGE_HC = "Slight handicap!", "Huge handicap!"

# ---------------------------------------------------------------- room create

# tex 050 @0x3a7ec0: room-create options + handicap gauge labels + green prompt
# strips. slot_end = the 0x800-aligned block that follows the stream (0x3bb800).
ROOM_CREATE = dict(name="room-create", file="IMAGE.DAT", fo=0x3a7ec0, slot_end=0x3bb800, edits=[
    # Gauge labels: one edit per SPRITE, rects from the block's layout table
    # (sub-stream 0 @0x3a7810). The old version erased three loose bands
    # ((0,257,506,276), (0,276,252,297), (334,122,506,146)) and centred each label
    # on a 26 px tall clip; that (a) wiped the bottom rows of the Cancel/Off/On
    # toggle sprites (the room-password switch) and the top rows of Ok / 3 Times
    # Match / the big panel's border, (b) left the JP bottoms of rows 297-301 in the
    # すこし/同じ sprites, (c) drew text across sprite edges (cut off in game), and
    # (d) let the AA edge pick opaque black (index 1) from outside the sprites.
    # Normal -> highlighted pairs (same size; the JP sits at the same offset in both):
    #   とっても有利 (336,122) -> (0,262), ちょっと有利 (106,258) -> (210,256),
    #   すごく不利 (314,254) -> (410,254), すこし不利 (0,282) -> (96,282),
    #   同じ (442,122) -> (192,278).
    _spr((336, 122, 442, 142), HUGE_ADV, 12, NORM_RC), _spr((0, 262, 106, 282), HUGE_ADV, 12, HIGH),
    _spr((106, 258, 210, 278), SLIGHT_ADV, 12, NORM_RC), _spr((210, 256, 314, 276), SLIGHT_ADV, 12, HIGH),
    _spr((314, 254, 410, 274), HUGE_HC, 12, NORM_RC), _spr((410, 254, 506, 274), HUGE_HC, 12, HIGH),
    _spr((0, 282, 96, 302), SLIGHT_HC, 12, NORM_RC), _spr((96, 282, 192, 302), SLIGHT_HC, 12, HIGH),
    _spr((442, 122, 502, 142), EVEN, 12, NORM_RC), _spr((192, 278, 252, 298), EVEN, 12, HIGH),
    # prompt strips (flat green key, white text, purple outline)
    _key((252, 276, 420, 294), "Pick your handicap!"),
    _key((0, 302, 168, 320), "How many matches?"),
    _key((168, 302, 336, 320), "Lock with a password?"),
    _key((336, 294, 504, 312), "Enter the password!"),
    _key((0, 320, 168, 338), "Name your room!"),
])

# ---------------------------------------------------------------- handicap

# tex 018 @0x168490: Play Condition handicap labels (same wording as room-create).
HANDICAP = dict(name="handicap", file="IMAGE.DAT", fo=0x168490, slot_end=0x173000, edits=[
    # One edit per sprite (layout table @0x14d010, tex 1). The old loose clears ran
    # 2 px into the circle sprite (312,0,410,114) and stopped 3 px short of the
    # ちょっと/とっても sprites' edges; the 26 px label clips crossed sprite edges.
    # Pairs (normal -> highlighted): 同じ (410,26,484,50) -> (410,0,486,26) and
    # ちょっと有利 (0,184,130,208) -> (272,114,404,140); each highlighted sprite is
    # 2 px larger and its JP sits +1,+1 inside it, i.e. the game centres both, so
    # every label is centred in its own sprite. One font size for the sheet.
    _spr((410, 26, 484, 50), EVEN, 14, NORM_HC), _spr((410, 0, 486, 26), EVEN, 14, HIGH),
    _spr((0, 184, 130, 208), SLIGHT_ADV, 14, NORM_HC), _spr((272, 114, 404, 140), SLIGHT_ADV, 14, HIGH),
    _spr((288, 140, 420, 164), HUGE_ADV, 14, NORM_HC),
    _spr((130, 184, 248, 208), HUGE_HC, 14, NORM_HC),
    _spr((248, 184, 366, 208), SLIGHT_HC, 14, NORM_HC),
])

# ---------------------------------------------------------------- room view

# tex 051 @0x3bbd70 (in-room screen; everything else on it is native English):
# 勝 -> W, 敗 -> L in both player panels. Each kanji sits on a small dark-teal
# block over a horizontally striped panel, so bg="rows" rebuilds the stripes by
# copying each row's own panel index from beside the block. Letters are drawn in
# the kanji's pale cyan (fill 255 maps to it) with a dark teal outline.
def _wl(x0, x1, txt):
    # x1 stops at the panel's right-edge gradient (L) so it is never rebuilt
    return dict(clip=(x0, 169, x1, 189), lines=[txt], ty0=170, lh=20, fs=15,
                bg="rows", wht=110, drk=90, dil=3, fill=255, outline=30, sw=2)


ROOM_VIEW = dict(name="room-view", file="IMAGE.DAT", fo=0x3bbd70, slot_end=0x3d38e0, edits=[
    _wl(60, 90, "W"), _wl(122, 148, "L"),      # ROOM OWNER panel
    _wl(402, 432, "W"), _wl(464, 490, "L"),    # CHALLENGER panel
])

# ---------------------------------------------------------------- BB Unit dialogs

# Dialog text: pale letters with a thick navy outline on a light-blue panel made of
# HORIZONTAL bands. Two passes on the same clip:
#  1. bg="rows": the bright upper part of each letter (min channel > 215) seeds the
#     mask (+ the navy outline near it); each masked pixel copies the original index
#     of the nearest clean pixel in its own row, so the bands continue exactly.
#  2. bg="outlined" with a low `wht`: whatever navy outline is left (letter bottoms,
#     where the fill gradient is too dark to seed pass 1) plus a 3 px halo is
#     inpainted; these leftovers are small, so the inpaint stays local. The English
#     is drawn in this pass (pass 1 must not draw, pass 2 would erase it).
# Clips hug each text block with a few px of clean panel on both sides.
# `drk` must stay below the panel's darkest band (measured per panel: blue ~182,
# pink ~161); `seed` above the panel's brightest band where possible.
def _dlg(clip, lines, ty0, lh=22, fs=14, drk=170, seed=185, sweep=(), **kw):
    """`sweep` = rows where pass 1 left a dark streak (a row copied from a dark pixel
    it could not mask): each gets a 1-px bg="flat" refill of its dark pixels with the
    row's own panel index, between the two passes."""
    e = dict(clip=clip, lines=lines, ty0=ty0, lh=lh, fs=fs, bg="outlined",
             wht=100, drk=drk, reach=3, dil=1, fill=250, outline=40, sw=2)
    e.update(kw)
    sw_ = [dict(clip=(clip[0], y, clip[2], y + 1), bg="flat", hat=0, wht=255, drk=drk, dil=1)
           for y in sweep]
    return [dict(clip=clip, bg="rows", wht=seed, drk=drk, dil=14), *sw_, e]


# tex 376 @0x28716c0: Auto Load dialogs on the LEFT; the RIGHT (x >= 368) is the
# online/lobby cat sprites + ONLINE logo, never touched (clips stop at x 332).
AUTOLOAD = dict(name="autoload", file="IMAGE.DAT", fo=0x28716c0, slot_end=0x2884b00, edits=[
    *_dlg((10, 203, 330, 298),
          ["Now loading!",
           "Data may be damaged, so don't turn off",
           'or reset the "PlayStation 2" or unplug',
           'the "PlayStation BB Unit"!'], 206),
    *_dlg((60, 352, 280, 390), ["Load complete!"], 358),
])


# tex 004 @0x38d40: the same Auto Load dialogs on the title-screen atlas (MANUAL
# cat sprites on the right, x >= 340, untouched); same layout as AUTOLOAD.
AUTOLOAD_TITLE = dict(AUTOLOAD, name="autoload-title", fo=0x38d40, slot_end=0x4d110)

# tex 005 @0x4d110: BB Unit dialogs (pink "Warning", blue "creating save area",
# blue "not enough space" + Yes/No). The old built-in text for the warning was a
# mistranslation and its slot_end (0x60020) ran 0x20 bytes into the block
# directory at 0x60000; the slot here stops at 0x60000.
BBUNIT_SAVE = dict(name="bbunit-save", file="IMAGE.DAT", fo=0x4d110, slot_end=0x60000, edits=[
    *_dlg((10, 50, 330, 106),
          ["Follow the manual that came with your",
           '"PlayStation BB Unit" to repair it!'], 58, lh=23, drk=150, seed=185,
          outline=(70, 30, 70)),
    *_dlg((10, 180, 330, 220),
          ["Making room for save data on the",
           '"PlayStation BB Unit"!'], 182, lh=18, fs=13, drk=180, seed=185),
    *_dlg((10, 280, 330, 354),
          ['Not enough free space on the "PlayStation BB Unit"!',
           "This game needs 2MB or more to save!",
           "Start anyway?"], 286, lh=22, fs=13, drk=155, seed=185),
])

# tex 379 @0x28ac5e0: Auto Load warning (memory card variant) + install-space
# dialogs (blue panels, same text style as AUTOLOAD).
INSTALL_SPACE = dict(name="install-space", file="IMAGE.DAT", fo=0x28ac5e0, slot_end=0x28c1ec0, edits=[
    *_dlg((10, 33, 330, 127),
          ["Now loading!",
           "Data may be damaged, so don't turn off or",
           'reset the "PlayStation 2", or remove the',
           "memory card (8MB) or the controllers!"], 39, lh=21, fs=13, drk=170, seed=185),
    *_dlg((10, 148, 330, 220),
          ['Not enough free space on the "PlayStation BB Unit"!',
           "Installing this app needs 128MB or more!",
           "Start without installing?"], 153, lh=22, fs=13, drk=160, seed=185),
    *_dlg((10, 306, 330, 358),
          ["Please free up 128MB or more",
           'on the "PlayStation BB Unit"!'], 314, lh=22, fs=14, drk=175, seed=185),
])


# ---------------------------------------------------------------- lobby tiles

# Prefecture / rank name tiles: pale letters with a dark outline on a TRANSPARENT
# cell (72x20 for prefectures, laid out on a 72 px pitch). Each sheet's tile grid is
# erased as whole regions first (_clear), then every name is redrawn left-aligned
# inside its own cell (_txt). Names match the ELF tables (elf.en.tsv pref:/rank).
def _cells(rows, fill, outline, fs=13, dy=2, sw=2):
    """rows = [(y0, y1, [(x0, x1, text), ...]), ...] -> text-only edits."""
    out = []
    for y0, y1, cells in rows:
        for x0, x1, t in cells:
            out.append(_txt((x0, y0, x1, y1), t, y0 + dy, fs, dict(fill=fill, outline=outline, sw=sw),
                            align="l"))
    return out


def _row72(y0, y1, names, x0=0):
    return (y0, y1, [(x0 + 72 * k + 1, x0 + 72 * k + 72, n) for k, n in enumerate(names) if n])


# Help-line key legend strip (flat cream, white letters with a dark outline, icons
# left of each label). bg="key": the cream is the key (wht=252 keeps it a
# "mid-tone"), letters + outline (within 3 px of the white) are refilled with it.
def _kb(clip, txt, fs=11, wht=252, sw=2):
    # wht must sit between the cream's luminance (238 on 0x6ee600, 248 elsewhere)
    # and the letters' white
    return dict(clip=clip, lines=[txt], ty0=clip[1] + 1, lh=14, fs=fs, bg="key",
                wht=wht, dil=5, align="l",
                fill=250, outline=(41, 43, 37), sw=sw)


def _kbstrip(y, wht=252):
    """The 4-row key legend whose top row starts at y (rows 14 px apart)."""
    r1, r2, r3, r4 = y, y + 14, y + 28, y + 42
    import functools
    _kb_ = functools.partial(_kb, wht=wht)
    return [
        _kb_((22, r1, 90, r1 + 14), "Keyboard"), _kb_((112, r1, 182, r1 + 14), "Create room"),
        _kb_((22, r2, 90, r2 + 14), "Hide keys"), _kb_((112, r2, 182, r2 + 14), "Confirm"),
        # after the O/X swap: the X icon (x 284-358) is OK / Type and the O icon
        # (x 376-446) is Cancel / Backspace (the native BACKSPACE art next to X goes)
        _kb_((194, r2, 268, r2 + 14), "Convert"), _kb_((284, r2, 358, r2 + 14), "OK"),
        _kb_((376, r2, 446, r2 + 14), "Cancel"),
        _kb_((22, r3, 90, r3 + 14), "Hide keys"), _kb_((112, r3, 182, r3 + 14), "Send"),
        _kb_((194, r3, 268, r3 + 14), "Convert"), _kb_((284, r3, 358, r3 + 14), "Type"),
        _kb_((376, r3, 446, r3 + 14), "Backspace"),
        _kb_((22, r4, 90, r4 + 14), "Keyboard"),
    ]


LOBBY_TILES_C = dict(name="lobby-tiles-c", file="IMAGE.DAT", fo=0x6ee600, slot_end=0x6f9800, edits=[
    _clear((331, 0, 480, 40)),
    _clear((0, 40, 512, 100)),
    *_cells([
        (0, 20, [(332, 404, "Osaka"), (404, 476, "Hyogo")]),
        (20, 40, [(332, 404, "Nara"), (404, 476, "Wakayama")]),
        _row72(40, 60, ["Tottori", "Shimane", "Okayama", "Hiroshima", "Yamaguchi", "Tokushima", "Kagawa"]),
        _row72(60, 80, ["Ehime", "Kochi", "Fukuoka", "Saga", "Nagasaki", "Kumamoto", "Oita"]),
        _row72(80, 100, ["Miyazaki", "Kagoshima", "Okinawa"]),
    ], fill=(231, 228, 189), outline=(26, 19, 81)),
    *_kbstrip(100, wht=245),
])



def _tile(clip, txt, fill, outline, fs=13, dy=2, align="l", sw=2):
    """Erase every non-black pixel of one transparent name cell, then draw `txt`."""
    e = _clear(clip)
    e.update(lines=[txt], ty0=clip[1] + dy, lh=20, fs=fs, align=align,
             fill=fill, outline=outline, sw=sw)
    return e


# Rank tiles: every rank sprite on every sheet is 38x20 on the transparent entry, and
# the game draws it over the player row plate (orange/brown, teal, ...). fix5 (live
# test: "8 Kyu" illegible above Hi-Score): the old labels were fs 12 with a 1 px
# outline and auto-shrunk per word; they became "8Kyu"/"1Dan" (no space) at one size
# for the whole family, centred in the sprite on the same "Hg" baseline box, with
# "Master" compressed horizontally (squeeze) instead of shrinking.
# fix6 (live test: fs 15 + 2 px aliased outline looked clotted at 1x, the outline ate
# the letter interiors): fs 15 with a 1 px dark outline, aliased. Compared at 1x over
# orange / tan / teal / maroon / purple row plates against sw 2, AA (+ ramp mapper:
# fuzzy, blends toward the transparent black), faux bold 1 (closes the counters), the
# JP's lighter second-ring outline colour (weak on the orange row) and fs 13/14 (the
# top counter of "8" fills in, it reads as a 9); this one keeps the counters open and
# the edge crisp on every plate. Widest label "8Dan" = 35 px.
RANK_FS, RANK_SW = 15, 1


def _rank(rect, txt, fill, outline):
    """`rect` = the rank sprite's exact rect from the block layout table (38x20)."""
    from PIL import ImageFont, ImageDraw, Image
    import pntexnat
    x0, y0, x1, y1 = rect
    assert (x1 - x0, y1 - y0) == (38, 20), rect
    f = ImageFont.truetype(pntexnat.FONT, RANK_FS)
    r = ImageDraw.Draw(Image.new("RGB", (4, 4))).textbbox((0, 0), "Hg", font=f, stroke_width=RANK_SW)
    ty0 = y0 + (y1 - y0 - (r[3] - r[1])) // 2 - r[1]
    e = _clear(rect)
    e.update(lines=[txt], ty0=ty0, lh=20, fs=RANK_FS, align="c", fill=fill, outline=outline,
             sw=RANK_SW, margin=1, squeeze=True,
             # aliased (set explicitly; pntexnat's default depends on bg): AA blends the
             # edge toward the transparent entry's black and reads fuzzy at 1x
             aa=False)
    return e


def _grid(rows, fill, outline, fs=13, dy=2, align="l"):
    """rows = [(y0, y1, x0, pitch, w, [names...]), ...]; '' skips a cell."""
    out = []
    for y0, y1, x0, pitch, w, names in rows:
        for k, n in enumerate(names):
            if n:
                out.append(_tile((x0 + pitch * k, y0, x0 + pitch * k + w, y1), n,
                                 fill, outline, fs, dy, align))
    return out


def _wl2(x0, x1, y0, txt):
    """勝/敗 on a striped INFORMATION panel (same method as the room view)."""
    return dict(clip=(x0, y0, x1, y0 + 20), lines=[txt], ty0=y0 + 1, lh=20, fs=15,
                bg="rows", wht=110, drk=90, dil=3, fill=255, outline=30, sw=2)


KYU = ["8Kyu", "7Kyu", "6Kyu", "5Kyu", "4Kyu", "3Kyu", "2Kyu", "1Kyu"]
DAN = ["1Dan", "2Dan", "3Dan", "4Dan", "5Dan", "6Dan", "7Dan", "8Dan"]
PREFS = ["Hokkaido", "Aomori", "Iwate", "Miyagi", "Akita", "Yamagata", "Fukushima",
         "Ibaraki", "Tochigi", "Gunma", "Saitama", "Chiba", "Tokyo", "Kanagawa",
         "Niigata", "Toyama", "Ishikawa", "Fukui", "Yamanashi", "Nagano", "Gifu",
         "Shizuoka", "Aichi", "Mie", "Shiga", "Kyoto", "Osaka", "Hyogo", "Nara",
         "Wakayama", "Tottori", "Shimane", "Okayama", "Hiroshima", "Yamaguchi",
         "Tokushima", "Kagawa", "Ehime", "Kochi", "Fukuoka", "Saga", "Nagasaki",
         "Kumamoto", "Oita", "Miyazaki", "Kagoshima", "Okinawa"]


def P(a, b=None):
    """Prefectures by 1-based JIS order: P(1, 7) = Hokkaido..Fukushima."""
    return PREFS[a - 1:(b or a)]


# Main lobby frame (teal) tex @0x6c4c00 and its green beginner-lobby twin in
# IMAGE1.DAT @0x132460: INFORMATION panel 勝/敗, 八級 rank tile, prefectures 1-7.
def _lobby_frame(name, f, fo, slot_end, fill, outline, prefs):
    return dict(name=name, file=f, fo=fo, slot_end=slot_end, edits=[
        _wl2(404, 430, 199, "W"), _wl2(466, 491, 199, "L"),
        _rank((450, 448, 488, 468), KYU[0], fill, outline),
        *_grid([(492, 512, 0, 72, 72, prefs)], fill, outline),
    ])


LOBBY_A = _lobby_frame("lobby-frame", "IMAGE.DAT", 0x6c4c00, 0x6d8d70,
                       (142, 215, 220), (0, 49, 58), P(1, 7))
LOBBY_D = _lobby_frame("lobby-frame-green", "IMAGE1.DAT", 0x132460, 0x144cc0,
                       (254, 205, 159), (1, 56, 64), P(1, 7))

# IMAGE1.DAT @0x144cc0: lobby frame variant with 七級/六級 tiles and prefectures 8-14.
LOBBY_E = dict(name="lobby-frame-2", file="IMAGE1.DAT", fo=0x144cc0, slot_end=0x157950, edits=[
    _wl2(404, 430, 199, "W"), _wl2(466, 491, 199, "L"),
    _rank((450, 448, 488, 468), KYU[1], (171, 254, 246), (2, 56, 65)),
    _rank((450, 468, 488, 488), KYU[2], (171, 254, 246), (2, 56, 65)),
    *_grid([(492, 512, 0, 72, 72, P(8, 14))], (171, 254, 246), (2, 56, 65)),
])

# Lobby room list sheet tex @0x6d8d70: rank column (七級..神) + prefectures 8-25.
_FB, _OB = (150, 233, 225), (31, 20, 69)
LOBBY_B = dict(name="lobby-list", file="IMAGE.DAT", fo=0x6d8d70, slot_end=0x6ee600, edits=[
    # rank sprites (layout table): 7/6 Kyu at x 450, 5/4/3 Kyu at x 464, then a
    # column at x 462 from y 128 (2 Kyu .. God)
    _rank((450, 0, 488, 20), KYU[1], _FB, _OB),
    _rank((450, 20, 488, 40), KYU[2], _FB, _OB),
    _rank((464, 40, 502, 60), KYU[3], _FB, _OB),
    _rank((464, 88, 502, 108), KYU[4], _FB, _OB),
    _rank((464, 108, 502, 128), KYU[5], _FB, _OB),
    *[_rank((462, 128 + 20 * k, 500, 148 + 20 * k), t, _FB, _OB)
      for k, t in enumerate(KYU[6:] + DAN + ["Master", "God"])],
    *_grid([(368 + 20 * r, 388 + 20 * r, 332, 72, 72, P(8 + 2 * r, 9 + 2 * r)) for r in range(6)],
           _FB, _OB),
    *_grid([(488, 512, 0, 72, 72, P(19, 25))], _FB, _OB, dy=5),
])


# IMAGE1.DAT @0x157950: beginner-lobby sheet: rank column (五級..名人) and
# prefectures 15-18 / 19-34 (two 72 px columns).
_FF, _OF = (201, 249, 249), (55, 35, 82)
LOBBY_F = dict(name="lobby-list-beginner", file="IMAGE1.DAT", fo=0x157950, slot_end=0x16d890, edits=[
    # ここは初心者ロビーだよ！ / このロビーには五級以上のユーザーは入れないよ！
    *_dlg((30, 30, 312, 92), ["This is the Beginner Lobby!",
                              "Players ranked 5 Kyu or up can't enter!"], 34, lh=33,
          fs=14, drk=165, seed=192, outline=(60, 30, 90)),
    # rank sprites (layout table): 5/4/3 Kyu at x 472, 2/1 Kyu + 1 Dan at x 470,
    # 2 Dan .. Master at x 462
    *[_rank((472, 20 * k, 510, 20 * k + 20), t, _FF, _OF) for k, t in enumerate(KYU[3:6])],
    *[_rank((470, 60 + 20 * k, 508, 80 + 20 * k), t, _FF, _OF)
      for k, t in enumerate(KYU[6:] + DAN[:1])],
    *[_rank((462, y, 500, y + 20), t, _FF, _OF) for y, t in
      [(134, DAN[1]), (154, DAN[2]), (174, DAN[3]), (220, DAN[4]), (266, DAN[5]),
       (286, DAN[6]), (306, DAN[7]), (326, "Master")]],
    *_grid([(201, 221, 332, 72, 72, P(15, 16)), (247, 267, 332, 72, 72, P(17, 18))]
           + [(347 + 20 * r, 367 + 20 * r, 332, 72, 72, P(19 + 2 * r, 20 + 2 * r)) for r in range(8)],
           _FF, _OF),
])

# IMAGE1.DAT @0x16d890: prefectures 35-47 + 神 tile, and the key legend strip.
_FG, _OG = (251, 215, 168), (35, 19, 97)
LOBBY_G = dict(name="lobby-list-2", file="IMAGE1.DAT", fo=0x16d890, slot_end=0x17a800, edits=[
    *_grid([(20 * r, 20 * r + 20, 332, 72, 72, P(35 + 2 * r, 36 + 2 * r)) for r in range(6)]
           + [(120, 140, 332, 72, 72, P(47))], _FG, _OG),
    _rank((404, 120, 442, 140), "God", _FG, _OG),
    *_kbstrip(200),
])

# Room screen sheet tex @0x3d38e0: prefecture/rank tiles + key legend row.
_FH, _OH = (171, 254, 246), (50, 50, 43)
def _grad(clip, txt, ty0, fill, outline, fs=22):
    # big coloured letters with a dark outline on a pale, faintly patterned card
    # (card luminance >= 208, every letter pixel < 204): threshold mask (hat=0) of
    # everything darker than the card, inpainted from the card around it
    return dict(clip=clip, lines=[txt], ty0=ty0, lh=30, fs=fs, bg="inpaint",
                hat=0, wht=255, drk=204, dil=2,
                fill=fill, outline=outline, sw=2)


ROOM_TILES = [
    # 初心者ロビー卒業おめでとう！ / これからはノーマルロビーで / 対戦を楽しんでね！
    _grad((14, 78, 408, 124), "Beginner Lobby graduate!", 86, (202, 14, 14), (79, 0, 0), fs=28),
    _grad((14, 130, 408, 176), "Now enjoy matches in", 138, (45, 130, 64), (109, 23, 22), fs=28),
    _grad((14, 182, 408, 228), "the Normal Lobby!", 190, (45, 130, 64), (109, 23, 22), fs=28),
    # Attention: ルームから退出する？ (banded blue panel, Yes/No are English)
    *_dlg((222, 301, 420, 330), ["Leave the room?"], 303, fs=15, drk=120, seed=200),
    *_grid([(62 + 20 * k, 82 + 20 * k, 420, 72, 72, P(1 + k)) for k in range(9)], _FH, _OH),
    *_grid([(396, 416, 148, 72, 72, P(10, 14)), (416, 436, 180, 72, 72, P(15, 18)),
            (436, 456, 0, 72, 72, P(19, 25)), (456, 476, 0, 72, 72, P(26, 32)),
            (476, 496, 0, 72, 72, P(33, 39))], _FH, _OH),
    _rank((468, 414, 506, 434), KYU[0], _FH, _OH),
    # the band is one flat cream index (lum 248) over rows 496..509, with a dark
    # border at 510..511: clear everything not cream (the glyph tops reach row 497),
    # then draw; keep both clips off the border
    dict(_clear((22, 496, 90, 510)), wht=248, drk=248),
    dict(_clear((112, 496, 182, 510)), wht=248, drk=248),
    dict(_kb((22, 496, 90, 510), "Keyboard", fs=11, sw=1), ty0=499, fill=(255, 255, 255), outline=(2, 56, 65)),
    dict(_kb((112, 496, 182, 510), "vs CPU", fs=11, sw=1), ty0=499, fill=(255, 255, 255), outline=(2, 56, 65)),
]


# Room help sheet tex @0x3f4ef0: prefectures 40-47, rank tiles (38 px cells), the
# key legend (決定 variant) and the two IN-ROOM HELP LINES (white text on a flat
# brown plate; these were thought to be font-drawn but live here).
_FR, _OR = (150, 233, 225), (31, 20, 69)


def _help(clip, txt, fs=11, dy=0):
    return dict(clip=clip, lines=[txt], ty0=clip[1] + dy, lh=14, fs=fs, bg="key",
                wht=190, dil=3, fill=250, outline=(61, 29, 7), sw=1)


ROOM_HELP = dict(name="room-help", file="IMAGE.DAT", fo=0x3f4ef0, slot_end=0x401800, edits=[
    *_grid([(0, 20, 0, 72, 72, P(40, 46)), (20, 40, 0, 72, 56, P(47))], _FR, _OR),
    *[_rank((72 + 38 * k, 20, 110 + 38 * k, 40), t, _FR, _OR)
      for k, t in enumerate(KYU[1:] + DAN[:4])],
    *[_rank((38 * k, 40, 38 * k + 38, 60), t, _FR, _OR)
      for k, t in enumerate(DAN[4:] + ["Master", "God"])],      # God = (190, 40, 228, 60)
    *[_kb(c, t) for c, t in [
        ((22, 60, 90, 74), "Hide keys"), ((112, 60, 182, 74), "OK"),
        ((194, 60, 268, 74), "Convert"), ((284, 60, 358, 74), "OK"),      # X (swapped)
        ((376, 60, 446, 74), "Cancel"),                                   # O (swapped)
        ((22, 74, 90, 88), "Hide keys"), ((112, 74, 182, 88), "Send"),
        ((194, 74, 268, 88), "Convert"), ((284, 74, 358, 88), "Type"),
        ((376, 74, 446, 88), "Backspace"),
        ((22, 88, 90, 102), "Keyboard")]],
    # CHALLENGERが入室するまで待っててね！CPUと対戦しながら待つときはSTART BUTTONを押してね！
    _help((0, 102, 412, 116),
          "Wait for a CHALLENGER! To play the CPU while you wait, press START BUTTON!", dy=2),
    # ROOM OWNERは対戦条件を変更できるよ！対戦する場合はREADYを選んでね！
    _help((44, 116, 412, 130), "The ROOM OWNER can change the rules! Pick READY to play!"),
])


# Data-update progress screen tex @0x386940: title button, warning panel (pale
# horizontal gradient: same two-pass method as the BB Unit dialogs) and the
# progress labels 現在 .. % / 残り約 .. 分 (white letters on a dithered green panel).
DATA_UPDATE_PROGRESS = dict(name="data-update-progress", file="IMAGE.DAT", fo=0x386940,
                            slot_end=0x39ab00, edits=[
    # title plate: a top-to-bottom gradient (every row one colour), so each row is
    # its own 1-px bg="flat" edit: letter pixels (lum > 205 fill, < 100 outline, +1 px;
    # the plate is 105..202 on rows 89-116) get that row's most common plate index;
    # then the text is drawn
    *[dict(clip=(38, y, 168, y + 1), bg="flat", hat=0, wht=205, drk=100, dil=1)
      for y in range(89, 117)],
    _txt((38, 89, 168, 117), "Updating!", 92, 17, dict(fill=250, outline=28, sw=2)),
    *_dlg((84, 144, 436, 236),
          ["Please wait a moment!", "",
           "Data may be damaged, so don't turn off",
           'or reset the "PlayStation 2" or unplug',
           'the "PlayStation BB Unit"!'], 147, lh=16, fs=13, drk=175, seed=186,
          sweep=range(226, 236),
          outline=(20, 60, 40)),
    _key((222, 372, 264, 394), "Now", fs=14, outline=(20, 40, 20), ty0=375, wht=200, dil=3),
    _key((358, 372, 412, 394), "Left", fs=14, outline=(20, 40, 20), ty0=375, wht=200, dil=3),
    _key((432, 372, 470, 394), "min", fs=14, outline=(20, 40, 20), ty0=375, wht=200, dil=3),
])


# ---------------------------------------------------------------- save / load dialogs

# Memory card / BB Unit save, load and data-move dialogs: up to three stacked
# panels per sheet (interiors y 5-129, 139-263, 273-397, x 6-332), pale letters
# with a dark outline on horizontally banded panels. Each panel's clip hugs its
# Japanese text block (title and Yes/No buttons are native English and stay
# outside); `drk` sits under the panel's darkest band and `seed` over its brightest
# band, swl/swh = the panel's own luminance range (all measured from the stock
# sheet). Method: the rows pass, then a 1-px bg="flat" sweep of every row (any
# pixel outside the panel's luminance range, e.g. a row-copy streak of letter
# colour, gets that row's most common panel index), then the outlined pass that
# draws the English.
def _panel(clip, lines, ty0, lh, drk, seed, outline, swl, swh, fs=14):
    x0, y0, x1, y1 = clip
    if len(lines) == 1:                  # short message: room for a full-size line
        x0, x1 = min(x0, 40), max(x1, 300)
        clip = (x0, y0, x1, y1)
    sweep = [dict(clip=(x0, y, x1, y + 1), bg="flat", hat=0, wht=swh, drk=swl, dil=1)
             for y in range(y0, y1)]
    return [dict(clip=clip, bg="rows", wht=seed, drk=drk, dil=14), *sweep,
            dict(clip=clip, lines=lines, ty0=ty0, lh=lh, fs=fs, bg="outlined",
                 wht=100, drk=drk, reach=3, dil=1, fill=250, outline=outline, sw=2)]


# (fo, slot_end, [(clip, lines, ty0, lh, drk, seed, outline, swl, swh), ...])
_SAVE_LOAD = [
    (0x77f60, 0x92270, [
        ((50, 31, 291, 127), ['Now saving!', "Data may be damaged, so don't turn off or", 'reset the "PlayStation 2" or unplug the', '"PlayStation BB Unit"!'], 41, 19, 143, 202, (63, 31, 10), 153, 224),
        ((8, 149, 331, 223), ['The memory card (8MB) in MEMORY CARD slot 1', 'is out of space! Saving needs 155KB or more', 'free. Keep playing anyway?'], 159, 19, 137, 185, (63, 31, 10), 141, 211),
        ((8, 299, 331, 395), ['Saving to the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 309, 19, 143, 218, (63, 31, 10), 153, 228),
    ]),
    (0x92270, 0xa6090, [
        ((129, 31, 208, 83), ['Save complete!'], 47, 20, 143, 185, (53, 9, 46), 153, 195),
        ((20, 165, 322, 240), ['Follow the manual that came with your', '"PlayStation BB Unit" to repair it!'], 183, 19, 115, 185, (43, 3, 36), 125, 199),
        ((20, 277, 321, 395), ['Checking the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 299, 19, 133, 213, (13, 35, 92), 143, 228),
    ]),
    (0xa6090, 0xbcbe0, [
        ((8, 15, 331, 89), ["Couldn't check the memory card (8MB) in", "MEMORY CARD slot 1, so you can't save!", 'Keep playing anyway?'], 25, 19, 151, 185, (39, 66, 110), 152, 212),
        ((8, 149, 331, 223), ['No memory card (8MB) in MEMORY CARD slot 1,', "so you can't save!", 'Keep playing anyway?'], 159, 19, 151, 185, (39, 66, 110), 152, 212),
        ((8, 283, 331, 357), ['The memory card (8MB) in MEMORY CARD slot 1', "isn't formatted! Format it now?"], 302, 19, 135, 185, (39, 66, 110), 145, 212),
    ]),
    (0xbcbe0, 0xc9000, [
        ((11, 9, 330, 127), ['Formatting the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 31, 19, 131, 220, (30, 70, 104), 141, 228),
    ]),
    (0x417890, 0x42a890, [
        ((8, 31, 331, 89), ['A new character is now available!'], 49, 20, 100, 185, (74, 110, 86), 110, 192),
        ((8, 165, 331, 223), ['Save complete!'], 183, 20, 100, 185, (74, 110, 86), 110, 192),
        ((8, 299, 331, 357), ['Save failed!'], 317, 20, 100, 185, (74, 110, 86), 110, 192),
    ]),
    (0x42a890, 0x433000, [
        ((8, 31, 331, 89), ['New attack balls are now available!'], 49, 20, 104, 185, (90, 85, 157), 114, 186),
    ]),
    (0x457660, 0x4869e0, [
        ((51, 165, 291, 261), ['Now saving!', "Data may be damaged, so don't turn off or", 'reset the "PlayStation 2" or unplug the', '"PlayStation BB Unit"!'], 176, 19, 141, 207, (35, 65, 107), 151, 227),
        ((8, 285, 331, 357), ['The memory card (8MB) in MEMORY CARD slot 1', 'is out of space! Saving needs 155KB or more', 'free. Keep playing anyway?'], 295, 19, 130, 185, (35, 65, 107), 140, 212),
    ]),
    (0x4869e0, 0x49a8f0, [
        ((8, 31, 331, 127), ['Saving to the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 41, 19, 147, 217, (28, 49, 99), 157, 225),
        ((129, 165, 208, 217), ['Save complete!'], 181, 20, 141, 185, (65, 3, 56), 151, 195),
        ((20, 299, 322, 374), ['Follow the manual that came with your', '"PlayStation BB Unit" to repair it!'], 317, 19, 115, 187, (43, 3, 36), 125, 199),
    ]),
    (0x49a8f0, 0x4b3000, [
        ((20, 9, 321, 127), ['Checking the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 31, 19, 131, 197, (31, 69, 104), 141, 223),
        ((8, 149, 331, 223), ["Couldn't check the memory card (8MB) in", "MEMORY CARD slot 1, so you can't save!", 'Keep playing anyway?'], 159, 19, 148, 197, (31, 69, 104), 141, 212),
        ((8, 283, 331, 357), ['No memory card (8MB) in MEMORY CARD slot 1,', "so you can't save!", 'Keep playing anyway?'], 293, 19, 148, 197, (31, 69, 104), 141, 212),
    ]),
    (0x4b3000, 0x4c5000, [
        ((8, 15, 331, 89), ['The memory card (8MB) in MEMORY CARD slot 1', "isn't formatted! Format it now?"], 34, 19, 133, 185, (36, 61, 107), 143, 212),
        ((11, 143, 330, 261), ['Formatting the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 165, 19, 133, 219, (36, 61, 107), 143, 226),
    ]),
    (0x797070, 0x7a8000, [
        ((37, 32, 303, 106), ['The "PlayStation BB Unit" isn\'t formatted!', "The game can't be installed like this, so", 'please install "PlayStation BB Navigator"!'], 41, 19, 139, 210, (38, 62, 106), 149, 228),
        ((10, 165, 331, 240), ['The "PlayStation BB Unit" isn\'t connected!', "Without it the game can't be installed,", "so you can't play online!"], 175, 19, 139, 210, (38, 62, 106), 149, 228),
    ]),
    (0x27c45c0, 0x27dc040, [
        ((18, 15, 323, 89), ['Move the save data on the memory card (8MB)', 'in MEMORY CARD slot 1 to the', '"PlayStation BB Unit"?'], 25, 19, 159, 197, (43, 81, 120), 169, 229),
        ((20, 143, 321, 261), ['Checking the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 165, 19, 159, 225, (52, 73, 126), 169, 241),
        ((8, 283, 331, 357), ["Couldn't check the memory card (8MB)", 'in MEMORY CARD slot 1!', 'Continue without moving it?'], 293, 19, 159, 197, (34, 47, 109), 169, 229),
    ]),
    (0x27dc040, 0x27f1380, [
        ((10, 15, 331, 89), ['No memory card (8MB) in MEMORY CARD slot 1!', 'Continue without moving it?'], 34, 19, 160, 199, (57, 80, 130), 170, 230),
        ((8, 149, 331, 223), ['No save data on the memory card (8MB)', 'in MEMORY CARD slot 1!', 'Continue without moving it?'], 159, 19, 160, 199, (57, 80, 130), 170, 230),
        ((50, 290, 290, 342), ['The "PlayStation BB Unit" isn\'t connected!', 'Continue without moving it?'], 298, 19, 161, 197, (46, 86, 122), 171, 224),
    ]),
    (0x27f1380, 0x28047f0, [
        ((35, 23, 304, 74), ['The "PlayStation BB Unit" isn\'t formatted!', 'Continue without moving it?'], 31, 19, 163, 185, (47, 85, 123), 173, 225),
        ((35, 166, 306, 240), ['The "PlayStation BB Unit" is low on space!', 'Moving the save data needs', '2MB or more free!'], 175, 19, 163, 216, (47, 85, 123), 173, 241),
        ((27, 291, 314, 342), ['The "PlayStation BB Unit" already has', 'save data! Overwrite it?'], 299, 19, 168, 185, (47, 85, 123), 173, 225),
    ]),
    (0x28047f0, 0x2817ee0, [
        ((26, 9, 314, 127), ['Moving save data to the "PlayStation BB Unit"!', 'Don\'t turn off or reset the "PlayStation 2",', 'unplug the "PlayStation BB Unit", or remove', 'the memory card (8MB) or the controllers!'], 31, 19, 159, 219, (38, 52, 113), 169, 241),
        ((101, 188, 239, 217), ['Save data moved!'], 193, 20, 180, 185, (30, 43, 106), 191, 214),
        ((69, 289, 271, 342), ['Moving the save data failed!', 'Continue without moving it?'], 297, 19, 164, 188, (59, 82, 131), 174, 218),
    ]),
    (0x2817ee0, 0x2828000, [
        ((8, 9, 331, 127), ['Loading save data from the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 31, 19, 164, 230, (57, 77, 128), 174, 243),
        ((69, 155, 271, 208), ['Load failed!', 'Continue without moving it?'], 163, 19, 159, 198, (57, 77, 128), 169, 217),
    ]),
    (0x2884b00, 0x2899a40, [
        ((10, 15, 331, 89), ['No "PlayStation 2" memory card (8MB)!', 'This game needs 155KB or more to save!', 'Start anyway?'], 25, 19, 162, 201, (55, 77, 127), 172, 230),
        ((51, 176, 289, 227), ['No "PlayStation 2" memory card (8MB)', 'in MEMORY CARD slot 1!'], 183, 19, 175, 215, (55, 77, 127), 185, 230),
        ((26, 299, 314, 380), ['The memory card (8MB) in MEMORY CARD slot 1', "has no pop'n Puzzle-dama ONLINE", 'save data!'], 311, 19, 169, 212, (55, 77, 127), 179, 239),
    ]),
    (0x28c1ec0, 0x28cc800, [
        ((8, 15, 331, 89), ['The "PlayStation 2" memory card (8MB) is out', 'of space! This game needs 155KB or more', 'to save! Start anyway?'], 25, 19, 168, 199, (54, 76, 128), 175, 231),
    ]),
    (0x28ecc40, 0x2903340, [
        ((8, 15, 331, 89), ['The memory card (8MB) in MEMORY CARD slot 1', 'is out of space! Saving needs 155KB or more', 'free. Keep playing anyway?'], 25, 19, 137, 185, (21, 37, 90), 139, 211),
        ((8, 165, 331, 261), ['Saving to the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 175, 19, 142, 215, (21, 37, 90), 152, 228),
        ((129, 299, 208, 351), ['Save complete!'], 315, 20, 144, 185, (21, 37, 90), 154, 191),
    ]),
    (0x2903340, 0x291ba50, [
        ((20, 9, 321, 127), ['Checking the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 31, 19, 131, 197, (31, 69, 104), 141, 223),
        ((8, 149, 331, 223), ["Couldn't check the memory card (8MB) in", "MEMORY CARD slot 1, so you can't save!", 'Keep playing anyway?'], 159, 19, 148, 197, (31, 69, 104), 141, 212),
        ((8, 283, 331, 357), ['No memory card (8MB) in MEMORY CARD slot 1,', "so you can't save!", 'Keep playing anyway?'], 293, 19, 148, 197, (31, 69, 104), 141, 212),
    ]),
    (0x291ba50, 0x2932030, [
        ((8, 15, 331, 89), ['The memory card (8MB) in MEMORY CARD slot 1', "isn't formatted! Format it now?"], 34, 19, 135, 189, (36, 64, 109), 145, 210),
        ((11, 143, 330, 261), ['Formatting the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 165, 19, 135, 219, (36, 64, 109), 145, 228),
        ((20, 310, 320, 362), ['No memory card (8MB)', 'in MEMORY CARD slot 1!'], 318, 19, 148, 189, (36, 64, 109), 158, 219),
    ]),
    (0x2932030, 0x294a0a0, [
        ((8, 15, 331, 89), ['The memory card (8MB) in MEMORY CARD slot 1', "isn't formatted! Format it now?"], 34, 19, 133, 185, (40, 66, 108), 143, 211),
        ((11, 143, 330, 261), ['Formatting the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 165, 19, 133, 207, (38, 64, 107), 143, 228),
        ((8, 299, 331, 384), ['The memory card (8MB) in MEMORY CARD slot 1', 'is out of space! Saving needs 155KB or more!'], 322, 19, 143, 185, (40, 66, 108), 153, 218),
    ]),
    (0x294a0a0, 0x2962300, [
        ((8, 31, 331, 100), ['The memory card (8MB) in MEMORY CARD slot 1', 'already has save data! Overwrite it?'], 47, 19, 142, 209, (41, 67, 109), 152, 222),
        ((53, 165, 288, 234), ['Create save data on the memory card (8MB)', 'in MEMORY CARD slot 1?'], 181, 19, 142, 192, (41, 67, 109), 152, 221),
        ((8, 299, 331, 395), ['Saving to the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 309, 19, 142, 209, (41, 67, 109), 152, 228),
    ]),
    (0x2962300, 0x2976830, [
        ((131, 31, 208, 83), ['Save complete!'], 47, 20, 137, 185, (40, 66, 109), 147, 192),
        ((24, 165, 317, 234), ['Save to the memory card (8MB)', 'in MEMORY CARD slot 1?'], 181, 19, 137, 199, (40, 66, 109), 147, 225),
        ((20, 277, 321, 395), ['Checking the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 299, 19, 133, 199, (40, 66, 109), 143, 225),
    ]),
    (0x2976830, 0x298c2d0, [
        ((27, 42, 313, 94), ["Couldn't check the memory card (8MB)", 'in MEMORY CARD slot 1!'], 50, 19, 148, 216, (42, 4, 35), 158, 221),
        ((21, 165, 321, 234), ['Load from the memory card (8MB)', 'in MEMORY CARD slot 1?'], 181, 19, 142, 216, (17, 36, 89), 152, 224),
        ((8, 299, 331, 395), ['Loading from the memory card (8MB) in', "MEMORY CARD slot 1! Don't turn off or reset", 'the "PlayStation 2" or remove the memory', 'card (8MB) or the controllers!'], 309, 19, 142, 216, (17, 36, 89), 152, 222),
    ]),
    (0x298c2d0, 0x2998800, [
        ((132, 31, 207, 83), ['Load complete!'], 47, 20, 141, 185, (18, 37, 90), 151, 191),
        ((8, 165, 331, 233), ['No save data on the memory card (8MB)', 'in MEMORY CARD slot 1!'], 179, 19, 141, 185, (20, 39, 92), 151, 220),
    ]),
]

SAVE_LOAD = [dict(name="saveload-%x" % fo, file="IMAGE.DAT", fo=fo, slot_end=se,
                  edits=[e for pnl in panels for e in _panel(*pnl)])
             for fo, se, panels in _SAVE_LOAD]

# ---------------------------------------------------------------- Option art on 0x457660
# Block 0x1a (0x433000, layout table @0x433020) tex1 also carries Option-menu sprites
# (rects = layout-table entries). They are crops of the Option background with the
# glyphs baked in, so each one gets: the Japanese removed (white fill + dark outline,
# inpainted from inside the sprite only), then the English drawn in the sprite's own
# style. Two styles: BRIGHT (selected: navy outline) and DIM (unselected: teal outline).
_OB_FILL, _OB_OUT = (244, 238, 234), (21, 39, 92)       # bright
_OD_FILL, _OD_OUT = (244, 238, 234), (25, 123, 112)     # dim


def _orm(rect, drk):
    # (bg="rows" was tried: it leaves Japanese stroke residue on these textured plates)
    return dict(clip=rect, bg="outlined", wht=150, drk=drk, reach=4, dil=2, local=True)


def _otx(rect, txt, ty0, fs, fill, out, align="c", margin=2):
    return dict(clip=rect, lines=[txt], ty0=ty0, lh=24, fs=fs, align=align, fill=fill,
                outline=out, sw=2, squeeze=True, margin=margin, bold=1,
                bg="flat", hat=255, kk=3, dil=0)


def _ospr(rect, txt, ty0, fs, bright=True, align="c", margin=2):
    st = (_OB_FILL, _OB_OUT, 100) if bright else (_OD_FILL, _OD_OUT, 125)
    # second pass: leftover very dark outline (navy / dark olive, lum < 80) the first
    # mask missed (glyph bottoms away from any white) is inpainted too
    left = dict(clip=rect, bg="inpaint", hat=0, wht=999, drk=80, dil=1)
    return [_orm(rect, st[2]), left, _otx(rect, txt, ty0, fs, st[0], st[1], align, margin)]


OPTION_HL = []
# Help lines (one per Option row; navy, left-aligned like the Japanese).
for _r, _t in [((340, 152, 498, 178), "Check the rankings!"),          # ランキング情報が見られるよ!
               ((340, 178, 484, 204), "Vibration on or off!"),          # 振動のありなしが選べるよ!
               ((340, 256, 458, 282), "Leave the Options!"),            # Optionを終了するよ!
               ((340, 334, 434, 360), "Pick the BGM!"),                 # BGMが選べるよ!
               ((0, 404, 248, 430), "Special balls on or off in Normal Mode!"),
               ((248, 404, 480, 430), "Set Stereo/Monaural and the voice!"),
               ((0, 430, 224, 456), "Change the ball speed in Normal Mode!"),
               ((224, 430, 426, 456), "Put the Options back to default!"),
               ((0, 456, 194, 482), "Change the controller buttons!")]:
    OPTION_HL += _ospr(_r, _t, _r[1] + 2, 17, align="l", margin=3)
# Highlighted Ball Cancel heads, twins of the heads baked into the Option background
# (0x433a50, options_menus.BALLS). Mask correlation puts these sprites at bg (256,133)
# / (323,133) / (391,133); the twin English is drawn at ty0 138 with fs 14 / 16 / 14
# (pntexnat's auto-fit of "Good ball" / "Bad ball" / "Eater ball" in a 64 px clip), so
# the same fs and baseline here: ty0 = sprite top + 5. The twin words are 61-63 px wide
# but these sprites are only 50-52, so the word is squeezed to the sprite width (same
# height, centre within 2 px of the twin's).
OPTION_HL += _ospr((458, 256, 510, 282), "Good ball", 256 + 5, 14, margin=2)
OPTION_HL += _ospr((370, 456, 420, 482), "Bad ball", 456 + 5, 16, margin=2)
OPTION_HL += _ospr((420, 456, 470, 482), "Eater ball", 456 + 5, 14, margin=2)
# BGM value plates. ROSE (dim, 176x26) is the twin of options_menus' ROSE_OPT (178x28 @
# (0,482), fs 17, squeezed to 174 px from x+2, ty0 = top+3); correlation puts this sprite
# at (+1, 0) inside it, so: text from sprite x+1 (margin 2 -> 174 px), ty0 = top+3.
OPTION_HL += _ospr((194, 456, 370, 482), "ROSE ~Lover, Be Dyed in Rose~", 456 + 3, 17,
                   bright=False, margin=2)
# ジャージメン 愛のテーマ dim (340,204) / bright (340,230): same placement in both.
OPTION_HL += _ospr((340, 204, 464, 230), "Jersey Men: Theme of Love", 204 + 3, 17,
                   bright=False, margin=2)
OPTION_HL += _ospr((340, 230, 464, 256), "Jersey Men: Theme of Love", 230 + 3, 17, margin=2)
# ランダム dim (426,430, 56 wide) / bright (0,482, 50 wide): centred in each.
OPTION_HL += _ospr((426, 430, 482, 456), "Random", 430 + 3, 17, bright=False, margin=2)
OPTION_HL += _ospr((0, 482, 50, 508), "Random", 482 + 3, 17, margin=2)

# セーブ失敗! label (62x26), same style as online_ui's "Save failed!" plates
OPTION_HL.append(dict(clip=(414, 360, 476, 386), lines=["Save failed!"], ty0=360 + 2, lh=20,
                      fs=15, align="c", fill=(253, 220, 251), outline=(51, 0, 39), sw=2,
                      squeeze=True, margin=4, bg="outlined", wht=50, drk=140, reach=4,
                      dil=2, local=True))

for _s in SAVE_LOAD:
    if _s["fo"] == 0x457660:
        _s["edits"] = _s["edits"] + OPTION_HL

# tex @0x2899a40: byte-identical dialog area to BBUNIT_SAVE (0x4d110)
BBUNIT_SAVE_2 = dict(BBUNIT_SAVE, name="bbunit-save-2", fo=0x2899a40, slot_end=0x28ac5e0)


# Software keyboard sheet tex @0x6ae6e0: canned chat phrases (same English as the
# ELF chat table), the side key labels and the kana-mode tabs. The kana keys
# themselves are input characters and stay Japanese.
_FK, _OK = (253, 253, 253), (85, 138, 191)
KEYBOARD = dict(name="keyboard", file="IMAGE.DAT", fo=0x6ae6e0, slot_end=0x6b8ee0, edits=[
    *[dict(_tile((4, y, 236, y + 24), t, _FK, _OK, fs=16, dy=3), sw=1)
      for y, t in [(377, "Thanks for the game!"), (401, "I'll make a room."),
                   (425, "Away for a bit."), (449, "I'll stop soon."), (473, "Thank you!")]],
    *[dict(_tile((448, y, 500, y + 24), t, _FK, _OK, fs=12, dy=5, align="c"), sw=1)
      for y, t in [(326, "Convert"), (350, "OK"), (374, "Send"), (398, "Back")]],
    dict(_tile((264, 352, 352, 376), "Hiragana", _FK, _OK, fs=14, dy=3, align="c"), sw=1),
    dict(_tile((360, 352, 436, 376), "Katakana", _FK, _OK, fs=14, dy=3, align="c"), sw=1),
])


# ---------------------------------------------------------------- sprite fit
# Sprite rects (layout tables, sub-stream 0 of each block) for the tile sheets whose
# hand-made clips were off by 1-2 px or a few px too wide. A clip that reached past its
# sprite wiped the edge rows of the NEIGHBOUR sprite (seen in game: the room screen's
# highlighted READY (448,494,506,512) lost the tops of its letters to the Okinawa /
# prefecture row clip (432,476,504,496); the real cells there are 474-494).
# Only sprites that some clip touches are listed. _fit() moves every clip onto the
# sprite it belongs to:
#   * same size as the sprite: the clip becomes the sprite and the text moves with it
#     (ty0 shifted by the same dy), so every cell keeps one sprite-relative placement;
#   * within 4 px of the sprite's size: the clip becomes the sprite, the text stays
#     where it was tuned (it is centred / left-aligned inside the new clip);
#   * otherwise: the clip is cut down to its part inside the sprite;
#   * an erase-only edit that spans several sprites is split into one edit per sprite
#     it covers (>= half of that sprite), each cut to the sprite.
_SPRITES = {
    "lobby-tiles-c": [(0, 0, 332, 40), (0, 40, 72, 60), (0, 60, 72, 80), (0, 80, 72, 100), (0, 100, 448, 114), (0, 114, 448, 128), (0, 128, 448, 142), (0, 142, 448, 156), (72, 40, 144, 60), (72, 60, 144, 80), (72, 80, 144, 100), (144, 40, 216, 60), (144, 60, 216, 80), (144, 80, 216, 100), (216, 40, 288, 60), (216, 60, 288, 80), (288, 40, 360, 60), (288, 60, 360, 80), (332, 0, 404, 20), (332, 20, 404, 40), (360, 40, 432, 60), (360, 60, 432, 80), (404, 0, 476, 20), (404, 20, 476, 40), (432, 40, 504, 60), (432, 60, 504, 80)],
    "lobby-list": [(0, 452, 332, 492), (0, 492, 72, 512), (72, 492, 144, 512), (144, 492, 216, 512), (216, 492, 288, 512), (288, 492, 360, 512), (332, 44, 464, 74), (332, 88, 464, 118), (332, 368, 404, 388), (332, 388, 404, 408), (332, 408, 404, 428), (332, 428, 404, 448), (332, 448, 404, 468), (332, 468, 404, 488), (360, 488, 432, 508), (404, 368, 476, 388), (404, 388, 476, 408), (404, 408, 476, 428), (404, 428, 476, 448), (404, 448, 476, 468), (404, 468, 476, 488), (432, 488, 504, 508), (450, 0, 488, 20), (450, 20, 488, 40), (462, 128, 500, 148), (462, 148, 500, 168), (462, 168, 500, 188), (462, 188, 500, 208), (462, 208, 500, 228), (462, 228, 500, 248), (462, 248, 500, 268), (462, 268, 500, 288), (462, 288, 500, 308), (462, 308, 500, 328), (462, 328, 500, 348), (462, 348, 500, 368), (464, 40, 502, 60), (464, 88, 502, 108), (464, 108, 502, 128), (488, 0, 498, 14), (488, 14, 496, 28)],
    "lobby-frame-2": [(0, 492, 72, 512), (72, 492, 144, 512), (144, 492, 216, 512), (216, 492, 288, 512), (288, 492, 360, 512), (360, 488, 432, 508), (432, 488, 504, 508), (450, 448, 488, 468), (450, 468, 488, 488)],
    "lobby-list-beginner": [(332, 200, 404, 220), (332, 220, 462, 246), (332, 246, 404, 266), (332, 266, 462, 292), (332, 346, 404, 366), (332, 366, 404, 386), (332, 386, 404, 406), (332, 406, 404, 426), (332, 426, 404, 446), (332, 446, 404, 466), (332, 466, 404, 486), (332, 486, 404, 506), (340, 0, 472, 30), (340, 30, 472, 60), (340, 60, 470, 90), (340, 90, 470, 120), (404, 200, 476, 220), (404, 246, 476, 266), (404, 346, 476, 366), (404, 366, 476, 386), (404, 386, 476, 406), (404, 406, 476, 426), (404, 426, 476, 446), (404, 446, 476, 466), (404, 466, 476, 486), (404, 486, 476, 506), (462, 134, 500, 154), (462, 154, 500, 174), (462, 174, 500, 194), (462, 220, 500, 240), (462, 266, 500, 286), (462, 286, 500, 306), (462, 306, 500, 326), (462, 326, 500, 346), (470, 60, 508, 80), (470, 80, 508, 100), (470, 100, 508, 120), (472, 0, 510, 20), (472, 20, 510, 40), (472, 40, 510, 60), (476, 194, 508, 212)],
    "lobby-list-2": [(0, 200, 448, 214), (0, 214, 448, 228), (0, 228, 448, 242), (0, 242, 448, 256), (332, 0, 404, 20), (332, 20, 404, 40), (332, 40, 404, 60), (332, 60, 404, 80), (332, 80, 404, 100), (332, 100, 404, 120), (332, 120, 404, 140), (404, 0, 476, 20), (404, 20, 476, 40), (404, 40, 476, 60), (404, 60, 476, 80), (404, 80, 476, 100), (404, 100, 476, 120), (404, 120, 442, 140)],
    "room-msgs": [(0, 414, 180, 436), (0, 436, 72, 456), (0, 456, 72, 476), (0, 476, 72, 496), (0, 496, 448, 510), (72, 436, 144, 456), (72, 456, 144, 476), (72, 476, 144, 496), (144, 436, 216, 456), (144, 456, 216, 476), (144, 476, 216, 496), (148, 394, 220, 414), (180, 414, 252, 434), (216, 434, 288, 454), (216, 454, 288, 474), (216, 474, 288, 494), (220, 394, 292, 414), (252, 414, 324, 434), (288, 434, 360, 454), (288, 454, 360, 474), (288, 474, 360, 494), (292, 394, 364, 414), (324, 414, 396, 434), (360, 434, 432, 454), (360, 454, 432, 474), (360, 474, 432, 494), (364, 394, 436, 414), (396, 414, 468, 434), (420, 62, 492, 82), (420, 82, 492, 102), (420, 102, 492, 122), (420, 122, 492, 142), (420, 142, 492, 162), (420, 162, 492, 182), (420, 182, 492, 202), (420, 202, 492, 222), (420, 222, 492, 242), (432, 434, 504, 454), (432, 454, 504, 474), (432, 474, 504, 494), (436, 394, 508, 414), (448, 494, 506, 512), (468, 414, 506, 434)],
    "room-help": [(0, 0, 72, 20), (0, 20, 72, 40), (0, 40, 38, 60), (0, 60, 448, 74), (0, 74, 448, 88), (0, 88, 448, 102), (0, 102, 410, 116), (0, 116, 410, 130), (38, 40, 76, 60), (72, 0, 144, 20), (72, 20, 110, 40), (76, 40, 114, 60), (110, 20, 148, 40), (114, 40, 152, 60), (144, 0, 216, 20), (148, 20, 186, 40), (152, 40, 190, 60), (186, 20, 224, 40), (190, 40, 228, 60), (216, 0, 288, 20), (224, 20, 262, 40), (228, 40, 310, 54), (262, 20, 300, 40), (288, 0, 360, 20), (300, 20, 338, 40), (338, 20, 376, 40), (360, 0, 432, 20), (376, 20, 414, 40), (414, 20, 452, 40), (432, 0, 504, 20), (452, 20, 490, 40)],
    "keyboard": [(0, 376, 440, 400), (0, 400, 440, 424), (0, 424, 440, 448), (0, 448, 440, 472), (0, 472, 440, 496), (264, 350, 352, 374), (352, 350, 440, 374), (440, 324, 506, 348), (440, 348, 506, 372), (440, 372, 506, 396), (440, 396, 506, 420), (440, 420, 462, 444), (462, 420, 484, 444), (484, 420, 506, 444)],
}


def _ix(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def _fit(edits, sprites):
    out = []
    for e in edits:
        c = tuple(e["clip"])
        if any(_ix(c, r) == c for r in sprites):
            out.append(e); continue
        hits = [r for r in sprites if _area(_ix(c, r))]
        if not hits:
            out.append(e); continue
        if not e.get("lines") and len(hits) > 1:
            for r in hits:
                if 2 * _area(_ix(c, r)) >= _area(r):
                    out.append(dict(e, clip=_ix(c, r)))
            continue
        best = max(hits, key=lambda r: _area(_ix(c, r)))
        cw, ch, bw, bh = c[2] - c[0], c[3] - c[1], best[2] - best[0], best[3] - best[1]
        e = dict(e)
        if (cw, ch) == (bw, bh):
            if "ty0" in e:
                e["ty0"] += best[1] - c[1]
            e["clip"] = best
        elif abs(cw - bw) <= 4 and abs(ch - bh) <= 4:
            e["clip"] = best
        else:
            e["clip"] = _ix(c, best)
        out.append(e)
    return out


SCREENS = [BBUNIT_SAVE, HANDICAP, ROOM_CREATE, ROOM_VIEW, AUTOLOAD, AUTOLOAD_TITLE, INSTALL_SPACE, LOBBY_TILES_C,
           LOBBY_A, LOBBY_B, LOBBY_D, LOBBY_E, LOBBY_F, LOBBY_G,
           dict(name="room-msgs", file="IMAGE.DAT", fo=0x3d38e0, slot_end=0x3f4ef0, edits=ROOM_TILES),
           ROOM_HELP, BBUNIT_SAVE_2, KEYBOARD, *SAVE_LOAD]
SCREENS = [dict(s, edits=_fit(s["edits"], _SPRITES[s["name"]])) if s["name"] in _SPRITES else s
           for s in SCREENS]
# DATA_UPDATE_PROGRESS (0x386940) is left out: login_account.py also defines that
# sheet (data-updating); add it here instead if this version is preferred.
