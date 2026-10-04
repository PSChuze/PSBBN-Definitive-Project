"""Tutorial speech banners (Practice / How to play) - IMAGE3.DAT.

The banners are whole-sprite captions the tutors say over the orange starry strip
(IMAGE3.DAT 0x80170, the strip backdrop; it has no Japanese): rounded letters with a
brown-to-gold vertical gradient, a 1 px white rim and a thick dark-blue outline, on the
TRANSPARENT palette entry 0 (the strip shows through). Reported line: 3つ並べると消せるのよ
("Line up 3 to clear them!"), tex 0x63860 sprite (222,326,434,360).

IMAGE3.DAT (NOT IMAGE.DAT) holds two blocks with 0x10 headers, one per tutor; each
block's sub-stream 0 is the LZSS layout table (u16 x, y, w, h per sprite, y / 512 =
texture number). Every clip below is a sprite rect from those tables.
  block 0x0      tutor 1 (rough boy: ...だ! / ...ぜ!)
      tex 0x130    slot_end 0x24050   19 banners
      tex 0x24050  slot_end 0x3fab0   18 banners (0x3fab0 = the block's end offset)
  block 0x40000  tutor 2 (girl: ...のよ / ...ね)
      tex 0x40130  slot_end 0x63860   17 banners
      tex 0x63860  slot_end 0x7feb0   19 banners
Each slot is the stream + <= 17 bytes of tail; the tail past each stream is zero.

Ellipses are drawn as U+2026: with the faux bold, "..." merges into an underscore.

Drawing (no pntexnat changes, existing modes only), per banner:
  1. wipe the sprite to the transparent entry (bg="key", key=0, wht=-1, dil=0);
  2. per English line, the dark-blue outline layer: text in the outline blue with a
     4 px stroke, aliased (aa=False: an antialiased edge over the transparent entry's
     black RGB would map to a dark fringe);
  3. per English line, one 1-px-high band edit per row: text with a 1 px WHITE stroke
     and that row's gradient colour as fill, clipped to the row. pntexnat maps drawn
     pixels to the indices the band row already used, i.e. the Japanese gradient's own
     entries at that height (English lines sit in the Japanese line slots, so the rows
     line up with the original gradient).
The English keeps the Japanese line count; each line is centred in its Japanese line
slot (sprite height / line count), one font size per banner (largest that fits).
"""
import os, sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "..", "tools"))
import pntexnat as _pn
from PIL import Image, ImageDraw, ImageFont

BLUE = (0, 28, 138)          # outline (palette entry 2/5/7 in these sheets)
WHITE = (253, 253, 253)      # rim (entry 255)
G_TOP = (139, 61, 7)         # gradient at the cap top (dark brown)
G_BOT = (198, 150, 13)       # gradient at the baseline (gold)
G_DESC = (157, 90, 10)       # below the baseline (descenders): the Japanese glyphs'
                             # darker bottom edge, an entry their bottom rows still have
SW = 5                       # blue stroke (the white rim covers its inner 1 px)
BOLD = 2                     # faux bold: the Japanese strokes are thick
FS_MAX, FS_MIN = 22, 11
MARGIN = 4                   # px kept free at the sprite's left + right edges (total)

_dr = ImageDraw.Draw(Image.new("RGB", (8, 8)))
_fonts = {}


def _font(fs):
    return _fonts.get(fs) or _fonts.setdefault(fs, ImageFont.truetype(_pn.FONT, fs))


def _w(t, fs):
    b = _dr.textbbox((0, 0), t, font=_font(fs), stroke_width=SW)
    return b[2] - b[0] + BOLD


def _fit(rect, lines, pitch):
    """Largest font size where every line fits the sprite width and the outlined
    glyph box ("Ag" + stroke) fits the line slot."""
    x0, y0, x1, y1 = rect
    for fs in range(FS_MAX, FS_MIN - 1, -1):
        b = _dr.textbbox((0, 0), "Ag", font=_font(fs), stroke_width=SW)
        if b[3] - b[1] > pitch - 1:
            continue
        if all(_w(t, fs) <= x1 - x0 - MARGIN for t in lines):
            return fs
    raise SystemExit("ingame_banners: %r does not fit %r" % (lines, rect))


def _lerp(t):
    t = min(1.0, max(0.0, t))
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(G_TOP, G_BOT))


NOOP = dict(bg="flat", hat=255, wht=256, drk=-1, dil=0)     # draw only, remove nothing


def banner(rect, lines, dy=0):
    """Edits that replace one tutor banner sprite with `lines` (one per Japanese line).
    dy nudges every line up/down (px): a descender row the Japanese never filled has
    no gold entry to map to (banderr check: it came out blue)."""
    x0, y0, x1, y1 = rect
    n = len(lines)
    pitch = (y1 - y0) / float(n)
    fs = _fit(rect, lines, pitch)
    f = _font(fs)
    ab = _dr.textbbox((0, 0), "Ag", font=f)           # cap top .. descender bottom
    cap_top = _dr.textbbox((0, 0), "A", font=f)[1]
    base = f.getmetrics()[0]                          # baseline below the draw y
    eds = [dict(clip=rect, bg="key", key=0, wht=-1, dil=0)]         # 1. wipe
    for i, t in enumerate(lines):
        cy = y0 + pitch * (i + 0.5)
        ty = int(round(cy - (ab[1] + ab[3]) / 2.0)) + dy
        common = dict(lines=[t], ty0=ty, lh=pitch, fs=fs, align="c", margin=MARGIN,
                      bold=BOLD, **NOOP)
        # 2. blue outline layer over the whole sprite
        eds.append(dict(common, clip=rect, fill=BLUE, outline=BLUE, sw=SW, aa=False))
        # 3. white rim + gradient fill, one row at a time
        lb = _dr.textbbox((0, ty), t, font=f, stroke_width=1)
        g0, g1 = ty + cap_top, ty + base
        for y in range(max(y0, lb[1] - 1), min(y1, lb[3] + 2)):
            eds.append(dict(common, clip=(x0, y, x1, y + 1), sw=1, outline=WHITE, aa=False,
                            fill=G_DESC if y > g1 + 2 else _lerp((y - g0) / float(max(1, g1 - g0)))))
    return eds


# ---- the banners ----------------------------------------------------------------------
# (sprite rect, English lines[, dy]). Line count = the Japanese line count.
# Terms (GLOSSARY + options_menus): こだま small ball, おおだま big ball, ぜんだま Good
# ball, あくだま Bad ball, くいだま Eater ball, こうげきだま attack balls, 連鎖 chain.

# tutor 1, tex 0x130
T1A = [
    ((0, 0, 212, 98), ["Clear a big ball", "next to small ones,", "and they turn big!"]),  # こだまの隣のおおだまを消せば、こだまはおおだまにチェンジ!
    ((212, 0, 402, 68), ["Whoa! No, no.", "No diagonals!"]),                   # おっと~!だめだめ。ななめは消せないよ!
    ((402, 0, 492, 34), ["Take that!"]),                                      # そりゃ~!
    ((402, 34, 490, 68), ["Eat this!"]),                                      # くらえ~!
    ((412, 68, 484, 102), ["Alright!"]),                                      # よ~し!
    ((412, 102, 480, 136), ["Brrr…"]),                                      # さぶ...
    ((0, 98, 170, 166), ["Chain to attack", "your rival!"]),                  # 連鎖すれば相手に攻撃できるのだ!
    ((170, 98, 412, 164), ["Use their attack balls", "to hit back. Sweet~!"]),  # 相手のこうげきだまを反撃に使って、ハッピー~~!
    ((240, 164, 478, 230), ["Then try turning", "small balls big~!"]),        # そういう時はこだまをおおだまに変えてみよう~!
    ((0, 166, 240, 232), ["There are tons of", "attack patterns!"]),          # 攻撃パターンにはたくさんの種類があるんだ!
    ((0, 232, 238, 298), ["Use it where small", "balls pile up! Then…"]),   # こだまの多い所で使うべし!すると...
    ((238, 232, 472, 298), ["Clear a big ball right", "by a small one~!"]),   # こだまの上下左右どこかでおおだまを消してくれ~っ!
    ((0, 298, 232, 364), ["The small balls near it", "all turn big~!"]),      # その周りにあるこだまがおおだまになっちゃうし~!
    ((232, 298, 452, 364), ["Now I'll chain with", "the small balls!"]),      # それじゃあこだまを使って連鎖を組んでみるぜ!
    ((452, 298, 512, 332), ["Smash!"]),                                       # 必殺!
    ((0, 364, 214, 430), ["Lining up small balls", "won't clear them!"]),     # こだまは並べただけでは消せないんだ!
    ((214, 364, 428, 430), ["Hey, who came up", "with this rule!?"]),         # って、誰だよ!こんなルール作ったのは!
    ((0, 430, 214, 496), ["Good luck! Adios!", "Amigo! De Niro!"]),           # グッドラック!アディオス!アミーゴ!デニーロ!
    ((214, 430, 426, 496), ["Drop an Eater ball", "by junk balls…"]),       # くいだまは邪魔なたまのそばで箱から出すと...
]

# tutor 1, tex 0x24050
T1B = [
    ((0, 0, 198, 66), ["Right as you set up", "a chain, they drop…"]),      # 連鎖いくぜ~って時に落ちてくると...
    ((198, 0, 390, 66), ["Anyway, just", "give it a whirl!"]),                # まあ、とにもかくにもやってみてちょんまげ!
    ((0, 66, 182, 132), ["N-no! My precious", "big ball~!"]),                 # お、おれのおおだまちゃんが~!
    ((182, 66, 352, 132), ["Balls come big", "and small!"]),                  # たまにはおおだまとこだまがあるんだ!
    ((352, 66, 496, 132), ["Munch munch!", "It eats them up!"]),              # ぱくぱくぱくっと食べてくれるよ!
    ((0, 132, 198, 196), ["And this one…", "is a real pain…"]),           # あとは...こいつはホント嫌なやつ...
    ((198, 132, 390, 196), ["Next up:", "special balls!"]),                   # じゃあ次は、特別なたまの説明だ!
    ((0, 196, 242, 232), ["Whoa! A counterattack!"]),                         # どわ~っ!相手の反撃だ~!
    ((242, 196, 474, 232), ["Got all that so far!?"]),                        # ここまでは覚えたか~い!?
    ((0, 232, 226, 268), ["In this case, like so…"]),                       # この場合はこうやって...と
    ((226, 232, 428, 268), ["Line up 3 to clear them!"]),                     # 3つ並べると消せるぞ!
    ((0, 268, 200, 304), ["#@$%! Not again!"]),                               # ○$♂△×!またかよ!
    ((200, 268, 374, 304), ["Big balls of a color…"]),                      # 同じ色のおおだまを
    ((0, 304, 204, 338), ["Attaboy! Good job!"]),                             # よ~しよし!グッジョブ!
    ((204, 304, 384, 338), ["It's the Bad ball!"]),                           # その名もあくだまだ!
    ((0, 338, 168, 372), ["Next: Good ball!"]),                               # お次はぜんだまだ!
    ((168, 338, 332, 372), ["Rainbo~w…!"]),                                 # レインボ~~...!
    ((332, 338, 492, 372), ["First: Eater ball!"]),                           # まずはくいだまだ!
]

# tutor 2, tex 0x40130
T2A = [
    ((0, 0, 220, 98), ["Now I'll chain with", "small balls, so", "watch closely!"]),  # これじゃあこだまを使って連鎖を組んでみるから、ちょっと見ててね
    ((220, 0, 430, 96), ["Clear a big ball", "next to small ones,", "and they turn big!"]),  # こだまの隣のおおだまを消せば、こだまをおおだまにできるの
    ((430, 0, 494, 32), ["Okay!"]),                                           # よ~し
    ((400, 96, 508, 130), ["Here I go~!"]),                                   # いくわよ~!
    ((400, 130, 488, 162), ["Now…"]),                                       # さあ~...
    ((0, 98, 206, 194), ["It turns all the", "small balls near it", "into big ones!"]),  # その周りにあるこだまをみんなおおだまにしてくれるのよ
    ((206, 98, 400, 194), ["Using their attack", "balls to hit back", "is how you win!"]),  # 相手のこうげきだまを反撃に使うことが、勝利への近道ね
    ((0, 194, 248, 260), ["Then just turn", "small balls big!"]),             # そんな時は、こだまをおおだまに変えればいいのよ
    ((248, 194, 490, 260), ["There are lots of", "attack patterns!"]),        # 攻撃パターンにはたくさんの種類があるのよ
    ((0, 260, 242, 326), ["Just as you go for", "a chain, they drop…"]),    # これから連鎖しようかなって時に落ちてくると...
    ((242, 260, 476, 326), ["Just clear a big ball", "by a small one!"]),     # こだまの上下左右どこかでおおだまを消せばいいのよ
    ((0, 326, 214, 392), ["Lining up small balls", "won't clear them."]),     # こだまは並べただけでは消せないの
    ((214, 326, 426, 392), ["But careful:", "no diagonals!"]),                # でも、ななめは消せないから注意してね
    ((0, 392, 210, 458), ["Drop an Eater ball", "by junk balls…"]),         # くいだまは邪魔なたまの隣で箱から出すと...
    ((210, 392, 412, 458), ["Make chains to", "attack your rival!"]),         # 連鎖すれば相手に攻撃できるのよ
    ((0, 458, 236, 494), ["Use it by small balls…"]),                       # こだまの多い所で使うと...
    ((236, 458, 410, 494), ["Big balls of a color…"]),                      # 同じ色のおおだまを
]

# tutor 2, tex 0x63860
T2B = [
    ((0, 0, 200, 66), ["All your big balls", "turn small!"]),                 # おおだまがみんなこだまにされてしまうの
    ((200, 0, 392, 66), ["Never give up,", "and good luck!"]),                # 最後まで諦めないで、がんばってね!
    ((392, 0, 508, 36), ["Easy, right?"]),                                    # 簡単でしょ?
    ((0, 66, 190, 132), ["It eats the balls", "that way!"]),                  # その方向にあるたまを食べてくれるの
    ((190, 66, 360, 132), ["Balls come big", "and small!"]),                  # たまにはおおだまとこだまがあるのよ
    ((360, 66, 500, 100), ["One more~!"]),                                    # もういっちょ~!
    ((0, 132, 160, 198), ["Next up:", "special balls!"]),                     # 次は特別なたまの説明をするわね
    ((160, 132, 400, 196), ["And this one…", "is a bit tricky"], -1),           # あとは...ちょっとやっかいなんだけど
    ((0, 198, 192, 262), ["Keep at it till", "you get the knack!"]),          # 何度もやって、コツをつかんで欲しいな
    ((192, 196, 368, 260), ["Eek!", "Got me again!"], -1),                        # や~ん。またやられちゃった!
    ((368, 196, 508, 230), ["Next: Good ball"]),                              # 次はぜんだまよ
    ((0, 262, 154, 326), ["Uh-oh…", "a counterattack!?"]),                  # あららら...、相手の反撃ね!?
    ((154, 262, 308, 326), ["It may be hard", "at first, but"]),              # 初めは難しいかもしれないけど
    ((308, 260, 442, 294), ["First: Eater ball"]),                            # まずはくいだま
    ((0, 326, 222, 360), ["There's the Bad ball"]),                           # あくだまというのがあるの
    ((222, 326, 434, 360), ["Line up 3 to clear them!"]),                     # 3つ並べると消せるのよ  (the reported banner)
    ((0, 360, 212, 394), ["In this case, like so…"]),                       # この場合はこうやって...
    ((212, 360, 336, 394), ["Handy, huh?"]),                                  # これは便利ね
    ((336, 360, 458, 394), ["Go for it~!"]),                                  # いっちゃえ~!
]


def _edits(table):
    out = []
    for row in table:
        out += banner(*row)
    return out


SCREENS = [
    dict(name="tutor1-banners-a", file="IMAGE3.DAT", fo=0x130, slot_end=0x24050,
         edits=_edits(T1A)),
    dict(name="tutor1-banners-b", file="IMAGE3.DAT", fo=0x24050, slot_end=0x3fab0,
         edits=_edits(T1B)),
    dict(name="tutor2-banners-a", file="IMAGE3.DAT", fo=0x40130, slot_end=0x63860,
         edits=_edits(T2A)),
    dict(name="tutor2-banners-b", file="IMAGE3.DAT", fo=0x63860, slot_end=0x7feb0,
         edits=_edits(T2B)),
]


if __name__ == "__main__":
    for nm, tb in (("T1A", T1A), ("T1B", T1B), ("T2A", T2A), ("T2B", T2B)):
        for row in tb:
            rect, lines = row[:2]
            p = (rect[3] - rect[1]) / float(len(lines))
            print(nm, rect, _fit(rect, lines, p), lines)
