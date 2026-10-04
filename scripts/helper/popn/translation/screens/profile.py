"""Character-select profiles + Attack Select commentary - IMAGE1.DAT texture edits.

Loaded by ../apply_textures_nat.py (see README.md). Located by re/RE-profile-text.md.

Two IMAGE1 blocks with 0x20-byte headers (pnimage.iter_blocks skips them; the offsets
below are absolute stream offsets, each one starts `a1 02 02 80` and inflates to a
normal 512x512 8bpp texture, so pntexnat.edit_texture decodes them as-is):

  block 0xd000 = [0x20, 0x240, 0x2eaa0, 0x5c530, 0x829f0, 0x9b6b0, end 0xa08e0]
    0xd020   layout table (u16 u,v,w,h; v runs on across the 5 textures, 512 each)
    0xd240   tex 1  portraits + 2 bios          (210x30 sprites at y 480)
    0x3baa0  tex 2  portraits + 2 bios          (y 480)
    0x69530  tex 3  portraits, name logos + 2 bios (y 480)
    0x8f9f0  tex 4  name logos + 18 bios        (2 columns, y 240..480)
    0xa86b0  tex 5  last bio + the two "Secret!?" sprites (y 0, 30); the rest is unused
  block 0xae000 = [0x20, 0x1f0, 0x1a9e0, 0x36aa0, end 0x47c10]
    0xae020  layout table
    0xae1f0  tex 1  72x72 attack drop-pattern diagrams (no text)
    0xc89e0  tex 2  30 commentary sprites + the 8-step difficulty ladder (88x26 at x 420)
    0xe4aa0  tex 3  23 commentary sprites ("Secret!?", "picked at random")

Every bio / commentary sprite is 210x30 and holds two lines (rows 1-13 and 16-28),
RIGHT-aligned to x+206, in a yellow fill with a green outline on a transparent
background (index 0); the game draws it on the green profile panel. Each sprite is
erased to index 0 (only non-black pixels, plus 2 px around them, so the transparent
background stays index 0), then each English line is drawn as its own text-only edit
whose clip ends at the sprite's right text edge, so the line is right-aligned like the
Japanese. The text is mapped onto palette entries the Japanese line already used.

There are no separate attack NAME textures: the Attack Select screen shows the drop
diagram, this commentary and the difficulty ladder, and its frame art ("Attack Select",
"attack commentary", "Random") is already English (IMAGE.DAT 0x75c060 / 0x779750).

Slot ends: the three middle streams of each block end at the next sub-stream. The two
block-final streams (0xa86b0, 0xe4aa0) recompress to almost exactly their original size
(our coder is ~170 bytes worse than Konami's on 0xe4aa0), so like lobby_room.py they may
run into the zero padding up to the next 0x800-aligned block (0xae000 / 0xf6000).
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import pntexnat as _pn
from PIL import Image, ImageDraw, ImageFont

SW = 1                       # outline width (the Japanese has a 1 px green outline)
FILL = (219, 206, 95)        # Japanese bio/commentary fill (yellow)
OUTL = (26, 135, 46)         # Japanese outline (green)
MAXW = 202                   # usable line width (JP text spans x+3 .. x+206)
RIGHT = 207                  # right text edge, relative to the sprite (exclusive)
FS_TRY = (13, 12, 11)        # preferred sizes; below 11 the line is squeezed instead
SQUEEZE_FS = 11

_dr = ImageDraw.Draw(Image.new("RGB", (8, 8)))
_fonts = {}


def _bb(t, fs):
    f = _fonts.get(fs) or _fonts.setdefault(fs, ImageFont.truetype(_pn.FONT, fs))
    return _dr.textbbox((0, 0), t, font=f, stroke_width=SW)


def _fit(lines):
    """One font size for both lines of a sprite (the largest that fits); lines still
    too wide at SQUEEZE_FS are compressed horizontally instead of shrinking further."""
    for fs in FS_TRY:
        if all(_bb(t, fs)[2] - _bb(t, fs)[0] <= MAXW for t in lines):
            return fs
    return SQUEEZE_FS


def _erase(x, y, w=210, h=30):
    # every non-black pixel (+2 px) -> the transparent background index (the clip's
    # most common index among the untouched pixels, i.e. 0)
    return dict(clip=(x, y, x + w, y + h), bg="flat", hat=0, wht=0, drk=-1, dil=2)


def _line(x, y, row, t, fs, fill=FILL, outline=OUTL):
    """Text-only edit for one right-aligned line. row 0 = top line (JP rows 1-13),
    row 1 = bottom line (rows 16-28)."""
    bb = _bb(t, fs)
    w = bb[2] - bb[0]
    cap = _bb("A", fs)[1]                      # top of a capital, incl. outline
    top = y + (1 if row == 0 else 16)
    y0, y1 = y + 15 * row, y + 15 * row + 15
    x1 = x + RIGHT
    sq = w > MAXW
    x0 = x1 - (MAXW if sq else w)
    return dict(clip=(x0, y0, x1, y1), lines=[t], ty0=top - cap, lh=15, fs=fs,
                align="l", margin=0, squeeze=sq, bg="flat", hat=0, wht=999, drk=-1,
                dil=0, fill=fill, outline=outline, sw=SW)


def _dekey(x, y, w=210, h=30):
    # Clean-up pass for sheets whose Japanese lines used an opaque-black palette entry
    # (tex 5 only): the drawn text's faint anti-aliasing fringe would map to that black
    # and read as a black halo on the green panel. Every near-black drawn pixel (lum < 55, i.e. nearer black than the green outline) goes
    # back to the transparent background index (the clip's most common original index
    # under the remaining, bright, text pixels = 0); only the yellow/green letters stay.
    return dict(clip=(x, y, x + w, y + h), bg="flat", hat=0, wht=999, drk=55, dil=0)


def _sprite(x, y, lines, dekey=False):
    lines = [lines] if isinstance(lines, str) else list(lines)
    fs = _fit(lines)
    out = [_erase(x, y)] + [_line(x, y, i, t, fs) for i, t in enumerate(lines) if t]
    return out + ([_dekey(x, y)] if dekey else [])


def _sheet(sprites, dekey=False):
    out = []
    for x, y, lines in sprites:
        out += _sprite(x, y, lines, dekey)
    return out


# ---------------------------------------------------------------------------------
# Character bios (2 lines each). Order = the name-logo order on tex 3/4.
# ---------------------------------------------------------------------------------
BIO_1 = [  # 0xd240
    (0, 480, ["On a different TV show every day", "Nyami's best friend and partner!"]),       # Mimi
    (210, 480, ["A famous TV host and singer", "Always hanging out with her pal Mimi!"]),      # Nyami
]
BIO_2 = [  # 0x3baa0
    (0, 480, ['Pop\'n\'s self-styled "King of Music"', "A top-class singer AND dancer!"]),  # the KING
    (210, 480, ["The super dancer everyone knows", "Her high-energy dancing is a blast!"]),  # Mary
]
BIO_3 = [  # 0x69530
    (0, 480, ["A Japanese artist big in America", "Want him to produce YOU next?"]),         # SHOLLKEE
    (210, 480, ["A cute dancer from the West Coast", "Will she bust out her dazzling moves?"]),  # JUDY
]
BIO_4 = [  # 0x8f9f0, left column then right column per row
    (0, 240, ["18, and studying fashion design", "Can't wait to see today's outfit!"]),        # RIE
    (210, 240, ["A girl with a lovely singing voice", "Will she show off her guitar skills?"]),  # SANAE
    (0, 270, ["An angel in training from White Land", "When will she be a real angel?"]),      # Poet
    (210, 270, ["A hit musician of the pop'n world", "Who will he produce next?"]),            # ice
    (0, 300, ["The invisible-man band member", "Cool on stage, but a real goofball!"]),        # Smile
    (210, 300, ["A musician who sings AND chats", "Can his gift of gab win fans too?"]),       # Timer
    (0, 330, ["A power-packed band guy", "His energetic vocals win fans over!"]),               # Ash
    (210, 330, ["A vampire who leads a hit band", "His romantic voice slays the fans!"]),      # Yuli
    (0, 360, ["A cool cop at the Pop Precinct", "What burns in that passionate heart?"]),      # SUIT
    (210, 360, ["A wandering hip-rock samurai", "Roaming to master sword and word!"]),         # Roku
    (0, 390, ["A mystery dancer of Saturday nights", "Are her moves beyond godly?"]),          # Rave girl
    (210, 390, ['The man Roppongi called "the Devil"', "He'll spin you a slick remix!"]),      # MZD
    (0, 420, ["A tracksuit-loving performer crew", "Can song and dance save the Earth?"]),     # Jersey crew
    (210, 420, ["A schoolgirl from Sweden", "The town loves her cold-proof pep!"]),     # rosetta
    (0, 450, ["A charismatic young girl poet", "Always seeking something far away?"]),        # Kagome
    (210, 450, ["Strolls around, sketchbook in hand", "She just found a secret little lane!"]),  # MUTSUKI
    (0, 480, ["A candy lover dreaming of sweet love", "Seeking her soulmate at the dentist!"]),  # MILK
    (210, 480, ["A stray kitten living in a trash can", "Will somebody notice it someday?"]),  # kitten
]
BIO_5 = [  # 0xa86b0
    (0, 0, ["A gothic-lolita zombie girl", "She's huge in B-movie horror now!"]),             # Liddell
    (210, 0, ["Secret!?", "This character appears in ONLINE MODE!"]),
    (0, 30, ["Secret!?"]),
]

# ---------------------------------------------------------------------------------
# Attack commentary. Many attacks share a sentence; the shared lines are kept
# identical in English too.
# ---------------------------------------------------------------------------------
FILL_D = "Balls drop to fill the field"
FILL_R = "Balls rise to fill the field"
ROW_UP = "A full row rises up from below!"
EVEN = "Leftovers fall to even things out!"
ANY = ["No matter what the field looks like,", "a whole row of balls drops in!"]
U12 = ["Under 12 balls? They fall from the top!", "12 or more? One row rises from below!"]
MID4 = ["Balls drop in the middle 4 columns,", "then on the edges too at 10 rows!"]
EDGES = "Columns drop from each edge in turn!"
INWARD = "At 10 rows, it shifts 1 column inward!"
LEFT1 = "At 10 rows, it shifts 1 column left!"
GAPS = "then into the gaps at 10 rows!"
SHAPE_L = [FILL_D, "in an L shape!"]
SHAPE_G = [FILL_D, "in an upside-down L shape!"]
DIAG = [FILL_D, "diagonally!"]
FLAT = ["Balls drop to level out", "the whole field!"]
MOUNT = [FILL_D, "in a mountain shape!"]
VALLEY = [FILL_D, "in a valley shape!"]

ATK_2 = [  # 0xc89e0 (the two top sprites sit at x 216)
    (216, 0, ["Balls drop in the right 3 columns,", "then the left 3 at 10 rows!"]),
    (216, 30, SHAPE_G),
    (0, 72, [ROW_UP, EVEN]),
    (210, 72, SHAPE_L),
    (0, 102, ANY),
    (210, 102, ["Every other column from the right,", GAPS]),
    (0, 132, [EDGES, INWARD]),
    (210, 132, U12),
    (0, 162, MID4),
    (210, 162, DIAG),
    (0, 192, ANY),
    (210, 192, [ROW_UP, EVEN]),
    (0, 222, FLAT),
    (210, 222, MOUNT),
    (0, 252, U12),
    (210, 252, VALLEY),
    (0, 282, ["Every other column from the left,", GAPS]),
    (210, 282, DIAG),
    (0, 312, ["One column at a time from the right!", LEFT1]),
    (210, 312, [FILL_D, "in a pinwheel pattern!"]),
    (0, 342, ["Every third column from the right!", LEFT1]),
    (210, 342, DIAG),
    (0, 372, [ROW_UP, "Leftovers drop on the far left & right!"]),
    (210, 372, [ROW_UP, EVEN]),
    (0, 402, FLAT),
    (210, 402, VALLEY),
    (0, 432, ["Balls drop in the middle 4 columns,", "then on both edges at 10 rows!"]),
    (210, 432, MOUNT),
    (0, 462, ["Columns rise from each edge in turn!", INWARD]),
    (210, 462, ["Rises every third column from the right!", LEFT1]),
]
ATK_3 = [  # 0xe4aa0
    (0, 0, ["Balls rise in the right 3 columns,", "then the left 3 at 10 rows!"]),
    (210, 0, ["Balls rise in the middle 4 columns,", "and leftovers rise on both edges!"]),
    (0, 30, [EDGES, INWARD]),
    (210, 30, MOUNT),
    (0, 60, MID4),
    (210, 60, ["Every other column from 2nd-right,", GAPS]),
    (0, 90, U12),
    (210, 90, MID4),
    (0, 120, ["Balls drop in the right 2 columns,", "then the left 2 at 10 rows!"]),
    (210, 120, ["Balls rise in the right 2 columns,", "then the left 2 at 10 rows!"]),
    (0, 150, ["The right 3 columns rise from below,", "the left 3 drop in to level it out!"]),
    (210, 150, ["Columns 1, 3 and 5 rise from below,", "2, 4 and 6 drop in to level it out!"]),
    (0, 180, ["The left 3 columns rise from below,", "the right 3 drop from above!"]),
    (210, 180, ["Balls rise in the 4 outer columns!", EVEN]),
    (0, 210, ["Balls rise to level out", "the whole field!"]),
    (210, 210, MOUNT),
    (0, 240, ["Balls rise to level out", "the whole field!"]),
    (210, 240, VALLEY),
    (0, 270, DIAG),
    (210, 270, [FILL_R, "diagonally!"]),
    (0, 300, ["Secret!?", "This ball appears in ONLINE MODE!"]),
    (210, 300, ["It's picked at random!"]),
    (0, 330, ["Secret!?"]),
]

# ---------------------------------------------------------------------------------
# Difficulty ladder (0xc89e0, 88x26 sprites at x 420, y 60 + 26k): the label is rows
# 0-11 above a row of stars (rows 12-25, untouched). Cream fill, dark green outline.
# ---------------------------------------------------------------------------------
LADDER = ["Breezy", "Easy", "Normal", "Tricky", "Brutal", "Puzzle Alien", "Demigod", "God"]
LAD_FILL = (243, 245, 216)
LAD_OUT = (14, 55, 7)
LAD_FS = 10


def _ladder():
    out = []
    cap = _bb("A", LAD_FS)[1]
    for k, t in enumerate(LADDER):
        y = 60 + 26 * k
        clip = (420, y, 508, y + 12)
        out.append(dict(clip=clip, bg="flat", hat=0, wht=0, drk=-1, dil=1))
        out.append(dict(clip=clip, lines=[t], ty0=y - cap, lh=12, fs=LAD_FS, align="c",
                        margin=4, bg="flat", hat=0, wht=999, drk=-1, dil=0,
                        fill=LAD_FILL, outline=LAD_OUT, sw=SW))
    return out


SCREENS = [
    dict(name="profile-1", file="IMAGE1.DAT", fo=0xd240, slot_end=0x3baa0, edits=_sheet(BIO_1)),
    dict(name="profile-2", file="IMAGE1.DAT", fo=0x3baa0, slot_end=0x69530, edits=_sheet(BIO_2)),
    dict(name="profile-3", file="IMAGE1.DAT", fo=0x69530, slot_end=0x8f9f0, edits=_sheet(BIO_3)),
    dict(name="profile-4", file="IMAGE1.DAT", fo=0x8f9f0, slot_end=0xa86b0, edits=_sheet(BIO_4)),
    dict(name="profile-5", file="IMAGE1.DAT", fo=0xa86b0, slot_end=0xad8e0, edits=_sheet(BIO_5, dekey=True)),
    dict(name="attack-2", file="IMAGE1.DAT", fo=0xc89e0, slot_end=0xe4aa0,
         edits=_sheet(ATK_2) + _ladder()),
    dict(name="attack-3", file="IMAGE1.DAT", fo=0xe4aa0, slot_end=0xf5c10, edits=_sheet(ATK_3)),
]
