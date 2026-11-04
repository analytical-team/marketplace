## 15. Reports & diagrams

Any Markdown a program produces — an analysis writeup, a run summary, a generated doc page — is built with
[`mdreport`](https://mdreport.tycho.engineering/llms-full.txt), not f-strings or hand-assembled `"\n".join(...)`. Any
diagram that accompanies it is an `mdreport` `Diagram`, not Mermaid, Graphviz, or hand-written SVG. One library covers
both, the output is deterministic, and the escaping is handled for you — which is the §10 argument applied to Markdown:
compose through the emitter, don't interpolate into it.

### Reports

`MarkdownReport` is a chainable builder. Each method appends content and returns the report.

```python
from mdreport import CalloutKind, MarkdownReport

report = (
    MarkdownReport()
    .frontmatter(title="Nightly ingest", author="pipeline")
    .title("Nightly ingest")
    .table_of_contents()
    .heading("Summary")
    .text("Processed {{count}} records.", params={"count": record_count})
    .bullet_list(["12 jobs passed", "0 jobs failed"])
    .callout("Counts are provisional.", kind=CalloutKind.WARNING)
    .table(metrics, title="Revenue by region", decimal_places=1)
)
report.save(output_path)
```

What to reach for:

- `title`, `heading`, `text`, `bullet_list`, `numbered_list`, `code_block`, `markdown` for ordinary content. Both list
  methods nest — a list immediately after an item hangs beneath it.
- `callout(..., kind=CalloutKind.NOTE | TIP | IMPORTANT | WARNING | CAUTION)` for an admonition.
- `table(dataframe, ...)` and `csv(dataframe, ...)` for Polars DataFrames. Both emit every row; slice first.
- `figure(path, alt_text=..., caption=...)` for images. Captions are numbered `Figure 1`, `Figure 2` at render time, so
  never number them yourself. `is_embedded=True` inlines a local image (base64 for raster, inline markup for SVG).
- `frontmatter(...)` for YAML metadata, `table_of_contents(start_level=..., depth=...)` for the heading list.
- `render()` returns the string; `save(path)` writes UTF-8.

Templating is Jinja and runs **only** when you pass `params` — that is the seam for interpolated values, so pass data
through `params` rather than building the string yourself. Content with literal braces goes in without `params`.

Alt text is not optional. Every `figure` gets `alt_text` that describes what the reader would otherwise miss.

### Diagrams

A `Diagram` is a canvas with components at explicit coordinates. The library does not measure text, lay out graphs, or
stop nodes overlapping — you place things, and the same code always emits the same bytes.

```python
from pathlib import Path

from mdreport import (
    CENTERED_NODE_HEIGHT,
    TITLE_NODE_HEIGHT,
    Diagram,
    DiagramTheme,
    NodeRole,
    PortSide,
    centered_node,
    node_port,
    title_node,
)

diagram = Diagram(
    "Ingest",
    width=987,
    height=144,
    theme=DiagramTheme.LIGHT,
    palette={"background": "#ffffff"},
    background="background",
)
title_node(diagram, 34, 44.5, 288, "Source", role=NodeRole.ROOT)
centered_node(diagram, 466, 27.5, 288, "Transform", "Normalize the input", role=NodeRole.PARENT)
diagram.line(
    *node_port(34, 44.5, 288, TITLE_NODE_HEIGHT, PortSide.RIGHT),
    *node_port(466, 27.5, 288, CENTERED_NODE_HEIGHT, PortSide.LEFT),
    arrow=True,
)
diagram.save(Path("docs/ingest.svg"))
```

Rules that keep diagrams consistent across a codebase:

- **Role, not color.** `NodeRole.ROOT` for input, `PARENT` for processing, `LEAF` for output. Let the role pick the
  stroke and fill. Pass explicit `fill`/`stroke` only for a deliberate accent, and never to imply a role the node
  doesn't have.
- **Palette keys, not hex.** Paint arguments take keys — `"ink"`, `"muted"`, `"line"`, `"soft_line"`, `"panel"`,
  `"neutral_fill"`, `"root_fill"`, and so on — resolved against the active theme. In custom elements use
  `diagram.color("parent_fill")`. A literal hex value is a theme bug waiting to happen; the exceptions are Lucide icon
  colors, which must be hex. To brand a diagram, pass only the changed keys to `palette`, with separate overrides per
  theme.
- **Stay on the scale.** Sizes and offsets come from the golden-ratio scale the library ships: `FIBONACCI_SPACE` for
  spacing and widths, `TYPE_SCALE` for text sizes, and the named heights (`TITLE_NODE_HEIGHT` 55, `CENTERED_NODE_HEIGHT`
  and `ICON_NODE_HEIGHT` 89, `INFORMATION_NODE_HEIGHT` 144, `LANE_HEADER` 144). Use `golden_split`, `golden_height`, and
  `golden_point` rather than arithmetic on magic numbers. Components with content-dependent heights return their height
  — position the next component from the returned value, not a guess.
- **Pick the node for the copy.** `title_node` for a name, `centered_node` for a name plus one line,
  `information_node` for an eyebrow, title, and description lines, `icon_node` when an icon helps, `list_node` for
  fields, `decision_node` for a branch, `repeated_stack` for many-of-a-thing, `box_label` for a plain box. Text does not
  wrap, so every line must fit the width.
- **Size the box for the copy, not the other way around — and prove it by looking.** The library measures nothing: a
  line longer than its box silently overflows into whatever is next to it, and there is no exception to catch. Fixed
  node components don't expose a font-size override, so width and copy length are the only levers.
  - **Estimate before drawing.** At the library's default sizes, a bold title (`TYPE_SCALE` 21) runs about 12px/char
    and a regular description (18) about 9px/char; a node's usable width is roughly its declared width minus a ~40-unit
    inset (two 21-unit gutters). Check the longest string in your data — the longest role name, the longest label —
    against that budget before picking a node width, not after something clips.
  - **A floating label needs its gap sized to it, not the other way round.** `labeled_connector` and a bare
    `diagram.text` between two nodes aren't clipped by anything, so a label wider than the gap it sits in visually
    overlaps both neighbors even though nothing "errors." Either widen the gap to fit the longest label plus margin, or
    shorten the copy (`"building"`, not `"status:building"`) — check the widest label in the set, not just one.
  - **Detection is visual, not programmatic.** Coordinates that satisfy every `node_port` call can still overflow,
    because overflow is a text-vs-box comparison the library never makes. After every layout change, render the SVG to
    a raster image and look at it — `qlmanage -t -s 1600 -o /tmp <file>.svg` or, for something scriptable,
    `<chrome-binary> --headless --disable-gpu --screenshot=out.png --window-size=<w>,<h> file://<abs-path>.svg` — then
    read the PNG back. Check every box: does any title or description run past its border, does any connector label
    cross into a neighboring node, does any multi-line stack clip its own box.
  - **When it doesn't fit, fix the cause, not the symptom.** Widen the node, shorten the copy, or split it across
    `information_node`'s multiple description lines — don't shrink `stroke_width` or nudge coordinates by eye to hide
    an overflow one pixel at a time.
- **Use the connector helpers.** `node_port(x, y, width, height, side)` for an attachment point instead of a computed
  edge coordinate, `line`/`path` (`dashed=True` for conditional routes) for connectors, `labeled_connector` for a
  captioned horizontal arrow, `junction` for an intentional split, `annotation_callout` for a leader note.
- **A connector spans the gap, never the node.** `node_port` is only as good as the box you hand it: pass the
  component's real height and the arrow starts on the edge; pass a guessed one and the port lands inside the shape, so
  the line is drawn over the node it was leaving. A content-sized component (`information_node`, `list_node`,
  `legend_header`) returns its height — keep it and use it for the port, the next component's position, and anything
  aligned beside it. When the layout needs those heights before `Diagram(height=...)` exists, draw the components once
  on a scratch `Diagram` and read the heights back; measuring costs a few lines and survives a copy change that a
  hardcoded height does not. After rendering, look at every arrowhead and tail: leaking into a box is the failure this
  catches.
- **Fill the canvas.** Under the light theme `background` defaults to None, which leaves the SVG transparent, so the
  figure picks up whatever the host page is behind it — including a dark README. Pass a `background` always. For white,
  override the one key (`palette={"background": "#ffffff"}`) and pass `background="background"`; under
  `DiagramTheme.DARK` leave the theme's own color alone.
- **Frame and explain.** `group_panel` (reserve 55 above for the heading, 34 below for the caption), `swimlane` (first
  144 units are the header), and `boundary_frame` for containment. When roles or connector styles carry meaning, add a
  legend with `legend_header`, `color_key`, and `arrow_key`.
- **Light by default, dark only on request.** A diagram script's bare `uv run scripts/...` invocation writes the light
  theme only — don't render and save a dark copy alongside it unless the user asked for one. `--theme` (default
  `DiagramTheme.LIGHT`) is how a caller opts into dark, not something the script exercises for them. If a dark version
  is requested, check it in both themes before calling it done: the default dark palette draws every role in the same
  gray, so color keys mean nothing there — either omit them under `DiagramTheme.DARK` or override the role colors.
- **Reach for `svg_element` last.** It exists for shapes the library lacks. Resolve its colors with `diagram.color` and
  keep it on the scale.

A diagram is an artifact in its own right. Default to `diagram.save(path)`, with the document linking the SVG, so it
can be regenerated, diffed as text, and reused by more than one page without each one carrying its own copy. Reach
for `diagram.figure(caption=...)` inside a `MarkdownReport` when the Markdown has to travel as a single
self-contained file; that inlines the SVG and makes the page unreadable as a diff. Either way alt text defaults to the
diagram title, which is usually the wrong description, so pass real alt text whenever the title doesn't describe the
picture.

A diagram is a script, and this is the exception to §3's rule that logic belongs in the package. One numbered script
per diagram: the coordinates, the copy, and a `main` that saves the SVG. Nothing imports a diagram, so there is
nothing to reuse, and keeping the drawing beside the data it is drawn from is what makes it editable a year later.
Give the script options only where a caller would really choose — `--output`, `--theme` — each defaulting so the bare
`uv run scripts/...` invocation writes the committed file (§3). Move a diagram into the package only when the program
itself renders it at runtime, at which point it is a feature, not documentation.

---

