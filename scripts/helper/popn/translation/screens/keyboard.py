"""Software keyboard, second sheet - IMAGE.DAT block 0x6ae000, texture 2 @0x6b8ee0.

Block 0x6ae000 header = [0x10, 0x6e0, 0xaee0, 0x16780]:
  0x6ae010  layout table (compressed small stream; u16 u,v,w,h sprite rects, v>=512 =
            this second texture)
  0x6ae6e0  texture 1 (key grid, side labels, Hiragana/Katakana tabs, canned phrases)
            -> lobby_room.py KEYBOARD
  0x6b8ee0  texture 2 (this file): the 英数 / 定型文 mode tabs + the kana/ASCII key faces
            (stream ends 0x6c476f, block ends 0x6c4780)

The two mode tabs are layout rects (0,512,88,24) and (88,512,88,24), i.e. (0,0)-(88,24)
and (88,0)-(176,24) here; the key faces start at x=176 (22 px cells) and stay Japanese.
Same look as the Hiragana/Katakana tabs on texture 1: white letters with a light blue
1 px outline on a transparent cell (drawn over the dark blue tab bar).
"""

_FK, _OK = (253, 253, 253), (85, 138, 191)


def _tab(clip, txt, fs=14, dy=3):
    # erase every non-black (non-transparent) pixel of the cell, then draw centred
    return dict(clip=clip, bg="flat", hat=0, wht=6, drk=-1, dil=0,
                lines=[txt], ty0=clip[1] + dy, lh=20, fs=fs, align="c",
                fill=_FK, outline=_OK, sw=1)


KEYBOARD_TABS = dict(name="keyboard-tabs", file="IMAGE.DAT", fo=0x6b8ee0, slot_end=0x6c4780,
                     edits=[_tab((0, 0, 88, 24), "ABC 123"),
                            _tab((88, 0, 176, 24), "Phrases")])

SCREENS = [KEYBOARD_TABS]
