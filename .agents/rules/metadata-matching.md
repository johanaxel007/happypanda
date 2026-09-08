---
name: metadata-matching
description: Rules for the online metadata pipeline — query building, candidate scoring, source fallback and request budget. A wrong match overwrites the user's stored metadata with no undo, and the sources ban by IP on request volume, so changes here are measured against real logs rather than reasoned about. Enforced when editing fetch.py, pewnet.py or title_formatter.py.
trigger: glob
glob: "{version/fetch.py,version/pewnet.py,version/formatters/title_formatter.py}"
paths:
  - "version/fetch.py"
  - "version/pewnet.py"
  - "version/formatters/title_formatter.py"
---

# Metadata matching

Two things make this code unforgiving:

- **A wrong match is data loss.** With `Replace metadata` on, the matched gallery's title,
  artist, tags and date overwrite the local ones, with no undo. Not matching is a *better*
  outcome than matching the wrong gallery — a sibling volume, a different translation, a
  same-series sequel.
- **The sources ban by IP on volume.** Every extra query variation multiplies across the whole
  library. `MAX_SEARCH_ATTEMPTS` in `_auto_metadata_process` bounds it; `CommonHen.begin_lock` /
  `end_lock` pace it. Neither is decoration.

## Measure before you change matching

Query order, the confidence threshold and the guards are tuned against real runs, not intuition.
Before reordering, loosening, or adding a variation:

```sh
python misc/analyze_fetch_log.py path/to/happypanda.log            # what matched, on which attempt
python misc/analyze_fetch_log.py path/to/happypanda.log --failures # and why the rest did not
```

The analyzer separates the three failure modes, and they need opposite fixes:

| Symptom in the log | Meaning | Where the fix belongs |
|---|---|---|
| `No hits found` on every query | the query never reached the gallery | query building |
| candidates returned, `Found 0 confident result(s)` | the titles disagree | scoring / canonicalisation |
| `Discarded N result(s) with different numbering` | a guard rejected them | usually correct; check the numbers |

An attempt that never wins across a whole run is dead weight — give its slot to something that
does, rather than raising `MAX_SEARCH_ATTEMPTS`. The cap is deliberately 4 and all four slots
have since been measured producing matches, so treat a proposal to lower it as needing the same
evidence as a proposal to raise it.

**A short title is the unsolved case.** `fuzz.ratio` against a title of a few characters clears
70 for anything containing it: a real run searching `"Hong"` returned 75 hits and scored 35 of
them confident, which is a chooser nobody can work through. The threshold cannot fix this on its
own, because the same threshold is right for a long title. Treat a proposal here as needing a
measurement first - the shape of a fix is probably a length-aware threshold or refusing to search
below some title length at all, and neither has been tried.

## Scoring invariants

- **Canonicalise both sides.** `canonical_title()` before `fuzz.ratio`, never a raw title
  against a raw title. Sources keep `[Circle (Artist)]`, `(Magazine)`, `[English]`, `[Digital]`
  and translator credits that the folder name has already lost, and `fuzz.ratio` is length
  sensitive enough that those alone sink an exact match.
- **Never `token_set_ratio` or `partial_ratio`.** Both return 100 when one title is a subset of
  the other, so `Schoolgirl Guide` scores a perfect match against `Schoolgirl Guide 2` and gets
  auto-applied. A score of 100 must mean "identical after canonicalisation", because
  `_select_match` auto-selects a lone perfect hit.
- **Numbering is decisive, whatever the score.** `title_numbers()` compares the *set* of numbers
  on both sides; a mismatch rejects the candidate. Volume, chapter and sequel numbers are a tiny
  edit distance apart and a large semantic one.
- **Compare halves too, on the candidate side only.** `match_forms()` offers each half of a
  `romaji | translated` pair, because a folder often kept one half while the source has both.
  Do **not** split the local title as well: `Kaizoku Kyonyuu` would then match
  `Kaizoku Kyonyuu Yawara`, a family the numbering guard cannot separate. The same one-sided rule covers the
  trailing `-Subtitle-` form: reducing both sides would score `Title -Sub A-` and
  `Title -Sub B-` a perfect 100 against each other.
- **Language is evidence, but only in one direction.** `title_languages()` reads the bracketed
  tags off a candidate. A candidate tagged with a language the local gallery is not in is a
  different release and gets dropped; a candidate that states no language is the ordinary shape
  of an untranslated listing and is always kept. The filter runs only when the *local* language
  is itself a translation, because `G_DEF_LANGUAGE` is stored for every gallery whose folder
  name never stated one - "Japanese" is as often "nobody knew" as it is a fact, and filtering on
  it would throw away correct English hits.
- **Order the candidates, not just the list.** Sources list newest first, so a work's later
  translations arrive ahead of the release actually held locally, and equal scores are common
  enough that the tie decides what the user sees first. The sort therefore breaks ties on
  whether the candidate's language matches the gallery's. This is presentation, so it applies
  whatever the filter setting says.
- **An unverifiable pair is `None`, not 0.** A title-less result (chaika resolving by hash) and
  a cross-script pair (Japanese folder name, romaji site title) cannot be compared. Scoring them
  0 discards correct hits; `None` marks them unverified, so a lone one is used and several go to
  the picker.

## Query building

- `TranslationStyle.SEARCH` normalises full width to ASCII for queries. `DEFAULT` does the
  opposite, for filenames. Using the wrong one sends `｜`, `＂` and `＜＞` to a source that
  indexes none of them.
- Strip `"` from a title before wrapping the query in quotes, or the phrase closes early.
- A quoted phrase that had to be truncated matches nothing — drop the quotes when trimming.
- `split_on_separator()` takes the **raw** folder name. A deleted separator survives only as the
  whitespace run around it, and formatting collapses that.
- **`Gallery.path_title` is only a title when the path is a live directory.** It returns
  `path.parent.name` for anything else, so an archive-backed gallery, or any gallery whose drive
  is not mounted, reports the name of the folder *above* it. A fetch run started with the library
  offline would search for that same string for every gallery. The scoring guards reject most of
  the results, but the run is wasted; check the first query in the log looks like a real title.

## The picker

Ambiguity is resolved by a human, at the *end* of the pass, so what the chooser shows is part of
matching rather than a separate UI concern.

- **The listing gives one title, it may be the wrong alphabet, and it has no cover.** A
  Japanese folder name against a list of romaji candidates cannot be told apart by eye. Three
  things address this and none should be removed: every choice carries its source url and opens
  in a browser on right or double click; the local gallery opens its own folder the same way;
  and `PICKER_PREVIEWS` supplies each candidate's native title and cover.
- **Batch the preview lookup across the whole run, never per dialog.** `_candidate_previews`
  collects every candidate url from every ambiguous gallery, dedupes, and asks `gdata` in chunks
  of `EHen.MAX_GDATA_URLS`. One call per dialog would be a request each and would put
  `begin_lock`'s pacing delay in front of every prompt the user is waiting at; batching turns a
  few hundred candidates into a handful of requests made once, before the first dialog opens.
- **Read the raw `gmetadata`, not `parse_metadata`'s output.** Preview data is only ever looked
  at. Routing it through the parser puts it one call away from `apply_metadata`, which writes to
  the gallery.
- **Do not swap the api lookup for scraping the search page.** The listing html very likely
  carries a thumbnail already, which looks like a free replacement for the `gdata` call. It has
  never been verified against a live page, the markup differs between the list and thumbnail
  views the account can be set to, and getting it wrong fails silently as a missing cover. The
  api field is documented and already relied on elsewhere in `pewnet`.
- **Covers load lazily and off the api host.** Thumbnails come from the image CDN, so hovering
  costs nothing against the rate limited source. Fetch on hover through `Downloader`, cache per
  dialog, and connect a *bound method* to `file_rdy` - a lambda has no thread affinity and would
  run the slot on the download thread, touching widgets from the wrong one.
- **Say where in the queue the user is.** A long run ends in a stack of these blocking on
  `GALLERY_PICKER_QUEUE.get()` with no other sign of how many are left.
- **Log the candidate list at info.** An ordering complaint cannot be diagnosed from a count,
  and the builds these runs come from do not have debug logging on. Bounded by
  `MAX_LOGGED_CANDIDATES`, because a short title clears the threshold dozens of times over.

## Sources

- `CommonHen.QUEUE` is a **class attribute shared by every source.** Drain it between passes or
  one source's urls get fetched against another's api.
- **chaika is a small archive, not a mirror.** Its whole corpus is on the order of twenty thousand
  archives, so as a fallback it recovers a handful per run rather than a large share. A quiet
  chaika pass is the normal outcome, not a bug to chase.
- Follow the site's own pagination link rather than constructing one; it is only rendered when a
  further page exists, which is the gate for fetching it.
- **The search parameters drift, and a stale one fails silently.** `f_sh` once folded expunged
  galleries into the results and now selects them exclusively — the two listings are disjoint, so
  a flag that read as "also include" had become "only". Nothing errors when this happens; the
  result set just changes shape. Before trusting any search flag, check it against a live query
  whose total you can compare (`N results` appears in the page text), not against what the
  parameter name implies. Already ruled out as explanations for that behaviour, so do not re-probe
  them: `advsearch=1`, `f_cats=0`, and the `f_sft` / `f_sfl` / `f_sfu` scope flags all change
  nothing.
- `begin_lock` calls `random.randint(3, TIME_RAND)`, so a `global ehen time offset` below 3
  raises.

## After changing anything here

- [ ] `pytest tests/test_metadata_matching.py -q` passes — its cases are real past failures
- [ ] a new behaviour has a regression case added there, using the real title that motivated it
- [ ] the request count per gallery has not grown for the common (matching) path
