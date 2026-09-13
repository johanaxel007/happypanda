---
name: create-design-doc
description: Author a design doc under Documentation/Design/ — a durable record of an analysis, the decisions it settled and a phased plan — following this repo's mandatory header, status taxonomy, verified/unverified claim tagging and Document History footer. Use when the user asks to "write a design doc", "document this analysis", "turn this into a design doc", or to record findings so a future session can pick the topic up without redoing the work. For work you are about to execute this session use create-implementation-plan instead; for a short "decided but not built" note, add a ROADMAP.md entry instead.
---

# Create Design Doc

Authoring protocol for documents in `Documentation/Design/`. These are written to be **trusted by
default** — a future session reads one instead of redoing the analysis, so every claim in one gets
acted on. That is what drives the two rules this skill exists to enforce: claims are tagged
verified or unverified (Step 4), and the doc is cross-linked from `ROADMAP.md` so it is actually
found (Step 6).

This skill owns the document's *form*. It does not own the analysis: `create-implementation-plan`
owns planning work about to be executed, and a design doc often *feeds* it later — a phase from
the plan table becomes that skill's input when the phase is finally picked up.

`Documentation/Design/QT6_MIGRATION.md` is the first doc written to this format and is a working
exemplar. Read it when a section below is ambiguous — but read the template for structure, since a
living doc drifts as its phases close.

## Step 1 — Confirm it is a design doc at all

Four homes, and picking the wrong one is the usual mistake:

| Home | For | Shape |
|---|---|---|
| `Documentation/Design/*.md` | An analysis worth preserving: a decision with real alternatives, a multi-phase plan, findings that cost measurement | Full doc, this skill |
| `ROADMAP.md` | Decided but not built, and small enough to state in prose | One `##` section: what it is / what exists already / what the hard part is |
| `CHANGELOG.md` | Behaviour that **shipped** | An entry under `## Unreleased`, phrased for someone who runs the app |
| `create-implementation-plan` | Work starting **now** | Presented in chat, not a file |

The `ROADMAP.md` boundary is the one to get right, because both describe unbuilt work. **Prose
that fits in one ROADMAP section belongs there.** Promote to a design doc when there is a decision
with rejected alternatives, a phase table, or a body of verification that would otherwise be
re-done. When a design doc exists, the ROADMAP entry stays as a short pointer to it (Step 6) —
ROADMAP is where sessions look.

Do not write a design doc for a change that is about to be implemented in the same session. That
is `create-implementation-plan`'s job, and a doc written for work already underway is stale on
arrival.

## Step 2 — Name the file and its phase IDs

- `Documentation/Design/SCREAMING_SNAKE_CASE.md`, descriptive, **no date in the filename**.
  Suffix `_REPORT.md` for a findings list, `_ROADMAP.md` for a plan-only doc.
- If the doc has a phased plan, give the phases a short prefix unique in `Documentation/` and
  number them from 0, with phase 0 being foundation or tooling work (`Q0`…`Q5` in the Qt6 doc).
- **Phase IDs are never recycled and never dropped.** Commit messages cite them, so a closed phase
  keeps its row rather than being deleted.
- Save as UTF-8 **without** a BOM. Several modules under `version/` carry one; do not copy that
  habit into documentation.

## Step 3 — Write the mandatory header

The full skeleton is in [references/system-design-template.md](references/system-design-template.md).
Read it before writing rather than copying an existing doc, which will have drifted.

**The invisible part, and the easiest thing to get wrong:** stacked `**Label:**` fields need
**two trailing spaces** or Markdown joins them into one run-on line. The rule: two trailing spaces
on any line whose *next* line starts a new `**Label:**` field — never on ordinary wrapped prose,
which is meant to rejoin. The last field in a block needs none, because a blank line follows it.
A field line directly after a blockquote cannot be fixed this way; put a blank line between them.

Two repo settings keep those spaces alive and are already in place — `.editorconfig`
(`[*.md] trim_trailing_whitespace = false`) and `.gitattributes` (`*.md whitespace=-blank-at-eol`,
which stops `git apply --whitespace=fix` stripping them). Verify after writing, because a heredoc
or an editor can still eat them:

```bash
sed -n '1,8p' Documentation/Design/<DOC>.md | cat -A | sed 's/\$$/<EOL>/'
```

**Status taxonomy** (exact strings):

- `Draft — not scheduled.` — direction captured. **Must name what to re-verify** before
  implementation starts, in the blockquote and in a verification-checklist section.
- `Proposed design — not implemented.` — ready to build against.
- `Implemented (<YYYY-MM-DD>)` — the design shipped. The doc stays in `Design/`; `CHANGELOG.md`
  describes the resulting behaviour. (`Documentation/Architecture/` does not exist yet — create it
  only when a doc genuinely needs to become authoritative reference rather than a record.)

**The Audited line is not optional.** Pin the commit (`git rev-parse --short HEAD`) and the branch,
and be honest about what was actually inspected — name the files read and the probes run.

## Step 4 — Write the body using the house patterns

The template shows each in place. The three this repo cares about most:

### Verified vs unverified claims — required

Define a two-state legend near the top and tag claims throughout:

| Tag | Meaning |
|-----|---------|
| ✅ **Verified** | Reproduced by executing something. Name the method inline. |
| ⚠️ **Unverified** | Static reading, grep, or reasoning. A lead, not a fact. |

Prefer executing a check over recalling one. For a claim about a third-party library, build a
throwaway venv in the scratchpad and probe the real thing rather than trusting memory. Effort
estimates, rendering behaviour, build outcomes and "it should still work" are unverified by
default. Re-check numbers while writing instead of copying them forward from earlier in the
session.

Untagged claims are the failure this rule exists to prevent: the doc is read as ground truth, so an
unmarked guess is worse than no doc.

### Decision sections — show the losers

`### Option A — <name> (rejected)` with ✅/❌ bullets, steelmanning each; the winner marked
`✅ **CHOSEN**` (or `✅ **preferred direction**` in a Draft). Verdicts are explicit, never implied.

### Constraint compliance checklist

A table mapping each of the four **Core Constraints** in `@CLAUDE.md` to how the design satisfies
it — the real library it writes to, the gallery database being the only copy, the e-hentai request
budget, and settings plumbing through four places. Do not restate the constraints; name them and
say how this design complies. A design that touches none of them says so per row rather than
dropping the table.

Also useful, per the template: goals and versioned non-goals, a current-state table anchored with
`file.py:line`, a phased plan with dated statuses, an extension roadmap, and **Rejected
alternatives** at the bottom — the standing "do not re-litigate this" list, which is the section
that most repays a reader a year later. Record options refuted by *measurement* there, not only
design-time choices.

### Style

- ~100-char prose lines; tables may exceed it. Wrapped prose is meant to rejoin, so never add
  trailing spaces to it.
- Pre-align table pipes.
- Write it as a continuous design. Do not ship "open question → resolved same day" scaffolding;
  fold same-session answers into the section where they belong. Only genuinely open questions
  survive to the commit.
- Cross-references use `§N`; re-check them after restructuring.

## Step 5 — Close with the Document History footer

```markdown
---

## Document History

* **v1.0** - Initial <draft|design|report>

---

**Last Updated:** <YYYY-MM-DD>  
**Next Review:** <an event, not a date — e.g. "when Q0 starts">
```

Every later substantive edit bumps **Version**, adds a one-line entry, and updates
**Last Updated**. Typo fixes do not. A real later amendment also gets a dated
`**Amended:** <date> — <what changed>` line under the Audited block.

## Step 6 — Integrate and hand off

1. **Cross-link from `ROADMAP.md` in the same commit.** A design doc nobody links is a design doc
   nobody finds — ROADMAP is where a session actually looks for unbuilt work. Keep the entry in
   ROADMAP's house shape (what it is / what exists already / what the hard part is) and point at
   the doc for the detail rather than duplicating it.
2. **Do not add the doc to `CLAUDE.md`/`AGENTS.md`** unless the user asks. Those reference
   ground truth, not proposals — and they are byte-identical twins, so any change means both.
3. **Run `review-changes`** before offering the commit, as for any change. Gate 12 does not apply:
   a design doc is not a user-visible change and owes no `CHANGELOG.md` entry.
4. **Offer a commit message; never auto-commit.** Single-line `Verb: description` per `@CLAUDE.md`
   — `Docs:` prefix, aspects joined with ` + `, cause and effect with ` -> `.

## Constraints

- **Never fabricate the Audited line.** If the analysis was partly reasoning, the tags in Step 4
  are how that is disclosed — not a vaguer Audited line.
- **Do not transcribe another doc's structure.** Only the template is stable; living docs drift.
- **A phase table with undated closed phases is a trap.** `✅ <YYYY-MM-DD>` on every closed phase —
  an undated one reads as present tense, and a reader cannot tell a phase closed last week from
  one closed a year ago.
