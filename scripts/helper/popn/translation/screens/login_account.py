"""Login / account / registration / disc-check texture screens (natural editor).

Replaces the converted built-ins for these sheets with tight, per-element clips
and the right removal mode for each element (see README.md in this folder).
"""


def _rows(clip, lines, ty0, lh=22, fs=15, **kw):
    """Text on a panel whose background only varies top to bottom (gradient +
    horizontal stripes): masked pixels copy the nearest clean index in the same
    row, so the gradient and stripes continue exactly."""
    d = dict(clip=clip, lines=lines, ty0=ty0, lh=lh, fs=fs, bg="rows",
             fill=250, outline=28, sw=2, wht=215, drk=90, dil=4)
    d.update(kw)
    return d


def _out(clip, lines, ty0, lh=22, fs=15, **kw):
    """White letters with a dark outline on a busy plate/gradient panel."""
    d = dict(clip=clip, lines=lines, ty0=ty0, lh=lh, fs=fs, bg="outlined",
             fill=250, outline=28, sw=2, wht=200, drk=90, reach=2, dil=1)
    d.update(kw)
    return d


def _wipe(clip, dil=30, wht=215, **kw):
    """Erase-only: remove a whole text block from a panel whose rows are uniform
    (vertical gradient + horizontal stripes). The mask is the white letter fill
    grown by `dil` px, so with a clip that starts at the text's left edge every
    masked pixel copies the clean row colour from the right side of the clip."""
    d = dict(clip=clip, bg="rows", wht=wht, drk=90, dil=dil)
    d.update(kw)
    return d


def _txt(clip, lines, ty0, lh=22, fs=15, **kw):
    """Draw-only (after a _wipe/erase): no glyph mask, just the English text in
    the game's white-fill + dark-outline style, centred in `clip`."""
    d = dict(clip=clip, lines=lines, ty0=ty0, lh=lh, fs=fs, bg="flat",
             hat=255, wht=256, drk=-1, dil=0, fill=250, outline=28, sw=2)
    d.update(kw)
    return d


def _btn(clip, txt, fs, **kw):
    """Button label: white letters with a dark outline on the button plate."""
    d = dict(clip=clip, lines=[txt], ty0=clip[1] + 2, lh=20, fs=fs, bg="outlined",
             fill=250, outline=28, sw=2, wht=200, drk=90, reach=2, dil=1)
    d.update(kw)
    return d


def _pair(clip, step, inner=None):
    """Erase the labels of two IDENTICAL button plates at once. `clip` spans both
    plates; `step` = (dx, dy) from one plate to the other. Each label pixel copies
    the ORIGINAL index at the same spot on the other plate (exact plate, stripes
    and gradient included); pixels that are label on both plates fall back to the
    nearest clean pixel in the row. A second, tight 'outlined' pass then inpaints
    the few outline crumbs the first mask missed (the JP fill is pale yellow, not
    white, so its outer outline can sit beyond the mask)."""
    x0, y0, x1, y1 = clip
    return [dict(clip=clip, bg="rows", dir=step, wht=212, drk=120, dil=3),
            dict(clip=inner or (x0 + 1, y0 + 1, x1 - 1, y1 - 1), bg="outlined",
                 wht=150, drk=90, reach=3, dil=1)]


def _whiteout(block):
    """Paint a rectangle pure white (threshold mask, every pixel). Used as a
    placeholder mask for a following bg="rows" pass, which rewrites every white
    pixel with an ORIGINAL plate index; nothing white survives."""
    return dict(clip=block, bg=255, hat=0, wht=-1, drk=-1, dil=0)


def _diag(block, plate, step=(3, -1), inner=None):
    """Rebuild a striped button plate under its label: `block` (the label's
    bbox) is whited out, then each pixel copies the original plate pixel found by
    walking along the stripe direction `step` (both ways) to the first pixel
    outside the block inside `plate`. Stripes continue exactly.
    v4 (splotch probe): `inner` = (first, end) row of the plate's striped
    interior. The stripe walk is confined to it; the highlight / bottom border /
    dotted rows of `plate` outside it are refilled along their own row (2-px step,
    keeps a dotted row's phase), so no stripe colour is dragged into the border."""
    if inner is None:
        return [_whiteout(block), dict(clip=plate, bg="rows", dir=step, wht=250, drk=-1, dil=0)]
    x0, y0, x1, y1 = plate
    iy0, iy1 = max(y0, inner[0]), min(y1, inner[1])
    out = [_whiteout(block), dict(clip=(x0, iy0, x1, iy1), bg="rows", dir=step, wht=250, drk=-1, dil=0)]
    if y0 < iy0:
        out.append(dict(clip=(x0, y0, x1, iy0), bg="rows", dir=(2, 0), wht=250, drk=-1, dil=0))
    if iy1 < y1:
        out.append(dict(clip=(x0, iy1, x1, y1), bg="rows", dir=(2, 0), wht=250, drk=-1, dil=0))
    return out


def _reseam(block, xl, xr, seam, inner=None):
    """Two-tone plate (flat left colour, diagonal edge, flat right colour): whited
    `block` rows are refilled from the left source column for x < seam(y) and
    from the right source column for x >= seam(y), so the plate's diagonal colour
    edge is continued straight through where the label was.
    v4 (splotch probe): `inner` = (first, end) row of the plate interior. Only those
    rows are two-tone; the top highlight and bottom border rows have their own
    colours and edge, and the seam copy painted the interior red/green into them.
    They are now refilled along their own row (lerp, mapped to the band's own
    unmasked indices so the palette animation still covers them)."""
    x0, y0, x1, y1 = block
    out = [_whiteout(block)]
    if inner is not None:
        iy0, iy1 = inner
        if y0 < iy0:
            out.append(dict(clip=(xl, y0, xr, iy0), bg="lerp", local="ring", wht=254, drk=-1, dil=0))
        if iy1 < y1:
            out.append(dict(clip=(xl, iy1, xr, y1), bg="lerp", local="ring", wht=254, drk=-1, dil=0))
        y0, y1 = max(y0, iy0), min(y1, iy1)
    for y in range(y0, y1):
        sx = max(x0, min(x1, int(round(seam(y)))))
        if sx > x0:
            out.append(dict(clip=(xl, y, sx, y + 1), bg="rows", wht=250, drk=-1, dil=0))
        if sx < x1:
            out.append(dict(clip=(sx, y, xr, y + 1), bg="rows", wht=250, drk=-1, dil=0))
    return out


def _plabel(ox, oy, txt, fs=12, w=90):
    """Label on a small button sprite whose top-left is (ox, oy). Clip, font
    size and baseline are all relative to the sprite, so a normal sprite and its
    highlighted twin (same JP offset) get the English at the identical offset."""
    return _txt((ox + 2, oy + 1, ox + w - 2, oy + 21), [txt], oy + 4, fs=fs,
                outline=(46, 23, 5))


def _msg(clip, txt, fs=13, **kw):
    """Left-aligned text strip on a flat key colour (salmon/green message strips)."""
    d = dict(clip=clip, lines=[txt], ty0=clip[1] + 1, lh=20, fs=fs, bg="key",
             align="l", fill=250, outline=28, sw=2, wht=190, dil=5)
    d.update(kw)
    return d


def _wipe_lines(bands, x1, dil=30, **kw):
    """One _wipe per JP text line: band = (x0, y0, y1) with x0 at the line's own
    left outline edge, so the left walk of the row copy leaves the clip at once
    and every pixel copies the clean row colour from the right."""
    return [_wipe((bx0, by0, x1, by1), dil=dil, **kw) for bx0, by0, by1 in bands]


# Disc-check dialogs: three pink panels (x 0..336), white text with a thick
# magenta/purple 3D outline, centred on x=170. Rows are uniform right of the
# bubbles (x>=80), so each JP line is wiped from its own left edge rightwards.
DISC_CHECK = dict(name="disc-check", file="IMAGE.DAT", fo=0x1ffa90, slot_end=0x213b50, edits=(
    _wipe_lines([(126, 30, 58), (97, 54, 81), (74, 76, 106)], 322)
    + [_txt((66, 28, 274, 112), ["Wrong disc!", "Please insert the correct disc!",
                                 "Press X to start the disc check!"], 36, lh=22, fs=15)]
    + _wipe_lines([(90, 175, 202), (73, 198, 228)], 322)
    + [_txt((66, 160, 274, 246), ["The disc is still in!",
                                  "Take out the disc and press X!"], 181, lh=22, fs=15)]
    + _wipe_lines([(93, 299, 325), (97, 321, 347), (74, 343, 372)], 322)
    + [_txt((66, 292, 274, 382), ["No disc inserted!", "Please insert the correct disc!",
                                  "Press X to start the disc check!"], 303, lh=22, fs=15)]
    # account footer: white text on a flat green strip (index 127), x 0..264
    + [_msg((0, 402, 264, 440), "", fs=14, lines=["Let's make an account!",
                                                   "First time? Register here!"], lh=19)]
))

# HELP-line message sprites + login buttons (tex @0x1e0a40). The right-hand and
# bottom strips are the built-in HELP_MSGS edits (salmon key index 106). Added:
# the three green disc-check dialogs on the left (x 0..336), pale-yellow text
# with a dark brown outline on a row-uniform gradient (bubbles at x<90).
HELP_MSGS = dict(name="help-msgs", file="IMAGE.DAT", fo=0x1e0a40, slot_end=0x1ffa90, edits=(
    # v4 (splotch probe, OUTSIDE rows + live test "cut-in text on the highlighted
    # Connect"): every strip clip is now inside its own sprite rect from the block
    # layout table (sub-stream 0 of block 0x1cc800, tex 1). The old clips ran 1-4 px
    # past several strips; "Connecting to the server!" started at y 249, which is the
    # bottom row of the highlighted Password sprite (340,226,430,250), and the key
    # refill punched salmon (hidden at draw time = holes) into that plate's border.
    [_msg((345, 30, 506, 50), "Initializing Ethernet!"),     # sprite (340,26,506,50)
     _msg((345, 54, 500, 73), "Checking for updates!"),      # (340,50,500,74)
     _msg((345, 78, 488, 98), "Verifying pop'n ID!"),        # (340,74,488,98)
     _msg((345, 101, 470, 122), "Talking to the server!"),   # (340,98,470,122)
     _msg((345, 133, 464, 153), "Checking DNAS!"),           # (340,130,464,154)
     _msg((345, 157, 430, 175), "Saved!"),                   # (340,154,430,178)
     _msg((345, 181, 430, 199), "Save failed!"),             # (340,178,430,202)
     _msg((340, 250, 484, 268), "Connecting to the server!", ty0=250),  # (340,250,484,268); サ/メ reach x 340
     _msg((340, 316, 452, 334), "Back to the menu!", ty0=316),          # (340,316,452,334)
     _msg((1, 403, 166, 420), "Enter your pop'n ID!"),                 # (0,402,312,440)
     _msg((1, 421, 312, 439), "First time? Register on the sign-up screen!"),
     _msg((1, 440, 157, 457), "Enter your password!"),                 # (0,440,312,478)
     _msg((1, 458, 312, 476), "First time? Register on the sign-up screen!"),
     _msg((1, 478, 236, 495), "Enter your pop'n ID and password!", ty0=478),  # (0,478,236,496)
     _msg((323, 405, 504, 426), "Logging in to the play server!"),     # (312,402,504,426)
     _msg((323, 429, 502, 450), "Accessing the gate server!"),         # (312,426,502,450)
     _msg((323, 452, 502, 472), "Logging in to the gate server!")]     # (312,450,502,474)
    # the four small RED buttons are the highlighted versions of the login-main
    # buttons (sprites at x 340..429, tops 202/226/268/292). The plate stripes
    # run along (3, -1); each label is rebuilt along the stripes, and the
    # English sits at the same sprite-relative offset as on login-main.
    # red plate rows: border top+0..3, stripes top+4..top+18, dotted/dark top+19..
    + _diag((358, 206, 412, 222), (343, 206, 426, 222), inner=(206, 221))
    + _diag((358, 230, 411, 246), (343, 230, 426, 246), inner=(230, 245))
    + _diag((372, 272, 399, 289), (343, 272, 426, 289), inner=(272, 287))
    + _diag((358, 296, 411, 312), (343, 296, 426, 312), inner=(296, 311))
    + [_plabel(340, 202, "pop'n ID"), _plabel(340, 226, "Password"),
       _plabel(340, 268, "Connect"), _plabel(340, 292, "Cancel")]
    + _wipe_lines([(116, 32, 58), (98, 55, 80), (75, 77, 104)], 322, wht=225)
    + [_txt((66, 28, 274, 112), ["Let's check the disc!", "Please insert the correct disc!",
                                 "Press X to start the disc check!"], 36, lh=22, fs=15)]
    + _wipe_lines([(124, 186, 216)], 322, wht=225)
    + [_txt((66, 180, 274, 222), ["Checking the disc!"], 190, fs=15)]
    + _wipe_lines([(95, 309, 337), (72, 333, 362)], 322, wht=225)
    + [_txt((66, 300, 274, 368), ["Correct disc confirmed!",
                                  "Take out the disc and press X!"], 314, lh=22, fs=15)]
))

# ID/password ISSUED screen (tex @0x2b1100): shown after sign-up with the new
# ID and password filled in. Title plate and the grey "press O" band are
# row-uniform; the field labels sit on a bubbly translucent panel; the footer is
# white text on a flat green strip (index 105).
LOGIN = dict(name="login", file="IMAGE.DAT", fo=0x2b1100, slot_end=0x2c4e40, edits=[
    _wipe((36, 86, 227, 118), dil=12, wht=200, drk=130),
    _txt((36, 86, 227, 118), ["Your ID & Password"], 92, fs=17, outline=(20, 70, 30)),
    # field labels on the bubbly translucent panel: morphology mask + inpaint
    dict(clip=(126, 147, 188, 168), bg="inpaint", hat=30, kk=15, dil=2,
         lines=["pop'n ID"], ty0=150, lh=20, fs=12, fill=250, outline=(20, 70, 30), sw=2),
    dict(clip=(126, 174, 188, 196), bg="inpaint", hat=30, kk=15, dil=2,
         lines=["Password"], ty0=177, lh=20, fs=12, fill=250, outline=(20, 70, 30), sw=2),
    _wipe((196, 219, 330, 244), dil=8, wht=200),
    _txt((196, 219, 330, 244), ["Press the X button!"], 223, fs=14),
    _msg((0, 448, 426, 510), "", fs=14, lh=19, ty0=451, lines=[
        "Your ID and password are ready! Don't forget them!",
        "IDs and passwords never use o, O (oh), i, I (eye)",
        "or l, L (el), so watch out!"], dil=7, wht=160),
])

def _blue(clip, txt, ty0, fs, align="l"):
    """Blue letters with a grey outline on the plain white sheet: the glyphs are
    found by morphology and refilled with the page's own white index."""
    return dict(clip=clip, lines=[txt], ty0=ty0, lh=24, fs=fs, align=align,
                bg="flat", hat=20, kk=21, dil=2,
                fill=(0, 142, 231), outline=(109, 109, 109), sw=1)


# Communication-error page (tex @0x1b40a0): white page; the old slot_end is kept
# because a small non-texture block lives in the zero gap before 0x1be050.
COMM_ERROR = dict(name="comm-error", file="IMAGE.DAT", fo=0x1b40a0, slot_end=0x1bd9c0, edits=[
    _blue((20, 58, 200, 94), "Connection error!", 63, 20),
    _blue((20, 444, 328, 472), "Sending data! Just a moment!", 448, 17),
    _blue((330, 444, 506, 472), "Press the X button!", 448, 17),
])

_DKG = (20, 70, 30)   # dark green outline used on the green Online screens


def _inp(clip, lines, ty0, fs, lh=20, **kw):
    """Text on a soft patterned panel (translucent bubbles): morphology mask +
    inpaint, then white letters with a dark green outline."""
    d = dict(clip=clip, lines=lines, ty0=ty0, lh=lh, fs=fs, bg="inpaint",
             hat=30, kk=15, dil=2, fill=250, outline=_DKG, sw=2)
    d.update(kw)
    return d


def _pairbtn(clip, step, labels, fs=13, ty=None):
    """_pair() for two identical side-by-side/stacked button plates plus their
    new labels: labels = [(label_clip, text), ...]."""
    x0, y0, x1, y1 = clip
    out = [dict(clip=clip, bg="rows", dir=step, wht=230, drk=130, dil=4),
           dict(clip=(x0 + 5, y0 + 2, x1 - 5, y1 - 3), bg="outlined",
                wht=150, drk=90, reach=3, dil=1)]
    for lc, t in labels:
        out.append(_txt(lc, [t], lc[1] + 2 if ty is None else ty, fs=fs, outline=(46, 23, 5)))
    return out


# Data-update prompt (tex @0x372970; old slot_end kept, see COMM_ERROR).
DATA_UPDATE = dict(name="data-update", file="IMAGE.DAT", fo=0x372970, slot_end=0x386210, edits=(
    [_wipe((36, 86, 149, 118), dil=11, wht=200, drk=130),
     _txt((36, 86, 149, 118), ["Data Update"], 93, fs=16, outline=_DKG),
     _inp((120, 144, 394, 186), ["The game has been updated!",
                                 "You can't play online without updating!"], 146, 14, lh=20),
     _wipe((224, 224, 310, 252), dil=10, wht=200, drk=130),
     _txt((206, 226, 306, 251), ["Update now?"], 230, fs=14, outline=_DKG)]
    + _pairbtn((153, 273, 359, 296), (116, 0),
               [((156, 274, 240, 294), "Update"), ((272, 274, 356, 294), "Cancel")])
))

# Data-update result dialogs (tex @0x39ab00): same green panels as the HELP
# disc dialogs. The long middle line starts inside the bubbles (x<90), so its
# left end is inpainted after the row wipe.
DATA_UPDATE_RESULT = dict(name="data-update-result", file="IMAGE.DAT", fo=0x39ab00,
                          slot_end=0x3a73a0, edits=(
    _wipe_lines([(142, 27, 55), (90, 54, 82), (98, 83, 109)], 322, wht=225)
    + [dict(clip=(42, 54, 94, 82), bg="inpaint", hat=30, kk=15, dil=2),
       _txt((40, 26, 300, 112), ["Update complete!",
                                 "The game will quit. Please turn it on again!",
                                 "Press X to quit!"], 32, lh=25, fs=15)]
    + _wipe_lines([(107, 176, 203), (119, 204, 230)], 322, wht=225)
    + [_txt((66, 172, 274, 236), ["Data update failed!", "Press the X button!"],
            181, lh=26, fs=15)]
))

def _title(x1, txt, fs=16, dil=11, y0=86):
    """Green title plate at (34, 84): row-uniform, text from x~50. `x1` = last
    clean plate column (the wipe copies the plate rows from the right end).
    `y0` must start below any all-white highlight row of the plate."""
    return [_wipe((36, y0, x1, 118), dil=dil, wht=200, drk=130),
            _txt((36, 86, x1, 118), [txt], 102 - fs // 2 - 2, fs=fs, outline=_DKG)]


_NEXT_CANCEL = lambda y0, a, b: _pairbtn((153, y0 + 1, 359, y0 + 24), (116, 0),
                                         [((156, y0 + 2, 240, y0 + 22), a),
                                          ((272, y0 + 2, 356, y0 + 22), b)])

# The registration sheets (0x2cac40 / 0x2dfcb0 / 0x2ed1b0 / 0x3006d0 / 0x307970 /
# 0x31c8e0) are owned by char_select.py.

# Manual contents menu (tex @0x5431f0; old slot_end kept). White text with a dark
# outline on the soft translucent panel -> inpaint, left-aligned like the JP.
# The page-header tabs at the bottom (y 448..494) sit on textured sprite rects
# and are not done here.
_MAN = [(222, 243, "Greeting"), (244, 265, "Online Notices"), (266, 288, "Network Setup"),
        (289, 309, "Controller"), (311, 332, "Getting Started"), (333, 355, "How to Play"),
        (356, 377, "User Support")]
_MOUT = (40, 30, 70)
MANUAL = dict(name="manual", file="IMAGE.DAT", fo=0x5431f0, slot_end=0x562e40, edits=(
    [_inp((150, 222, 234, 243), ["Contents"], 225, 14, outline=_MOUT, fill=(250, 248, 205))]
    + [_inp((238, y0, 404, y1), [t], y0 + 3, 14, align="l", outline=_MOUT, fill=(250, 248, 205))
       for y0, y1, t in _MAN]
))

# Live ID/password login screen (tex @0x1ccd20). Redone from the built-in: the
# title plate is row-wiped (no blotches), the two field plates and the
# Connect/Cancel plates are identical pairs (cross-copied), the long
# "Create an account" plates use a stronger outlined mask. DNAS trademark notice
# (y 448..482, wraps the DNAS logo) is still left as-is.
_LONG = dict(wht=170, drk=110, reach=3, dil=2)
LOGIN_MAIN = dict(name="login-main", file="IMAGE.DAT", fo=0x1ccd20, slot_end=0x1e0a40, edits=(
    _title(226, "Enter ID & Password", fs=16, dil=12, y0=88)
    # normal small buttons (highlighted twins are the red ones on HELP_MSGS):
    # labels rebuilt along the plate stripes, English at the shared offset
    # (interior rows stop above each plate's distinct bottom row)
    + _diag((130, 162, 184, 178), (115, 161, 199, 179), (4, -1), inner=(161, 178))
    + _diag((130, 190, 183, 206), (115, 189, 199, 207), (4, -1), inner=(189, 206))
    + _diag((185, 249, 211, 266), (156, 248, 240, 266), (4, -1), inner=(248, 265))
    + _diag((287, 249, 340, 265), (272, 248, 356, 266), (4, -1), inner=(248, 265))
    + [       _plabel(112, 158, "pop'n ID"), _plabel(112, 186, "Password")]
    + [_plabel(153, 245, "Connect"), _plabel(269, 245, "Cancel")]
    # "Create an account": normal plate at (153, 272), pressed (red) twin at
    # (69, 485). Both are two-tone with a diagonal edge (slope -3.8 px/row) under
    # the label; the edge is continued through, and the label offset is shared.
    # Blocks start 1 row under the plate top: the JP glyph tops reach that high.
    + _reseam((204, 273, 310, 293), 200, 313, lambda y: 276 - 3.8 * (y - 273), inner=(276, 293))
    + _reseam((101, 486, 226, 506), 98, 230, lambda y: 205 - 3.8 * (y - 489), inner=(489, 505))
    + [_txt((158, 274, 352, 294), ["Create an account"], 277, fs=13, outline=(46, 23, 5)),
       _txt((74, 487, 268, 507), ["Create an account"], 490, fs=13, outline=(46, 23, 5)),
       # v4 (splotch probe): these two float on the flat green backdrop; the
       # outlined inpaint left brown/olive blobs around the letters. The JP is now
       # refilled with the backdrop's own index (key mode) and the clips are the
       # sprite rects (428,448,504,472) / (274,486,466,510) from the layout table.
       dict(clip=(429, 449, 503, 471), lines=["Saving!"], ty0=451, lh=20, fs=13, bg="key",
            wht=190, dil=5, fill=250, outline=28, sw=2),
       dict(clip=(276, 487, 465, 510), lines=["Accessing play server!"], ty0=489, lh=20, fs=13,
            bg="key", wht=190, dil=5, fill=250, outline=28, sw=2)]
))

# Old-version notice (tex @0x1be050): white page like COMM_ERROR, grey-brown text.
_GREY = dict(fill=(127, 90, 106), outline=(102, 102, 102), sw=1)


def _page(clip, lines, ty0, fs=15, lh=22, **kw):
    d = dict(clip=clip, lines=lines, ty0=ty0, lh=lh, fs=fs, align="l", bg="flat",
             hat=20, kk=21, dil=2, **_GREY)
    d.update(kw)
    return d


VERSION_OLD = dict(name="version-old", file="IMAGE.DAT", fo=0x1be050, slot_end=0x1cc800, edits=[
    _page((20, 62, 480, 180), [
        "Your \"pop'n Taisen Puzzle-dama ONLINE\" is an old",
        "version, so it can't start!",
        "Get the new \"pop'n Taisen Puzzle-dama ONLINE\"",
        "from GAME CHANNEL, install it, and then",
        "start it again!"], 66, fs=17, lh=22),
    _page((20, 196, 300, 224), ["Press the X button!"], 200, fs=17),
])

# Terms of use frame (tex @0x223a00): title plate + Agree/Decline plates, plus
# the pressed (red) Agree/Decline tab sprites at the bottom. The prose pages
# themselves are separate sheets (0x2328d0..0x297240), not done.
_TERMS_STEP = (4, -1)
TERMS = dict(name="terms", file="IMAGE.DAT", fo=0x223a00, slot_end=0x2328d0, edits=(
    _title(136, "Terms of Use", fs=16, y0=87)
    # Agree/Decline: normal plates at (153, 376) / (269, 376) are identical
    # rebuilt along their stripes too; the pressed red tabs at (181, 448) / (272, 448) are
    # rebuilt along their stripes. Labels share sprite-relative offsets.
    # (striped interior rows: normal 380..396, pressed 452..467; v4 splotch probe)
    + _diag((175, 381, 221, 397), (156, 379, 240, 397), _TERMS_STEP, inner=(380, 397))
    + _diag((286, 381, 342, 397), (272, 379, 356, 397), _TERMS_STEP, inner=(380, 397))
    + _diag((203, 453, 250, 470), (184, 451, 268, 470), _TERMS_STEP, inner=(452, 468))
    + _diag((289, 453, 345, 470), (275, 451, 359, 470), _TERMS_STEP, inner=(452, 468))
    + [_plabel(153, 376, "Agree", 13), _plabel(269, 376, "Decline", 13),
       _plabel(181, 448, "Agree", 13), _plabel(272, 448, "Decline", 13)]
))

# "Issuing your ID and password" dialog (tex @0x2a8ae0): green HELP-style panel.
ID_ISSUING = dict(name="id-issuing", file="IMAGE.DAT", fo=0x2a8ae0, slot_end=0x2b1000, edits=(
    _wipe_lines([(90, 37, 65), (123, 65, 93)], 322, wht=225)
    + [_txt((66, 32, 274, 98), ["Issuing your ID and password!", "Just a moment!"],
            41, lh=26, fs=15)]
))

# Data-update progress screen (tex @0x386940).
_BOX = dict(bg="key", wht=190, dil=4, fill=250, outline=28, sw=2, lh=20)
DATA_UPDATING = dict(name="data-updating", file="IMAGE.DAT", fo=0x386940, slot_end=0x39ab00, edits=(
    _title(165, "Updating Data", fs=16, y0=87)
    + [_inp((190, 144, 322, 168), ["Just a moment!"], 147, 13),
       _inp((96, 178, 420, 235), ["Data may be damaged, so please don't turn",
                                  'off or reset the "PlayStation 2" or unplug',
                                  'the "PlayStation BB Unit"!'], 180, 12, lh=18),
       dict(clip=(224, 372, 266, 395), lines=["Now"], ty0=374, fs=14, **_BOX),
       dict(clip=(356, 372, 412, 395), lines=["Left ~"], ty0=374, fs=14, **_BOX),
       dict(clip=(436, 372, 470, 395), lines=["min"], ty0=374, fs=14, **_BOX)]
))

SCREENS = [DISC_CHECK, HELP_MSGS, LOGIN, COMM_ERROR, DATA_UPDATE, DATA_UPDATE_RESULT,
           MANUAL, LOGIN_MAIN, VERSION_OLD, TERMS, ID_ISSUING, DATA_UPDATING]
