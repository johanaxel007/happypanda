---
name: gallery-database
description: Rules for the gallery SQLite database — its schema, the columns that encode which tab a gallery lives in and whether metadata has been applied, and the protocol for the rare out-of-band repair. Foreign keys are not enforced, so a raw delete silently orphans rows in four other tables. Enforced when editing gallerydb.py or database/db.py.
trigger: glob
glob: "{version/gallerydb.py,version/database/db.py}"
paths:
  - "version/gallerydb.py"
  - "version/database/db.py"
---

# Gallery database

The database is the only copy of the library index — see Core Constraint 2 in `@CLAUDE.md`, which
this rule does not restate: **application code writes through `gallerydb`, never raw SQL.** What
follows is the schema knowledge that makes `gallerydb`'s own code readable, and the one documented
exception to that constraint.

## Schema facts worth knowing before touching a row

| Fact | Consequence |
|---|---|
| `series` has primary key **`series_id`**, not `id` | a query written against `id` fails outright, which is the harmless case |
| `series.view` holds an `app_constants.ViewType`: **1 Default (library), 2 Addition (inbox), 3 Duplicate** | which tab a gallery appears under is this column and nothing else |
| `series.exed` is set to 1 once metadata has been applied | a fetch run skips these when `Skip galleries that has already been processed` is on, so a gallery re-queued for another attempt needs it cleared |
| `series_path` and `link` come back as **`bytes` for some rows**, `str` for others | decode defensively; a `str`-only assumption raises `TypeError` partway through a scan of the whole table |
| inbox → library is the manual *Send to library* action in `misc.py`, not something a fetch does | a gallery in the library got there because someone put it there |

Re-derive counts rather than trusting a number written here; they change every run.

## Foreign keys are not enforced

`PRAGMA foreign_keys` reports **0**, and four tables carry a `series_id`:

```
chapters · series_tags_map · hashes · series_list_map
```

Nothing stops a delete from `series` leaving all four holding rows that point at a gallery which
no longer exists, and SQLite reports no error when it happens. `series_tags_map` is the largest
table in the database by a wide margin, so the orphans are not a rounding error.

**Never `DELETE FROM series` directly.** `GalleryDB.del_gallery(list_of_galleries, local=False)`
already takes a list and already leaves the filesystem alone; it exists because the cascade has to
be done by hand.

## The one-off repair exception

Repairing rows the application itself has no UI for — undoing a wrong metadata match across
several galleries, say — is the one case where raw SQL is the right tool, because driving
`gallerydb` headlessly needs the app's database init and executors, which is more machinery and
more risk than the repair. This is a documented exception for a one-off, **not** a pattern
application code may follow.

When it is warranted, every one of these steps has earned its place:

- [ ] **The app is not running.** It holds galleries in memory and writes them back on close, so
      an open app silently undoes the repair.
- [ ] **Take a fresh backup first**, and check its timestamp against the live file. A backup the
      user made earlier in the session is usually already stale.
- [ ] **Inspect read-only** — `sqlite3.connect(f'file:{path}?mode=ro', uri=True)`.
- [ ] **Show the rows before changing them**, and let the user confirm the identification. After
      `Replace metadata` has run, a gallery's stored title is the *source's* title, so matching on
      a title from an old log finds the wrong row or none.
- [ ] **Dry run inside a transaction**, rolling back, before the run that commits.
- [ ] **Guard on the expected current state** — refuse when a row is missing or is not in the
      state the repair was written for, rather than writing anyway.
- [ ] **`PRAGMA integrity_check`** afterwards, and confirm the total row count is unchanged.

Address rows by `series_id`, touch only the columns the repair needs, and keep the whole thing in
one transaction.

## Related

- `@.agents/rules/metadata-matching.md` owns what *writes* this metadata, and why a wrong match is
  data loss rather than a cosmetic miss. A repair here is the cleanup after that rule was broken.
- `@.agents/rules/settings-plumbing.md` owns the ini-backed settings, which are not in this
  database at all.
