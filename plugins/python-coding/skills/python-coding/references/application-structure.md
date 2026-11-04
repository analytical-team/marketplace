## 6. Application structure & dependency wiring

Dependencies are wired through a single `Services` registry and plain functions — not ad-hoc globals or service-locator
classes.

### Classes hold resources; functions use them

- A **class** earns its place when it owns a resource, client, or long-lived/mutable state: a database pool, a cache, an
  HTTP or directory client, a background-task supervisor. Construct and own these on the central `Services` registry and
  nowhere else (§4 forbids module-level globals; `Services` is where shared state lives), so lifecycle — setup and close
  — is in one place.
- **Behavior that merely uses those resources is a module-level function that takes `services` (or the single service it
  needs) as its first parameter** — not a class. Do not introduce a class just to hold a `services` reference and hang
  methods off it: it reads as something that ought to be registered on `Services`, yet registering it would only add
  wiring and often an import cycle. A function `do_thing(services, ...)` has no lifecycle and is trivially testable with
  a fake `services`.

```python
# Resource: constructed and owned by Services.
class Services:
    def __init__(self) -> None:
        self.cache = Cache(...)
        self.databases = PostgresRegistry(...)


# Behavior: a plain function taking services first.
async def list_api_keys(services: Services, *, dsid: str) -> list[ApiKeyInfo]:
    async with acquire(services) as conn:
        ...
```

### Prefer module-level functions to nested closures

Behavior belongs at module level, taking its dependencies as parameters — not nested inside another function as a `def`,
`async def`, or `lambda` that closes over them. A nested function hides a unit of behavior where it can't be imported,
named in a traceback, or tested on its own, and it usually closes over local state that a parameter would carry just as
well. This is the same instinct as preferring a function to a class that only holds `services` (above): if a nested
helper needs only values you could pass it, lift it to the module and pass them. A cross-cutting check is the worked
example — `forbid_unless_member(services, *, dsid, group_ids)` is a module-level function, and the dependency factory
that gates a route merely _calls_ it; it does not re-implement the check inside a closure.

Nesting is warranted only when a framework or library hands you state you cannot reach any other way — and even then the
closure stays a thin shell that delegates real work to a module-level function. The legitimate cases:

- a **FastAPI dependency factory** closing over its fixed arguments (see "Parametrize a dependency with a factory");
- an **ASGI middleware** wrapping the per-request `send`/`receive` it is handed in `__call__` — it closes over
  request-lifetime state (a response-started flag, an inbound queue, a cancel scope) that has no life outside that one
  call;
- a **`@functools.wraps` decorator** wrapping the handler it decorates;
- a **callback a C or library API demands** — an `asyncpg` type codec, a `threading.Timer` fire, a `StreamingResponse`
  generator binding the per-request spill file it must delete on completion.

Lambdas follow the same line: fine as a **deferred thunk an API demands**
(`cache.remember(key, ttl, lambda: fetch(...))`), a lazy accessor, or a sort `key=`; never as a place to park logic. Use
a named callable for `default_factory=` (`Field(default_factory=list)`), never `default_factory=lambda: ...`.

### Resources construct synchronously, set up asynchronously

A constructor cannot be `async`, so a resource that needs I/O to become usable splits initialization in two. `__init__`
does only cheap, synchronous wiring — open a handle, read settings, allocate the lock. An awaited `setup()` does the I/O
— connect the pool, fetch initial state, attach databases — and must run once before the first request is served.
Shutdown mirrors it: a `close()` (or `aclose()`) releases what `setup()` acquired. The composition root drives all three
from one place (a FastAPI `lifespan`, a CLI `main`), so every resource opens and closes in the same order, once.

A resource is legal to construct but not yet usable in the window between `__init__` and `setup()`; keep that window
inside single-threaded startup, before anything concurrent can touch it. Don't paper over a missing `setup()` with lazy
"connect on first use" guards scattered through the methods — that smears the lifecycle the registry exists to
centralize.

```python
class QueryEngine:
    def __init__(self, settings: Settings) -> None:
        self.connection = connect(settings)  # cheap, synchronous
        self.lock = asyncio.Lock()

    async def setup(self) -> None:
        """Awaited once at startup, before the server serves."""
        await self.attach_databases()
        self.lock_down()
```

### Optional resources are typed `T | None`, resolved through a `require_*` helper

A resource that may not be configured in a given deployment is typed `T | None` on `Services` and left `None` when its
configuration is absent — the app runs degraded rather than refusing to start. Callers do not each re-check for `None`:
a single `require_thing(services) -> Thing` helper returns the resource or raises one uniform "not configured" error (a
503 at an API boundary). Handlers then receive a non-`None` value, and the unconfigured branch — its message, its status
code — lives in exactly one place per resource.

```python
def require_platform_store(services: Services) -> PlatformStore:
    """Return the platform store, or raise 503 when it is not configured."""
    store = services.platform_store
    if store is None:
        raise HTTPException(status_code=503, detail="projects are unavailable")
    return store
```

### Cross-request state belongs in an expirable cache, not an in-memory dict

The tempting shortcut is a `dict` — module-level, or hung on a long-lived object — that accumulates state between
requests. It is a memory leak with no expiry, lost on restart, and wrong the moment a second instance runs. §4 already
bans the module-level case; the rule here is stronger: **state that outlives a single request belongs in a local cache
that can expire**, not in process memory.

Reach for a small SQLite-backed cache — one file, written and read by this process — keyed by a string, with a per-entry
TTL and a compute-on-miss helper. Sessions, resolved directory lookups, anything derived-and-reusable goes there: it
bounds memory by expiring rows, survives a restart, and gives every cached thing one place with one eviction story.
Reconstruct it on demand through the cache rather than holding it live.

```python
class Cache:
    """Async SQLite cache: get/set with TTL and compute-on-miss."""

    async def get(self, key: str, default: Any = None) -> Any:
        """Return the cached value, or default if missing or expired (deletes on expiry)."""
        ...

    async def set(self, key: str, value: Any, expire: float | None = None) -> None:
        """Store key -> value, expiring after `expire` seconds (None = no expiry)."""
        ...

    async def remember(
        self, key: str, ttl: float | None, callback: Callable[[], Awaitable[T]]
    ) -> T:
        """Return the cached value, or compute it via callback and store it under ttl."""
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await callback()
        await self.set(key, value, expire=ttl)
        return value
```

This is not a ban on an in-process collection that lives for a single operation and is guarded by a lock (§8) — a
request-scoped buffer or a bounded work queue is fine. The line is **accumulation across requests**: the moment a dict's
lifetime is "the process," it should have been a cache with a TTL.

### Dataclasses for internal data; BaseModel at boundaries

- Use `@dataclass` (frozen for anything passed between coroutines, §8) for internal domain types and data moved between
  functions. Build one straight from a database row with `Type(**dict(row))` when the selected columns match its fields,
  rather than a hand-written `from_row` constructor.
- Use a pydantic `BaseModel` at **boundaries** — API request/response shapes, settings and config, and anywhere input is
  untrusted or needs validation, coercion, or JSON (de)serialization. The validation is the reason to reach for it;
  don't use it for a plain internal record that a dataclass models more cheaply.

### Settings compose from the domains that own them

One `settings.py` defines the root `Settings(BaseSettings)` — built on `pydantic-settings`, loaded once at startup, held
on `Services` and reached as `services.settings`. Nothing else reads the environment; a setting that isn't on `Settings`
(or a domain settings class it composes) does not exist.

**Never read `os.environ` (or `os.getenv`) directly.** Every environment variable enters the program through a
`BaseSettings` field and nowhere else. A raw `os.environ["API_KEY"]` is an untyped, uncoerced, undocumented, unvalidated
read that fails at the moment of use rather than at startup, is invisible to anyone auditing what the program is
configured by, and can't be overridden in a test without mutating process state. A `BaseSettings` field gives you the
type, the default, the validation, and one greppable declaration of the whole configuration surface.

```python
# Avoid — untyped, unvalidated, undiscoverable, and blows up deep inside a request:
timeout = int(os.environ.get("HTTP_TIMEOUT", "30"))
api_key = os.environ["API_KEY"]  # KeyError at first use, not at startup


# Correct — the field is the declaration; pydantic coerces and validates at load.
class HTTPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HTTP_")
    timeout: int = 30
    api_key: SecretStr
```

**Load `.env` files with `python-dotenv`, before `Settings` is constructed.** Call `load_dotenv()` once at the
composition root (the CLI `main`, the `lifespan`) so the file's values are present in the environment by the time
pydantic reads them; keep `env_file` set on the root `model_config` as well, so settings still load correctly when a
process starts without the explicit call. `.env` is for local development only — it is gitignored, and deployed
environments supply real environment variables.

**Keep the variables in `.env`, and dev/test-specific overrides in `.env.dev`.** Both are gitignored. List them on the
root `model_config` in precedence order — `env_file=(".env", ".env.dev")` — where the later file wins, so `.env` holds
the shared baseline and `.env.dev` overrides only what a development or testing environment needs to differ. Don't fork
a whole second configuration file: if a value is the same everywhere, it belongs in `.env` alone.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.dev"), extra="ignore")
```

The narrow exemptions, and they are narrow: setting a variable for a **subprocess** you spawn (pass an `env=` dict, not
a mutation of `os.environ`), and a variable that must be set before an imported library reads it at import time. Both
happen at the composition root, with a comment saying why.

A domain module that has configuration of its own defines its own `BaseSettings` subclass next to the code that reads
it, scoped so its variables don't collide with another domain's — through an `env_prefix` for plain fields, or its own
collection logic when the keys are dynamic. The root `Settings` wires each one in as a nested field with
`Field(default_factory=...)`. Composition happens at the root, and the dependency points only downward — `settings.py`
imports the domain modules, never the reverse — the same direction as the route layer (§6). A domain with no
configuration provides no class; don't create empty settings shells.

```python
# cache.py — the domain owns its own settings class, scoped with an env_prefix
# so its variables don't collide with another domain's.
class CacheSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CACHE_")
    ttl_seconds: int = 60


# settings.py — the root composes each domain's settings; it is the only env reader.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    cache: CacheSettings = Field(default_factory=CacheSettings)
```

Why this way: a domain's configuration lives beside the code that consumes it (the same ownership rule as types and
behavior), each domain namespaces its own variables through `env_prefix`, and the domain layer never depends back on the
settings root — so a new domain adds one field at the root and nothing above it has to change.

### Inject via a typed `Annotated` alias

FastAPI dependencies that inject a service or a resolved model are defined once as a `typing.Annotated` alias pairing
the type with its `Depends(...)`, then reused as the parameter annotation. Handlers then read as ordinary typed
parameters and the wiring lives in exactly one place.

```python
ServicesDep = Annotated[Services, Depends(get_services)]
ConnDep = Annotated[asyncpg.Connection, Depends(get_conn)]
CurrentUserDep = Annotated[AuthContext, Depends(require_user)]


async def me(services: ServicesDep, ctx: CurrentUserDep) -> MePayload:
    return await me_payload(services, ctx.user)
```

The conventions that keep this uniform:

- **Name every alias `SomethingDep`** and define it immediately beneath its resolver, in the module that owns the
  resolver (`ServicesDep` in `services.py`, `CurrentUserDep` in `authorization.py`). Cross-module handlers import the
  alias, never re-spell the `Depends(...)`.
- **Always the `Annotated` form.** Never the old default-value style (`param: T = Depends(fn)`), never a bare
  `Depends(...)` inline in a handler signature, and never a `dependencies=[...]` argument on the app or a router — those
  scatter the wiring the alias exists to centralize.
- **Shape the resolver to its job.** A resolver that only pulls an already-resolved object off the request
  (`Request -> request.app.state.services`, `request.scope["auth"]`) is a plain **sync** function taking `Request`. A
  resolver that does I/O to authenticate or resolve (an API-key hash lookup, token validation) is **async** and composes
  the aliases it needs (`async def authenticated_api_user(services: ServicesDep, request: Request)`).
- **No `yield` dependencies.** Per-request resource lifecycle lives on `Services` and the `lifespan` (§6), not in a
  yield-based dependency that opens and closes a resource per request.

### Parametrize a dependency with a factory

When a dependency needs arguments — gate on _these_ groups, require _this_ scope — write a factory that closes over them
and returns the dependency function, then wrap the result in an `Annotated` alias at each use. The arguments are fixed
at wiring time; the handler still reads as an ordinary typed parameter.

```python
def require_groups(*group_ids: int) -> Callable[..., Awaitable[AuthUser]]:
    """Build a dependency that admits only members of the given groups."""

    async def dependency(services: ServicesDep, user: CurrentUserDep) -> AuthUser:
        await forbid_unless_member(services, dsid=user.dsid, group_ids=list(group_ids))
        return user

    return dependency


AdminDep = Annotated[AuthUser, Depends(require_groups(GROUP_ADMIN))]
```

### A cross-cutting check is a function; the dependency is the thin wrapper

A check that must guard both route handlers and inner code paths — an authorization gate, a precondition — lives as a
plain function taking `services` first (the §6 rule), so any code path can call it directly. The dependency factory
above is then only a thin adapter: it resolves the caller and delegates to that function. The rule is defined once and
reachable two ways — as a handler dependency (`AdminDep`), and as a direct call deep in a request where no dependency
injection reaches (`await forbid_unless_member(services, dsid=..., group_ids=[...])`). Don't implement the gate _inside_
the dependency, or the inner code paths can't reuse it.

### Register routes explicitly, not with decorators

Define each route handler as a plain function and register it with `app.add_api_route(path, handler, methods=[...])`. Do
not use decorator routing (`@app.get`, `@router.post`, and the like). A decorator has to reference a module-level `app`
or `router` object — that is exactly the global state §4 bans. Explicit registration takes the `app` as a parameter
where routes are wired (in `create_app`), so handler modules stay free of any global, and handlers remain ordinary,
directly callable and testable functions.

```python
async def me(services: ServicesDep, ctx: CurrentUserDep) -> MePayload:
    return await me_payload(services, ctx.user)


app.add_api_route("/users/me", me, methods=["GET"], name="me", tags=["Users"])
```

### Route handlers live in a per-domain route layer, not in domain modules

A route handler routinely composes several domains — `GET /users/me` returns the user _and_ their API keys. If the
handler lives inside a domain module (`users.py`), that module must import every other domain it touches
(`api_keys.py`), and the moment two domains each need a handler that references the other you have an import cycle.
Co-locating handlers with domain types pulls cross-domain composition _down_ into the domain layer, which is exactly
where it causes cycles.

Put handlers in a dedicated route layer instead: one module per domain, named `domain_routes.py` (`user_routes.py`,
`api_key_routes.py`). Each module holds **bare handler functions and nothing else** — no `app`, no router, no per-module
registration hook. The composition root (`create_app`) imports every route module and is the single place that
enumerates the routes with `add_api_route` (see "Register routes explicitly"). This is a strict layering with one
invariant:

Route modules import domain modules. Domain modules never import route modules. Route modules never import each other.
Only `create_app` imports the route modules.

```python
# api_key_routes.py — bare handlers. The module knows nothing about `app` or routing.
from __future__ import annotations

from .api_keys import ApiKeyInfo, list_api_keys
from .services import ServicesDep
from .users import CurrentUserDep


async def list_keys(services: ServicesDep, ctx: CurrentUserDep) -> list[ApiKeyInfo]:
    return await list_api_keys(services, dsid=ctx.user.dsid)
```

```python
# asgi.py — create_app is the ONE place that enumerates every route, across all domains.
from . import api_key_routes, user_routes

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, ...)
    ...
    app.add_api_route("/users/me", user_routes.me, methods=["GET"], tags=["Users"])
    app.add_api_route("/api/keys", api_key_routes.list_keys, methods=["GET"], tags=["API Keys"])
    ...
    return app
```

Prefer this central enumeration over a per-module `register(app)` hook: one file lists the entire URL surface, so a
route's path, method, tags, and OpenAPI metadata are read and reviewed in one place, and no route module ever has to
touch `app`. Group the calls by domain with comments and shared response dicts; that grouping, not a function boundary,
is the only structure the list needs.

**Why this keeps the layer acyclic:** nothing depends back on the route layer except `create_app` (the composition root,
which is meant to know everything), so a handler can import as many domains as it needs — always downward. The "routes
use many domains" pressure never reaches the domain layer, because composition happens above it.

**What moves and what stays:** only the thin handler moves to the route module. Boundary models (`MePayload`,
`ApiKeyInfo`) and behavior functions (`me_payload`, `list_api_keys`) stay in their domain module — they are domain-owned
and the route module imports them. This is the deliberate trade: you give up handler-next-to-type co-location to keep
the domain layer acyclic. Co-location wins for types and the behavior that owns them; the route layer wins for
composition across domains.

`domain_routes.py` is not the catch-all §4 bans. A single `routes.py` holding every handler is the magnet for unowned
code; a route module scoped to one domain and named after it is the opposite. A handler spanning several domains lives
in the route module of its primary resource (the response type's owner), or its own `feature_routes.py` when it has no
natural primary.

### The composition root wires structure in one factory; the lifespan owns resources

`create_app() -> FastAPI` is the composition root: a zero-argument factory that builds a fully wired app and returns it.
It is the one place that knows the whole system — it enumerates every route, mounts every sub-app, and adds every
middleware — so nothing else has to. Because it takes no arguments and holds no module-level singleton, each call yields
an independent app, which is exactly what a test wants: call `create_app()`, drive it with a test client, and override
`app.state.services` (or the `get_services` dependency) to inject fakes. Production invokes it once; a reload server is
handed the `"package.asgi:create_app"` factory string so its workers re-invoke it.

The factory wires **structure**; it does not build **resources**. A module-level `lifespan` async context manager
(passed as `FastAPI(lifespan=...)`) owns the resource lifecycle: it constructs `Services`, awaits `setup()`, publishes
it on `app.state.services`, enters any mounted sub-app's own lifespan, `yield`s to serve, and awaits `shutdown()` in a
`finally`. Keep `lifespan` module-level rather than nested in `create_app` (the nested-closure rule above), so it is the
single, importable driver of the startup/teardown ordering §6 describes.

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    setup_logging()
    services = Services()
    await services.setup()              # the async half of the two-phase lifecycle (§6)
    app.state.services = services
    try:
        yield
    finally:
        await services.shutdown()       # mirrors setup in reverse, each resource None-guarded


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, ...)
    app.add_middleware(InnermostMiddleware)    # added first → wraps innermost
    app.add_middleware(OutermostMiddleware)    # added last  → wraps outermost
    # ... add_api_route for every route, grouped by domain ...
    app.mount("/", static_fallback)            # catch-all mounts go LAST, after every explicit route
    return app
```

Two ordering rules the factory encodes, both easy to get subtly wrong:

- **Middleware is added in reverse of execution order** — the last `add_middleware` wraps outermost. Add the innermost
  layer first and say so in a comment; a reviewer cannot infer the intended nesting from source order alone.
- **Catch-all and static mounts (`/`, `/static`) go last,** after every explicit `add_api_route`, so the specific routes
  match before the fallback.

### Error rendering is chosen by the surface, not the domain

Domain functions raise presentation-neutral `AppError`s (`NotFound`, `Forbidden`); they never decide how the error
looks. The default rendering is the JSON envelope, produced by the outer `ErrorMiddleware` for any `AppError` — every
API route gets it for free.

A surface that needs a different representation translates at its own boundary: the route layer catches the domain
`AppError` and re-raises a surface-specific exception that is deliberately not an `AppError`, with a registered
exception handler that renders it. Because it is not an `AppError`, the middleware ignores it and the handler wins. The
HTML page routes do this — a `NotFound` from `get_project` becomes `PageNotFound`, rendered as an HTML 404; the same
`NotFound` on an API route stays JSON.

```python
# pages_routes.py — translate the domain error into an HTML-rendered one.
class PageNotFound(Exception):
    """Raised when the requested project or page does not exist.

    Deliberately not an AppError: that is what routes it to the HTML handler
    instead of the JSON envelope ErrorMiddleware produces for an AppError.
    """


async def authorize_page(services: ServicesDep, *, slug: str, name: str) -> AuthorizedPage:
    try:
        project = await get_project(services, slug=slug)
        page = await get_page(services, project_id=project.id, name=name)
    except NotFound as e:
        raise PageNotFound() from e
    ...
```

Two rules. The surface exception must not subclass `AppError` — that is what routes it to the HTML handler, so say so in
its docstring; otherwise someone "tidying up" by making it an `AppError` silently turns the page back into JSON. And the
translating `try/except` wraps only the lookups that produce the condition, never the whole handler, so an unrelated
error from deeper code isn't mislabeled.

---

