#!/usr/bin/env python3
"""Run translation/apply_textures_nat.py with Pillow's text layout pinned, so the
English lettering in IMAGE.DAT / IMAGE1.DAT / IMAGE3.DAT is drawn the same on every OS.

    python3 textures_build.py <apply_textures_nat.py> <disc dir> <out dir>

Pillow draws text with one of two layout engines: BASIC (FreeType only) or RAQM
(HarfBuzz shaping + kerning). Which one is the default depends on how Pillow was
built: the Windows wheels have no libraqm and use BASIC, the Linux wheels ship it
and use RAQM. The two place glyphs a pixel apart here and there, which changes
every texture. The shipped textures were made with BASIC, so this forces BASIC
for every ImageFont.truetype() call and then runs the script unchanged.

On the same machine and Python environment the output is byte-identical to
apply_textures_nat.build() over all screens. Across operating systems it is
not: OpenCV's Telea inpaint (the background behind the erased Japanese) gives
slightly different pixels on Windows and on Linux, even with the same OpenCV
version. The text itself matches.
"""
import runpy
import sys

from PIL import ImageFont

_truetype = ImageFont.truetype


def _truetype_basic(*args, **kwargs):
    kwargs.setdefault("layout_engine", ImageFont.Layout.BASIC)
    return _truetype(*args, **kwargs)


ImageFont.truetype = _truetype_basic

if __name__ == "__main__":
    script = sys.argv[1]
    sys.argv = sys.argv[1:]
    runpy.run_path(script, run_name="__main__")
