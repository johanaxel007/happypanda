---
name: review-changes
description: Reviews a working diff against this project's own invariants — the metadata matching rules, settings plumbing, request budget, library-writing paths, GUI code nothing can test, and doc/CHANGELOG sync — and ends with a single verdict. Safe to run repeatedly mid-work. Use when the user says "review my changes", "review the diff", "pre-merge check", "is this ready to merge", "review before commit", "check my work", or before offering a commit on a non-trivial change. To plan work that does not exist yet, use create-implementation-plan instead.
---

# Review changes

A pass over the project-specific invariants that `pytest` does not check, built to be run
**repeatedly** — after each meaningful chunk while the work is in progress, and once more before
merge.

The test suite covers the metadata matching functions and nothing else: no type checker, no lint
gate, no GUI coverage. That is what this skill is for. The failure modes here are *silent* — a
setting that reverts on the next Ok press, a looser score that overwrites the user's metadata with
a sibling gallery's, a query variation that quietly triples the request count against a source
that bans by IP.

Its job is to be *runnable*. A review that reports the same pre-existing issues every time gets
ignored after one use, so everything here is scoped to the diff.

## Scope — read this before anything else

**What this does not do:**

- It does not replace the built-in `/code-review`, which covers general correctness. This covers
  *this project's* invariants. Running both is normal.
- It does not re-verify the tests. `pytest tests/ -q` owns that; four `test_init_db` failures are
  pre-existing and are not findings.
- It does not review code the diff did not touch. This codebase is old and uneven — pre-existing
  debt is not a finding, and modernising it is not a goal.

**What it does:** the gates in `references/` that the diff actually triggers, a refute pass over
whatever they turned up, then a verdict.

**Where the change lands changes the weighting.** The sharp edges are anything that writes to the
user's library or overwrites stored metadata, anything that changes what counts as a match, and
anything that changes how many requests a gallery costs. The soft edges are logging, tooling under
`misc/`, and read-only display code. Route effort accordingly: the same missing guard is a Blocker
in the matching path and a non-finding in a tooltip.

## Step 1 — establish the diff

Resolve scope in this order.

**1. The user's stated scope wins — always.**

| User says | Range to review |
|---|---|
| "my working changes" / "before I commit" | `git diff` (+ `git diff --staged`) |
| "the staged changes" | `git diff --staged` |
| "all unpushed commits" | `git diff @{u}...HEAD` |
| "starting from commit `<hash>`" | `git diff <hash>^...HEAD` |
| "the last N commits" | `git diff HEAD~N...HEAD` |
| "this branch" / "the whole PR" | `git diff master...HEAD` |

**2. Always run `git status --short` first**, whatever the scope. It is the only thing that
surfaces untracked files, and those are invisible to every `git diff` range above. A brand-new
module, test file, or rule has never been `git add`ed and produces no diff output at all. This is
not an edge case — it is the normal state of new work. Fold the `??` entries in; for a new file
**every line is added**, so read the whole file and run every gate its path triggers.

Note the **three-dot** form (`master...HEAD`): what HEAD *added* since it diverged, not everything
that landed on master meanwhile.

**3. No stated scope → default by size.**

```bash
git rev-list --count master..HEAD    # commits ahead of master
git rev-list --count @{u}..HEAD      # unpushed (needs an upstream)
```

Work happens on a feature branch off `master`, and the common case is the working tree: `git diff`
plus `git diff --staged`. If the range is huge, stop and ask.

The scope picks the **mode**:

| What the user is doing | Mode | Verdict vocabulary |
|---|---|---|
| Still writing the change | **intermediate** | `CONTINUE` / `FIX FIRST` |
| About to commit | **intermediate** | `CONTINUE` / `FIX FIRST` |
| Reviewing committed work | **pre-merge** | `MERGE` / `HOLD` |

The line is whether the work is still in the working tree or already committed — not which git
command produced the diff.

State which scope and mode you used. A review of the wrong scope is worse than none.

Get the file list first, then read the changed regions. **Do not review from diff hunks alone for
anything behavioral** — a hunk shows what changed, not what the surrounding function now does.

There is no code index here, so a blast radius is a `Grep` — and a symbol grep is blind to the
string-bound consumers this codebase relies on: Qt signal/slot connections, `settings` section and
key strings, and ini keys. Gate 5 exists because of that.

## Step 2 — the delta rule

**Only flag what this diff introduces.**

This is not politeness, it is the difference between a usable gate and a discarded one. The
codebase has plenty of pre-existing patterns a strict gate would flag — bare `except:`, mutable
default arguments, `%`-formatting, module-level globals. A gate that reports them all is worthless.

For every pattern-style gate:

1. Check whether the *diff* adds a violating line.
2. If yes → candidate.
3. If it was already there and the diff merely moved or reformatted it → not a finding. Mention it
   at Low only if the diff makes it materially worse (e.g. moved a one-shot request into a loop).

Establish a baseline when you need one rather than trusting a remembered number:

```bash
grep -rn "except:" version/ | wc -l
```

The delta rule is why gate 4 exists separately: the one class of regression the `+` side cannot
show you is a guard the `-` side removed.

## Step 3 — load the shards the diff earns, then run the gates

Twelve gates across four reference files. **Read `references/gates-core.md` always**, plus each
shard the changed-file list triggers. Route from the actual file list, not from a guess about what
the change was "about".

| Shard | Gates | Load when the diff touches |
|---|---|---|
| `references/gates-core.md` | 1–4 | **always** |
| `references/gates-fetch.md` | 5–8 | `version/fetch.py`, `version/pewnet.py`, `version/formatters/`, or `version/utils.py` title parsing |
| `references/gates-ui.md` | 9–10 | `version/settingsdialog.py`, `version/app_constants.py`, `version/settings.py`, or any dialog/widget/signal code |
| `references/gates-docs.md` | 11–12 | `CLAUDE.md`, `AGENTS.md`, `.agents/`, `CHANGELOG.md`, `tests/`, `misc/` |

**The shards summarize `.agents/rules/*.md`; the rules are the source of truth.** Those rule files
glob-attach while you *edit* a matching file — nothing auto-loads them during a review, so a gate
that names one is telling you to open it. Reviewing from the summary alone is how a half-wired
setting or an unbudgeted query ships.

| # | Gate | Shard |
|---|---|---|
| 1 | Core constraint violated (library written without a guard, DB touched outside `gallerydb`, request budget raised, `print()` in `version/`) | core |
| 2 | Style/convention regression on new code (comment narrating history, docstring naming a consumer, magic value, swallowed exception) | core |
| 3 | Behavior documented in `CLAUDE.md` or a rule changed with no doc edit in the same commit | core |
| 4 | Deleted guard or invariant not re-established | core |
| 5 | Matching loosened — a candidate that should be rejected is now accepted | fetch |
| 6 | Request cost per gallery raised without a gate | fetch |
| 7 | Title handling that breaks on a shape the library actually contains (CJK, `\|` pair, deleted separator, truncation) | fetch |
| 8 | New matching behavior with no regression case in `tests/test_metadata_matching.py` | fetch |
| 9 | Setting not wired through all four places, or a value that cannot round-trip | ui |
| 10 | GUI change with no named screen to open, a signal bound by a renamed name, or worker-thread code touching widgets | ui |
| 11 | `CLAUDE.md`/`AGENTS.md` twins diverged, or a rule edited through the `.claude/` junction path | docs |
| 12 | User-visible change with no `CHANGELOG.md` entry | docs |

### On an intermediate run: what may wait, and what may not

The unit of an intermediate review is **the next commit**, not the merge. A gate defers only when
finishing it needs something outside this moment. Exactly two have an owed half:

| Gate | Owed half — not a finding mid-work | Now half — always a finding |
|---|---|---|
| 10 GUI | the **manual screen load** that proves the widget appears and the signal fires — needs the app running | the **unwired widget or renamed connection itself**. Flag it now; the grep is free |
| 3 doc sync | *writing* the doc update | the **fact that documented behavior changed**. Say which doc is now wrong |

Everything else fires on every run. Three that look deferrable and are not:

- **Gate 5 (matching loosened).** A wrong match overwrites the user's metadata with no undo. It
  must never reach a commit on the assumption that a later run will catch it — the run *is* the
  damage.
- **Gate 6 (request cost).** The sources ban by IP, and the ban lands on the user, mid-run.
- **Gate 9 (settings wiring).** A half-wired setting does not fail loudly; it silently reverts, and
  the user discovers it weeks later as "that option never worked".

On an intermediate run the owed halves go under `Still owed before merge` — a checklist, not
findings. On a pre-merge run there is no owed half.

## Step 4 — refute each candidate before it becomes a finding

The gates produce *candidates*. A candidate is not a finding until it survives a pass whose
explicit goal is to kill it. Do this for every candidate, including the ones you are sure about —
certainty is exactly the state in which a grep hit gets promoted without anyone opening the file.

Land on one of:

- **Confirmed** — you can name the path, state, or title shape that triggers it and the concrete
  consequence, and you can quote the line. It ships.
- **Uncertain** — the mechanism is real but the trigger depends on runtime state you cannot pin
  down from source. It ships, **labelled as uncertain**, with the one thing that would settle it.
  Do not drop a candidate merely because it needs the app running, a real fetch run, or a
  populated database to prove — those are this project's normal failure modes, not speculation.
- **Refuted** — drop it silently. Only three things refute a candidate: the code does not say that
  (quote the line that proves it), the diff already handles it elsewhere (cite the guard), or it is
  pre-existing and the diff did not make it worse.

Two tools genuinely settle candidates here rather than merely suggesting them: `pytest
tests/test_metadata_matching.py -q` for a matching claim, and `misc/analyze_fetch_log.py` against a
real log for a claim about what a change would have done to a run.

"I could not be bothered to check" is not refutation — that belongs on the `Not verified` line.

## Step 5 — report

```markdown
Reviewed: <which diff, how many files> — <intermediate|pre-merge>, shards: core, <others>

### Blockers
- **#1** `version/fetch.py:NN` — <what is wrong> — <why it fails / what breaks>

### High
- **#2** `version/settingsdialog.py:NN` — …

### Medium
- **#3** …

### Low
- **#4** …

### Still owed before merge      (intermediate runs only, unnumbered)
- open Settings → Web → Metadata and confirm the new option shows its stored value

Carried: #5 fixed · #6 rejected · #8 deferred      (repeat runs only)

**Verdict: FIX FIRST** — <the one sentence that says what must change>
```

Rules for the report:

- **One verdict, always — from the mode's vocabulary.** Pre-merge: `MERGE` / `HOLD`; any Blocker ⇒
  `HOLD`. Intermediate: `CONTINUE` / `FIX FIRST`, where `FIX FIRST` means *this gets more expensive
  the longer you build on it* — a loosened score before more galleries are fetched against it, a
  settings key that will be written into everyone's ini. A self-contained Blocker (one missing
  regression case) is still `CONTINUE` with the Blocker listed.
- **Number every finding, and keep the number stable.** Use a literal `#N` token, **not** a
  markdown ordered list — a `1.` list restarts at each heading and would put two `#1`s in one
  report. Numbering runs across the whole report in printed order. **A carried finding keeps its
  number for the whole session**; new findings take the next unused one. Later runs are therefore
  non-contiguous (`#1, #4, #7`) — accepted, because referential stability is the entire point.
  Numbers reset when the session does.
- **Do not re-litigate a finding.** On a repeat run, re-report only if the code at that location
  changed. Otherwise it goes in the one-line `Carried:` summary. A finding the user rejected stays
  rejected — do not re-raise it in different words or through a different gate.
- **Answer a numbered reply directly.** `fix #1` → apply it; `drop #3` → closed and stays closed;
  `defer #2` → open, no fix now, re-reported only if that code changes. If a reply is ambiguous,
  restate which findings you are acting on before touching anything.
- **Cap the report at ten findings.** If more survive, keep the ten most severe and close with
  `+N further Low findings omitted`. The cap never cuts a Blocker.
- **Merge by root cause, not by call site.** One fix, one entry, one number. List the other sites
  inline: `[also at: file:NN, file:NN]`.
- **Mark uncertainty in place** — `— unconfirmed: <what would settle it>`.
- **Omit empty sections.** A short report is a good outcome.
- **Every finding cites a line you actually read.** Not a hunk header, not an unopened grep hit.
- **State what breaks, concretely.** "Violates the conventions" is not a finding; "this drops the
  numbering guard, so `Kaizoku Kyonyuu` now scores 90 against `Kaizoku Kyonyuu 2` and a lone hit is
  auto-applied, overwriting the gallery's metadata" is.
- **Never pad.** Inventing a Medium to look thorough trains the reader to skim. If the diff is
  clean, say so and stop.
- **Distinguish "did not verify" from "is fine."** Anything you could not run — a screen load, a
  real fetch run, a settings round-trip — goes on a final `Not verified` line rather than passing
  silently.
- **Name the shards you loaded.** The header line is the review's coverage claim.

## Routing

| Situation | Go here |
|---|---|
| Gate 5, 6, 7 or 8 fired | `@.agents/rules/metadata-matching.md` |
| Gate 9 fired | `@.agents/rules/settings-plumbing.md` |
| Gate 3 fired and you are unsure which doc owns the behavior | `@CLAUDE.md`, then the rule whose glob matches |
| A gate needs to know what a change did to a real run | `misc/analyze_fetch_log.py --failures` |
| The review shows the *approach* is wrong, not the code | `create-implementation-plan` — that is a re-plan, not a patch; say so instead of listing symptoms |
| The diff adds or edits a skill or rule | `manage-skill` owns the frontmatter and seam checks |

## Anti-patterns

- **Severity inflation.** If everything is a Blocker, nothing is. Reserve it for "this overwrites
  the user's metadata, damages their library, or gets their IP banned".
- **Reporting the test suite's job.** `pytest` owns the matching functions' correctness. This
  skill's output is the invariants it cannot see.
- **Blaming pre-existing patterns.** Run the delta rule. This is an old codebase with a lot of
  them, and sweeping them up is explicitly not a goal.
- **A verdict with no consequence.** `HOLD` must name the specific change that would flip it to
  `MERGE`; `FIX FIRST` must name what gets more expensive.
- **Skipping the refute pass on the obvious ones.** The candidate you are most certain about is
  the one most likely to reach the report unopened.
