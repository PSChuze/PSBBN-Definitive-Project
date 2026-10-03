#!/usr/bin/env python3
"""Apply all pop'n IMAGE.DAT texture translations with the NATURAL, atlas-safe
editor (pntexnat). Replaces the box+overlay apply_textures.py.

  PYTHONUTF8=1 python popn/translation/apply_textures_nat.py \
      work/disc/IMAGE.DAT  work/translation/IMAGE.en.DAT  [--preview DIR]

The English strings/positions are carried over from apply_textures.py, but each
old {erase box + text} pair becomes a natural edit: the Japanese glyphs are masked
and the real panel background is inpainted behind them (no flat rectangle), and
every edit is clipped to its own element so a shared sprite on the sheet is never
touched (pntexnat asserts it). AUTOLOAD, whose old box ran through the lobby cat
sprite, is redefined with panel-only clips.
"""
import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
sys.path.insert(0, os.path.join(_here, '..', 'tools'))
import pntexnat
import apply_textures as old   # reuse its SCREENS data (English + positions)

W = 512


def style(ink):
    # old `ink` <128 = dark text on a light panel; else white text on a dark one.
    if ink is not None and ink < 128:
        return dict(fill=int(ink), outline=232, sw=1)
    return dict(fill=250, outline=28, sw=2)


def convert(screen):
    """Turn an old-format screen (erase/text DSL) into natural clip+lines edits."""
    groups = []
    cur = None
    for e in screen["edits"]:
        if "erase" in e:
            cur = {"clip": tuple(e["erase"]), "texts": []}
            groups.append(cur)
        if "text" in e:
            if cur is None:
                cur = {"clip": None, "texts": []}
                groups.append(cur)
            cur["texts"].append(e)
    edits = []
    for g in groups:
        ts = g["texts"]
        if g["clip"] is None or not ts:
            continue
        tsub = sorted(ts, key=lambda t: t.get("ty", 0))
        ty0 = tsub[0].get("ty", g["clip"][1] + 2)
        if len(tsub) > 1:
            lh = tsub[1]["ty"] - tsub[0]["ty"]
        else:
            lh = 24
        fs = max(t.get("fs", 14) for t in tsub)
        align = tsub[0].get("align", "c")
        ink = tsub[0].get("ink", 245)
        ed = dict(clip=g["clip"], lines=[t["text"] for t in tsub],
                  ty0=ty0, lh=lh, fs=fs, align=align,
                  hat=22, kk=13, dil=3, _widen=True, **style(ink))
        edits.append(ed)
    return dict(fo=screen["fo"], slot_end=screen["slot_end"], edits=edits)


# AUTOLOAD: hand-tuned panel-only clips (x<=356 never touches the lobby cats at x>=368)
AUTOLOAD = dict(fo=0x28716c0, slot_end=0x2884b00, edits=[
    dict(clip=(14, 197, 356, 294),
         lines=["Now loading!",
                "Data may be lost if you turn off",
                'or reset the "PS2" or unplug the',
                '"BB Unit" while loading!'],
         ty0=198, lh=24, fs=14, **style(245)),
    dict(clip=(14, 344, 356, 374),
         lines=["Load complete!"], ty0=348, lh=24, fs=15, **style(245)),
])

# ROOM creation sheet (tex 023 @0x3a7ec0): room options + handicap gauge legend.
# Not in the old apply_textures (it only covered login/menu/dialog screens). Text
# floats on dark panels / black, so bg="flat" (fill the glyph mask with the panel's
# own level) - cleaner than inpaint here. Handicap wording matches the handicap
# screen. Clips dodge the gauge icons/arrows (atlas-safe assert enforces it).
def _rm(clip, txt, ty0, fs):
    return dict(clip=clip, lines=[txt], ty0=ty0, lh=22, fs=fs, bg="flat",
                fill=250, outline=28, sw=2, hat=22, kk=11, dil=3)

ROOM = dict(fo=0x3a7ec0, slot_end=0x3bb7c0, edits=[
    _rm((32, 294, 266, 320), "Choose match count!", 298, 13),
    _rm((220, 294, 400, 320), "Room password?", 298, 12),
    _rm((32, 316, 266, 342), "Name your room!", 320, 13),
    _rm((376, 292, 512, 314), "Enter the password!", 295, 12),
    _rm((248, 276, 512, 294), "Pick in-game strength!", 279, 12),
    _rm((328, 124, 452, 158), "Huge advantage!", 130, 12),
    _rm((450, 124, 508, 158), "Even!", 130, 12),
    _rm((0, 253, 152, 279), "Huge advantage!", 257, 11),
    _rm((154, 253, 308, 279), "Big advantage!", 257, 11),
    _rm((310, 253, 404, 279), "Big handicap!", 258, 10),
    _rm((414, 253, 510, 279), "Big handicap!", 258, 10),
    _rm((0, 279, 126, 294), "Small handicap!", 281, 9),
    _rm((128, 279, 250, 294), "Small handicap!", 281, 9),
])

# ROOM VIEW sheet (tex @0x3bbd70, the in-room screen): only the win/loss kanji are
# Japanese (everything else - Room/ROOM OWNER/CHALLENGER/READY/HISCORE/CHAT WINDOW -
# is native English). 勝->W, 敗->L in both panels (small single-kanji slots). It is a
# gap-region texture, so slot_end = fo + its own compressed length (next texture
# starts right after). Pt is already English.
def _wl(cx, txt):
    return dict(clip=(cx - 13, 168, cx + 13, 189), lines=[txt], ty0=169, lh=20,
                fs=16, bg="flat", fill=245, outline=30, sw=2, hat=18, kk=9, dil=2)

ROOM_VIEW = dict(fo=0x3bbd70, slot_end=0x3d38da, edits=[
    _wl(75, "W"), _wl(140, "L"),      # ROOM OWNER panel
    _wl(417, "W"), _wl(482, "L"),     # CHALLENGER panel
])

NAMES = ['disc-check', 'login', 'comm-error', 'user-select', 'data-update',
         'manual', 'user-data-reg', 'username-reg', 'reg-confirm', 'reg-done',
         'delete-select', 'delete-confirm', 'disconnect', 'handicap',
         'data-update-result', 'autoload', 'bbunit-save', 'install-space',
         'room-create', 'room-view']


def build_screens():
    out = []
    for s in old.SCREENS:
        if s["fo"] == AUTOLOAD["fo"]:
            out.append(AUTOLOAD)
        else:
            out.append(convert(s))
    out.append(ROOM)
    out.append(ROOM_VIEW)
    return out


# widening margin + mask dilation, tried most-aggressive first (best coverage)
# and backed off per screen until the texture fits its slot.
LADDER = [(28, 3), (28, 2), (16, 3), (16, 2), (8, 2), (0, 2), (0, 1)]


def _tune(edits, mx, dil):
    out = []
    for e in edits:
        e = dict(e)
        if e.get("_widen"):
            x0, y0, x1, y1 = e["clip"]
            my = 3 if mx else 0
            e["clip"] = (max(0, x0 - mx), max(0, y0 - my),
                         min(W, x1 + mx), min(W, y1 + my))
            e["dil"] = dil
        out.append(e)
    return out


def main(src, dst, preview=None):
    screens = build_screens()
    cur_src = src
    for i, s in enumerate(screens):
        pv = (os.path.join(preview, "%02d_%s.png" % (i, NAMES[i]))
              if preview else None)
        last = None
        for mx, dil in LADDER:
            try:
                comp, slot = pntexnat.edit_texture(
                    cur_src, dst, s["fo"], s["slot_end"],
                    _tune(s["edits"], mx, dil), preview_png=pv)
                print("%-20s @%#x  %d/%d  mx=%d dil=%d  OK"
                      % (NAMES[i], s["fo"], comp, slot, mx, dil))
                break
            except SystemExit as ex:
                last = ex
                if "atlas-safety" in str(ex):
                    raise
        else:
            raise SystemExit("%s: %s" % (NAMES[i], last))
        cur_src = dst   # chain edits onto the growing output
    print("wrote", dst)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    pv = None
    if "--preview" in sys.argv:
        pv = sys.argv[sys.argv.index("--preview") + 1]
        os.makedirs(pv, exist_ok=True)
    main(a[0], a[1], pv)
