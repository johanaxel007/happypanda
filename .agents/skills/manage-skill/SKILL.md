---
name: manage-skill
description: Create, edit, or audit an agent skill or rule under .agents/ following the Agent Skills specification and this project's conventions — frontmatter rules, trigger-rich descriptions, the description-token budget, progressive disclosure, and bidirectional seams between skills. Use when the user asks to create, write, or scaffold a new skill or rule, edit or audit an existing SKILL.md, turn a workflow or convention into a skill or rule, or asks "should this be a skill?".
---

# Manage a skill

Authoring and maintenance protocol for skills in `.agents/skills/`. Skills are auto-discovered
from that directory; a correctly-formed skill appears in the agent's available-skills list with no
other registration step. The format follows the **Agent Skills specification** — the condensed
spec is in [references/agent-skills-spec.md](references/agent-skills-spec.md); read it when unsure
about a constraint instead of guessing.

Creating a new skill is Steps 1–5; **Editing an existing skill** is a separate section after them.

## Where things live in this repo

`.agents/` is the canonical location. `.claude/rules` and `.claude/skills` are **directory
junctions** pointing at it — always create and edit files under `.agents/`, never through the
junction path. See the Agent Files section of `@CLAUDE.md` for the junction's git hazards and the
`mklink` command that recreates it after a clone.

## Step 1 — Decide it should be a skill at all

Four containers, and picking the wrong one is the most common mistake:

| Container | For | Loaded |
|---|---|---|
| `CLAUDE.md` / `AGENTS.md` | always-relevant constraints, commands, protocol | every session |
| `.agents/rules/*.md` | constraints that apply **while editing a specific area** | when a matching file is edited (glob frontmatter) |
| `.agents/skills/*/SKILL.md` | episodic, on-demand **procedure** | when its description matches the task |
| auto-memory | single facts, user preferences | recalled by relevance |

A rule and a skill are easy to confuse here. **If it is "do not do X when touching these files",
it is a rule** — glob-triggered, no invocation needed. **If it is "here is the multi-step
procedure for doing Y", it is a skill.** `.agents/rules/metadata-matching.md` is a rule; the
procedure for reviewing a diff against it is a skill.

Check the existing skills list before adding. Every skill's description is loaded into **every**
session forever, whether or not it fires, so measure the standing cost first:

```bash
# total always-loaded description cost across all skills, in BYTES (÷4 ≈ tokens)
for f in .agents/skills/*/SKILL.md; do grep -m1 '^description: ' "$f"; done | wc -c
```

The per-file `-m1` matters: a plain `grep -h` also counts example `description:` lines sitting in
a skill *body* (this file has one), inflating the total. Re-measure rather than trusting a
remembered number.

A near-duplicate costs every future session real context *and* dilutes activation — two similar
descriptions compete for the same trigger. **Prefer extending or splitting a sibling over adding a
near-duplicate.** If the new capability is one section long, it is a section in an existing skill.

## Step 2 — Name and scaffold

```
.agents/skills/<skill-name>/
├── SKILL.md          # required — UPPERCASE filename
├── references/       # optional — docs loaded on demand
├── scripts/          # optional — runnable helpers
└── assets/           # optional — templates, static resources
```

- `name`: lowercase letters/numbers/hyphens, 1–64 chars, no leading/trailing/double hyphens,
  **must equal the directory name**. Verb-first names for workflows (`create-…`, `review-…`);
  noun names for reference cards.
- Save `SKILL.md` as **UTF-8 without BOM**. A BOM before the opening `---` breaks frontmatter
  parsing and the description renders as garbage in the skills list. Note that several modules
  under `version/` *do* carry a BOM — do not copy that habit into `.agents/`.

## Step 3 — Write the frontmatter

This project uses only the two required fields:

```yaml
---
name: <skill-name>
description: <what it does + when to use it, ≤1024 chars>
---
```

(`license`, `compatibility`, `metadata`, `allowed-tools` exist in the spec — add them only with a
concrete reason.)

**The description is the skill's only always-loaded surface** — activation is decided from it
alone. Write it as:

1. One sentence: what the skill does, in specific nouns, not "helps with X".
2. "Use when …": concrete trigger situations *and* literal user phrasings in quotes.
3. If an adjacent skill could be confused with it, an explicit routing line
   (e.g. `For X use the <other> skill instead.`).

## Step 4 — Write the body

No format restrictions; the house style that works here:

- **Title + one-paragraph mission** stating what the skill owns and which sibling owns the
  neighbouring concern — seams stated in both skills, in both directions.
- **Numbered `## Step N` sections** for workflows; tables for reference cards.
- **"When to use / when to skip"** near the top if activation is nuanced.
- **Constraints section** at the end for the hard "do not"s.
- Reference project ground truth by path (`@CLAUDE.md`, `@.agents/rules/…`) instead of restating
  it — restated facts go stale silently.

**Budgets (progressive disclosure):** keep `SKILL.md` under ~500 lines / ~5k tokens. Anything
bulky, stable, or only-sometimes-needed goes in `references/` as its own focused file, linked with
a relative path from the skill root, one level deep. Reference files load only when needed — the
cheap place for templates, checklists, and lookup tables.

**Never-stale rule:** do not hardcode links to living artifacts (a current line number, today's
counts, a specific log's numbers) in `SKILL.md`. Either describe how to *find* the artifact (a
grep, or `misc/analyze_fetch_log.py`) or put a stable template in `references/`. Naming stable
*directories* and *conventions* is fine. Same for numbers: say how to re-measure rather than
baking in today's value.

**Scripts:** anything executable goes in `scripts/`, or — if it is substantial and reusable
outside the skill — in `misc/` at the repo root with the skill pointing at it. Run everything
through `venv/Scripts/python.exe`, never a bare `python`.

## Step 5 — Validate and integrate

1. **Self-check against the spec** using the checklist in
   [references/agent-skills-spec.md](references/agent-skills-spec.md).
2. **Read the file back once**: no BOM, frontmatter opens at byte 0, `name` matches the directory,
   description under 1024 chars.
3. **Cross-reference seams, both directions.** If the new skill borders an existing one, name the
   split in **both** bodies. A one-way seam is how two skills end up both half-owning a concern,
   and the older skill is the one an agent is more likely to already be inside. If a user could
   plausibly invoke the wrong one, put the routing line in the **description** too — the only
   surface available before either body loads.
4. **Update `CLAUDE.md` and `AGENTS.md` only if** the skill must be discoverable from a rule that
   already lives there. Most skills need no mention — the description is the discovery mechanism.
   The two files are byte-identical twins; change both.
5. Offer a commit message in the project's single-line `Verb: description` style (`Skill: …`);
   never auto-commit.

This skill owns a skill's *form* — frontmatter, budget, seams, where the file lives. It does not
review the resulting diff: `review-changes` owns that, and its gate 11 checks the twin files, the
junction paths and the frontmatter of anything under `.agents/`. Run it before offering the
commit, the same as for any other change.

## Editing an existing skill

- **If the edit adds capability, extend the description too.** A skill that grows a section
  nobody can trigger has gained nothing.
- **If the edit changes what the skill owns, re-check the seam** (Step 5.3) in the *other*
  direction — a sibling's routing line may now name the wrong owner.
- **Preserve the description's trigger phrases.** They are load-bearing for activation; never tidy
  them out to make the line read more cleanly. A tidier description that stops matching is a skill
  that never runs.
- **Read the file back** after editing: no BOM, frontmatter still at byte 0, `name` still equals
  the directory, description still under 1024 chars, fenced code blocks still valid.

## Gotchas

- **IDE auto-reflow corrupts SKILL.md code blocks.** An editor reformat can mangle fenced examples
  into one-token-per-line garbage. After any IDE-side save of a `SKILL.md`, re-check its code blocks.
- **Never create a file under `.claude/skills/` or `.claude/rules/`.** Those are junctions and are
  gitignored — a file created there is invisible to git and will be lost.
- **Don't write generic knowledge.** Ask of every line: *would the agent get this wrong without
  it?* If no, cut it. A skill is the corrections and conventions specific to this repo, not a
  restatement of what a capable model already knows.

## Constraints

- **One skill, one concern.** If the body needs an "and also, separately…" section, split it.
- **Do not duplicate a sibling skill's rules** — link by name and let it own them.
- **Do not write speculative skills** for workflows that have not happened at least once. Skills
  encode *proven* procedure.
