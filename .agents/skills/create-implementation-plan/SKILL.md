---
name: create-implementation-plan
description: Analyze a session-scale task (bug fix, feature, matching-logic change, new setting) and produce an implementation plan that has already survived an adversarial self-review, ending in a decision menu of the genuine judgment calls. Use when the user asks to "create an implementation plan", "analyze X and create a plan", "plan this fix/feature", or "research this, then give me a plan". For a trivial one-file change, skip the plan and just do it. To review a diff that already exists, use review-changes instead. To record an analysis as a durable document for work that may not start for months, use create-design-doc instead.
---

# Create Implementation Plan

Turns "analyze X and plan the implementation" into a plan that has **already survived an
adversarial self-review before the user sees it** — the first plan presented is the second draft.

```
0 Entry  →  1 Research  →  2 Draft  →  3 Adversarial  →  4 Present  →  5 Execute
            (verified      (internal,    (lenses +         (decision menu +  (restate, then
             facts only)    never shown)  dispositions)     labeled assumptions)  run the gates)
```

Only Step 4 is visible to the user.

## When to use / when to skip

- **Use** for session-scale work: a feature, a bug fix whose cause is already known, a change to
  the metadata matching pipeline, a new setting, a refactor spanning several modules.
- **Skip** for a trivial change — one file, one obvious approach. A plan there is ceremony.
- **Skip** when the bug is not yet diagnosed. Find the root cause first; plan the fix once you
  know what it is. A plan built on a guessed cause plans the wrong work. For a metadata-fetch
  bug, diagnosis means reading the log (`misc/analyze_fetch_log.py --failures`), not theorising.
- **Skip** when the work is not starting now and the analysis is what needs preserving — that is
  `create-design-doc`, which writes it to `Documentation/Design/`. The two compose: a phase from
  a design doc's plan table is a normal input to this skill once that phase is picked up.

## Step 0 — Entry

1. Restate the goal, the hard constraints, and the definition of done in a few lines. Ask only if
   genuinely ambiguous — otherwise state your interpretation and proceed.
2. Check `@CLAUDE.md`'s Core Constraints and the `@.agents/rules/` files whose globs match the
   area, plus `CHANGELOG.md` for whether this ground has been covered before.
3. **Run the doc-vs-code drift check.** `CLAUDE.md` and the rules describe the code as of their
   writing. Re-verify every count, name, path, and API claim against current code before the plan
   repeats it. Corrections found here surface in Step 4's "Doc drift found" section.
4. **Never re-plan what an existing plan already scoped.** If it is still sound, the deliverable
   is "execute the part that is not done", not a new plan — say so and stop.

## Step 1 — Research: verified facts only

- Orient with `Grep`/`Glob` for the symbols the plan will name, then `Read` the exact regions.
  There is no code index here, so a "nothing else uses this" claim costs a real grep — including
  for **string-bound** consumers: Qt signal/slot connections by name, `settings` section/key
  strings, and ini keys are invisible to a symbol search.
- **Read-before-claim rule:** no behavioral claim about existing code enters the draft unless that
  code path was read *this session*. "It should compose fine" without reading the callee is how
  plans acquire load-bearing fiction.
- Build an **environment-facts list**. Every fact carries its verification ("`begin_lock` sleeps
  `randint(3, TIME_RAND)` — read `pewnet.py`") or is tagged **ASSUMPTION** in so many words. A
  non-trivial plan that comes back with no assumptions means you did not look hard enough.
- If the work touches an area with a rule (`@.agents/rules/`), read the rule now. Its constraints
  are plan inputs, not review afterthoughts.
- For anything touching online metadata, **read a real log before planning**. The three failure
  modes need opposite fixes, and which one you are facing is a fact, not a guess.

## Step 2 — Draft the plan (do NOT present it)

Required structure — a draft missing one of these is not done:

1. **Numbered steps**, each naming its files and ending in a **verification gate**: which command,
   which screen opened, what specific result proves the step landed.
2. **Explicit out-of-scope list** — what is deliberately not being done, with the reason. This
   codebase is old and uneven; adjacent cleanups belong here, not in the plan.
3. **Commit sequence** — each commit leaves the app runnable on its own.
4. **Effort/risk statement.**

This draft is internal. Presenting it now is the failure mode this skill exists to prevent.

## Step 3 — Adversarial self-review (mandatory, internal)

Re-read the draft as a hostile reviewer, worst-first, against
[references/lenses.md](references/lenses.md) — **read that file now, every time, not only when the
change looks risky.** Run the 5 core lenses always, plus the domain packs matching the task shape.

Run them adversarially: **a pass that produces no changes to the draft is a failed pass, not a
clean one.**

| # | Lens | Asks |
|---|---|---|
| L1 | Shared state & init order | who else is standing on what I am changing |
| L2 | Read-before-claim | is every behavioral claim here something I actually read |
| L3 | False-green audit | could my verification pass while the change is broken |
| L4 | Taste vs mechanical | am I silently defaulting a call that is the user's |
| L5 | Conventions & limitations | does this violate a rule already written down here, and what does it not do |

### Give every hit exactly one disposition

A finding is not resolved by noticing it. Each is exactly one of:

| Disposition | When | Where it surfaces |
|---|---|---|
| **Mechanical fix** | one defensible answer given the constraints | folded into the plan silently |
| **Taste decision** | a reasonable person could choose differently | the decision menu, with a recommendation |
| **Assumption** | the plan depends on it and you cannot verify it this session | the assumptions list, **naming the step that will verify it** |
| **Limitation** | true, unfixable in scope, and the user should know | the plan's limitations, as a consequence |

A finding with *no* disposition gets noticed and quietly dropped — the review ran and changed
nothing. A finding with the *wrong* disposition is worse: a taste call filed as mechanical is
exactly the silent defaulting the decision menu exists to stop.

When torn between mechanical and taste, choose taste. Over-surfacing costs the user one line;
under-surfacing costs them the decision.

## Step 4 — Present: revised plan + decision menu

One message, in this shape. Keep it tight — a plan nobody finishes reading is skimmed, not approved.

```markdown
## Goal
One or two sentences. What is true after this lands that is not true now.

## Verified
- <path> — what it actually does, read this session

## Plan
1. <step> — <file(s)>, ending in its verification gate
2. …

## Decisions I need from you
1. **<the call>** — Option A … / Option B … · **Recommend A**, because …

## Assumptions
- <assumption> — unverified because …; wrong ⇒ <consequence for the plan>

## Verification
<the exact commands — pytest, a screen to open in the running app, a fetch run to re-read>,
and what result proves it.

## Not doing
- <adjacent thing> — <why it is out of scope>

## Doc drift found
- <doc> — says <X>, code says <Y>. Reporting, not fixing here.
```

Drop `Doc drift found` when Step 0 turned up nothing. Never drop the others.

Rules for the visible plan:

- **Decision menu = genuine judgment calls only.** Every surviving taste call gets the options with
  the recommended one first. Use `AskUserQuestion` when the options fit its shape.
- **Never present options without a recommendation.** "A or B?" with no lean pushes the analysis
  back onto the user, which is the work they asked you to do.
- **Every step's gate must be runnable here.** A gate is: `pytest tests/ -q`, a specific screen
  opened in a running app, or a fetch run whose log says the expected thing. "Verify it works" is
  not a gate.
- **State the destructive steps as destructive.** Anything that writes to the user's library,
  overwrites stored metadata, or issues more requests per gallery gets an explicit note about
  what limits the blast radius — a subset to run against, or the request budget it stays inside.

## Step 5 — Execute

Once approved: restate the plan in one line, then work the steps in order, running each step's gate
before moving on. If a step's research invalidates a later step, stop and say so rather than
improvising past it — the approval was for the plan as presented.

Finish with the work **uncommitted** and a suggested commit message, per the Execution Protocol in
`@CLAUDE.md`. Run the `review-changes` skill first on anything non-trivial.
