# Per-area texture screens

Each `*.py` here exports `SCREENS = [dict(name, file, fo, slot_end, edits), ...]` and is
loaded by `../apply_textures_nat.py`. A screen with the same `(file, fo)` as a built-in
one replaces it. `file` is `IMAGE.DAT` (default) or `IMAGE1.DAT` / `IMAGE3.DAT`.

Edit modes (`bg`), from `../../tools/pntexnat.py`:
- `outlined`: white letters with a dark outline on a busy plate or button (best for labels)
- `key`: text on a flat key colour (message strips, e.g. salmon index 106)
- `flat`: refill with the panel's most common original index (uniform panels)
- `inpaint`: smooth panels with soft gradients (dialog text)
- `copy` + `src=(dx, dy)`: rebuild the whole clip from a same-sized twin region (a plate the
  Japanese covered almost edge to edge, so there is nothing left to inpaint from)
Every edit needs a tight `clip` inside its own element (the atlas check enforces it).

Rules learned from live testing:
- Normal/highlighted (selected, pressed) sprite pairs must overlay exactly: same font size
  and the same x/y offset relative to each sprite's own top-left (from the Japanese
  position). Otherwise the English jumps when the highlight blinks.
- Never let a slot run past the texture's own stream: some textures are followed by
  non-texture data (sprite/layout tables) before the next texture header. pntexnat's slot
  guard refuses such a slot; padding over that data broke the whole login screen once.
- Diagonal-stripe plates: copy hidden pixels from exactly one stripe period away
  (bg="rows", dir=(P, 0)); pure gradients: dir=(1, 0).
- Button plates palette-cycle when selected (the orange/red glow). A rebuilt plate
  pixel must use an index the plate itself uses, never one of the JP glyph's own
  entries (they do not cycle and show as splotches only on the highlighted button).
  Opt-ins (2026-10-04): bg="rows" + src="cur" (copy current indices, e.g. after a
  twin-plate copy) + blend="dither" (distance-weighted ordered dither between the two
  stripe ends: no seam, plate indices only); bg="lerp"/"inpaint" + local="ring"
  (map to the clip's unmasked indices only). Refill the striped interior along the
  stripes and the highlight/border rows along their own row.
- Clips must lie inside their sprite rect (block layout table). Check every build with
  `popn/tools/splotch_probe.py` (static splotches, INDEX = foreign palette entries,
  CROSS = English drawn into a neighbouring sprite, OUTSIDE = writes outside every
  sprite).
