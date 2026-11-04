---
name: python-coding
description: >
  Read BEFORE writing or editing ANY Python code — new files, new functions,
  edits to existing ones, scripts, tests, FastAPI routes, or a one-line fix.
  The house style guide: strict typing, async-only concurrency, protocol-led
  APIs, a Services registry, pydantic-settings for all config, click CLIs in
  numbered scripts, typed exception hierarchies, parse-don't-regex for any
  format with a grammar, no-mock testing, and mdreport for every generated
  Markdown report and diagram. Triggers on: "write a Python
  ...", ".py" files, python/pytest/FastAPI/pydantic/asyncio/click/uv work,
  generating a Markdown report or a diagram/SVG from Python, refactoring
  Python, reviewing Python for style, or answering "how should I
  structure this in Python". Also read it before reviewing someone else's
  Python against these conventions.
---

# Python coding style

Load `references/style-guide.md` for the full guide with rationale and worked
examples. Read the relevant section before writing code in that area — the
checklist below is a reminder, not a substitute.

Rules with **safety or correctness** consequences (concurrency, errors, trust
boundaries) are prescriptive. Style rules (naming, layout) are for consistency.

## Before you write

1. If the rule you need is in the checklist and unambiguous, apply it.
2. Otherwise open the matching section of `references/style-guide.md`. Section
   numbers below map to headings in that file.
3. Run everything with `uv run` — `uv run pytest`, `uv run scripts/...`.
4. **Static quality gate**: Before declaring work complete, verify with both a
   linter (`ruff check`) and static type checker (`mypy --strict` or `ty check`).
   Never rely solely on passing test suites, as dynamic tests can easily miss
   uncalled methods, dead branches, or deprecated type overloads.

## Checklist

**Language (§1)** — Python 3.12+, `mypy --strict` clean. `from __future__ import
annotations` at the top of every file. Annotate every signature, attribute, and
return. Annotate generator context managers with `collections.abc.Generator[T]`
(for `@contextmanager`) and `collections.abc.AsyncGenerator[T]` (for
`@asynccontextmanager`) — **never `Iterator[T]` or `AsyncIterator[T]`**, which
modern type checkers and typeshed deprecate on context managers. No `threading`,
`multiprocessing`, `concurrent.futures`, or `queue.Queue` in new code — `asyncio`,
and `asyncio.to_thread` for blocking I/O.
Pin every dependency (`==`) and `requires-python = "==3.12.*"`. Python scripts
over shell scripts for anything non-trivial.

**Naming (§2)** — `UpperCamelCase` classes, `lower_snake_case` functions and
modules, booleans read as assertions. Protocols named for the capability
(`NoteStore`), never `-Base`/`-Interface`/`-Manager`. **No leading underscores
on any name.** A value from a closed set is an `enum` (`StrEnum` when it crosses
a wire), never a bare `str` with the options in a comment. Always fully
qualified members: `TaskState.PENDING` — bare only inside a `match` arm.

**Layout (§3)** — `src/<package>/` + `scripts/<category>/NNN_verb.py` + `tests/`
+ gitignored `data/`. Never touch `sys.path` (one exception: importing a
numbered script itself). Logic lives in the package; a script is a thin CLI over
it. Every script: one `@click.command()`, a module docstring ending in a
`Usage:` block of runnable `uv run` lines, `show_default=True` and `help=` on
every option, `click.echo` not `print`, no `required=True` — **every option
defaults so the bare invocation does the sensible, cheap, non-destructive
thing.** Number by tens within a category.

**Modules (§4)** — One primary class per file, named for it; a whole
client/subsystem (its settings, models, exceptions, client) stays in one module
even when long. Cohesion decides splits, never line count. No `utils.py`,
`helpers.py`, `common.py`. **No module-level mutable state** — constants only.

**API design (§5)** — Every name is public; `__all__` is the real boundary, keep
it small. Lead the public surface with `typing.Protocol` and dataclasses; export
the concrete type, but annotate dependencies against the protocol. `abc.ABC`
only when you need nominal subtyping. Modules talk through protocols and
dataclasses, never shared globals.

**Structure & wiring (§6)** — Classes own resources; behavior is a module-level
function taking `services` first. One `Services` registry owns every
resource — cheap sync `__init__`, awaited `setup()`, mirrored `close()`, driven
from the composition root. No nested `def`/`lambda` parking logic (framework
callbacks excepted). Optional resources are `T | None` behind one `require_*`
helper. Cross-request state goes in an expirable cache, never a dict. Frozen
dataclasses internally, `BaseModel` at boundaries. **Never read `os.environ`/
`os.getenv`** — every variable is a `BaseSettings` field; domains own their
settings with an `env_prefix`, the root `Settings` composes them; `load_dotenv()`
at the composition root. Environment variables live in a gitignored `.env`
loaded by `pydantic-settings`; dev/test-specific values go in `.env.dev`, which
overrides `.env` (list both in `env_file`, `.env.dev` last — later files win).
FastAPI: `SomethingDep = Annotated[T, Depends(fn)]`
aliases only, no `yield` dependencies, routes registered explicitly with
`app.add_api_route` in `create_app` (no `@app.get`), bare handlers in
`domain_routes.py` modules that import domains and never each other.
For Starlette Templates, use the full API reference:
<https://starlette-templates.tycho.engineering/llms-full.txt>.

**Docs (§7)** — Docstrings on every public class, method, function. Document the
contract — invariants, preconditions, what it raises — not the implementation.
No docstrings restating the name. No ticket/PR references in code.

**Concurrency (§8, correctness)** — `asyncio.Lock` around mutable shared state,
frozen dataclasses between coroutines, `asyncio.TaskGroup` for structured work
(`gather` for a fixed independent set; bare `create_task` only when the lifetime
truly outlives the scope, stored and cancellable). `asyncio.Queue`, never a spin
wait. `await asyncio.sleep`, never `time.sleep`. Never swallow `CancelledError`.

**Errors (§9)** — A typed exception hierarchy per area, subclasses naming
failure modes, dataclass fields carrying context, `raise ... from original`.
Document `Raises:`. Wrap foreign exceptions at the boundary. One pure function
maps an area's hierarchy to HTTP status. Your fault is 5xx even if upstream said
401; never leak internal detail to callers. No bare `except Exception`, no
swallowing, no logging inside exception classes, no `sys.exit()` in a library.

**Trust boundaries (§10, correctness)** — Validate by parsing with the engine's
own parser, never a denylist or regex. Any format with a grammar gets its real
parser: `ast`, `json`, `yaml.safe_load`, `tomllib`/`tomlkit`, `sqlglot`,
`docutils`, `markdown-it-py`, `lxml.html`/`BeautifulSoup`, `defusedxml` for
untrusted XML, `csv`, `urllib.parse`, `datetime.fromisoformat`. Emit through the
serializer or template engine: `jinja2` with `autoescape=True` (templates in
files), `ElementTree`, `EmailMessage`, `json.dumps`, bound SQL parameters,
`subprocess` argument lists with `shell=False`. Compose, don't interpolate.
Layer independent controls; apply irreversible lockdowns last.

**Testing (§11)** — Tests protect behavior for tomorrow; they are also the
documentation. **No `unittest.mock`, `MagicMock`, or monkeypatching internals** —
drive the real thing: framework test clients, a real test database with the
production engine and migrations, real clients, real fixtures. Arranging real
state (`tmp_path`, `monkeypatch.setenv`) is fine. Skip with a message naming the
fetch script when a resource is genuinely absent. Name the behavior, not the
function. Spend the budget on empty/boundary/malformed/absent/repeated cases,
not the happy path. Don't test trivia for coverage. Add a `TaskGroup`
concurrency stress test for anything with concurrent callers. If the seam to
test a behavior doesn't exist, building it is part of the change.

**Before writing a unit test, ask what it's actually for.** Most unit tests
don't find bugs — they mark territory, freezing code in place so nobody casually
rewrites it; if that's all this one does, skip it. Don't write tests that
re-hardcode "this ran once and produced X" as correct — that's not verification,
it's superstition. If correctness genuinely matters, use randomized /
property-based inputs against a stable API instead of a couple of hand-picked
cases; if the logic doesn't matter much, don't test it to satisfy a coverage
habit. And don't over-mock to isolate a "unit" — if the test only checks that
your mocks agree with your mocks, it isn't testing anything real. Test real
inputs against real outputs. **Write a test because a specific failure mode
worries you, not because the code exists.**

**Dependencies (§12)** — Stdlib by default. A new one needs concrete
justification, no reasonable stdlib path, stable provenance, bounded scope.
Format parsers (§10) clear this bar by construction. Record it in the inventory.

**Imports (§13)** — stdlib / third-party / local, blank line between. `from
__future__ import annotations` everywhere. No wildcards outside `__init__.py`.
No import-time side effects.

**Multi-line strings (§14)** — Triple-quoted. Never adjacent-literal
concatenation — one missing trailing space silently corrupts the text.

**Reports & diagrams (§15)** — **Every generated Markdown report is built with
`mdreport`'s `MarkdownReport`** — never f-strings or `"\n".join(...)`. Chainable
builder: `title`, `heading`, `text`, `bullet_list`, `code_block`, `callout`,
`table`/`csv` for Polars frames, `figure`, `frontmatter`,
`table_of_contents`, then `render()` or `save(path)`. Interpolate through
`params` (Jinja), never an f-string. Captions are auto-numbered — don't write
`Figure 3` yourself; always pass `alt_text`. **Every diagram is an `mdreport`
`Diagram`** — never Mermaid, Graphviz, or hand-written SVG. Place components at
explicit coordinates (`title_node`, `centered_node`, `information_node`,
`icon_node`, `list_node`, `decision_node`, `box_label`, `group_panel`,
`swimlane`, `boundary_frame`, legend helpers) and connect with `line`/`path` off
`node_port`. **Save it: `diagram.save(path)` writes the SVG the doc references**
— `figure(caption=...)` inlines it, which is for Markdown that must be
self-contained. Semantics come from `NodeRole`, colors from palette keys or
`diagram.color(...)` — no hex. Sizes come from the golden-ratio scale
(`FIBONACCI_SPACE`, `TYPE_SCALE`, the named heights, `golden_*`); position and
**every `node_port` height** come from the height a component returned, never a
guess — a wrong height puts the port inside the node and the arrow leaks over
it, so measure on a scratch `Diagram` if you need heights first. Always pass a
`background`; the light theme is transparent by default. Check both themes.
One numbered script per diagram — the drawing is the script, the §3
exception, with options like `--output`/`--theme` only where a caller would
really choose. Full API:
<https://mdreport.tycho.engineering/llms-full.txt>.

## Reviewing existing code

§16 of the guide is an anti-pattern quick reference: each entry pairs a smell
with its fix, grouped by architecture, concurrency, errors, trust boundaries,
style, testing, reports and diagrams, and layout. Use it as the review checklist when auditing Python
rather than re-deriving the rules.
