# <System Name> Design

<!-- The field lines below end in TWO TRAILING SPACES (invisible, easily stripped by an editor).
     Without them Markdown joins Version/Date/Status/Target into one run-on line. Same in the
     footer. Rule: two trailing spaces on any line whose NEXT line starts a new **Label:** field
     — never on ordinary wrapped prose, which is meant to rejoin. See the skill's Step 3. -->
**Version:** 1.0  
**Date:** <YYYY-MM-DD>  
**Status:** Proposed design — not implemented. <!-- or: Draft — not scheduled. / Implemented (<date>) -->  
**Target:** <optional; e.g. "PyQt6 6.11 on Python 3.14 (current: PyQt5 5.15.11)". Drop the line if the doc has no version target.>

> One-paragraph blockquote summary: what the design is, and the single most important decision or
> finding it settles (bold the decision). A reader should be able to stop here and know what was
> decided.
>
> For a **Draft**, add a second paragraph: what must be re-verified before implementation starts,
> and any prerequisite work that ships first.

**Audited:** <YYYY-MM-DD>, at commit `<short-hash>` (branch `<branch>`).
<What was actually read and run — name the modules inspected and any probes or harnesses built.
Be honest about the boundary between what was executed and what was reasoned; the §2 tags carry
the per-claim detail.>
<!-- Later substantive changes add dated lines here:
**Amended:** <YYYY-MM-DD> — <what changed and why>. -->

**Relationship to other documents:**

- [`../../ROADMAP.md`](../../ROADMAP.md) — carries the pointer to this doc.
- [`../../CLAUDE.md`](../../CLAUDE.md) — the Core Constraints checked in §6.
- [`../../.agents/rules/<RULE>.md`](../../.agents/rules/<RULE>.md) — invariant this design is bound by.

---

## 1. Goals & non-goals

### Goals

1. **<Goal>** — one line each; number them so later sections can reference "goal 2".

### Non-goals (v1)

- <Deferred item> — planned as a **v2 extension**, see the §7 roadmap. (Version deferred wishes;
  do not phrase them as permanent rejections unless they are.)
- <Genuinely rejected item> — why it stays out.

---

## 2. Current state (what exists today)

**Claim legend, used throughout this document:**

| Tag | Meaning |
|-----|---------|
| ✅ **Verified** | Reproduced by executing code. The method is named inline. |
| ⚠️ **Unverified** | Static reading, grep, or reasoning. Plausible, not executed. Treat as a lead. |

| Area | State |
|------|-------|
| <Area> | <Finding from actual code reading, anchored `file.py:line`, with its ✅/⚠️ tag> |

<Include a row for the gates that apply: `pytest tests/ -q` (note the four pre-existing
`test_init_db` failures), `misc/gui_smoke.py`, and whether launching the app is required. State
plainly what each gate does *not* cover — that is usually the residual risk.>

---

## 3. Decision: <the pivotal choice>

<One line naming why this is pivotal. Repeat the section per major decision.>

### Option A — <name> (rejected)

- ✅ <Genuine strength — steelman the losers.>
- ❌ **<Deal-breaker in bold.>** <Explanation, with its ✅/⚠️ tag if it rests on a claim.>

### Option B — <name> ✅ **CHOSEN** <!-- in a Draft: ✅ **preferred direction** -->

<Why it wins, in prose. Reference precedents in this codebase where they exist.>

---

## 4. Design / architecture

<The design itself. Code blocks for key functions or data shapes, matching the surrounding style
rather than a modernised one. An ASCII diagram where components interact:>

```
┌─────────────┐      ┌─────────────┐
│  Component  │ ───▶ │  Component  │
└─────────────┘      └─────────────┘
```

<Call out threading explicitly for anything touching `GENERAL_THREAD`, `moveToThread`, the
`gallerydb` method queue, or a signal whose slot may delete the emitter.>

---

## 5. Prerequisites & integration points

<Work that must exist first — flag a genuinely blocking one with ⚠️ — and seats reserved for
future features that will plug in without restructuring.>

---

## 6. Constraint compliance checklist

| Core constraint (`CLAUDE.md`) | How this design complies |
|-------------------------------|--------------------------|
| **1. Writes to the user's real library** | <…or "not touched", with why> |
| **2. Gallery database is the only copy** | <…> |
| **3. e-hentai request budget** | <…> |
| **4. Settings plumbed through four places** | <…> |

---

## 7. Phased implementation plan

| Phase | Scope | Effort | Depends on | Status |
|-------|-------|:------:|------------|--------|
| **<P>0 — <Foundation>** | <Tooling, gates, or data work first> | 🟢 | — | — |
| **<P>1 — <…>** | <…> | 🟢 | <P>0 | — |

Effort: 🟢 low (hours, localized) · 🟡 medium (days, several files) · 🔴 high (cross-cutting, or
dominated by manual verification).

Status: `—` not started · `In progress` · `✅ YYYY-MM-DD` complete · `⏸️ YYYY-MM-DD` deliberately
not implemented · `⛔ Superseded YYYY-MM-DD — <by what>`. **Date every closed phase** — an undated
completed phase reads as present tense.

<State which minimal phase set delivers standalone value, and which phase dominates the schedule.
Name each phase's gate: `pytest tests/ -q`, `misc/gui_smoke.py`, or launching the app — the GUI has
no pytest coverage, so anything the smoke test does not reach is verified by hand or not at all.>

### Extension roadmap (post-<P>N, in intended order)

| Version | Extension |
|---------|-----------|
| **v2**  | <…> |
| **v3+** | <…> — gets its own design doc when it becomes concrete. |

---

## 8. Open questions <!-- Only questions still open AT COMMIT TIME. Same-session answers are folded
into the body instead. A Draft titles this "Verification checklist (MUST re-verify before
implementation)" and lists what was never executed. -->

1. **<Question>** — <what would resolve it, and where the answer will land>.

---

## 9. Rejected alternatives

<The standing "do not re-litigate this" list, distinct from the §3 sections above: those capture
one choice in context, this is the durable record of what was turned down and why. Bottom
placement is deliberate — reference material for a rare reader.>

| Alternative | Why rejected | Date |
|-------------|--------------|------|
| <name/approach> | <the reason, including anything measured> | <YYYY-MM-DD> |

<Include options refuted by measurement, not only design-time choices — a measured NO-GO is the
most expensive kind of knowledge to rediscover.>

---

## Document History

* **v1.0** - Initial design

---

**Last Updated:** <YYYY-MM-DD>  
**Next Review:** <an event, not a date — e.g. "when <P>0 starts">
