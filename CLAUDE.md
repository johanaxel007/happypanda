# Happypanda

PyQt5 desktop manga/doujinshi library manager. Python 3.14, SQLite, single-process GUI app.

This is a fork of a community-maintained continuation of an abandoned project. Parts of the
codebase are old and inconsistent — dated syntax, deprecated packages, uneven formatting.
Modernising it wholesale is **not** a goal. Improve what you are already touching, and raise
anything larger with the user rather than starting it.

## Core Constraints (CRITICAL)

These are hard rules, not style preferences. If a request violates one, say why it breaks and
propose the alternative rather than implementing it.

1. **This app writes to the user's real library.** Galleries are moved, renamed and sent to the
   recycle bin in place. Metadata fetching overwrites stored titles, artists, tags and dates
   when `Web / Metadata / Replace metadata` is on, and there is no undo.
    - A wrong metadata match is therefore silent data loss, not a cosmetic miss. When matching
      is uncertain, failing to match is the correct outcome — see *Metadata matching* below.
2. **The gallery database is the only copy of the library index.** Thousands of galleries with
   tags, read counts and paths built up over years. Never write to it outside `gallerydb`, and
   treat schema changes as needing a migration path for existing users.
    - *Reference:* `@.agents/rules/gallery-database.md`.
3. **e-hentai and exhentai ban on request volume, by IP.** The user has been banned before.
   Anything that multiplies requests per gallery — a new query variation, following pagination,
   retrying — must stay inside the existing budget or be gated so it only fires when it can
   help. `CommonHen.begin_lock` / `end_lock` pace every request; do not bypass them.
4. **Settings are plumbed through four places.** A new setting needs an `app_constants` entry, a
   widget in `settingsdialog._make_*`, a read in `restore_options`, and a write in `accept`.
   Miss one and it silently reverts or latches to a wrong value on the next save.
    - *Reference:* `@.agents/rules/settings-plumbing.md`.

## Layout

Application code lives in `version/` — not a package. The modules import each other **flatly**
(`import app_constants`, not `import version.app_constants`), so `version/` itself has to be on
`sys.path`. `conftest.py` does that for tests; `version/main.py` is the entry point at runtime.

`main.py` also imports `pillow_jxl` and `pillow_avif` for their side effect. The JPEG XL plugin
does not register itself with Pillow, so a script that reads library images outside the app has
to import it too, or every `.jxl` page comes back as `UnidentifiedImageError` and the diagnosis
lands on the wrong cause.

There is a circular import between `app_constants` and `gallerydb` (`app_constants` annotates
with `gallerydb.Gallery` while `gallerydb` imports `app_constants`). Importing `fetch` or
`pewnet` first leaves `gallerydb` half initialised, so import in this order:

```python
import app_constants, gallerydb, fetch, pewnet
```

| file | what it holds |
| --- | --- |
| `version/fetch.py` | `Fetch.auto_web_metadata` / `_auto_metadata_process` — the online metadata pipeline: query building, result scoring, source fallback |
| `version/pewnet.py` | source clients: `EHen`, `ExHen` (e-hentai/exhentai), `ChaikaHen` (panda.chaika.moe), plus download managers |
| `version/gallerydb.py` | database access and the `Gallery` model |
| `version/utils.py` | `title_parser` (folder name → title/artist/language), archive and image helpers |
| `version/formatters/title_formatter.py` | title normalisation, `TranslationStyle` |
| `version/betterversions.py` | the better version review list: its own SQLite store, the three-axis classification, `BetterVersionScan` and `BetterVersionRecheck` |
| `version/tagreaders.py` | reading the source's tags off a stored gallery or a raw `gmetadata` entry, and comparing two releases on them. Imports nothing else, so it is safe anywhere in the import order |
| `version/settings.py` | ini-backed settings; `app_constants.py` reads defaults through it |
| `version/settingsdialog.py` | every setting needs a widget here **and** a read in `restore_options` **and** a write in `accept` |

## Commands

```sh
venv/Scripts/python.exe version/main.py                            # run the app
venv/Scripts/python.exe -m pytest tests/ -q                        # tests
venv/Scripts/pip.exe install -r requirements-dev.txt               # pytest + pyinstaller
venv\Scripts\pyinstaller.exe --noconfirm --clean HappyPanda.spec   # build -> dist/HappyPanda/

python misc/analyze_fetch_log.py path/to/happypanda.log --failures # diagnose a fetch run
python misc/analyze_scan_log.py path/to/happypanda.log --rejections # diagnose a better-version scan
venv/Scripts/python.exe misc/gui_smoke.py                          # exercise the gui headlessly
venv/Scripts/python.exe misc/app_smoke.py                          # drive the real AppWindow headlessly
venv/Scripts/python.exe misc/check_qt_enums.py --instance          # Qt enum sites left in the Qt5 spelling
venv/Scripts/python.exe misc/qt_modelview_bench.py PyQt6           # time the startup insert path against a model/view
```

The build reads its version string from `VS.txt`.

## Execution Protocol & Verification

- **Think first.** For any change touching multiple files, output a brief bulleted plan before
  writing code.
- **Verify before reporting done.** Run `pytest tests/ -q` after any edit under `version/`. Four
  failures in `tests/database/test_db.py::test_init_db` are **pre-existing** — stale assertions
  on exact mock call counts. Everything else must pass.
- **Static checks are thin here.** There is no type checker and no lint gate configured. The
  GUI has no pytest coverage, because the modules import each other flatly and a dialog needs a
  QApplication; `misc/gui_smoke.py` stands in for the settings dialog, the gallery chooser and
  the better version list under the offscreen platform, and `misc/app_smoke.py` builds the real
  `AppWindow` and drives its own methods. Run the first for a widget change, the second for
  anything touching an `AppWindow` method, and still launch the app for what neither reaches.
- **A signal is a hand-off to code that can delete you.** Widgets here carry
  `WA_DeleteOnClose`, so a slot may destroy the widget that emitted. Emit last, and never touch
  `self` afterwards - `misc/gui_smoke.py` holds the regression case.
- **Diagnose from the log, not from guesswork.** `happypanda.log` records every query, every
  candidate score, and every guard rejection. `misc/analyze_fetch_log.py --failures` separates
  the three failure modes — source returned nothing, candidates scored too low, candidates
  dropped by the numbering guard. Read it before theorising about a metadata bug.
- **Measure before changing matching behaviour.** Query ordering, thresholds and guards in
  `fetch.py` are tuned against real runs. Check what the log says actually produces matches
  before reordering or loosening anything.
- **Self-correction.** If tests fail, read the output, fix, and re-run. Do not hand back code
  that fails its own gate.
- **Atomic commits.** Leave the working tree runnable at each logical step.
- **Committing is the user's call — never commit unprompted.** Finish the work and **stop with
  it uncommitted**, ending the response with a suggested commit message. The user reads the diff
  and routinely adjusts before it lands; that review window is the point. The **next forward
  instruction** — "proceed", "continue", or an outright "commit" — *is* the trigger: commit
  then, without asking again. Two things feel like triggers and are **not**: executing a plan
  the user already approved, and the user confirming a fix works.
- **Commit message format:** a single brief subject line, `Verb: description` — past-tense verbs
  (`Fixed:`, `Added:`, `Updated:`, `Removed:`, `Refactored:`, `Feat:`) or scope prefixes
  (`Docs:`, `Skill:`, `CLAUDE:`). Join aspects with ` + `, express cause/effect with ` -> `. No
  body text, and **no `Co-Authored-By` trailer** — this overrides the harness default that asks
  for one. Group unrelated changes into separate commits, including tiny standalone cleanups.

## Metadata matching

The part with the most accumulated hard-won behaviour. `_auto_metadata_process` runs each
gallery through: existing URL → optional image hash → title search, then hands anything still
unmatched to the fallback sources in `app_constants.HEN_LIST`.

Load bearing, each because a real run got it wrong:

- **Compare like with like.** `canonical_title()` strips `[Circle (Artist)]`, `(Magazine)`,
  `[English]`, `[Digital]` and translator credits from *both* sides before scoring. `fuzz.ratio`
  is length sensitive, so those alone push an exact match below the threshold.
- **Never `token_set_ratio` or `partial_ratio`.** Both score `Schoolgirl Guide` against
  `Schoolgirl Guide 2` at 100, which auto-applies the wrong gallery.
- **Numbering is decisive.** `title_numbers()` compares the set of numbers in the two titles; a
  mismatch rejects the candidate whatever it scores. Roman numerals count as the number they
  denote, upper case and word-bounded, so `Erohon V` and `Erohon II` differ while `DepthSinker2`
  and `DepthSinker II` agree. Japanese numerals are deliberately not read.
- **A title may be half a title.** Sources carry the whole `romaji | translated` pair while a
  folder often kept one half. `match_forms()` offers each half for comparison.
- **A separator may be missing.** Some folder names have the `｜` deleted rather than
  substituted, leaving only the two spaces around it. `split_on_separator()` takes the raw
  folder name, never a formatted one, because formatting collapses that whitespace away.
- **Scripts may not match.** A Japanese folder name against a romaji site title scores 0. Such a
  pair is scored `None` ("unverifiable") rather than 0, and a lone unverifiable hit is used —
  unless the language filter is what left it alone, in which case it goes to the picker.
- **A language is only evidence once it is known.** Every gallery whose folder name never stated
  one is stored as `G_DEF_LANGUAGE`, which ships as `English`, so that value alone cannot be told
  apart from "nobody knew". Filtering candidates on it discards correct ones. And when the filter
  has removed a candidate's alternatives, that candidate is never auto-applied however well it
  scored — an unrecognised tag shape survives the filter as "states no language".
- **Two language vocabularies, and `G_LANGUAGES` is not the recognition set.** It is the four
  names the pickers offer; what the source can actually tag lives in `tagreaders.LANGUAGE_TAGS`.
  Deciding whether a string names a language goes through `utils.known_languages()`.
- **A language filter only narrows a language the source tags.** e-hentai tags one only when
  it is not its own default, so `l:japanese$` matches nothing on the whole site — the absence
  of a tag is what says Japanese. `search_queries()` builds the ladder, and the plain title
  with no prefix and no filters has to stay inside `MAX_SEARCH_ATTEMPTS`. The filters go out
  under the source's short namespaces (`a:`, `l:`), verified live, to spend less of
  `MAX_QUERY_LENGTH` on them; the app's own search box keeps `artist:` / `language:`.
- **A better version has to agree on its creator, not just its series.** Two doujins of one
  franchise share the parody tag as readily as a short title, so `same_creator` compares the
  pooled `Artist:`/`Group:` namespaces alongside `same_parody`. Read from the tag, never from
  the title's `[Circle (Artist)]` group.
- **`TranslationStyle.SEARCH` for queries, not `DEFAULT`.** `DEFAULT` converts ASCII *to* full
  width for filenames; searching needs the inverse.

`tests/test_metadata_matching.py` holds a regression case for every bug found here; the titles
in it are real ones taken from real logs, so a failure names a specific past defect. Verify a new
case actually fails against the old code — a test written against a helper can pass while the
call site that crashed stays broken.

A run has two phases, which matters for a large one. Searching is unattended, but ambiguous
galleries are collected and only presented at the **end** of the pass, where
`GALLERY_PICKER_QUEUE.get()` blocks until answered — expect roughly one in ten to land there.
`gallery.exed` is set only after metadata is applied, so a re-run retries failures and skips
successes.

*Reference:* `@.agents/rules/metadata-matching.md`.

## Agent Files

Rules and skills live under `.agents/` so every agent harness can read them. `.claude/rules` and
`.claude/skills` are **directory junctions** pointing at them — edit the files under `.agents/`,
never through the junction path, and never add a real file under `.claude/rules` or
`.claude/skills` (both are ignored so the junctions cannot duplicate tracked files). Recreate them
after a fresh clone with:

```sh
cmd /c "mklink /J .claude\rules .agents\rules"
cmd /c "mklink /J .claude\skills .agents\skills"
```

| Path                    | Contents                                                            |
|-------------------------|---------------------------------------------------------------------|
| `.agents/rules/`        | Glob-triggered rules; auto-attach while editing a matching file      |
| `.agents/skills/`       | Skills; each a directory with `SKILL.md` and optional `references/`  |
| `.claude/settings.json` | Permission allowlist and denylist for this project                   |
| `CLAUDE.md`/`AGENTS.md` | Byte-identical twins — update both together                          |
| `misc/`                 | Developer tooling that is not part of the app                        |

Four skills, each owning a distinct moment: `create-implementation-plan` before the work,
`review-changes` on a diff that already exists, `create-design-doc` when an analysis is worth
keeping in `Documentation/Design/`, and `manage-skill` when authoring a skill or rule.
Adding one is `manage-skill`'s job — it owns the frontmatter rules and the description-cost budget.

`AGENTS.md` is a copy of this file for harnesses that read that name instead. When you change
one, copy it to the other in the same commit.

**The junction makes two git operations unsafe:**

- **Never run `git stash` here.** The rules are tracked at their `.agents/` paths, so a stash
  silently reverts every uncommitted agent-file edit to its committed state — the work is not
  lost, but it disappears from the working tree with no warning. To compare against a clean
  tree, use `git show HEAD:<path>` or a worktree, never a stash.
- **Never `git checkout` / `git restore` a `.claude/rules` path** — it writes through the
  junction into `.agents/`. Always address these files by their `.agents/` path.

Note that `.gitignore` itself is untracked in this fork, excluded via `.git/info/exclude`, so
local ignore rules do not travel with a clone.

## Code Style

- Match the surrounding code. This codebase is not uniformly formatted and is not worth
  reformatting wholesale; a diff that reformats untouched lines hides the real change.
- Do not rewrite whole files for minor changes — apply targeted edits.
- Never delete existing docstrings or comments unless the code they describe is being deleted.
- Prefer f-strings for new code; the codebase still has `.format()` and `%` in older paths and
  those do not need converting on sight.
- Logging goes through the module-level `log_i` / `log_d` / `log_w` / `log_e` aliases, never
  `print()`, and the value logged is passed as a `str`. Encoding it first puts a bytes repr
  in the log with every non-ASCII character escaped, which is unreadable for a CJK title.
  `tests/test_log_titles.py` is the gate.
- Every text-mode `open()` names its `encoding`. A frozen build never enables Python's UTF-8
  mode however the environment is set, so an unmarked open reads and writes in whatever the
  machine's locale happens to be, and the exe and a source run then disagree. `utf-8` to write,
  `utf-8-sig` to read anything a user may have edited by hand. `misc/gui_smoke.py` under
  `-X warn_default_encoding -W error::EncodingWarning` is the gate.
- New settings read through `settings.get` with a default, and a blank ini value means "never
  configured" — an intentionally empty list is stored as `none` (see `HEN_LIST`).

## Commenting

Comments explain the **why** — intent, constraint, the non-obvious reason a line exists. They
must not restate the **what** the code already shows. A comment that only narrates the next
statement is noise; delete it.

**Inline comments: one line wherever possible, three lines maximum.** Go past three only for
genuinely intricate logic, and treat the length as a smell — the code may want an extracted,
well-named function instead. Flag that to the user rather than silently shipping the wall of
text.

```python
# Good — explains why the line exists.
page_url = next_page_url(soup, r.url)  # the site only renders this link when a further page exists

# Bad — restates the obvious.
# Increment the counter.
error_count += 1
```

**Describe the code as it stands, never its history.** When you fix a bug, update the comment to
describe the corrected behavior; do not leave, or add, text about the old symptom or the fix.
That narrative belongs in `CHANGELOG.md`, not in the source. The same goes for measurements from
a particular run — keep the rationale, drop the figures that will go stale.

**Document what a thing is, never who uses it.** A docstring describes the thing it sits on —
what it is, what it guarantees, why it is shaped that way. Naming the code that consumes it
parks a fact about the rest of the codebase in the one place nobody updates, and it goes stale
the first time a second consumer appears.

```python
# Bad — names a consumer.
"""Split a title. Called by the query builder and the scorer."""

# Good — says what it is.
"""Returns the part of the title before its 'romaji | translated' separator, or ''."""
```

## Files to Never Commit

- `settings.ini`, `.happypanda` — local paths and personal config
- `*.db`, `db/` contents — the gallery database
- `happypanda.log*` — runtime logs
- `dist/`, `build/`, `venv/` — build output and the virtual environment

## Testing

`pytest tests/ -q`. `tests/test_qt_scoping.py` is what stands between a mistyped Qt enum scope
and an `AttributeError` at paint time, and it has to stay green through the PyQt6 switch. It
checks three things against whichever binding is installed: no unscoped Qt5 spelling is left;
every `QClass.Scope.MEMBER` resolves; and for a scope read off a receiver rather than a class
— `v_header.ResizeMode.Fixed` — that the scope and member exist at all, tightened to the
enclosing class where the receiver is a bare `self`. What it cannot check is whether such a
scope is the right one for the object it was read off; that needs the receiver's type, which
is not in the source. `misc/check_qt_enums.py` is the same scan as a report.

`tests/test_metadata_matching.py` is the meaningful suite for the application itself — regression
cases for the online metadata pipeline, drawn from real failures. The four `test_init_db` failures are
pre-existing and unrelated.

`misc/gui_smoke.py` covers the settings dialog, the gallery chooser, the better version list
and the gallery edit dialog headlessly — the settings round-trip, the ini's encoding, the
chooser's covers, gestures and creator line, the edit dialog's language round-trip, a scan run
end to end, and the crash regressions. It runs in a temporary directory against the
shipped defaults, which is deliberate: the repo's `settings.ini` is untracked, so the suite
would otherwise test whatever configuration happens to be local. It builds widgets in
isolation, so it proves a button reaches a method **by name** but never what that method does.

`misc/app_smoke.py` covers that: it constructs the real `AppWindow` and drives its own methods
— the confirmation dialog, the worker thread, the notification, the metadata lock — with only
the network stubbed, on `pewnet.EHen` itself so the `isinstance` checks in the pipeline still
hold. It is the only gate on app-level assembly, which is where a method can reference a name
that does not exist and stay green under both pytest and `gui_smoke`. Run it for anything
touching an `AppWindow` method. `gui_smoke.py` stays the encoding gate — building the window
loads the icon font, and qtawesome opens its charmap without an encoding, so
`-W error::EncodingWarning` fails inside a dependency there.

Between them they still reach no other dialog, so anything touching one has to be exercised by
launching the app.
