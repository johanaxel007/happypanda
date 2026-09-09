# Plan Review Lenses

The checklist for the Step 3 adversarial self-review. Run every **core lens** on every plan; add
the **domain packs** matching the task shape. Work worst-first: a lens that finds an
implementation-breaking defect outranks ten style notes. Each hit gets exactly one disposition
(mechanical fix / taste decision / assumption / limitation) per `SKILL.md` Step 3.

Each lens carries a one-line **ask** and a closing **pass-fail question** — answer the pass-fail
out loud to yourself. "Probably fine" is a fail; go look. A pass that changes nothing in the draft
was not run adversarially.

## Core lenses (every plan)

### L1 — Shared state & initialization order

*Who else is standing on what I am changing?*

- **Module import order.** `app_constants` and `gallerydb` import each other; anything that adds a
  module-level reference across that boundary can break import for every consumer. New code goes
  after the existing imports, not before.
- **Class attributes used as process state.** `CommonHen.QUEUE`, `COOKIES`, `LOCK` and `LAST_USED`
  are **class** attributes shared by every source subclass — `EHen`, `ExHen` and `ChaikaHen` share
  one queue. A plan that touches queueing owns the drain path for the *other* sources too.
- **`app_constants` is mutable global state.** Settings live there and are rewritten wholesale by
  `settingsdialog.accept()`, whether or not the user visited that tab. Anything reading an
  `app_constants` value at import time captures it once and will not see a settings change.
- **Qt object lifetime and threads.** Fetch runs on a worker thread and talks to the GUI through
  signals. Dialogs are `WA_DeleteOnClose`; a reference kept past close is a dangling object. A
  plan that adds a signal names who connects it and when it is disconnected.

There is no code index in this repo, so "who else stands on this" is a `Grep` — and a grep for the
symbol misses string-bound consumers (Qt connections by name, `settings` keys, ini keys).

**Pass-fail:** for each shared thing the plan touches, can you name every other consumer, and say
what stops one path from leaving it in a state the next one misreads?

### L2 — Read-before-claim

*Is every behavioral claim in this plan something I actually read?*

- List every existing function or code path the draft makes a *behavioral* claim about ("this
  already handles that", "the guard covers it", "that returns a string").
- Each claim must be backed by having read that path this session; otherwise reclassify it as
  **ASSUMPTION** with a verification step.
- **Names that read like guarantees.** `Gallery.path_title` returns the *parent directory* name
  when the path is not a directory. `settings.get` returns the default for a blank value but
  `None` for the literal `none`. `strip_group_prefix` returns `''` when it changed nothing, not
  the input. Read the implementation; do not trust the name.
- **`CLAUDE.md` and the rules are a claim, not a verification.** They were true when written. If
  the plan depends on a specific detail from one, re-read the code for that detail.

**Pass-fail:** could you cite a path and say what you read, for every sentence in the plan that
asserts how existing code behaves?

### L3 — False-green audit

*Could my verification pass while the change is broken?*

This project's gates are weak — no type checker, no lint gate, and no GUI coverage at all — so
this lens carries more weight here than it would elsewhere. For every success signal the plan
relies on, name a failure mode that still shows green:

- **Tests pass, GUI broken.** `pytest` covers the metadata matching functions and nothing else. A
  settings widget that is never populated, a signal never connected, a dialog that raises on open
  — all green. Only launching the app and opening the screen proves those.
- **The module imports, so it works.** Import proves syntax and import order. It does not prove a
  Qt layout was added, a slot fires, or a value round-trips through the ini.
- **A setting appears to save.** `accept()` writes every setting it knows about. A value can be
  written correctly once and then silently overwritten by the next Ok press if `restore_options`
  does not read it back. Round-trip it: set, close, reopen, confirm.
- **A fetch run "succeeded".** A gallery that matched is not evidence the *right* gallery matched.
  Check the score and the chosen title in the log, not just the absence of an error.
- **Verified on one gallery.** Title shapes vary enormously — CJK titles, `|` pairs, deleted
  separators, sequels, anthology chapters. A change verified on one shape has verified one shape.
- **Four `test_init_db` failures are pre-existing.** Do not read them as a regression, and do not
  read a suite that "still has 4 failures" as unchanged without checking the count of passes.

Each named false-green gets a gate, or an explicit accepted-risk note.

**Pass-fail:** name the specific way your gate could pass with the change broken, and say what you
added to close it.

### L4 — Taste vs mechanical decisions

*Am I silently defaulting a call that belongs to the user?*

Classify **every design decision in the draft**:

- **Mechanical** — one defensible answer given the constraints. Decide it, one-line rationale, done.
- **Taste** — a reasonable user could pick differently. Signals: where a new setting goes and what
  its default is, whether a new behavior is opt-in or on by default, how many requests per gallery
  a change costs, naming of anything user-visible, how aggressive a match has to be before it is
  applied automatically.

The recurring taste call here is **how much to automate versus how much to ask**. A match applied
automatically overwrites the user's metadata with no undo; a match sent to the picker interrupts an
unattended batch. Both are defensible and the answer depends on how the user runs it — surface it
rather than assuming. The same goes for anything that raises the request count, given the sources
ban by IP.

**Pass-fail:** for every decision in the plan, can you say why a reasonable user could not have
wanted the other option? If not, it belongs in the decision menu.

### L5 — Conventions & limitations

*Does this violate a rule already written down here, and what does it not do?*

- Check the plan against `@CLAUDE.md`'s Core Constraints, Code Style and Commenting sections, and
  against every `@.agents/rules/` file whose glob the changed files match. A plan that violates a
  written rule is a plan the review will reject later — fix it now.
- Then state what the change **does not** do, as a consequence rather than a caveat: which title
  shapes it does not cover, which source is unaffected, which failure mode is still silent.
- Note any drift found on the way (a doc that is now wrong, a bug you noticed adjacent to the
  work). Report it; do not fold unrelated fixes into the plan. This codebase has plenty of old and
  messy code — modernising it is not a goal, and a plan that quietly starts is scope creep.

**Pass-fail:** can you name the rule files whose globs match every file the plan touches, and say
you read them?

## Domain packs

Add the packs matching the task shape.

### Pack: metadata matching change

*Triggered by:* `version/fetch.py`, `version/pewnet.py`, `version/formatters/title_formatter.py`.

- **Which failure mode is this?** Source returned nothing, candidates scored too low, or a guard
  rejected them — they need opposite fixes. Name it from a real log, not from the symptom.
- **What does it cost per gallery?** Any new query variation multiplies across the library and the
  sources ban by IP. Does the common (matching) path still cost the same number of requests?
- **What does it let through that it should not?** A looser score or a dropped guard is a wrong
  match, which overwrites the user's metadata with no undo. Name the sibling gallery it would now
  accept — sequels, volumes, other-language releases.
- **Does it survive the shapes?** CJK titles, `romaji | translated` pairs, deleted separators,
  bracket-prefixed titles, truncated titles.
- **Which regression case captures it?** New matching behavior means a new case in
  `tests/test_metadata_matching.py`, using the real title that motivated it.

### Pack: new or changed setting

*Triggered by:* `version/app_constants.py`, `version/settings.py`, `version/settingsdialog.py`.

- All four wiring points present, per `@.agents/rules/settings-plumbing.md`.
- Is the default conservative? Anything that writes, or that costs requests, defaults off.
- Does the value round-trip — set, Ok, reopen? A one-way `restore_options` read looks correct and
  silently latches.
- Does an intentionally empty value survive, or does it come back as the default?
- Is the option described in `CHANGELOG.md`?

### Pack: GUI change

*Triggered by:* dialogs, widgets, signals, anything under a `_make_*` method.

- Nothing here is covered by tests. Name the screen to open and what proves it.
- Signal connections are by name at runtime; a rename is invisible to a symbol search.
- Dialogs are `WA_DeleteOnClose` — a kept reference dangles after close.
- Work on a worker thread reaches the GUI only through signals, never by touching widgets.

### Pack: change that writes to the user's library

*Triggered by:* anything renaming, moving, trashing, or overwriting gallery data or metadata.

- There is no undo. What limits the blast radius while testing — a copy, a subset, a setting off?
- Does it respect the existing toggles (`Replace metadata`, `Send files to trash`,
  `Move imported galleries`) rather than acting unconditionally?
- Is the failure mode partial? A run that aborts halfway leaves some galleries changed and some
  not; say what state that leaves and whether re-running is safe.
