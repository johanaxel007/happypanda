# Agent Skills Specification (condensed)

Condensed from the Agent Skills spec at `https://agentskills.io/specification` (fetched
2026-07-03; re-check the source if a constraint seems off or tooling rejects a skill).

## Directory structure

A skill is a directory containing, at minimum, a `SKILL.md` file:

```
skill-name/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation loaded on demand
├── assets/           # Optional: templates, resources
└── ...               # Any additional files or directories
```

## SKILL.md frontmatter

YAML frontmatter followed by Markdown body. Fields:

| Field           | Required | Constraints                                                                                                                   |
|-----------------|----------|-------------------------------------------------------------------------------------------------------------------------------|
| `name`          | Yes      | ≤64 chars; lowercase `a-z`, `0-9`, hyphens; no leading/trailing/consecutive hyphens; **must match the parent directory name** |
| `description`   | Yes      | 1–1024 chars; what the skill does **and** when to use it, with trigger keywords                                               |
| `license`       | No       | License name or bundled license file reference                                                                                |
| `compatibility` | No       | ≤500 chars; only for real environment requirements (products, packages, network)                                              |
| `metadata`      | No       | Arbitrary string→string map; use unique-ish key names                                                                         |
| `allowed-tools` | No       | Space-separated pre-approved tools (experimental; support varies)                                                             |

Description quality bar: "Extracts text and tables from PDF files, fills PDF forms… Use when
working with PDFs, forms, or document extraction" ✅ — "Helps with PDFs" ❌.

## Body

No format restrictions. Recommended: step-by-step instructions, input/output examples, edge
cases. The entire body loads on activation.

## Progressive disclosure (token budgets)

1. **Metadata** (~100 tokens): `name` + `description` — loaded at startup for *every* skill.
2. **Instructions** (<5000 tokens recommended, keep `SKILL.md` under ~500 lines): loaded when
   the skill activates.
3. **Resources** (`references/`, `scripts/`, `assets/`): loaded only when needed.

Keep reference files focused (smaller files = less context per load). Reference them with
relative paths from the skill root; keep references one level deep — no nested reference chains.

## Optional directories

- `scripts/` — executable code; self-contained or with documented dependencies, helpful errors.
- `references/` — on-demand documentation (technical references, templates, domain files).
- `assets/` — static resources (templates, images, data files, schemas).

## Validation checklist (manual equivalent of `skills-ref validate`)

- [ ] `SKILL.md` exists, uppercase filename, UTF-8 **without BOM**, frontmatter `---` at byte 0.
- [ ] `name`: 1–64 chars, `[a-z0-9-]`, no `-` at start/end, no `--`, equals directory name.
- [ ] `description`: non-empty, ≤1024 chars, states what + when.
- [ ] `compatibility` (if present): ≤500 chars.
- [ ] Relative file references resolve; no absolute paths.
- [ ] `SKILL.md` body within budget (~500 lines); bulky content moved to `references/`.

Upstream validator: `skills-ref validate ./my-skill`
(github.com/agentskills/agentskills, `skills-ref` reference library — not installed in this
repo; install only if skill authoring becomes frequent).
