## 14. Multi-line strings

- **Use a triple-quoted string for any string that spans more than one line** — SQL queries, multi-line messages,
  embedded templates. Write the content as it reads, on its own lines.
- **Never build a multi-line string by adjacent string-literal concatenation** (one quoted fragment per line with no
  operator between them). It is a correctness hazard: a single missing trailing space silently joins two tokens
  (`"...SET "` + `"username..."` is fine, but drop the space and you get `SETusername`), and the bug is invisible in
  review. It also makes the text hard to read and re-indent.

```python
# Correct — reads as the query it is, no hidden whitespace seams:
row = await conn.fetchrow(
    f"""
    INSERT INTO users (dsid, email)
    VALUES ($1, $2)
    ON CONFLICT (dsid) DO UPDATE SET email = EXCLUDED.email
    RETURNING {USER_COLUMNS}
    """,
    dsid,
    email,
)

# Avoid — implicit concatenation; one missing trailing space corrupts the SQL:
row = await conn.fetchrow(
    "INSERT INTO users (dsid, email) "
    "VALUES ($1, $2) "
    "ON CONFLICT (dsid) DO UPDATE SET email = EXCLUDED.email "
    f"RETURNING {USER_COLUMNS}",
    dsid,
    email,
)
```

A single-line string that happens to be long is fine as one quoted literal — this rule is about text that wraps across
source lines, not about line length.

---

