## 10. Trust boundaries & untrusted input

When code accepts input from outside its trust boundary — a query a caller writes, a path a caller names, anything that
crosses from a user to an engine — treat **safety as a correctness domain** and read these as prescriptive.

### Validate by parsing, not by string-matching

To decide whether untrusted input is allowed, parse it into the same structure the engine will act on and inspect that —
never pattern-match the raw text. A denylist of forbidden substrings is bypassable (comments, casing, encoding,
whitespace) and an allowlist regex rejects valid input; both drift from what the engine actually does. Validate with the
engine's _own_ parser where you can, so there is no second grammar to diverge from and slip something past.

```python
def assert_read_only(self, sql: str) -> None:
    """Reject anything but a single read-only SELECT, using the engine's own parser.

    Validates with the engine's serializer so the parse matches exactly what it
    would execute — no second parser to diverge from and slip a write past.
    """
    parsed = self.serialize(sql)  # the engine's own parse, not a regex
    statements = parsed.get("statements", [])
    if len(statements) != 1:
        raise QueryRejected("exactly one statement is allowed")
    if statements[0]["node"]["type"] not in READ_ONLY_NODE_TYPES:
        raise QueryRejected("only read-only SELECT queries are allowed")
```

### Read structured formats with a parser, not with string operations

The same instinct applies outside the trust boundary, and it is not a rule about Python source: **whenever a format has
a grammar, use a parser for it — and where you must produce that format, use a serializer or a template engine.** This
covers everything a program routinely reads and writes: Python, JSON, YAML, TOML, SQL, reStructuredText, Markdown,
HTML/XML, CSV, URLs, dates, email messages, semantic versions, `.ini`/config files, log formats with a defined shape,
and any DSL you have invented yourself. Each of those has a specific library named below — pick from that list rather
than deciding per call site.

Reaching for `str.split`, `str.startswith`, `str.replace`, or a regex to pull a field out of one of these is
re-implementing a grammar you don't own. It fails on exactly the cases the real parser handles: nested quoting, escapes,
comments, line continuations, multi-line and folded values, significant indentation, delimiters appearing inside quoted
fields, anchors and references, encodings, BOMs, and every construct the format gained after you wrote the regex. The
failure is usually silent — the traversal returns a plausible-looking wrong answer rather than raising.

Reach for the grammar in this order: the format's **own parser** (best — no second grammar to diverge from), then the
**stdlib parser** where one exists, then the **established third-party parser** named below, then a **grammar you define
explicitly** for a format that has none off the shelf. Hand-rolled string traversal is not on the list.

Several of the libraries named below are third-party, which §12 would otherwise put a burden of proof on. Consider that
burden discharged: a format's parser is precisely the "concrete justification, no reasonable stdlib path, bounded scope"
case §12 describes — the alternative is maintaining a grammar yourself, which is the thing this section exists to
forbid. Still scope each one to the area that uses it and record it in the dependency inventory.

### The parser for each format

**Python** — `ast.parse`, then walk the tree with `ast.NodeVisitor`, `ast.walk`, or `ast.get_docstring` to find imports,
definitions, decorators, or call sites. A regex over source text cannot tell a name in a string literal from a name in
code, misses a call split across lines, and silently reports nothing when it drifts. Write source back with
`ast.unparse`, or edit the original text at the node's `lineno`/`col_offset` when formatting must be preserved.

**JSON** — `json.loads`/`json.dumps`. Never assemble JSON by concatenating or f-string-interpolating values into a
literal, and never pluck a field with a regex; one embedded quote or newline in a value produces text that is either
invalid or silently wrong. Serialize the object.

**YAML** — `yaml.safe_load` (never `yaml.load` with the default loader, which constructs arbitrary Python objects) and
`yaml.safe_dump` to write. YAML's indentation, anchors, aliases, block scalars, and implicit typing (`no` is a boolean,
`1.0` is a float, an unquoted version string is not what you meant) defeat line-oriented editing in particular.

**TOML** — `tomllib.load` (stdlib) to read. `tomllib` is read-only: to write, use `tomli-w`; to edit an existing file in
place while preserving comments and formatting, use `tomlkit`, whose round-tripping is the reason to prefer it over
load-then-dump. Don't regex `pyproject.toml`.

**SQL** — the strongest form of this rule, because it is also §10's trust boundary. Bind parameters rather than
interpolating values. Where you must _inspect_ or _rewrite_ a statement, use **`sqlglot`** — parse to an expression tree
with `sqlglot.parse_one(sql, dialect=...)`, walk or transform it with `find_all`/`transform`, and render it back with
`.sql(dialect=...)`. It is the default choice for SQL in this guide: it parses and transpiles across dialects, it gives
you a typed node tree rather than tokens, and it is pure Python with no engine to stand up. A regex cannot tell a
keyword from the same word inside a string literal or a comment, so "does this statement write?" answered by substring
match is answered wrong.

```python
# Avoid — substring matching over SQL; "delete" may be a column name, a string
# literal, or inside a comment, and a CTE hides the real statement type:
if "delete" in sql.lower() or "update" in sql.lower():
    raise QueryRejected("writes are not allowed")


# Correct — parse to an expression tree and ask what the statement IS:
def assert_read_only(sql: str, *, dialect: str) -> None:
    """Reject anything but a single read-only SELECT.

    Raises:
        QueryRejected: if sql is not exactly one read-only SELECT.
        sqlglot.ParseError: if sql does not parse in the given dialect.
    """
    statements = sqlglot.parse(sql, dialect=dialect)
    if len(statements) != 1:
        raise QueryRejected("exactly one statement is allowed")
    if not isinstance(statements[0], sqlglot.exp.Select):
        raise QueryRejected("only read-only SELECT queries are allowed")
```

Where the engine exposes its **own** parser, prefer that for a gate you are relying on for safety (as `assert_read_only`
in "Validate by parsing" does) — there is then no second grammar to diverge from what actually executes. Use `sqlglot`
when there is no such parser to reach, when you need to work across dialects, or when you are transforming rather than
merely admitting a statement. Building SQL still means composing an expression tree or binding parameters, never
interpolating caller values into text (see "Compose, don't interpolate").

**reStructuredText** — `docutils`: `docutils.core.publish_doctree` gives a document tree you walk with a
`docutils.nodes.NodeVisitor` for directives, roles, sections, and links, and `publish_string` renders it back out. RST's
indentation-sensitive directive bodies and inline markup rules are not something a regex reproduces. Sphinx-flavored RST
needs Sphinx itself to resolve its extra directives and roles.

**Markdown** — `markdown-it-py`, which parses to a token stream you walk (and, with `mdformat`, re-serializes). Match
neither `^#` for headings nor `\[.*\]\(.*\)` for links: fenced and indented code blocks contain text that looks exactly
like markup and must not be treated as such, which is the single most common bug in regex-based Markdown handling. When
you emit Markdown, escape through the library rather than hoping the interpolated text contains no `*`, `_`, `[`, or
backtick.

**HTML** — `lxml.html` (fast, XPath) or `BeautifulSoup` (lenient, forgiving of real-world markup) to parse;
`html.parser` in the stdlib only for something trivial. Never a regex — HTML is not a regular language, and the classic
`<([a-z]+)[^>]*>` breaks on attributes containing `>`, unclosed tags, and comments. Use `lxml.cssselect` or XPath to
select nodes rather than walking text.

**XML** — `lxml.etree` or the stdlib `xml.etree.ElementTree` for trusted input; for **untrusted** XML use `defusedxml`,
because the stdlib parsers are vulnerable to entity-expansion and external-entity attacks (§10's trust boundary applies
directly here).

**CSV** — `csv` in the stdlib, which handles the embedded delimiters, quotes, and newlines that `str.split(",")`
corrupts. Reach for `pandas.read_csv` only when you are already doing dataframe work, not as a parser of first resort.

**URLs** — `urllib.parse` (`urlparse`, `parse_qs`, `urlencode`, `urljoin`) for parsing and for building query strings.
Never concatenate query parameters by hand; `urlencode` does the percent-encoding you will otherwise get wrong.

**Dates** — `datetime.fromisoformat` for ISO-8601 (Python 3.11+ handles offsets and `Z`),
`email.utils.parsedate_to_datetime` for HTTP/email dates, and `dateutil.parser` only for genuinely unknown-shape input
from humans. Never `strptime` against a format you guessed, and never slice a timestamp string by index.

### Produce markup with a template engine, not with string formatting

The mirror of the parsing rule: **when you generate a structured format, use its templating or serialization library —
never f-strings, `str.format`, `%`, or concatenation.** A hand-built string has no idea what context it is interpolating
into, so it cannot escape correctly, and the failure mode is not a cosmetic glitch — it is XSS in HTML, injection in
SQL, a corrupt document everywhere else.

- **HTML** — `jinja2` with `autoescape=True` (always; it is off by default in a bare `Environment`, so set it
  explicitly). Autoescaping is the whole reason to use the engine: it escapes `<`, `>`, `&`, and quotes per
  interpolation site. Mark a value safe with `markupsafe.Markup` only when you have escaped or sanitized it yourself,
  and treat every such call as a thing a reviewer must look at. In a FastAPI app this is `Jinja2Templates`; for
  standalone fragments, `markupsafe.escape` directly.
- **XML** — build a tree with `lxml.etree` / `ElementTree` and serialize it, rather than templating tags as text; the
  serializer escapes attribute and text content for you.
- **Email** — `email.message.EmailMessage` and the `email` package, which handle MIME structure, headers, and encoding.
  Never assemble headers by concatenation: a newline in an interpolated value is header injection.
- **Shell commands** — no template at all. Pass an argument list to `subprocess` with `shell=False` (the default), so
  there is no shell grammar to escape into. `shlex.quote` is for the case where a shell is genuinely unavoidable.
- **Everything else** — the format's serializer, per the list above: `json.dumps`, `yaml.safe_dump`, `csv.writer`,
  `urlencode`, `sqlglot` / bound parameters.

Jinja2 templates live in their own files loaded through a `FileSystemLoader`, not in Python string literals — they get
syntax highlighting, they are diffable, and the separation keeps markup out of logic. Reserve inline `Template(...)` for
a short fragment with no reuse.

```python
# Avoid — no escaping; a display name containing "<script>" is now executable,
# and one containing a quote breaks out of the attribute:
html = f'<a href="/users/{user.id}" title="{user.name}">{user.name}</a>'


# Correct — the engine escapes each interpolation for its context:
environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader("templates"),
    autoescape=True,  # off by default; the reason we are using jinja2 at all
)
html = environment.get_template("user_link.html").render(user=user)
```

```python
# Avoid — a regex guessing at Python's grammar; misses aliases, parenthesized
# and multi-line imports, and matches the word inside a comment or docstring:
imports = re.findall(r"^import (\w+)", source, re.M)


# Correct — the language's own parser answers the question:
def imported_modules(source: str) -> set[str]:
    """Returns every top-level module name imported by source.

    Raises:
        SyntaxError: if source is not valid Python.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names
```

The same shape holds for a data format — parse, then query the structure:

```python
# Avoid — line-oriented traversal of a format with significant indentation,
# block scalars, and implicit typing. Matches the key at any nesting depth,
# inside a comment, or inside a multi-line string value:
for line in config_text.splitlines():
    if line.strip().startswith("image:"):
        image = line.split(":", 1)[1].strip()


# Correct — parse once, then ask the structure:
def container_images(config_text: str) -> list[str]:
    """Returns the image of every container in a deployment manifest.

    Raises:
        yaml.YAMLError: if config_text is not valid YAML.
    """
    document = yaml.safe_load(config_text)
    containers = document["spec"]["template"]["spec"]["containers"]
    return [container["image"] for container in containers]
```

### Define a grammar when there isn't one to reuse

When you invent a format — a query mini-language, a rule expression, a structured log line, an ID with internal
structure — write down its grammar and drive a parser from it rather than growing a chain of `split` calls. A grammar is
a single reviewable statement of what is legal, it gives you a real error with a position when input doesn't match, and
it forces the ambiguous cases (escaping, precedence, empty fields) to be decided once instead of discovered later.
Prefer not inventing a format at all — an existing one with an existing parser is almost always cheaper.

### Let the parser's error be the failure signal

A `SyntaxError`, `JSONDecodeError`, or `yaml.YAMLError` reports the line and column and names the problem; a regex just
returns nothing and looks like a legitimate empty result. Wrap the parser's exception at your area's boundary (§9) so it
doesn't leak, but keep it as the thing that fires — don't pre-validate with a regex and then parse.

String operations remain appropriate for genuinely unstructured text (a free-form message, a log line you wrote
yourself), for cheap pre-filters before a real parse, and for building a string that is only ever read by a human. They
are never the parse itself, and never the serialization of a format someone else will parse.

### Compose, don't interpolate

Build the structured input you hand to the engine — SQL, a command — by composing an AST or binding parameters, not by
interpolating caller values into a string. A value the caller controls is a **parameter** (a numbered placeholder bound
out-of-band), never a fragment of the statement text. String interpolation is how injection happens; the boundary should
make it structurally impossible, not catch it after the fact. Reach for explicit quoting/escaping only where binding is
genuinely unavailable — and then through one audited helper, never ad hoc.

### Layer independent controls; apply irreversible locks last

Defense in depth: put more than one independent control between untrusted input and harm, so bypassing one does not open
the door. A statement-shape gate (the AST check above) proves what the query _is_; a separate engine sandbox — disabled
filesystems, frozen configuration — holds even if that gate is ever bypassed, and neither relies on the other. Apply
one-way lockdowns **last**, after everything else is in place, and document the ordering, because they cannot be undone
for the life of the resource.

```python
def lock_down(con: Connection) -> None:
    """Sandbox the connection. Applied once, last — these locks are one-way."""
    con.execute("SET disabled_filesystems = 'LocalFileSystem,HTTPFileSystem'")
    con.execute("SET autoload_known_extensions = false")
    con.execute("SET lock_configuration = true")  # freezes all of the above
```

---

