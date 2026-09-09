# Core gates — always run

These four apply to any diff, whatever it touches, and they are the only gates that do. The other
shards (`fetch`, `ui`, `docs`) load per the router in `SKILL.md`.

Each gate carries **what fails**, **how to check**, **severity**, and whether it is **delta-based**
(flag only what the diff adds) or absolute (any occurrence in changed code is a finding).

Every severity below is a *ceiling*, not a fixed value. Downgrade when the blast radius is
genuinely small — a pattern in tooling under `misc/`, a smell in a debug path — and say why.

---

## Gate 1 — Core constraint violated

**What fails.** The diff breaks one of the Core Constraints in `@CLAUDE.md`. These are hard
rejections, not style preferences:

- a **library write with no guard** — renaming, moving, or trashing gallery files, or overwriting
  stored metadata, without respecting the toggle that governs it (`Replace metadata`,
  `Send files to trash`, `Move imported galleries`). There is no undo.
- the **gallery database written outside `gallerydb`** — raw `sqlite3` access, or DDL issued from
  another module.
- the **request budget raised** — a new query variation, a retry, or a followed link that is not
  bounded by `MAX_SEARCH_ATTEMPTS` / `MAX_SEARCH_PAGES`, or a request path that bypasses
  `CommonHen.begin_lock` / `end_lock`. See gate 6 for the detail.
- **`print()` added under `version/`** instead of the module's `log_i` / `log_d` / `log_w` /
  `log_e` aliases (tooling under `misc/` is exempt — it is a CLI and prints by design).

**How to check.** These follow from what the diff *adds*. Grep the added lines:

```bash
git diff --no-color $RANGE | grep -nE '^\+.*(^\+\s*print\(|sqlite3|os\.remove|shutil\.move|send2trash|requests\.(get|post))'
```

Then open each hit — `print(` also matches `pprint(`, and a `requests.get` inside an existing
locked block is fine while a new one outside it is the finding.

**Delta-based** — a violation the diff introduces or extends.

**Severity.** Blocker for an unguarded library write or a direct database write; High for a raised
request budget; Medium for `print()`.

---

## Gate 2 — Style or convention regression on new code

**What fails.** New code departs from the `@CLAUDE.md` Code Style and Commenting sections:

- a **comment that narrates history** — "used to", "previously", "this was broken because", or a
  measurement from a particular run. Comments describe the code as it stands; the bug narrative
  belongs in `CHANGELOG.md`. Keep the rationale, drop the symptom and the figures.
- a **docstring that names its consumers** ("called by the query builder") rather than saying what
  the thing is.
- a **comment that restates the next statement** instead of explaining why it exists.
- an **inline comment past three lines** — a smell that the code wants an extracted function;
  flag it rather than shipping the wall of text.
- a **magic value** inline where a module or method-level constant belongs.
- a **bare `except:` or new broad `except Exception`** that swallows without logging.
- **reformatting of untouched lines** — a diff that rewrites whitespace or quoting around the real
  change hides it. This codebase is deliberately not uniformly formatted.

**How to check.** Read the added lines. **New code only** — do not retrofit docstrings onto
untouched functions the diff happened to sit near, and do not flag a pre-existing broad except.

`@CLAUDE.md` also forbids *deleting* existing docstrings or comments whose code survives — that
half is gate 4, not this one.

**Delta-based.**

**Severity.** Low, ceiling Medium. A history-narrating comment is Low; a swallowed exception in a
path that writes to the library or the database is Medium.

---

## Gate 3 — Documented behavior changed with no doc edit

**What fails.** The diff makes a statement in `@CLAUDE.md` or an `@.agents/rules/` file false and
ships alone. Those files are read at the start of every session and by every rule glob, so a false
one actively misleads the next change.

The high-traffic claims, each of which a plausible diff can falsify:

- the import order and the circular import between `app_constants` and `gallerydb`
- the four-place settings wiring, and the blank-vs-`none` ini semantics
- any of the seven matching invariants in the Metadata matching section
- the commands block (a renamed script, a moved entry point)
- "four `test_init_db` failures are pre-existing" — if that count changes, the doc is now wrong

**How to check.** For each changed behavior, grep `CLAUDE.md` and `.agents/rules/` for the claim.
A change to a matching invariant almost always needs both `CLAUDE.md` and
`.agents/rules/metadata-matching.md` edited.

**Absolute** — the doc is either true after this diff or it is not.

**Severity.** Medium, ceiling High when the false claim would cause the next session to break
something (an import order or a settings-wiring claim).

---

## Gate 4 — Deleted guard or invariant not re-established

**What fails.** The `-` side of the diff removed a check and the `+` side did not put it back. This
is the one regression class the added lines cannot show you, so it needs its own pass over the
deletions.

Guards worth this attention here:

- a **numbering, script, or threshold check** in the matching path — see gate 5
- a **bounds check** on the request loop: the attempt cap, the page cap, the "only follow when the
  page was full" condition
- a **lock acquisition** around a request, or the queue drain between sources
- a **settings round-trip read** in `restore_options`
- a **docstring or comment whose code survives** — deleting it is forbidden by `@CLAUDE.md`

**How to check.**

```bash
git diff --no-color $RANGE | grep -nE '^-.*(if |assert |max\(|min\(|begin_lock|end_lock|\.clear\(\)|setChecked|return \[\])'
```

For each hit, find whether an equivalent exists on the `+` side. A guard that moved is fine; a
guard that vanished is the finding.

**Absolute.**

**Severity.** High, ceiling Blocker when the removed guard is what stopped a wrong match or an
unbounded request loop.
