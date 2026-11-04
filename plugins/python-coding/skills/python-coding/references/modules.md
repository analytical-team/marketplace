## 4. File & module organization

- **A module is a unit of cohesion, not a line budget.** File size and line count are not something to optimize for in
  either direction — don't split a cohesive module to make it shorter, and don't pad a small one to look substantial.
  What matters is whether everything a reader needs to understand and use the thing lives in one place.
- **One module per client or subsystem, holding everything that belongs to it.** A self-contained integration — a Google
  auth client, an S3 client, OIDC middleware — is a single file containing its settings class, its request/response
  models, its exceptions, its module-level helper functions, and the client class itself. Splitting one client's
  settings into `s3_settings.py`, its response models into `s3_models.py`, and its client into `s3_client.py` scatters
  one concept across files a reader has to open and reassemble in their head; keep them together in `s3_client.py` even
  when that makes the file long. Length is not a reason to split — a module stays whole as long as it is cohesive; it
  splits when it stops being about one thing (it holds two unrelated clients, or a client plus domain logic that doesn't
  belong to it), never because it crossed a line count.
- **One primary class per file remains the default outside that case.** The file name matches the class: `blob_store.py`
  contains `BlobStore`. The client/subsystem module above is the deliberate exception: everything that exists only to
  support that one client lives beside it rather than fanned out into sibling files.
- **Co-locate small helpers.** Module-level helpers that support only the primary class in the same file, and small
  dataclasses used only by that class, live in the same file.
- **Use a descriptive suffix for focused extensions.** When a module extends a type with a focused capability, name the
  file `type_capability.py` (e.g., `date_formatting.py`). The scope is visible at a glance.
- **No catch-all modules.** Never create `helpers.py`, `utils.py`, `extensions.py`, or `common.py`. They become magnets
  for unowned code. Either the helper has a home with the type it operates on, or it deserves its own named module
  (`string_escaping.py`, not `string_helpers.py`).
- **Order within a file:** class attributes first, then `__init__`, then methods grouped by responsibility. When a
  module holds more than one class — settings, models, the client — order them in the sequence a reader needs them:
  settings and data types first, the class that consumes them last.
- **No global variables.** Module-level mutable state is banned. Constants (all-caps, immutable) are the sole exception.
  If you need shared mutable state, it belongs in a class — and state that outlives a single request belongs in an
  expirable cache, not an in-memory dict (§6).

---

