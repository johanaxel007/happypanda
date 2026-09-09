# Roadmap

Features that have been decided on but not built. Each entry records what the feature is, what
already exists to build it from, and what the hard part is — so that picking one up does not
start with rediscovering the same ground.

Delete an entry when it ships; describe the shipped behaviour in `CHANGELOG.md` instead.

---

## Volume and part markers the numbering guard cannot read

`title_numbers()` decides whether two titles are the same work, and a mismatch rejects a
candidate whatever it scores. It reads Arabic digits and upper-case Roman numerals. It does not
read the markers a Japanese title uses for a volume or a part, so those pairs reach the scorer on
title similarity alone — and they sit close enough that a wrong one can be applied over the
gallery's own metadata.

The shapes, all taken from a real library:

| shape | a pair that reads as one work |
| --- | --- |
| romanised numerals | `Yurori Kyouiku Ni` / `Yurori Kyouiku San` |
| delimited numerals | `Hashihime Shinshoku -Ni-` / `Hashihime Shinshoku -San-` |
| counted numerals | `Kuchikukan … Zecchou Souchi Sono Ni` / `… Sono San` |
| part markers | `Ochikaku Parasite Chuu` / `Ochikaku Parasite Jou` |
| compilation markers | `Mahou Shoujo Soushuuhen` / `Mahou Shoujo Mana` |
| edition letters | `TORANOANA Girls Collection 2013 SUMMER TYPE-X` / `TYPE-A` |

**What exists already.** The guard is already decisive and already in one place:
`title_numbers()` in `version/fetch.py`, with two consumers (`process_and_filter_results` and
`betterversions.same_work`). `ROMAN_NUMERALS` and `ROMAN_BLOCK` beside it show the shape a
vocabulary takes and the case and word-boundary conditions it needs. `.agents/rules/metadata-matching.md`
carries the invariants.

**The hard part is that a vocabulary is a trap, and this is measured rather than suspected.**
Reading `ni`, `san` and `go` as 2, 3 and 5 **broke 142 already-matched galleries and fixed
none**:

- `Kashima Suitei ni Otsu`, `Suki ni Natte Kita node`, `Saredo Uraraka ni!` — `ni` is the
  particle "to/at", not two.
- `Yamashiro-san ga Shireishitsu de Fusou Nee-sama wo Matsu Riyuu` — `san` is the honorific.
- `Saimin Ihen Go` — here `Go` really *is* five, and the folder writes it `Saimin Ihen 5`, so
  any reading has to be two-way or it breaks the match it was meant to fix.

Context gating — counting a numeral only after a counter word like `Sono` or `Dai`, or inside a
delimited `-Ni-` — was prototyped and still cost more than it bought: 266 folder/source
disagreements against a baseline of 227, and it never reaches `Yurori Kyouiku Ni`, which has no
counter. Adding the part markers (`zenpen`/`chuuhen`/`kouhen`, `jou`/`chuu`/`ge`) added 28 more,
most of them pairing a marker against a character name rather than a sibling part.

**What the guard is worth in total.** 1,557 pairs of distinct works in a real library clear a 70%
ratio against each other *with the numbering guard passing them*. Reading Roman numerals
separated 114 of those. So the residue is real, but the marker families above are a modest share
of it and the rest differ by things no numbering guard can see.

**A different lever may beat the vocabulary, and is unmeasured.** Every shape in the table
differs from its sibling only in one trailing or bracketed token. A guard shaped as "these two
canonical titles differ only in a trailing token, so treat them as different works" would cover
Roman numerals, the Japanese markers, `TYPE-A` against `TYPE-X` and `Chuu` against `Jou` at once,
with no vocabulary to maintain in any language. Its risk is the opposite one: rejecting a correct
match whose source title carries a trailing word the folder name dropped. Measure that before
writing it — the population is folder-name against applied-source-title over the whole library,
which is how every figure above was obtained.

**Known gap in the shipped Roman fold, not worth its own entry.** A folder name that dropped a
colon reads `DR:II` as the single word `DRII`, so three galleries of Behind Moon's `DR:II` series
now fail the guard against their own source titles. Case-boundary splitting would fix it and
would cost more elsewhere.

**Sequencing note.** The value of any of this scales with the confidence threshold, because a
pair only reaches the guard if it clears the score first. At the default of 95 the exposed
population is much smaller than at 70 — the Roman fold's own accounting went from 5 gains and 8
losses at 70 to 1 gain and 3 losses at 95. Re-measure at the threshold in force rather than
reusing these figures.

---

## A short title cannot say which work it is, and the fetch has no tags to ask

`canonical_title` strips the trailing group naming the series, which is what lets a bare folder
name match a decorated site title. For a title of a few characters that also removes the only
thing telling two unrelated works apart: `Seishoku (Phantasy Star Online 2)` and
`Seishoku (Fate/Grand Order)` both reduce to `Seishoku` and score a perfect 100. A lone confident
hit is applied without being shown to anyone, so this is the failure mode with no undo.

It has been observed for real, once — a better version scan offered the Fate/Grand Order release
as an improvement on the Phantasy Star Online 2 gallery.

**What exists already.** The scan half is solved and shipped: `betterversions.same_parody`
compares the `Parody:` namespace by intersection, which works because the source normalises the
tag — one `kantai collection` against the two spellings titles use. See the scan section of
`@.agents/rules/metadata-matching.md`.

**The hard part is that the fetch cannot use that signal.** A gallery being fetched for the first
time has no tags yet — acquiring them is the point of the run — so there is nothing on the local
side to intersect. Only the titles' own groups are available, and those are exactly what the tag
was chosen over: comparing them rejects `Kantai Collection` against
`Kantai Collection -KanColle-`, which is one work. Worse, the local side is a *folder name*, and
folder names drop those groups routinely, which is why `canonical_title` strips them at all.

**Two shapes worth measuring, neither tried.** Compare the titles' groups only when both sides
carry one, accepting a loose match — the population to measure is folder name against the source
title actually applied, over the whole library, which is how every other figure in this file was
obtained. Or refuse to trust a canonical title below some length at all, which the rule already
names as an untried idea for the same underlying problem.

**Sequencing note.** Independent of the lone-confident entry below, and not helped by it: these
two titles score **exactly 100**, so requiring a perfect match before applying anything
unattended leaves this collision untouched. Nor does raising the confidence threshold — 100
clears every bar there is. A guard is the only lever, which is what makes this the sharper of the
two entries even though it is rarer.

---

## The better version scan follows only the first page of results

`betterversions.SCAN_SEARCH_PAGES` is 1, so a scan query costs exactly one request and a run's
total can be stated before the user agrees to it. The cost is that a query whose first page comes
back full is truncated: **4 of 46 galleries in a real run returned 25 hits**, so roughly one
gallery in ten has candidates that were never looked at.

**What exists already.** `EHen.search` takes `max_pages`, and `run_pass` already follows the
source's own next-page link only when a page came back full, so raising the cap is a one-value
change. The consent dialog builds its figure from `scan_estimate_seconds`, which assumes one
request per gallery and would have to change with it.

**The hard part is that it is a bad trade at the measured yield.** A run produced two rows from
59 galleries, and the galleries whose page filled up are the ones with the most generic titles —
which is also where `same_work` is weakest, so the extra page is mostly other works. Doubling the
request volume against a source that bans by IP, to chase that, is not obviously worth it.

**The cheap half is worth doing first.** Log which galleries came back with a full page. That
costs nothing, turns an invisible limitation into a list, and lets those few be rescanned by hand
from the gallery context menu — which already scans exactly a selection.

**Sequencing note.** Revisit only if the scan starts earning its keep. If the yield stays near
two rows per sixty galleries, the question is whether the whole pass is worth its ten hours, not
whether it should cost twenty.

---

## Require an exact title match before metadata is applied unattended

`_select_match()` applies a candidate with no further checking when it is the *only* one that
cleared the confidence threshold — `elif len(confident_results) == 1`. It does not have to be a
perfect match, only a lone one. That is the path by which a near-miss sibling gets written over a
gallery's metadata with nothing shown to the user, and it is the failure mode with no undo.

The alternative is to require a score of 100 to apply unattended and send everything else to the
chooser.

**What exists already.** The picker path is right there in the same function, and
`perfect_matches` is already computed. The change is which branch a lone confident result takes.

**The hard part is that nobody knows what it would cost.** Across every log available the lone
confident path fired **zero** times — `Single perfect` twice, `Multiple confident` (the chooser)
seven times — which makes it look free. But those logs come from a library that is 98.6%
matched by stored link, so title scoring barely runs at all. On a fresh import it is the normal
path, and requiring 100 there could mean thousands of chooser prompts, each of which blocks on a
human at the end of the pass.

**Measure it first, and the sample already exists.** The galleries that still carry no link are a
fresh-library sample — a couple of hundred of them, one fetch pass, well inside the request
budget. `misc/analyze_fetch_log.py` then reports the split between `Single perfect`,
`Single confident` and the chooser directly. That ratio is the whole decision.

**Sequencing note.** Raising the confidence threshold to 95% already removed the 70–94 band this
would have caught, so what remains is the narrow 95–99 band. Do the measurement before assuming
there is anything left to fix.

---

## Migrate from Qt5 to Qt6

PyQt5 5.15.11 / Qt 5.15.2 is the last supported Qt5, and the surface to move is ~572 edits across
16 modules. The full analysis, including the binding decision and a phased plan, is in
[`Documentation/Design/QT6_MIGRATION.md`](Documentation/Design/QT6_MIGRATION.md) — read that
before touching this, so a session does not repeat the measurement.

**What exists already.** The inventory is done and pinned to commit `69b1ae0`: 517 enum call
sites across 154 symbols, every one resolved to its Qt6 scope; the nine removed-API families with
their call sites; and a two-way compatibility matrix for PyQt5 against PyQt6. `misc/gui_smoke.py`
is the only GUI gate and is itself PyQt5, so it is the first thing to port.

**The hard part is not the mechanical diff — it is that nothing can test the result.** 98% of the
edits are forward-compatible, and that is measured, not assumed: all 517 enum sites already accept
the Qt6 spelling on the shipping PyQt5, with identical values. So the bulk can land incrementally
against the running Qt5 app. What remains is 62 widget subclasses and 7 custom painters with no
automated coverage, each of which fails only when a user opens that particular dialog, and
rescoping errors surface lazily at paint time rather than at import. The shakedown dominates the
schedule, and per Core Constraint 1 it has to run against a copy of the database, because a
mis-scoped button comparison inside a delete confirmation is silent data loss.
