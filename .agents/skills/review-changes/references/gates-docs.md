# Docs gates — agent files, changelog, tooling

Load when the diff touches `CLAUDE.md`, `AGENTS.md`, `.agents/`, `CHANGELOG.md`, `tests/`, or
`misc/`.

Small shard, but both gates catch things that are invisible in a normal read of the diff: a twin
that silently drifted, and a user-visible change nobody wrote down.

---

## Gate 11 — Agent file drift

**What fails.**

- **`CLAUDE.md` and `AGENTS.md` diverged.** They are byte-identical twins. A change to one without
  the other means half the harnesses read stale guidance, and nothing reports it.
- **A rule or skill edited through the `.claude/` junction path.** `.claude/rules` and
  `.claude/skills` are directory junctions into `.agents/`, and are gitignored. A file created
  there is invisible to git and will be lost; an edit made there writes into `.agents/` but is
  easy to then "restore" away with a `git checkout` on the `.claude/` path.
- **`git stash` used during the change.** The rules are tracked at their `.agents/` paths, so a
  stash silently reverts uncommitted agent-file edits with no warning.
- **A skill's frontmatter broken** — a BOM before the `---`, `name` not matching the directory, a
  description over 1024 chars. Route to `manage-skill`, which owns the full checklist.
- **A rule's glob no longer matching the files it describes** after a module was renamed or moved.

**How to check.**

```bash
diff CLAUDE.md AGENTS.md && echo "twins OK"
git diff --name-only $RANGE | grep '^\.claude/'          # should be empty except settings.json
for f in .agents/skills/*/SKILL.md; do head -c3 "$f" | grep -q $'\xef\xbb\xbf' && echo "BOM: $f"; done
```

**Absolute.**

**Severity.** Medium for twin drift; High for a file created under a junction path, because it is
lost rather than wrong.

---

## Gate 12 — User-visible change with no changelog entry

**What fails.** The diff changes something a user of the built app would notice, and
`CHANGELOG.md` has no entry under `## Unreleased`.

User-visible means: a new or changed setting, a change to what metadata fetching matches or
applies, a fixed crash, a changed default, a new supported file type, a visible UI change.

**Not** user-visible, and not owed an entry: refactors with identical behavior, comments, tests,
tooling under `misc/`, agent files, design docs under `Documentation/`, and internal renames.

The entry goes under the existing `- New Features` / `- Fixes` / `- Changes` headings, phrased for
someone who runs the app rather than reads it — what changed for them, not which function moved.
This is also where a bug's *history* belongs, which is why `@CLAUDE.md`'s Commenting section
forbids it in source comments; a fix that rewrites a comment to drop the old symptom should be
adding that symptom here.

**How to check.** `git diff --name-only $RANGE` against the definition above, then grep
`CHANGELOG.md` for the feature.

**Absolute** for a user-visible change.

**Severity.** Low, ceiling Medium for a new setting or a changed default — those are the entries
users actually go looking for, and a setting that appears with no explanation reads as a bug.
