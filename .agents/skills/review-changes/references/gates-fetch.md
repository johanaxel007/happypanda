# Fetch gates — online metadata pipeline

Load when the diff touches `version/fetch.py`, `version/pewnet.py`, `version/formatters/`, or the
title-parsing half of `version/utils.py`.

`@.agents/rules/metadata-matching.md` is the source of truth for everything below — open it when a
gate fires. These four are the review-side summary, not a replacement.

Two consequences make this shard the sharpest one: a wrong match **overwrites the user's stored
metadata with no undo**, and the sources **ban by IP on request volume**, with the ban landing on
the user mid-run.

---

## Gate 5 — Matching loosened

**What fails.** The diff makes the pipeline accept a candidate it previously rejected, in a way
that admits the wrong gallery. The specific regressions, each of which has happened:

- **`token_set_ratio` or `partial_ratio` substituted for `fuzz.ratio`.** Both return 100 when one
  title is a subset of the other, so `Schoolgirl Guide` scores a perfect match against
  `Schoolgirl Guide 2` — and 100 is what `_select_match` auto-applies.
- **The numbering guard weakened or bypassed.** `title_numbers()` mismatch must reject the
  candidate whatever it scores; volume, chapter and sequel numbers are a tiny edit distance and a
  large semantic one.
- **The local title split for comparison.** `match_forms()` splits the *candidate* only. Splitting
  the local side too lets `Kaizoku Kyonyuu` match `Kaizoku Kyonyuu Yawara`, a family the numbering
  guard cannot separate because neither has a number.
- **The confidence threshold lowered**, or a comparison moved off `canonical_title()` so raw
  titles are compared.
- **The unverifiable path widened.** A `None` score means "cannot be checked" and a lone one is
  used. Extending that to cases that *can* be compared turns a verified match into an unchecked one.

**How to check.** Read the scoring block in `process_and_filter_results` and `_select_match` in
full — not the hunks. For each loosening, name the sibling gallery it would now accept.

```bash
git diff --no-color $RANGE | grep -nE '^\+.*(token_set_ratio|partial_ratio|token_sort_ratio|FUZZ_CONFIDENCE|title_numbers|match_forms|score is None)'
```

`pytest tests/test_metadata_matching.py -q` settles most candidates here — its guard cases exist
precisely for this gate. A loosening that leaves them green needs a new case, not a shrug.

**Delta-based**, but weigh the consequence rather than the line count.

**Severity.** Blocker. This is the failure mode with no undo.

---

## Gate 6 — Request cost per gallery raised without a gate

**What fails.** A change that issues more requests per gallery on the **common path** — the one
where a gallery matches. Failures may cost more; successes may not.

- a query variation added without a corresponding removal, or `MAX_SEARCH_ATTEMPTS` raised
- pagination followed when the page was not full, or `MAX_SEARCH_PAGES` raised
- a retry loop added around a request
- a request issued outside `begin_lock` / `end_lock`, bypassing the pacing
- a fallback source queried before the primary has actually failed

**How to check.** Count the requests a matching gallery costs before and after. The log states it
directly:

```bash
venv/Scripts/python.exe misc/analyze_fetch_log.py <log>   # "queries issued — N (X per gallery)"
```

If an attempt was added, say which existing attempt it displaces. An attempt that has never
produced a match across a real run is dead weight and should give up its slot rather than extend
the budget.

**Delta-based.**

**Severity.** High, ceiling Blocker when the increase is unbounded (a loop with no cap, a
pagination follow with no "page was full" condition).

---

## Gate 7 — Title handling that breaks on a real shape

**What fails.** A change to query building or title normalisation that mishandles a shape the
user's library actually contains. Each of these has broken a real run:

| Shape | What breaks it |
|---|---|
| `romaji ｜ translated` | the full-width bar; `TranslationStyle.SEARCH` must fold it to `\|` |
| separator deleted, two spaces left | splitting a *formatted* title — formatting collapses the whitespace, so `split_on_separator()` needs the raw folder name |
| CJK title | comparing it to a romaji candidate; the ratio reads 0, not low |
| `[Circle (Artist)]` prefix | a regex that cannot span nested parentheses |
| title carrying `"` | wrapping it in quotes without stripping them — the phrase closes early |
| title over the length budget | keeping the quotes after truncating; a cut phrase matches nothing |
| `~decorated~` token | a delimiter set including `-` or `_`, which eats hyphenated words and artist names |

**How to check.** For each shape the change could touch, run the real title through the changed
function. The test suite has one case per shape with the real title that motivated it; extend it
rather than reasoning in the abstract.

**Delta-based.**

**Severity.** Medium, ceiling High when the shape is common in the library (the `|` pair and the
bracket prefix are the majority of titles).

---

## Gate 8 — New matching behavior with no regression case

**What fails.** The diff changes what matches or what is rejected, and
`tests/test_metadata_matching.py` gained nothing. Every case in that file is a real past failure,
which is what makes a failure there name a specific defect rather than a style disagreement.

A new case is owed when the diff:

- changes a score, threshold, guard, or the set of forms compared
- adds handling for a title shape
- changes what `_select_match` auto-applies versus sends to the picker

**How to check.** `git diff --stat` on `tests/`. Then read the new case: it must use the **real
title** that motivated the change, not a synthetic one — a synthetic title tests the code against
your own understanding of it, which is exactly what is in doubt.

**Absolute** for a behavior change; not owed for a pure refactor with identical behavior.

**Severity.** Medium, ceiling High when the change is a loosening — a guard with no test is a guard
that will be removed again.
