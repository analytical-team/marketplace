## 16. Anti-patterns quick reference

The negative space around the rules above. When you find one of these, fix it.

**Architecture**

- Concrete-type-only public APIs (no protocol seam) → lead with a `Protocol`.
- Modules coupling through globals or singletons → talk through protocols and dataclasses.
- Catch-all `utils.py` / `helpers.py` / `models.py` files → give helpers a real home.
- Module-level mutable state → move into a class.
- In-memory dict accumulating state across requests → an expirable SQLite-backed cache with a per-entry TTL (§6).
- Leading-underscore names → restructure so the concept doesn't need to exist as a named thing at all.
- Class created only to hold a `services` reference → module function taking `services` (see §6).
- Behavior nested as a `def`/`async def`/`lambda` closure inside another function → module-level function taking its
  deps as parameters; nest only for a framework-forced callback (dependency factory, ASGI send/receive wrapper,
  decorator, C-library codec) (§6).
- `default_factory=lambda: ...`, or a lambda parking real logic → a named callable (§6).
- Resource/client constructed outside the `Services` registry → own it on `Services` so lifecycle lives in one place.
- `BaseModel` for a plain internal record → frozen dataclass; reserve `BaseModel` for boundaries and validation (§6).
- `os.environ` / `os.getenv` read anywhere in the program → a typed `BaseSettings` field on the root `Settings` or a
  domain settings class it composes (§6).
- Hand-rolled `.env` parsing, or config read before the file is loaded → `load_dotenv()` at the composition root plus
  `env_file` on the root `model_config` (§6).
- Inline `Depends(...)` repeated across handler signatures, old-style `param: T = Depends(fn)`, or `dependencies=[...]`
  on the app/router → a shared `Annotated[T, Depends(fn)]` alias named `SomethingDep` (§6).
- `yield`-based dependency opening/closing a resource per request → own the lifecycle on `Services`/`lifespan` (§6).
- Dependency that needs arguments, written inline or duplicated → a factory returning the dependency, wrapped in the
  alias (§6).
- Cross-cutting gate implemented inside the dependency (unreachable from inner code) → a plain `services`-first
  function, with the dependency as a thin wrapper (§6).
- Optional resource re-checked for `None` at every call site → type it `T | None`, resolve through one `require_*`
  helper (§6).
- `async __init__` faked with lazy connect-on-first-use → cheap sync `__init__` + awaited `setup()`/`close()` driven
  from the composition root (§6).
- Decorator-routed handlers (`@app.get`, `@router.post`) → plain functions registered with `app.add_api_route` (§6).
- Route handler living inside a domain module, forcing it to import sibling domains → move it to a per-domain
  `domain_routes.py` layer of bare handlers; routes import domains, never the reverse (§6).
- Per-module `register(app)` hook, or routes scattered across modules → bare handlers enumerated centrally in
  `create_app`, the one place that lists the whole URL surface (§6).

**Concurrency**

- `threading.Thread` or `multiprocessing` in new async code → `asyncio.TaskGroup` or `asyncio.to_thread` for blocking
  calls.
- Mutable objects shared between coroutines without a lock → `asyncio.Lock` or immutable dataclasses.
- Bare `asyncio.create_task` where `TaskGroup` would do → structured concurrency.
- `time.sleep` in a coroutine → `await asyncio.sleep`.
- Swallowed `CancelledError` → let it propagate; cancellation is not an error.
- Polling loops with `await asyncio.sleep(0)` → `asyncio.Queue` or an event.

**Errors**

- Bare `except Exception:` without re-raising → name what you catch.
- Catch-and-swallow → propagate or model "missing" honestly with `None`.
- Third-party exception leaking across area boundary → wrap at the boundary.
- Logging inside an exception class → log at the catch site.
- `sys.exit()` in library code → raise an exception.
- Domain-exception → HTTP-status mapping scattered across handlers → one translation function per area (§9).
- Server-side fault returned as 4xx, or raw upstream detail leaked to the caller → blame in the status code (your fault
  is 5xx), caller-safe message only (§9).

**Trust boundaries**

- Validating untrusted input with a substring denylist or regex → parse it with the engine's own parser and inspect the
  structure (§10).
- Regex or `str.split` pulling fields out of a format that has a grammar (Python, JSON, YAML, TOML, SQL, RST, Markdown,
  HTML, CSV, URLs, dates) → use the real parser and walk the structure (§10).
- A format emitted by string concatenation or f-string interpolation (hand-built JSON, hand-escaped Markdown, SQL
  assembled from values) → use the serializer, or bind parameters (§10).
- HTML built with f-strings, `str.format`, `%`, or concatenation → `jinja2` with `autoescape=True`, or
  `markupsafe.escape` for a fragment; hand-built HTML is an XSS hole, not a style issue (§10).
- `jinja2.Environment()` left with autoescaping off, or `Markup(...)` wrapping a value that was never escaped →
  `autoescape=True`, and `Markup` only over text you sanitized (§10).
- Jinja2 templates embedded in Python string literals → template files behind a `FileSystemLoader` (§10).
- XML or email assembled as text → build an `lxml.etree` tree, or an `email.message.EmailMessage`; a newline in an
  interpolated header value is header injection (§10).
- Shell command built by interpolating into a string with `shell=True` → an argument list with `shell=False` (§10).
- `yaml.load` with the default loader → `yaml.safe_load`; untrusted XML through the stdlib parsers → `defusedxml` (§10).
- Line-oriented editing of an indentation-sensitive format (YAML, RST) or of Markdown that may contain code fences →
  parse, transform the structure, re-serialize (§10).
- A home-grown format parsed by a chain of `split` calls → write the grammar and parse it, or reuse a format that
  already has a parser (§10).
- Caller values interpolated into SQL or a command string → compose an AST or bind parameters; interpolation is
  injection (§10).
- SQL inspected or rewritten with regex/substring matching → parse it with the engine's own parser, or `sqlglot` when
  there isn't one to reach (§10).
- A single control guarding untrusted input → layer independent controls; apply irreversible locks last (§10).

**Style**

- One client/subsystem's settings, models, and client class split across sibling files (`s3_settings.py`,
  `s3_models.py`, `s3_client.py`) → keep them together in one module named after the client (§4).
- A module split, or padded, to hit a line-count target → cohesion decides the split, not length (§4).
- Docstrings that restate the code → document the contract, or delete the docstring.
- Comments referencing tickets/PRs → context goes in git history.
- Value from a closed set typed as bare `str`/`int` (allowed values in a comment) → model it as an `enum` (§2).
- Shorthand bare enum member imports → use the fully qualified `EnumType.MEMBER` form.
- Wildcard imports → explicit names or `__all__`.
- Multi-line strings built by adjacent-literal concatenation (one quoted fragment per line) → triple-quoted string.

**Testing**

- Tests pinned to one concrete implementation → test the protocol.
- "It ran locally" treated as "it works" → write the automated test.
- Shared mutable fixtures between tests → `scope="function"` fixtures.
- Missing concurrency stress test for a concurrent type → add one.
- `unittest.mock` / `MagicMock` / `monkeypatch` of internals standing in for a client → use the production client
  against a real local, CI, or external instance (§11).
- API route functions called directly → drive the application through its framework test client (§11).
- Database behavior tested against SQLite, a dictionary, or an in-memory repository → use an isolated test database with
  the production engine, schema, constraints, and migrations (§11).
- Synthetic records shaped to make the assertion pass → real fixtures from `data/` or a committed sample (§11).
- A test faked so it passes without the resource it needs → skip it with a message naming the fetch script (§11).
- Tests that only cover the happy path → spend the budget on empty, boundary, malformed, absent, and repeated cases
  (§11).
- Trivial function checks or assertions that restate the implementation → test a consequential contract, invariant,
  regression, edge case, or core workflow instead (§11).
- Test named after the function rather than the behavior → name the behavior; the test list is the specification (§11).

**Reports & diagrams**

- Markdown built with f-strings, `"\n".join(...)`, or a hand-rolled template → `MarkdownReport` (§15).
- A value interpolated into report text with an f-string → `params` on the method, so Jinja does the substitution
  (§15).
- Hand-numbered figure captions (`"Figure 3: ..."`) → `figure(caption=...)`; `render` numbers them in document order
  (§15).
- Mermaid, Graphviz, or hand-written SVG for a diagram → an `mdreport` `Diagram` (§15).
- Hex colors in diagram code → palette keys, or `diagram.color(key)` inside a custom element; hex belongs only in
  Lucide icon arguments and palette overrides (§15).
- Magic coordinates and sizes → `FIBONACCI_SPACE`, `TYPE_SCALE`, the named component heights, and `golden_*` helpers
  (§15).
- A computed box-edge coordinate for a connector → `node_port(...)` (§15).
- The next component positioned by a guessed offset below a content-sized one → use the height that component returned
  (§15).
- A hardcoded height passed to `node_port` for a content-sized node → the port lands inside the shape and the arrow is
  drawn over the node; measure the height on a scratch `Diagram` and lay out from that (§15).
- An arrowhead or tail overlapping a node in the rendered SVG → the port is using the wrong box; fix the height, don't
  nudge the coordinate (§15).
- `Diagram(...)` under the light theme with no `background` → transparent canvas that inherits the host page; pass one
  (§15).
- A diagram inlined into Markdown by default → `diagram.save(path)` and reference the SVG; inline only when the file
  has to be self-contained (§15).
- Node color chosen to imply a role → set `role`; explicit `fill`/`stroke` is for accents only (§15).
- `figure` without `alt_text`, or a diagram figure relying on the title as alt text → describe the picture (§15).
- Color keys in a legend under `DiagramTheme.DARK` with the default palette → every role is the same gray; drop them or
  override the colors (§15).
- A documentation diagram hidden in the package behind a thin script → the drawing is the script; keep it there
  (§3, §15).
- Node text or a connector label that runs past its box/gap in the rendered SVG → widen the box, shorten the copy, or
  widen the gap; the library never wraps or clips, so this only shows up by rendering the file and looking (§15).
- Judging a diagram's layout from its coordinates alone → render it to a PNG (headless Chrome screenshot, `qlmanage
  -t`) and inspect every box before calling the layout done (§15).

**Project layout**

- Logic living in a script rather than the package → move it to `src/myproject/`; scripts are thin CLIs (§3). The
  one exception is a documentation diagram, which is the script (§15).
- `argparse`, raw `sys.argv`, or `input()` parsing in a script → one `@click.command()` over a typed `main` (§3).
- Hand-written validation of a path, range, or closed set → `click.Path(exists=True)`, `click.IntRange`, `click.Choice`
  / an enum; let `click` produce the error (§3).
- Option with a default but no `show_default=True`, or no `help=` → `--help` is the interface people read (§3).
- `required=True`, or a script that errors out when run with no arguments → default every option so the bare
  `uv run scripts/...` invocation works (§3).
- Bare invocation that triggers the expensive path (full corpus, all epochs) → default to a small slice, with a flag to
  ask for the full run (§3).
- Flag whose default is the destructive or costly behavior (`--no-overwrite`) → invert it so you opt in (§3).
- Script with no module docstring, or one lacking a `Usage:` block of runnable `uv run ...` lines → add it (§3).
- `Usage:` lines that no longer parse against the script's options → keep them in sync; a stale invocation is worse than
  none (§3).
- Scripts unnumbered, or numbered `1`, `2`, `3` with no room to insert → group by category and step by tens (§3).
- Renumbering existing scripts to make room → insert at an intermediate number instead; the old names are referenced
  elsewhere (§3).
- Datasets, weights, or generated outputs committed to git → gitignore `data/` and provide a script that reproduces it
  (§3).
- Code imported from `data/` → it holds bytes, not modules (§3).
- Package directory at the repo root instead of `src/` → use the `src/` layout so tests exercise the installed package
  (§3).

---

_This guide is a distillation of conventions from strict-typed, async-first Python. The strong opinions — protocol
seams, structured concurrency, typed exception hierarchies, tests as contract, no private names, no global state — are
what make the resulting code safe to change. Adjust the thresholds to your targets; keep the principles._
