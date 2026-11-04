## 2. Naming

- **Classes** — `UpperCamelCase`, full words. No abbreviations except terms that are abbreviations everywhere (`URL`,
  `JSON`, `ID`, `HTTP`). Acronyms are uppercased: `JSONDecoder`, `HTTPClient`.
- **Functions & methods** — `lower_snake_case`, full words. Methods should read as English at the call site:
  `bridge.evaluate(script)`, `store.load(note_id)`, not `bridge.eval(s)`.
- **Protocols & abstract base classes** — name after the **capability or role** they represent: `NoteStore`,
  `PromptEncoder`, `Sendable`. Avoid `-Base`, `-Interface`, `-Mixin`, or `-Manager` suffixes glued onto names that
  aren't really capabilities. If you struggle to name a protocol after a real capability, it may not be earning its
  keep.
- **Parameters** — descriptive names. Avoid `value`, `data`, `result`, `item` unless the thing genuinely is opaque at
  that point.
- **Booleans** read as assertions: `is_enabled`, `has_changes`, `can_retry`.
- **Files / modules** — `lower_snake_case`, named after the primary type they contain (see §4).
- **Short local names** (`i`, `c`, `x`) are fine in tight scopes like loop bodies and short lambdas; full words
  everywhere persistent.
- **No leading underscores** on any name — no `_helper`, `__internal`, or `_MyClass`. Underscore-prefixed names
  communicate "private" by convention, and this guide bans that pattern entirely (see §5).

### Prefer enums over magic strings

**When a value is drawn from a small, closed set, model it as an `enum`, not a bare `str` (or `int`).** A field typed
`str` with a comment listing the allowed values is the type lying about itself — the comment drifts, typos pass type
checking, and the valid set isn't greppable. An enum makes the closed set explicit, lets the type checker reject invalid
members, and gives every value a greppable symbol.

```python
import enum

# Avoid — the type permits any string; the real contract lives in a comment that will drift:
auth_method: str | None = None  # "session" | "jwt" | "api_key" | None


# Correct — the closed set is the type. Subclass StrEnum when the wire/JSON value must stay a plain string:
class AuthMethod(enum.StrEnum):
    SESSION = "session"
    JWT = "jwt"
    API_KEY = "api_key"


auth_method: AuthMethod | None = None
```

Reach for `enum.StrEnum` (or `enum.IntEnum`) when the value crosses a serialization boundary and must compare equal to
its raw string (or int) form; use a plain `enum.Enum` otherwise. A `typing.Literal` is acceptable for a private, one-off
set that never needs members, iteration, or methods — but prefer an enum the moment the set is shared across modules or
gains behavior. Define the enum next to the type that owns it (§4) and import it where needed rather than re-spelling
the strings.

### Enum member qualification

**Always use fully qualified enum members.** Prefer `Color.BLUE` over a bare re-exported name, `TaskState.PENDING` over
an imported alias.

```python
# Correct — type is unambiguous without reading surrounding context:
language = NLLanguage.ENGLISH
state = TaskState.PENDING
raise PromptEncodingError.CANCELLED

# Avoid — type must be inferred; invisible in diffs and searches:
language = ENGLISH  # where did this come from?
state = PENDING
```

**Rationale:**

- Explicit types survive being read out of context (grep results, diffs, code review, agent analysis).
- Symbols are greppable — `TaskState.PENDING` appears in search results; a bare `PENDING` does not.
- Reduces ambiguity when the same name exists in multiple enums.

**Exception:** shorthand is acceptable inside a `match` arm, where the enum type is stated in the subject expression and
cannot be misread:

```python
match language:
    case NLLanguage.ENGLISH:  # type is declared in the match subject
        ...
    case NLLanguage.FRENCH:
        ...
```

---

