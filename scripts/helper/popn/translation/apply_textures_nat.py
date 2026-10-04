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

# LOGIN SCREEN AS DRAWN (tex @0x1ccd20). The old 'login' entry (0x2b1100) is a variant
# sheet ("Press the O button!" + an "ID issued" footer); the live ID/password screen
# (operator screenshot 2026-10-03) draws its title plate, ID/password buttons and
# Connect/Cancel/Register buttons from THIS sheet. The DNAS trademark notice
# (y 448-482) wraps around an embedded DNAS logo and is left as-is for now.
def _btn(clip, txt, fs):
    # bg="outlined": white letters with a dark outline on a busy plate (cream, stripes,
    # gradient); only the letters are removed and inpainted from the plate itself
    return dict(clip=clip, lines=[txt], ty0=clip[1] + 2, lh=20, fs=fs, bg="outlined",
                fill=250, outline=28, sw=2, wht=200, drk=90, reach=2, dil=1)

LOGIN_MAIN = dict(fo=0x1ccd20, slot_end=0x1e0a40, edits=[
    _btn((44, 88, 222, 116), "Enter ID & Password", 16),
    _btn((116, 159, 198, 180), "pop'n ID", 12),
    _btn((116, 187, 198, 208), "Password", 12),
    _btn((158, 246, 238, 267), "Connect", 13),
    _btn((272, 246, 354, 267), "Cancel", 13),
    _btn((158, 274, 352, 294), "Create an account", 13),
    _btn((78, 487, 268, 509), "Create an account", 13),    # pressed state
    _btn((436, 449, 508, 471), "Saving!", 13),
    _btn((282, 487, 464, 510), "Accessing play server!", 13),
])

# HELP-line message sprites + login buttons (tex @0x1e0a40): white text strips on a
# salmon key colour (index 106) the game hides at draw time, so letters are refilled
# with that exact index (bg="flat" with the palette known). Left-aligned like the JP;
# each clip stays inside its own strip (the strips are the sprite rects). The three
# disc-check dialogs on the left are skipped: the disc check is patched out.
def _msg(clip, txt, fs=13):
    return dict(clip=clip, lines=[txt], ty0=clip[1] + 1, lh=20, fs=fs, bg="key",
                align="l", fill=250, outline=28, sw=2, wht=190, dil=5)

HELP_MSGS = dict(fo=0x1e0a40, slot_end=0x1ffa90, edits=[
    _msg((345, 30, 508, 50), "Initializing Ethernet!"),
    _msg((345, 54, 502, 73), "Checking for updates!"),
    _msg((345, 78, 490, 98), "Verifying pop'n ID!"),
    _msg((345, 101, 472, 122), "Talking to the server!"),
    _msg((345, 133, 468, 153), "Checking DNAS!"),
    _msg((345, 157, 432, 175), "Saved!"),
    _msg((345, 181, 432, 199), "Save failed!"),
    _btn((348, 204, 426, 221), "pop'n ID", 12),
    _btn((348, 228, 426, 244), "Password", 12),
    _msg((343, 249, 487, 268), "Connecting to the server!"),
    _btn((348, 272, 426, 287), "Connect", 12),
    _btn((348, 294, 426, 311), "Cancel", 12),
    _msg((341, 315, 454, 336), "Back to the menu!"),
    _msg((1, 403, 166, 420), "Enter your pop'n ID!"),
    _msg((1, 421, 312, 439), "First time? Register on the sign-up screen!"),
    _msg((1, 440, 157, 457), "Enter your password!"),
    _msg((1, 458, 312, 476), "First time? Register on the sign-up screen!"),
    _msg((1, 477, 236, 495), "Enter your pop'n ID and password!"),
    _msg((323, 405, 505, 427), "Logging in to the play server!"),
    _msg((323, 429, 505, 450), "Accessing the gate server!"),
    _msg((323, 452, 505, 472), "Logging in to the gate server!"),
])

NAMES = ['disc-check', 'login', 'comm-error', 'user-select', 'data-update',
         'manual', 'user-data-reg', 'username-reg', 'reg-confirm', 'reg-done',
         'delete-select', 'delete-confirm', 'disconnect', 'handicap',
         'data-update-result', 'autoload', 'bbunit-save', 'install-space',
         'room-create', 'room-view', 'login-main', 'help-msgs']


def _builtin():
    out = []
    for nm, s in zip(NAMES, [AUTOLOAD if s["fo"] == AUTOLOAD["fo"] else convert(s)
                             for s in old.SCREENS] + [ROOM, ROOM_VIEW, LOGIN_MAIN, HELP_MSGS]):
        out.append(dict(s, name=nm))
    return out


def _modules():
    """Screens from popn/translation/screens/*.py (one file per area, each exporting
    SCREENS = [dict(name, file="IMAGE.DAT", fo, slot_end, edits), ...])."""
    import importlib.util, glob
    out = []
    for path in sorted(glob.glob(os.path.join(_here, "screens", "*.py"))):
        if os.path.basename(path).startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location("popn_screens_" + os.path.basename(path)[:-3], path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        out += [dict(s, _src=os.path.basename(path)) for s in mod.SCREENS]
    return out


def build_screens():
    """All screens, each with name/file/fo/slot_end/edits. Module screens replace a
    built-in with the same (file, fo); order is by file then offset."""
    by = {}
    for s in _builtin():
        by[(s.get("file", "IMAGE.DAT"), s["fo"])] = s
    for s in _modules():
        k = (s.get("file", "IMAGE.DAT"), s["fo"])
        if k in by and by[k].get("_src") and by[k]["_src"] != s["_src"]:
            print("WARNING: %s %#x is defined in both %s and %s; using %s"
                  % (k[0], k[1], by[k]["_src"], s["_src"], s["_src"]))
        by[k] = s
    return sorted(by.values(), key=lambda s: (s.get("file", "IMAGE.DAT"), s["fo"]))


# widening margin + mask dilation, tried most-aggressive first (best coverage)
# and backed off per screen until the texture fits its slot.
LADDER = [(28, 3), (28, 2), (16, 3), (16, 2), (8, 2), (0, 2), (0, 1)]


def _tune(edits, mx, dil, flat=False):
    out = []
    for e in edits:
        e = dict(e)
        if e.get("_widen"):
            x0, y0, x1, y1 = e["clip"]
            my = 3 if mx else 0
            e["clip"] = (max(0, x0 - mx), max(0, y0 - my),
                         min(W, x1 + mx), min(W, y1 + my))
            e["dil"] = dil
        if flat and e.get("bg", "inpaint") == "inpaint":
            e["bg"] = "flat"
        out.append(e)
    return out


# Inpainting in true colour spreads a gradient over many palette entries, which
# compresses worse; when a tight slot will not take it, fall back to filling the glyph
# mask with the panel's own colour (bg="flat"), which compresses like the original.
VARIANTS = [False, True]


def build(src, dst, screens, preview=None):
    """Apply `screens` (all for one file) to `src`, writing `dst`."""
    cur_src = src
    for s in screens:
        name = s.get("name", hex(s["fo"]))
        pv = os.path.join(preview, "%s_%x.png" % (name, s["fo"])) if preview else None
        last = None
        done = False
        for flat in VARIANTS:
            for mx, dil in LADDER:
                try:
                    comp, slot = pntexnat.edit_texture(
                        cur_src, dst, s["fo"], s["slot_end"],
                        _tune(s["edits"], mx, dil, flat), preview_png=pv)
                    print("%-22s %-10s @%#x  %d/%d  mx=%d dil=%d%s  OK"
                          % (name, s.get("file", "IMAGE.DAT"), s["fo"], comp, slot, mx, dil,
                             " flat" if flat else ""))
                    done = True
                    break
                except SystemExit as ex:
                    last = ex
                    if "atlas-safety" in str(ex):
                        raise
            if done:
                break
        if not done:
            raise SystemExit("%s: %s" % (name, last))
        cur_src = dst   # chain edits onto the growing output
    if cur_src == src:              # nothing applied: still produce the output file
        import shutil
        shutil.copyfile(src, dst)
    print("wrote", dst)


def main(src, dst, preview=None):
    """Two forms:
      main(<disc>/IMAGE.DAT, <out IMAGE.DAT>)   only IMAGE.DAT screens (installer form)
      main(<disc dir>, <out dir>)              every file that has screens
                                               (IMAGE.DAT, IMAGE1.DAT, ...)"""
    screens = build_screens()
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        for f in sorted({s.get("file", "IMAGE.DAT") for s in screens}):
            build(os.path.join(src, f), os.path.join(dst, f),
                  [s for s in screens if s.get("file", "IMAGE.DAT") == f], preview)
    else:
        build(src, dst, [s for s in screens if s.get("file", "IMAGE.DAT") == "IMAGE.DAT"],
              preview)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    pv = None
    if "--preview" in sys.argv:
        pv = sys.argv[sys.argv.index("--preview") + 1]
        os.makedirs(pv, exist_ok=True)
    main(a[0], a[1], pv)
